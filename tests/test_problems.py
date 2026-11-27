"""Tests for retro problem tracking and repeat-miss fault escalation."""
import contextlib
import glob
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from sisi import retro, store
GAP = ("--gap", "the export dropped rows with empty names until the person noticed",
       "--cause", "no check compared the row counts before and after", "--term", "evidence")


def tree():
    out = hashlib.sha1()
    for p in sorted(glob.glob(os.path.join(REPO, "sisi", "*")) + glob.glob(os.path.join(REPO, "canon", "*"))):
        if os.path.isfile(p):
            with open(p, "rb") as f:
                out.update(p.encode() + f.read())
    return out.hexdigest()


class Problems(unittest.TestCase):
    def setUp(self):
        before = tree()
        self.addCleanup(lambda: self.assertEqual(tree(), before, "a test wrote into the product tree"))
        self.tmp = tempfile.mkdtemp(prefix="sisi-prob-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.data = os.path.join(self.tmp, "data")
        self.env = dict(os.environ, HOME=self.tmp, SISI_DATA=self.data,
                        SISI_STATE=os.path.join(self.tmp, "state"), SISI_LIB=os.path.join(self.tmp, "lib"))
        for name in ("SISI_SESSION_ID", "CLAUDE_ENV_FILE", "XDG_DATA_HOME", "XDG_STATE_HOME", "CODEX_HOME"):
            self.env.pop(name, None)
        self.proj = os.path.join(self.tmp, "alpha")
        os.makedirs(self.proj)
        for args in (["init", "-q"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "start"]):
            subprocess.run(["git"] + args, cwd=self.proj, check=True, stdin=subprocess.DEVNULL, capture_output=True)

    def sisi(self, *args, cwd=None, sid=None, stdin=""):
        env = dict(self.env, SISI_SESSION_ID=sid) if sid else self.env
        out_f = os.path.join(self.tmp, "stdout.tmp")
        err_f = os.path.join(self.tmp, "stderr.tmp")
        with open(out_f, "w+", encoding="utf-8") as fo, open(err_f, "w+", encoding="utf-8") as fe:
            r = subprocess.run([sys.executable, os.path.join(REPO, "bin", "sisi")] + list(args),
                               cwd=cwd or self.proj, env=env, input=stdin, stdout=fo, stderr=fe, text=True)
            fo.seek(0)
            fe.seek(0)
            return r.returncode, fo.read(), fe.read()

    def records(self):
        p = os.path.join(self.data, "retro.jsonl")
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as f:
            return [json.loads(l) for l in f.read().splitlines() if l.strip()]

    def test_open_cite_missing_unknown_old_records_and_stable_numbers(self):
        # Seed old records without 'problem' field and ensure they stay valid and belong to no problem
        os.makedirs(self.data, exist_ok=True)
        log = os.path.join(self.data, "retro.jsonl")
        with open(log, "w", encoding="utf-8") as f:
            f.write(json.dumps({"ts": "2026-11-20T10:00:00", "gap": "old gap without problem",
                                "cause": "old cause", "improve": "Old rule without problem", "term": "evidence"}) + "\n")
            f.write(json.dumps({"ts": "2026-11-21T10:00:00", "no-gap": "all good",
                                "better": "do something better next time", "term": "time"}) + "\n")

        # Missing --problem on --gap is refused with nothing written
        rc, out, err = self.sisi("retro", *GAP, "--improve", "Compare row counts before and after every export")
        self.assertNotEqual(rc, 0, out)
        self.assertEqual(len(self.records()), 2)
        self.assertFalse(os.path.exists(os.path.join(self.proj, ".sisi", "rules.md")))
        self.assertIn("--problem", out)

        # Open problem #1 by words
        rc, out, err = self.sisi("retro", *GAP, "--improve", "Compare row counts before and after every export",
                                 "--problem", "export drops empty names")
        self.assertEqual((rc, err), (0, ""), out)
        self.assertEqual(self.records()[-1]["problem"], "export drops empty names")
        self.assertNotIn("has come back", out)

        # Open problem #2 by words
        rc, out, err = self.sisi("retro", "--gap", "build script left stale artifacts in output",
                                 "--cause", "clean step was skipped on incremental runs",
                                 "--improve", "Always clean output directory before packaging release",
                                 "--term", "value", "--problem", "stale build artifacts")
        self.assertEqual((rc, err), (0, ""), out)
        self.assertEqual(self.records()[-1]["problem"], "stale build artifacts")

        # Unknown problem numbers refused with nothing written, listing known problems and re-run syntax
        for bad_num in ("0", "-1", "3", "99"):
            before_count = len(self.records())
            rc, out, _ = self.sisi("retro", *GAP, "--improve", "Should not be recorded at all", "--problem", bad_num)
            self.assertNotEqual(rc, 0, bad_num)
            self.assertEqual(len(self.records()), before_count, bad_num)
            self.assertIn("export drops empty names", out)
            self.assertIn("stale build artifacts", out)
            self.assertIn("--problem", out)

        # --no-gap and --later unchanged and refuse --problem
        self.assertEqual(self.sisi("retro", "--no-gap", "the export kept every row cleanly",
                                   "--term", "time", "--better", "start the first build sooner than before")[0], 0)
        self.assertNotIn("problem", self.records()[-1])
        self.assertNotEqual(self.sisi("retro", "--no-gap", "the export kept every row cleanly",
                                      "--term", "time", "--better", "start the first build sooner than before",
                                      "--problem", "1")[0], 0)
        self.assertNotEqual(self.sisi("retro", "--later", "waiting for the owner to reply", "--problem", "1")[0], 0)

        # Cite problem #1 by number: numbers remain stable (#1 is still export drops empty names)
        rc, out, err = self.sisi("retro", *GAP, "--improve", "Add an automated row-count assertion to export tests",
                                 "--problem", "1")
        self.assertEqual((rc, err), (0, ""), out)
        self.assertEqual(self.records()[-1]["problem"], "export drops empty names")
        self.assertIn("problem 1 'export drops empty names' has come back: 1 miss", out)
        self.assertNotIn("1 misses", out)
        self.assertIn("Compare row counts before and after every export", out)

        # Add more non-problem records and cite #2; numbers stay stable
        self.assertEqual(self.sisi("retro", "--no-gap", "the build passed cleanly on first run",
                                   "--term", "time", "--better", "parallelize the test suite run here")[0], 0)
        rc, out, _ = self.sisi("retro", "--gap", "build script left stale artifacts again",
                               "--cause", "incremental cache kept old binary",
                               "--improve", "Hash inputs before reusing build artifacts",
                               "--term", "value", "--problem", "2")
        self.assertEqual(rc, 0, out)
        self.assertIn("problem 2 'stale build artifacts' has come back: 1 miss", out)
        self.assertNotIn("1 misses", out)
        self.assertIn("Always clean output directory before packaging release", out)

    def test_misses_and_fault_escalation_lifecycle(self):
        # 1st attempt: 0 misses, no fault
        rc, out, _ = self.sisi("retro", *GAP, "--improve", "First rule attempt for empty names",
                               "--problem", "empty name export bug")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.sisi("fault")[1].strip(), "no open faults.")

        # 2nd attempt: 1 miss, no fault
        rc, out, _ = self.sisi("retro", *GAP, "--improve", "Second rule attempt for empty names",
                               "--problem", "1")
        self.assertEqual(rc, 0, out)
        self.assertIn("problem 1 'empty name export bug' has come back: 1 miss", out)
        self.assertNotIn("1 misses", out)
        self.assertIn("First rule attempt for empty names", out)
        self.assertEqual(self.sisi("fault")[1].strip(), "no open faults.")

        # 3rd attempt (2nd miss): opens a fault, records retro and rule
        rc, out, _ = self.sisi("retro", *GAP, "--improve", "Third rule attempt for empty names",
                               "--problem", "1")
        self.assertEqual(rc, 0, out)
        self.assertIn("problem 1 'empty name export bug' has come back: 2 misses", out)
        self.assertIn("First rule attempt for empty names", out)
        self.assertIn("Second rule attempt for empty names", out)
        self.assertEqual(len(self.records()), 3)
        with open(os.path.join(self.proj, ".sisi", "rules.md"), encoding="utf-8") as f:
            self.assertIn("Third rule attempt for empty names", f.read())

        faults_out = self.sisi("fault")[1]
        self.assertEqual(len(faults_out.strip().splitlines()), 1, faults_out)
        self.assertIn("empty name export bug", faults_out)
        self.assertIn("2 times", faults_out)
        self.assertIn("hook or an automatic check", faults_out)

        # 4th attempt while fault is still open (or started): opens NO duplicate fault
        self.assertEqual(self.sisi("fault", "--started", "1", "building automatic export test hook")[0], 0)
        rc, out, _ = self.sisi("retro", *GAP, "--improve", "Fourth rule attempt while fault open",
                               "--problem", "1")
        self.assertEqual(rc, 0, out)
        self.assertIn("problem 1 'empty name export bug' has come back: 3 misses", out)
        self.assertEqual(len(self.sisi("fault")[1].strip().splitlines()), 1)

        # Fix the fault, then another attempt opens a new fault
        self.assertEqual(self.sisi("fault", "--fixed", "1", "added export hook to CI check")[0], 0)
        self.assertEqual(self.sisi("fault")[1].strip(), "no open faults.")
        rc, out, _ = self.sisi("retro", *GAP, "--improve", "Fifth rule attempt after fix",
                               "--problem", "1")
        self.assertEqual(rc, 0, out)
        self.assertIn("problem 1 'empty name export bug' has come back: 4 misses", out)
        faults_after = self.sisi("fault")[1]
        self.assertEqual(len(faults_after.strip().splitlines()), 1, faults_after)
        self.assertIn("4 times", faults_after)

    def test_no_arg_retro_lists_problems_most_recent_first_capped_at_15(self):
        for i in range(1, 18):
            rc, out, _ = self.sisi("retro", *GAP, "--improve", "Rule number %02d for problem" % i,
                                   "--problem", "problem item %02d" % i)
            self.assertEqual(rc, 0, out)
        # Re-cite problem 1 so it becomes the most recently cited
        rc, out, _ = self.sisi("retro", *GAP, "--improve", "Second rule for problem 01", "--problem", "1")
        self.assertEqual(rc, 0, out)

        rep = self.sisi("retro")[1]
        lines = [l for l in rep.splitlines() if "problem item " in l]
        self.assertEqual(len(lines), 15, "\n".join(lines))
        # Most recently cited (#1 with 2 attempts) is first, followed by #17 .. #4; #2 and #3 drop off the 15-line cap
        self.assertIn("#1:", lines[0])
        self.assertIn("problem item 01", lines[0])
        self.assertIn("2 attempts", lines[0])
        self.assertIn("#17:", lines[1])
        self.assertIn("problem item 17", lines[1])
        self.assertIn("1 attempt", lines[1])
        self.assertNotIn("problem item 02", rep)
        self.assertNotIn("problem item 03", rep)

    def test_race_derives_number_and_misses_after_append(self):
        real_append = store.append
        log_path = os.path.join(self.data, "retro.jsonl")

        def racing_append(extra_records):
            injected = False

            def wrapper(path, line, once=False):
                nonlocal injected
                if not injected and path == log_path:
                    injected = True
                    for rec in extra_records:
                        real_append(path, json.dumps(rec))
                return real_append(path, line, once=once)

            return wrapper

        base_args = list(GAP) + ["--improve", "Always verify export row count in CI checks", "--problem"]
        with mock.patch.object(store, "DATA", self.data), \
                mock.patch.object(store, "STATE", os.path.join(self.tmp, "state")), \
                mock.patch.object(store, "LIB", os.path.join(self.tmp, "lib")):
            # Between pre-check (empty log) and append, another session opens a different problem and the same problem
            extra = [
                {"ts": "2026-11-26T10:00:00", "gap": "other gap", "cause": "other cause",
                 "improve": "Other rule first", "term": "time", "problem": "other race problem"},
                {"ts": "2026-11-26T10:00:01", "gap": "same gap", "cause": "same cause",
                 "improve": "Earlier racing rule for shared problem", "term": "evidence", "problem": "shared race problem"},
            ]
            out1 = io.StringIO()
            with mock.patch.object(store, "append", side_effect=racing_append(extra)), contextlib.redirect_stdout(out1):
                rc1 = retro.run(base_args + ["shared race problem"], cwd=self.proj)
            self.assertEqual(rc1, 0, out1.getvalue())
            self.assertIn("problem 2 'shared race problem' has come back: 1 miss", out1.getvalue())
            self.assertNotIn("opened problem 1", out1.getvalue())
            rep1 = self.sisi("retro")[1]
            self.assertIn("#1: other race problem (1 attempt", rep1)
            self.assertIn("#2: shared race problem (2 attempts", rep1)

            # Second race: pre-check sees #2 with 2 attempts (1 miss); racing session adds 3rd attempt before append
            extra2 = [
                {"ts": "2026-11-26T10:05:00", "gap": "third gap", "cause": "third cause",
                 "improve": "Third racing rule for shared problem", "term": "evidence", "problem": "shared race problem"},
            ]
            out2 = io.StringIO()
            with mock.patch.object(store, "append", side_effect=racing_append(extra2)), contextlib.redirect_stdout(out2):
                rc2 = retro.run(base_args + ["2"], cwd=self.proj)
            self.assertEqual(rc2, 0, out2.getvalue())
            self.assertIn("problem 2 'shared race problem' has come back: 3 misses", out2.getvalue())
            self.assertIn("opened fault #1", out2.getvalue())
            rep2 = self.sisi("retro")[1]
            self.assertIn("#2: shared race problem (4 attempts", rep2)

    def test_large_log_past_2mb_keeps_problem_numbers_and_attempts(self):
        os.makedirs(self.data, exist_ok=True)
        log = os.path.join(self.data, "retro.jsonl")
        first = json.dumps({"ts": "2026-01-01T10:00:00", "gap": "early gap", "cause": "early cause",
                            "improve": "Early rule for problem one", "term": "evidence", "problem": "early problem"}) + "\n"
        pad_line = json.dumps({"ts": "2026-06-01T10:00:00", "no-gap": "all checks passed cleanly today " + ("x" * 120),
                               "better": "start the build earlier next time around", "term": "time"}) + "\n"
        last = json.dumps({"ts": "2026-11-26T10:00:00", "gap": "late gap", "cause": "late cause",
                           "improve": "Late rule for problem two", "term": "value", "problem": "late problem"}) + "\n"
        repeat_count = (2_100_000 // len(pad_line)) + 1
        with open(log, "w", encoding="utf-8") as f:
            f.write(first + (pad_line * repeat_count) + last)
        self.assertGreater(os.path.getsize(log), 2_000_000)

        rep = self.sisi("retro")[1]
        self.assertIn("#1: early problem (1 attempt", rep)
        self.assertIn("#2: late problem (1 attempt", rep)

        rc, out, _ = self.sisi("retro", *GAP, "--improve", "Second rule for early problem", "--problem", "1")
        self.assertEqual(rc, 0, out)
        self.assertIn("problem 1 'early problem' has come back: 1 miss", out)
        rep2 = self.sisi("retro")[1]
        self.assertIn("#1: early problem (2 attempts", rep2)
        self.assertIn("#2: late problem (1 attempt", rep2)

    def test_wording_refusals_and_miss_singular(self):
        # With no problems yet, refusals must not say "numbers above"
        for p_args in ((), ("--problem", "1")):
            rc, out, _ = self.sisi("retro", *GAP, "--improve", "Should not be written anywhere", *p_args)
            self.assertNotEqual(rc, 0)
            self.assertIn("none yet", out)
            self.assertNotIn("numbers above", out)
            self.assertEqual(self.records(), [])

        # Problem name over 400 characters is refused with a message mentioning the 400-character limit
        rc, out, _ = self.sisi("retro", *GAP, "--improve", "Should not be written anywhere", "--problem", "p" * 401)
        self.assertNotEqual(rc, 0)
        self.assertIn("400", out)
        self.assertEqual(self.records(), [])

        # --no-gap with --problem says --problem goes only with --gap
        rc, out, _ = self.sisi("retro", "--no-gap", "the export kept every row cleanly",
                               "--term", "time", "--better", "start the first build sooner than before",
                               "--problem", "1")
        self.assertNotEqual(rc, 0)
        self.assertIn("--problem", out)
        self.assertIn("--gap", out)
        self.assertNotIn("that is not a retro yet", out)
        self.assertEqual(self.records(), [])

    def test_redacted_problem_names_refused(self):
        bad_names = (
            "sk-abcdefghijklmnopqrstuvwx",
            "0123456789abcdef0123456789abcdef01234567",
            "1234567890" * 4,
            "api_key=supersecret999 broken",
        )
        for bad in bad_names:
            rc, out, _ = self.sisi("retro", *GAP, "--improve", "Should not record secret problem name", "--problem", bad)
            self.assertNotEqual(rc, 0, bad)
            self.assertIn("plain words", out)
            self.assertNotIn(bad, out)
            self.assertEqual(self.records(), [])
            self.assertFalse(os.path.exists(os.path.join(self.proj, ".sisi", "rules.md")))

    def test_two_problems_each_open_own_fault_and_case_spacing_joins(self):
        self.assertEqual(self.sisi("retro", *GAP, "--improve", "Alpha rule one for export", "--problem", "alpha issue")[0], 0)
        self.assertEqual(self.sisi("retro", *GAP, "--improve", "Bravo rule one for export", "--problem", "bravo issue")[0], 0)

        # Citing by name with different case and spacing joins the same problem
        rc, out, _ = self.sisi("retro", *GAP, "--improve", "Alpha rule two by name", "--problem", "  ALPHA   issue  ")
        self.assertEqual(rc, 0, out)
        self.assertIn("problem 1 'alpha issue' has come back: 1 miss", out)
        self.assertNotIn("1 misses", out)
        self.assertEqual(self.sisi("fault")[1].strip(), "no open faults.")

        # 2nd miss on problem 1 opens its fault
        rc, out, _ = self.sisi("retro", *GAP, "--improve", "Alpha rule three opens fault", "--problem", "1")
        self.assertEqual(rc, 0, out)
        self.assertIn("problem 1 'alpha issue' has come back: 2 misses", out)

        # Same-length second problem joins via case/spacing then reaches 2 misses and opens its own fault
        rc, out, _ = self.sisi("retro", *GAP, "--improve", "Bravo rule two by name", "--problem", "  bravo   ISSUE ")
        self.assertEqual(rc, 0, out)
        self.assertIn("problem 2 'bravo issue' has come back: 1 miss", out)
        rc, out, _ = self.sisi("retro", *GAP, "--improve", "Bravo rule three opens fault", "--problem", "2")
        self.assertEqual(rc, 0, out)
        self.assertIn("problem 2 'bravo issue' has come back: 2 misses", out)

        faults_lines = self.sisi("fault")[1].strip().splitlines()
        self.assertEqual(len(faults_lines), 2, faults_lines)
        self.assertTrue(any("alpha issue" in l for l in faults_lines), faults_lines)
        self.assertTrue(any("bravo issue" in l for l in faults_lines), faults_lines)


if __name__ == "__main__":
    unittest.main()
