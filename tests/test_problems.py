"""Tests for retro problem tracking and repeat-miss fault escalation."""
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
        self.assertIn("problem 1 'export drops empty names' has come back: 1 misses", out)
        self.assertIn("Compare row counts before and after every export", out)

        # Add more non-problem records and cite #2; numbers stay stable
        self.assertEqual(self.sisi("retro", "--no-gap", "the build passed cleanly on first run",
                                   "--term", "time", "--better", "parallelize the test suite run here")[0], 0)
        rc, out, _ = self.sisi("retro", "--gap", "build script left stale artifacts again",
                               "--cause", "incremental cache kept old binary",
                               "--improve", "Hash inputs before reusing build artifacts",
                               "--term", "value", "--problem", "2")
        self.assertEqual(rc, 0, out)
        self.assertIn("problem 2 'stale build artifacts' has come back: 1 misses", out)
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
        self.assertIn("problem 1 'empty name export bug' has come back: 1 misses", out)
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


if __name__ == "__main__":
    unittest.main()
