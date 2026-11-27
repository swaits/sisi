"""Tests for organize evidence, drop reasons, and revert consistency."""
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


class OrganizeEvidence(unittest.TestCase):
    def setUp(self):
        before = tree()
        self.addCleanup(lambda: self.assertEqual(tree(), before, "a test wrote into the product tree"))
        self.tmp = tempfile.mkdtemp(prefix="sisi-orgev-")
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

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def read(self, *parts):
        with open(os.path.join(*parts), encoding="utf-8") as f:
            return f.read()

    def test_brief_has_problem_evidence_and_respects_caps(self):
        self.assertEqual(self.sisi("retro", "--gap", "export dropped rows with empty names in table",
                                   "--cause", "first cause missed null guard",
                                   "--improve", "Check null names before exporting rows",
                                   "--term", "evidence", "--problem", "row count mismatch")[0], 0)
        self.assertEqual(self.sisi("retro", "--gap", "export dropped rows again on blank fields",
                                   "--cause", "second cause forgot whitespace trim",
                                   "--improve", "Strip whitespace and assert total row count matches",
                                   "--term", "evidence", "--problem", "1")[0], 0)
        rc, brief, err = self.sisi("rules", "organize")
        self.assertEqual((rc, err), (0, ""), brief)
        self.assertIn("row count mismatch", brief)
        self.assertIn("2 attempts", brief)
        self.assertIn("1 miss", brief)
        self.assertIn("first cause missed null guard", brief)
        self.assertIn("Check null names before exporting rows", brief)
        self.assertIn("second cause forgot whitespace trim", brief)
        self.assertIn("Strip whitespace and assert total row count matches", brief)
        self.assertIn("keep the latest attempt", brief)
        self.assertIn("keep the cause", brief)

        # Add 17 more problems (18 total > 15 cap) and a 5000-char cause on problem 18
        long_cause = "word " * 1000
        for i in range(2, 19):
            cause = long_cause if i == 18 else "cause number %02d in batch" % i
            self.assertEqual(self.sisi("retro", "--gap", "gap number %02d failed verification check" % i,
                                       "--cause", cause,
                                       "--improve", "Rule number %02d for problem" % i,
                                       "--term", "evidence", "--problem", "problem item %02d" % i)[0], 0)
        # Re-cite problem 1 so it is most recently cited
        self.assertEqual(self.sisi("retro", *GAP, "--improve", "Latest rule for row count mismatch",
                                   "--problem", "1")[0], 0)
        rc, brief2, _ = self.sisi("rules", "organize")
        self.assertEqual(rc, 0)
        ev = brief2.split("=== Known problems")[1]
        self.assertLessEqual(len(ev), 5050)
        self.assertIn("row count mismatch", ev)
        self.assertIn("problem item 18", ev)
        self.assertNotIn(long_cause, ev)
        self.assertNotIn("problem item 02", ev)
        self.assertNotIn("problem item 03", ev)
        self.assertNotIn("problem item 04", ev)

    def test_no_problems_brief_is_minimal_and_organize_works(self):
        self.assertEqual(self.sisi("learn", "--project", "Keep project outputs deterministic always")[0], 0)
        self.assertEqual(self.sisi("retro", "--no-gap", "the run passed every check cleanly",
                                   "--term", "time", "--better", "start the verification step much earlier")[0], 0)
        rc, brief, _ = self.sisi("rules", "organize")
        self.assertEqual(rc, 0)
        self.assertNotIn("=== Known problems", brief)
        self.assertIn("## drops", brief)
        self.assertIn("a missing line is recorded as 'none given'", brief)
        self.assertIn("copied as it is", brief)
        shape = brief.split("Answer with exactly this shape")[1].split("===")[0]
        self.assertLess(shape.index("## project"), shape.index("## drops"))
        self.assertLess(shape.index("## drops"), shape.index("## flags"))
        self.assertEqual(len(brief.split("=== The first list now")[0].splitlines()), 35)
        proj_line = self.read(self.proj, ".sisi", "rules.md").splitlines()[0]
        ans = self.write(os.path.join(self.tmp, "ans.md"),
                         "## user\n## project\n- Kept project rule [retro 2026-11-26]\n"
                         "## drops\n- %s | #- | reworded for clarity\n" % proj_line[2:])
        rc, out, err = self.sisi("rules", "organize", "--record", ans)
        self.assertEqual((rc, err), (0, ""), out)
        recs = [json.loads(l) for l in self.read(self.data, "rules", "drops.jsonl").splitlines() if l.strip()]
        self.assertEqual(len(recs), 1)
        self.assertIsNone(recs[0]["problem"])
        self.assertEqual(recs[0]["reason"], "reworded for clarity")

    def test_missing_and_unparseable_drops_accepted_with_none_given(self):
        self.assertEqual(self.sisi("retro", *GAP, "--improve", "First rule for empty names",
                                   "--problem", "empty names")[0], 0)
        self.assertEqual(self.sisi("retro", *GAP, "--improve", "Second rule for empty names",
                                   "--problem", "1")[0], 0)
        rules_path = os.path.join(self.proj, ".sisi", "rules.md")
        r1, r2 = self.read(rules_path).splitlines()
        self.assertEqual(self.sisi("rules", "organize")[0], 0)

        ans = os.path.join(self.tmp, "ans.md")
        for body in (
            "## user\n## project\n%s\n" % r2,
            "## user\n## project\n%s\n## drops\n- %s | #1 | \n" % (r2, r1[2:]),
            "## user\n## project\n%s\n## drops\n- %s\n" % (r2, r1[2:]),
        ):
            rc, out, err = self.sisi("rules", "organize", "--record", self.write(ans, body))
            self.assertEqual((rc, err), (0, ""), (body, out))
            self.assertIn("1 dropped rule had no reason recorded", out)
            recs = [json.loads(l) for l in self.read(self.data, "rules", "drops.jsonl").splitlines() if l.strip()]
            self.assertEqual(recs[-1]["rule"], r1)
            self.assertEqual(recs[-1]["reason"], "none given")
            self.assertIsNone(recs[-1]["problem"])
            self.assertEqual(self.sisi("rules", "revert")[0], 0)
            self.assertEqual(self.sisi("rules", "organize")[0], 0)

        good = "## user\n## project\n%s\n## drops\n- %s | #1 | superseded by second rule\n" % (r2, r1[2:])
        rc, out, err = self.sisi("rules", "organize", "--record", self.write(ans, good))
        self.assertEqual((rc, err), (0, ""), out)
        self.assertNotIn("no reason recorded", out)
        self.assertEqual(self.read(rules_path), r2 + "\n")
        recs = [json.loads(l) for l in self.read(self.data, "rules", "drops.jsonl").splitlines() if l.strip()]
        self.assertEqual(recs[-1]["problem"], 1)
        self.assertEqual(recs[-1]["rule"], r1)
        self.assertEqual(recs[-1]["reason"], "superseded by second rule")

    def test_owner_rules_stay_verbatim_with_drops_format(self):
        self.sisi("prompt", sid="o1", stdin=json.dumps({"session_id": "o1", "cwd": self.proj, "prompt": "Always keep the owner rule verbatim"}))
        self.assertEqual(self.sisi("learn", "Always keep the owner rule verbatim", sid="o1")[0], 0)
        self.assertEqual(self.sisi("retro", *GAP, "--improve", "Check row counts before export", "--problem", "empty names")[0], 0)
        own = self.read(self.data, "rules", "user.md").splitlines()[0]
        ret = self.read(self.proj, ".sisi", "rules.md").splitlines()[0]
        self.assertEqual(self.sisi("rules", "organize")[0], 0)

        ans = os.path.join(self.tmp, "ans.md")
        # Dropping an owner rule even with a ## drops entry is refused
        bad_drop = "## user\n## project\n%s\n## drops\n- %s | #- | tried to drop owner\n" % (ret, own[2:])
        rc, out, _ = self.sisi("rules", "organize", "--record", self.write(ans, bad_drop))
        self.assertEqual(rc, 1, out)
        self.assertIn("owner rule missing or changed", out)
        self.assertIn(own, self.read(self.data, "rules", "user.md"))

        # Rewording an owner rule is still refused
        bad_edit = "## user\n- Keep owner rule [owner 2026-11-26]\n## project\n%s\n" % ret
        rc, out, _ = self.sisi("rules", "organize", "--record", self.write(ans, bad_edit))
        self.assertEqual(rc, 1, out)
        self.assertIn("owner rule missing or changed", out)

        # Keeping owner verbatim while dropping retro rule with reason succeeds
        good = "## user\n%s\n## project\n- Export verifies row counts [retro 2026-11-26]\n## drops\n- %s | #1 | replaced with stronger rule\n" % (own, ret[2:])
        rc, out, err = self.sisi("rules", "organize", "--record", self.write(ans, good))
        self.assertEqual((rc, err), (0, ""), out)
        self.assertIn(own, self.read(self.data, "rules", "user.md"))

    def test_recorded_drop_appears_in_next_brief_and_retro_has_come_back(self):
        self.assertEqual(self.sisi("retro", *GAP, "--improve", "First attempt rule to drop", "--problem", "empty names")[0], 0)
        self.assertEqual(self.sisi("retro", *GAP, "--improve", "Second attempt rule to keep", "--problem", "1")[0], 0)
        r1, r2 = self.read(self.proj, ".sisi", "rules.md").splitlines()
        self.assertEqual(self.sisi("rules", "organize")[0], 0)
        ans = self.write(os.path.join(self.tmp, "ans.md"),
                         "## user\n## project\n%s\n## drops\n- %s | #1 | too vague to prevent bug\n" % (r2, r1[2:]))
        self.assertEqual(self.sisi("rules", "organize", "--record", ans)[0], 0)

        rc, brief, _ = self.sisi("rules", "organize")
        self.assertEqual(rc, 0)
        self.assertIn("earlier dropped:", brief)
        self.assertIn("has not come back yet", brief)
        self.assertIn("note it in `## flags`", brief)
        self.assertIn(r1, brief)
        self.assertIn("too vague to prevent bug", brief)

        rc, retro_out, _ = self.sisi("retro", *GAP, "--improve", "Third attempt rule after drop", "--problem", "1")
        self.assertEqual(rc, 0, retro_out)
        self.assertIn("problem 1 'empty names' has come back: 2 misses", retro_out)
        self.assertIn("dropped [", retro_out)
        self.assertIn(r1, retro_out)
        self.assertIn("too vague to prevent bug", retro_out)

    def test_revert_after_organize_undoes_and_redoes_drop_reasons(self):
        self.assertEqual(self.sisi("retro", *GAP, "--improve", "First rule before organize", "--problem", "empty names")[0], 0)
        self.assertEqual(self.sisi("retro", *GAP, "--improve", "Second rule before organize", "--problem", "1")[0], 0)
        rules_path = os.path.join(self.proj, ".sisi", "rules.md")
        before = self.read(rules_path)
        r1, r2 = before.splitlines()
        self.assertEqual(self.sisi("rules", "organize")[0], 0)
        ans = self.write(os.path.join(self.tmp, "ans.md"),
                         "## user\n## project\n%s\n## drops\n- %s | #1 | dropped during organize\n" % (r2, r1[2:]))
        self.assertEqual(self.sisi("rules", "organize", "--record", ans)[0], 0)
        self.assertIn("dropped during organize", self.read(self.data, "rules", "drops.jsonl"))

        rc, out, _ = self.sisi("rules", "revert")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.read(rules_path), before)
        drops_path = os.path.join(self.data, "rules", "drops.jsonl")
        self.assertFalse(os.path.exists(drops_path) and "dropped during organize" in self.read(drops_path))
        self.assertNotIn("dropped during organize", self.sisi("rules", "organize")[1])

        # Second revert re-applies both the organized rules and the drop reason
        rc, out, _ = self.sisi("rules", "revert")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.read(rules_path), r2 + "\n")
        self.assertIn("dropped during organize", self.read(drops_path))
        self.assertIn("dropped during organize", self.sisi("rules", "organize")[1])

    def test_lenient_drops_variants_all_accepted(self):
        self.assertEqual(self.sisi("retro", *GAP, "--improve", "Check row counts before export", "--problem", "empty names")[0], 0)
        self.assertEqual(self.sisi("retro", *GAP, "--improve", "Trim whitespace before export", "--problem", "1")[0], 0)
        rules_path = os.path.join(self.proj, ".sisi", "rules.md")
        r1, r2 = self.read(rules_path).splitlines()
        r1_notags = r1[2:].rsplit(" [retro ", 1)[0]
        ans = os.path.join(self.tmp, "ans.md")
        drops_path = os.path.join(self.data, "rules", "drops.jsonl")

        # 1. No brief printed first + reworded rule + no drops section + plural message
        rc, out, err = self.sisi("rules", "organize", "--record", self.write(
            ans, "## user\n## project\n- Reworded export check [retro 2026-11-26]\n"))
        self.assertEqual((rc, err), (0, ""), out)
        self.assertIn("2 dropped rules had no reason recorded", out)
        recs = [json.loads(l) for l in self.read(drops_path).splitlines()]
        self.assertEqual([(x["rule"], x["reason"], x["problem"]) for x in recs],
                         [(r1, "none given", None), (r2, "none given", None)])
        self.assertEqual(self.sisi("rules", "revert")[0], 0)

        cases = [
            ("backticks", "## user\n## project\n- Merged [retro 2026-11-26]\n## drops\n- `%s` | #1 | reason one\n- `%s` | #1 | reason two\n" % (r1, r2[2:]),
             [(r1, "reason one", 1), (r2, "reason two", 1)], False),
            ("no_date_tag", "## user\n## project\n- Merged [retro 2026-11-26]\n## drops\n- %s | #1 | no tag reason\n- %s | #- | second reason\n" % (r1_notags, r2[2:].rsplit(" [", 1)[0]),
             [(r1, "no tag reason", 1), (r2, "second reason", None)], False),
            ("one_of_two_merged", "## user\n## project\n- Merged [retro 2026-11-26]\n## drops\n- %s | #1 | merged into one\n" % r1[2:],
             [(r1, "merged into one", 1), (r2, "none given", None)], "1 dropped rule had no reason recorded"),
            ("pipe_in_reason", "## user\n## project\n- Merged [retro 2026-11-26]\n## drops\n- %s | #1 | replaced A | B | C\n- %s | #- | x | y\n" % (r1[2:], r2[2:]),
             [(r1, "replaced A | B | C", 1), (r2, "x | y", None)], False),
            ("none_under_drops", "## user\n## project\n- Merged [retro 2026-11-26]\n## drops\nnone\n",
             [(r1, "none given", None), (r2, "none given", None)], "2 dropped rules had no reason recorded"),
            ("closing_fence", "## user\n## project\n- Merged [retro 2026-11-26]\n## drops\n- %s | #1 | kept reason\n- %s | #- | also kept\n```\n" % (r1[2:], r2[2:]),
             [(r1, "kept reason", 1), (r2, "also kept", None)], False),
            ("star_and_indented", "## user\n## project\n- Merged [retro 2026-11-26]\n## drops\n  * %s | #1 | star reason\n  1. %s | #- | num reason\n" % (r1[2:], r2[2:]),
             [(r1, "star reason", 1), (r2, "num reason", None)], False),
            ("drops_between_user_and_project", "## user\n## drops:\n- %s | #1 | middle drops\n- %s | #- | middle two\n## project\n- Kept project [retro 2026-11-26]\n" % (r1[2:], r2[2:]),
             [(r1, "middle drops", 1), (r2, "middle two", None)], False),
            ("heading_h3_Drops", "## user\n## project\n- Kept project [retro 2026-11-26]\n### Drops\n- %s | #1 | h3 reason\n- %s | #- | h3 two\n## notes\n- %s | #1 | ignored after next heading\n" % (r1[2:], r2[2:], r1[2:]),
             [(r1, "h3 reason", 1), (r2, "h3 two", None)], False),
            ("drops_before_flags", "## user\n## project\n- Kept project [retro 2026-11-26]\n## drops\n- %s | #1 | before flags\n- %s | #- | two\n## flags\n- flag item\n" % (r1[2:], r2[2:]),
             [(r1, "before flags", 1), (r2, "two", None)], False),
        ]
        for name, text, expected, notice in cases:
            self.assertEqual(self.sisi("rules", "organize")[0], 0, name)
            rc, out, err = self.sisi("rules", "organize", "--record", self.write(ans, text))
            self.assertEqual((rc, err), (0, ""), (name, out))
            self.assertIn("Kept project" if "Kept project" in text else "Merged", self.read(rules_path), name)
            if notice:
                self.assertIn(notice, out, name)
            else:
                self.assertNotIn("no reason recorded", out, name)
            recs = [json.loads(l) for l in self.read(drops_path).splitlines()]
            self.assertEqual([(x["rule"], x["reason"], x["problem"]) for x in recs[-2:]], expected, name)
            self.assertEqual(self.sisi("rules", "revert")[0], 0, name)

    def test_drops_ignore_kept_owner_and_invented_rules(self):
        self.sisi("prompt", sid="o1", stdin=json.dumps({"session_id": "o1", "cwd": self.proj, "prompt": "Always keep the owner rule verbatim"}))
        self.assertEqual(self.sisi("learn", "Always keep the owner rule verbatim", sid="o1")[0], 0)
        self.assertEqual(self.sisi("retro", *GAP, "--improve", "Kept retro rule always here", "--problem", "empty names")[0], 0)
        own = self.read(self.data, "rules", "user.md").splitlines()[0]
        ret = self.read(self.proj, ".sisi", "rules.md").splitlines()[0]
        ans = self.write(os.path.join(self.tmp, "ans.md"),
                         "## user\n%s\n## project\n%s\n## drops\n"
                         "- %s | #- | named kept rule\n"
                         "- %s | #- | named owner rule\n"
                         "- Invented rule never existed | #1 | invented\n" % (own, ret, ret[2:], own[2:]))
        rc, out, err = self.sisi("rules", "organize", "--record", ans)
        self.assertEqual((rc, err), (0, ""), out)
        self.assertFalse(os.path.exists(os.path.join(self.data, "rules", "drops.jsonl")))

    def test_drops_bounded_redacted_and_invalid_problem_numbers_safe(self):
        long_rule = "Very long rule text " + ("x" * 350)
        self.assertEqual(self.sisi("retro", *GAP, "--improve", long_rule, "--problem", "empty names")[0], 0)
        rules_path = os.path.join(self.proj, ".sisi", "rules.md")
        r1 = self.read(rules_path).splitlines()[0]
        for i in range(3):
            self.assertEqual(self.sisi("retro", *GAP, "--improve", "Extra rule number %d here" % i, "--problem", "1")[0], 0)
        rs = self.read(rules_path).splitlines()
        big_num = "9" * 5000
        long_reason = "api_key=sk-abcdefghijklmnopqrstuvwx " + ("y" * 350)
        ans = self.write(os.path.join(self.tmp, "ans.md"),
                         "## user\n## project\n- Remaining [retro 2026-11-26]\n## drops\n"
                         "- %s | #999 | %s\n"
                         "- %s | #0 | zero prob\n"
                         "- %s | #%s | five thousand digits\n"
                         "- %s | #\uff11 | fullwidth digit\n"
                         % (rs[0][2:], long_reason, rs[1][2:], rs[2][2:], big_num, rs[3][2:]))
        rc, out, err = self.sisi("rules", "organize", "--record", ans)
        self.assertEqual((rc, err), (0, ""), out)
        recs = [json.loads(l) for l in self.read(self.data, "rules", "drops.jsonl").splitlines()]
        self.assertEqual(len(recs), 4)
        for rec in recs:
            self.assertIsNone(rec["problem"])
            self.assertLessEqual(len(rec["rule"]), 300)
            self.assertLessEqual(len(rec["reason"]), 300)
        self.assertNotIn("sk-abcdefghijklmnop", recs[0]["reason"])
        self.assertIn("<redacted>", recs[0]["reason"])

    def test_retro_caps_drops_at_five_with_more_and_evidence_is_newest_first(self):
        self.assertEqual(self.sisi("retro", *GAP, "--improve", "Seed rule for problem one", "--problem", "empty names")[0], 0)
        long_r = "Long dropped rule " + ("a" * 220)
        long_why = "Long drop reason " + ("b" * 220)
        dp = os.path.join(self.data, "rules", "drops.jsonl")
        os.makedirs(os.path.dirname(dp), exist_ok=True)
        with open(dp, "w", encoding="utf-8") as f:
            for i in range(1, 8):
                rule_s = long_r if i == 7 else "- Dropped rule %02d [retro 2026-11-26]" % i
                why_s = long_why if i == 7 else "drop reason %02d" % i
                f.write(json.dumps({"ts": "2026-11-26T00:00:%02d" % i, "rule": rule_s, "problem": 1, "reason": why_s}) + "\n")
        rc, brief, _ = self.sisi("rules", "organize")
        self.assertEqual(rc, 0)
        ev = brief.split("=== Known problems")[1]
        self.assertLess(ev.index("Long dropped rule"), ev.index("drop reason 01"))

        rc, retro_out, err = self.sisi("retro", *GAP, "--improve", "Next rule after seven drops", "--problem", "1")
        self.assertEqual((rc, err), (0, ""), retro_out)
        drop_lines = [l for l in retro_out.splitlines() if l.strip().startswith("- dropped [")]
        self.assertEqual(len(drop_lines), 5, retro_out)
        self.assertIn("and 2 more", retro_out)
        self.assertNotIn("drop reason 01", retro_out)
        self.assertNotIn("drop reason 02", retro_out)
        self.assertIn("drop reason 03", retro_out)
        for dl in drop_lines:
            self.assertLessEqual(len(dl), 390)
        self.assertNotIn("a" * 170, retro_out)
        self.assertNotIn("b" * 170, retro_out)

    def test_evidence_cap_counts_header_and_truncates_single_large_problem(self):
        # One problem with 70 attempts of ~90 chars each -> >6000 chars total, exceeding 5000.
        # Fails if: (1) cap is raised, (2) truncation branch is removed, (3) header is not counted.
        os.makedirs(self.data, exist_ok=True)
        with open(os.path.join(self.data, "retro.jsonl"), "w", encoding="utf-8") as f:
            for i in range(70):
                f.write(json.dumps({
                    "ts": "2026-11-26T00:00:00",
                    "problem": "single huge problem",
                    "cause": "cause_%02d_%s" % (i, "c" * 30),
                    "improve": "rule_%02d_%s" % (i, "r" * 20),
                }) + "\n")
        rc, brief, err = self.sisi("rules", "organize")
        self.assertEqual((rc, err), (0, ""))
        ev_raw = ("\n\n=== Known problems" + brief.split("=== Known problems")[1]).rstrip("\n")
        self.assertLessEqual(len(ev_raw), 5000)
        self.assertIn("#1: single huge problem", ev_raw)
        self.assertIn("attempt [", ev_raw)
        self.assertNotIn("rule_69_", ev_raw)


if __name__ == "__main__":
    unittest.main()
