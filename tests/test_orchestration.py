import json, os, re, stat, time, unittest
from support import *

FAKE_TOOL = """#!/bin/sh
case "$1" in
  exec)
    if [ "$2" = "--list-models" ]; then echo "beta-1"; echo "beta-2"; exit 0; fi
    echo '{"usage":{"total_tokens":2000000}}'
    echo "worker final report: done ok" ;;
  usage) echo '{"allowance":{"tier":"flat plan","weekly":{"usedPercent":25},"window":{"usedPercent":10}}}' ;;
  *) echo 'help' ;;
esac
exit 0
"""


def valid_brief():
    return (
        "You are a worker.\n\n"
        "## Outcome and scope\nDo the toy task.\n\n"
        "## Context and sources of truth\nThe brief itself.\n\n"
        "## Constraints and interfaces\nNo interface changes.\n\n"
        "## Acceptance\nThe report says done and the toy check passes.\n\n"
        "## Deliverables and report format\nA short report.\n\n"
        "## Files you may change\ntoy.txt only.\n\n"
        "## Verification\nRun the toy check.\n\n"
        "## Budget and escalation\nTen minutes; escalate if blocked.\n")


class OrchCase(SisiCase):
    def setUp(self):
        super().setUp()
        self.bindir = os.path.join(self.tmp, "bin")
        os.makedirs(self.bindir)
        p = os.path.join(self.bindir, "muse")
        open(p, "w").write(FAKE_TOOL)
        os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)

    def env(self, **kw):
        return dict(PATH=self.bindir, **kw)

    def ledger(self):
        p = os.path.join(self.data, "delegations.jsonl")
        if not os.path.exists(p):
            return []
        return [json.loads(l) for l in open(p)]

    def seed_attempts(self, rows):
        os.makedirs(self.data, exist_ok=True)
        with open(os.path.join(self.data, "delegations.jsonl"), "w") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")

    def attempt(self, id, worker="muse/beta-1", outcome="accepted", check="tests",
                type="impl", difficulty=2, minutes=5, retry_of=None, ts=None):
        return {"kind": "attempt", "id": id, "ts": round(time.time()) if ts is None else ts,
                "project": "proj", "type": type, "difficulty": difficulty, "worker": worker,
                "outcome": outcome, "check": check, "minutes": minutes, "tokens": None,
                "retry_of": retry_of, "note": None}


class BriefTests(OrchCase):
    def test_brief_template_has_eight_parts(self):
        """R-7.5-1..R-7.5-9: delegate brief prints a template with every contract part."""
        r = self.sisi("delegate", "brief", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        for title in ("Outcome and scope", "Context and sources of truth",
                      "Constraints and interfaces", "Acceptance",
                      "Deliverables and report format", "Files you may change",
                      "Verification", "Budget and escalation"):
            self.assertIn(title, r.stdout)

    def test_check_reports_missing_parts(self):
        """R-7.5-2, R-7.5-4, R-7.5-6: delegate check names the parts a brief lacks."""
        p = os.path.join(self.proj, "thin.md")
        open(p, "w").write("Do the thing.\n")
        r = self.sisi("delegate", "check", p, env=self.env())
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Outcome and scope", r.stdout)
        self.assertIn("Acceptance", r.stdout)
        self.assertIn("Files you may change", r.stdout)

    def brief_with(self, **parts):
        """valid_brief() with the text of some parts replaced; keys are the heading words."""
        text = valid_brief()
        heads = {"acceptance": "Acceptance", "verification": "Verification", "outcome": "Outcome and scope",
                 "deliverables": "Deliverables and report format"}
        for key, body in parts.items():
            h = heads[key]
            start = text.index("## " + h)
            end = text.find("\n\n##", start)
            end = len(text) if end < 0 else end
            text = text[:start] + "## %s\n%s" % (h, body) + text[end:]
        return text

    def advice(self, text):
        p = os.path.join(self.proj, "b.md")
        open(p, "w").write(text)
        r = self.sisi("delegate", "check", p, env=self.env())
        self.assertEqual(r.returncode, 0, r.stdout)  # advice never blocks
        self.assertLessEqual(len(r.stdout.splitlines()), 20)
        return r.stdout

    def test_brief_template_carries_what_the_rebuild_learned(self):
        """R-7.5-1: the template's guidance names the six cases, and an unfilled template is still unfilled."""
        t = self.sisi("delegate", "brief", env=self.env()).stdout
        for phrase in ("a number with the command that measures it", "name that reader", "different worker",
                       "held-out", "abuse cases", "forge the field that marks trust", "unrelated reason",
                       "30 times", "in parallel", "done / next"):
            self.assertIn(phrase, t)
        p = os.path.join(self.proj, "t.md")
        open(p, "w").write(t)
        r = self.sisi("delegate", "check", p, env=self.env())
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("advice", r.stdout)  # the template's own guidance is not the author's words

    def test_check_flags_each_case_and_stays_quiet_on_a_clean_brief(self):
        """R-7.5-1, abuse: each flag has a brief that trips it and a near-identical one that does not."""
        self.assertNotIn("advice", self.advice(valid_brief()))
        cases = {
            "acceptance": (dict(acceptance="Keep the report short and fast."), "Acceptance says"),
            "gate": (dict(outcome="Add an approval gate for deploys."), "abuse cases"),
            "tests": (dict(verification="Write tests for the parser."), "repeat run"),
            "reader": (dict(outcome="Write the index file for other modules to read."), "no reader is named"),
            "labels": (dict(outcome="Build a matcher and a labelled set of examples."), "different worker"),
            "commits": (dict(deliverables="1. the parser\n2. the writer"), "commit per item"),
        }
        for name, (parts, flag) in cases.items():
            with self.subTest(name):
                self.assertIn(flag, self.advice(self.brief_with(**parts)))
        fixed = {
            "acceptance": dict(acceptance="The report is under 40 lines (`wc -l report.md`) and the check runs in 5 s."),
            "gate": dict(outcome="Add an approval gate for deploys.", verification="Abuse cases: omit the trigger field."),
            "tests": dict(verification="Write tests; run the new module 30 times in parallel."),
            "reader": dict(outcome="Write the index for other modules to read; the reader is `sisi/search.py`."),
            "labels": dict(outcome="Build a matcher; the labelled set comes from a different worker."),
            "commits": dict(deliverables="1. the parser\n2. the writer\nCommit after each item with a done / next note."),
        }
        for name, parts in fixed.items():
            with self.subTest("fixed " + name):
                self.assertNotIn("advice", self.advice(self.brief_with(**parts)))
        self.assertLessEqual(len(self.advice(self.brief_with(**{k: v for c in cases.values() for k, v in c[0].items()})).splitlines()), 20)

    def test_check_passes_a_full_brief(self):
        p = os.path.join(self.proj, "full.md")
        open(p, "w").write(valid_brief())
        r = self.sisi("delegate", "check", p, env=self.env())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_delegate_refuses_brief_without_acceptance(self):
        """R-7.5-4, R-7.5-10: running a brief that lacks acceptance is refused."""
        p = os.path.join(self.proj, "noacc.md")
        open(p, "w").write(valid_brief().replace("## Acceptance\nThe report says done and the toy check passes.", "## Acceptance\n[...]"))
        r = self.sisi("delegate", "--kind", "impl", "--difficulty", "2", "--brief", p,
                      "--worker", "muse/beta-1", env=self.env())
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Acceptance", r.stdout + r.stderr)


class LedgerTests(OrchCase):
    def test_direct_judge_records_without_a_run(self):
        """R-7.2-3: judge is the write path even for work run through the host's own subagents."""
        r = self.sisi("delegate", "judge", "--worker", "muse/beta-1", "--type", "read",
                      "--difficulty", "1", "--outcome", "accepted", "--check", "read",
                      "--minutes", "3", "--tokens", "1200", "--project", "proj",
                      env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = [x for x in self.ledger() if x.get("kind") == "attempt"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["worker"], "muse/beta-1")
        self.assertEqual(rows[0]["tokens"], 1200)

    def test_recent_lists_judgements_with_check_strength(self):
        self.seed_attempts([self.attempt("a1", check="none"), self.attempt("a2", check="tests")])
        r = self.sisi("delegate", "recent", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("a1", r.stdout)
        self.assertIn("a2", r.stdout)

    def test_down_with_until_and_up(self):
        """Unavailability is temporary and carries an until-date; it is not a quality judgement."""
        r = self.sisi("workers", "down", "muse/beta-1", "--reason", "limit",
                      "--until", "2999-01-01", "--note", "monthly limit", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        avail = json.load(open(os.path.join(self.data, "worker-availability.json")))
        self.assertIn("muse/beta-1", avail)
        self.assertEqual(avail["muse/beta-1"]["reason"], "limit")
        self.assertEqual(avail["muse/beta-1"]["note"], "monthly limit")
        r2 = self.sisi("workers", "up", "muse/beta-1", env=self.env())
        self.assertEqual(r2.returncode, 0, r2.stderr)
        avail2 = json.load(open(os.path.join(self.data, "worker-availability.json")))
        self.assertNotIn("muse/beta-1", avail2)

    def test_rejection_never_marks_worker_down(self):
        """A rejected judgement must not make the worker unavailable."""
        r = self.sisi("delegate", "judge", "--worker", "muse/beta-1", "--type", "impl",
                      "--difficulty", "2", "--outcome", "rejected", "--check", "tests",
                      env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        p = os.path.join(self.data, "worker-availability.json")
        avail = json.load(open(p)) if os.path.exists(p) else {}
        self.assertNotIn("muse/beta-1", avail)

    def test_import_is_idempotent_and_counts_rows(self):
        src = os.path.join(self.tmp, "orch.jsonl")
        rows = [self.attempt("x1", ts=1700000000), self.attempt("x2", outcome="rejected", ts=1700000100),
                {"kind": "amend", "id": "x1", "ts": 1700000200, "note": "later wrong"}]
        with open(src, "w") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
        r = self.sisi("workers", "import", src, env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("before: 0", r.stdout)
        self.assertIn("after: 3", r.stdout)
        r2 = self.sisi("workers", "import", src, env=self.env())
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("after: 3", r2.stdout)
        self.assertEqual(len(self.ledger()), 3)


class FactsTests(OrchCase):
    def test_fact_requires_source_and_is_stored(self):
        """Prices and benchmark standing carry a source and date (worker facts)."""
        bad = self.sisi("workers", "fact", "muse/beta-1", "--price", "3", env=self.env())
        self.assertNotEqual(bad.returncode, 0)
        r = self.sisi("workers", "fact", "muse/beta-1", "--price", "3",
                      "--source", "test fixture pricing page", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        prices = json.load(open(os.path.join(self.data, "worker-prices.json")))
        entry = prices["models"]["muse/beta-1"]
        self.assertEqual(entry["cost_per_million_tokens"], 3)
        self.assertEqual(entry["source"], "test fixture pricing page")
        self.assertTrue(entry["date"])

    def test_fact_score_is_stored(self):
        r = self.sisi("workers", "fact", "muse/beta-1", "--score", "70",
                      "--source", "test fixture benchmark", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        prior = json.load(open(os.path.join(self.data, "model-strength.json")))
        self.assertEqual(prior["models"]["muse/beta-1"]["standing"], 70)
        self.assertNotIn("score", prior["models"]["muse/beta-1"])

    def test_avoid_and_prefer_are_honoured(self):
        """A user's own avoid/prefer constraints shape the recommendation."""
        self.sisi("workers", "fact", "muse/beta-1", "--price", "1", "--source", "fixture", env=self.env())
        self.sisi("workers", "fact", "muse/beta-2", "--price", "2", "--source", "fixture", env=self.env())
        plain = self.sisi("route", "--kind", "impl", "--difficulty", "2", env=self.env())
        self.assertEqual(plain.returncode, 0, plain.stderr)
        self.assertEqual(plain.stdout.splitlines()[0], "muse/beta-1")
        r = self.sisi("workers", "avoid", "beta-1", "--why", "fixture reason", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        after = self.sisi("route", "--kind", "impl", "--difficulty", "2", "--explain", env=self.env())
        self.assertEqual(after.returncode, 0, after.stderr)
        self.assertEqual(after.stdout.splitlines()[0], "muse/beta-2")
        self.assertIn("fixture reason", after.stdout)


class RouteTests(OrchCase):
    def test_route_names_a_mechanism(self):
        """R-7.1-1: the recommendation says how to start the worker."""
        r = self.sisi("route", "--kind", "impl", "--difficulty", "2", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("mechanism:", r.stdout)

    def _big_catalogue(self, n=2000):
        names = ["m-%d" % i for i in range(n)] + ["contributor-%d" % i for i in range(40)]
        script = FAKE_TOOL.replace('echo "beta-1"; echo "beta-2";', " ".join('echo "%s";' % x for x in names))
        with open(os.path.join(self.bindir, "muse"), "w") as f:
            f.write(script)

    def test_explain_stays_short_with_a_huge_catalogue(self):
        """R-7.2-1: --explain prints at most 20 lines and 3 example names per reason group,
        and still shows every reason group, however many catalogue models were passed over."""
        self._big_catalogue()
        self.sisi("workers", "avoid", "m-7", "--why", "fixture avoid", env=self.env())
        r = self.sisi("route", "--kind", "impl", "--difficulty", "2", "--explain", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertLessEqual(len(lines), 20, r.stdout[:2000])
        self.assertTrue(lines[0].startswith("muse/"))
        self.assertIn("mechanism:", r.stdout)
        self.assertIn("cold start", r.stdout)
        self.assertIn("worker facts", r.stdout)
        groups = [l for l in lines if l.startswith("passed over")]
        for l in groups:
            self.assertLessEqual(len(re.findall(r"muse/[\w-]+", l.split("):")[0])), 3, l)
        text = "\n".join(groups)
        self.assertIn("contributor", text)   # the training-tier reason group
        self.assertIn("fixture avoid", text)  # the user's avoid-pattern group
        self.assertIn("equal on price and load", text)  # the bulk group

    def test_explain_line_budget_holds_with_many_distinct_reasons(self):
        """R-7.2-1: when reasons alone would overflow, groups merge into one line that still
        names every reason with its count."""
        from sisi import routing
        passed = [("w%d" % i, "reason number %d" % (i % 40)) for i in range(400)]
        result = {"choice": None, "passed_over": passed, "stats": {}}
        lines = routing.explain_choice(result, "impl", 2)
        self.assertLessEqual(len(lines) + 5, 20)
        text = "\n".join(lines)
        for k in range(40):
            self.assertIn("reason number %d" % k, text)

    def test_unpriced_catalogue_models_are_not_candidates(self):
        """Candidates need a judged record, a price or a benchmark prior."""
        self.seed_attempts([self.attempt("j%d" % i) for i in range(8)])
        r = self.sisi("route", "--kind", "impl", "--difficulty", "2", "--explain", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines()[0], "muse/beta-1")
        self.assertNotIn("beta-2\" is chosen", r.stdout)

    def test_cost_is_estimated_from_facts(self):
        """R-7.3-1: tokens without a reported cost get an estimated cost from known prices."""
        self.sisi("workers", "fact", "muse/beta-1", "--price", "2", "--source", "fixture", env=self.env())
        p = os.path.join(self.proj, "b.md")
        open(p, "w").write(valid_brief())
        r = self.sisi("delegate", "--kind", "read", "--difficulty", "1", "--brief", p,
                      "--worker", "muse/beta-1", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        runs = [x for x in self.ledger() if x.get("kind") == "run"]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["tokens"], 2000000)
        self.assertEqual(runs[0]["cost"], 4.0)
        self.assertEqual(runs[0]["cost_class"], "estimated")


class DigestTests(OrchCase):
    def test_workers_shows_three_tables_and_thin_marks(self):
        """R-7.2-3: the judged record is shown honestly, thin rows marked, checks named."""
        rows = [self.attempt("a%d" % i, check="tests") for i in range(8)]
        rows.append(self.attempt("r1", outcome="rejected", check="read"))
        rows.append(self.attempt("r2", retry_of="r1"))
        rows.append({"kind": "amend", "id": "a0", "ts": round(time.time()), "note": "later wrong"})
        self.seed_attempts(rows)
        r = self.sisi("workers", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Workers by task", r.stdout)
        self.assertIn("What fixed each rejection", r.stdout)
        self.assertIn("Difficulty guesses", r.stdout)
        self.assertIn("Checked well", r.stdout)

    def test_delegations_for_project_reports_overlap(self):
        """Scorecard seam: delegations for a project in a window, with overlap (parallelism)."""
        from sisi import workers
        now = time.time()
        rows = [self.attempt("p1", minutes=20, ts=round(now - 600)),
                self.attempt("p2", minutes=20, ts=round(now - 300))]
        self.seed_attempts(rows)
        got = workers.delegations_for_project("proj", now - 3600, now + 60)
        self.assertEqual(got["count"], 2)
        self.assertEqual(got["overlapping_pairs"], 1)
        got2 = workers.delegations_for_project("proj", now + 3600, now + 7200)
        self.assertEqual(got2["count"], 0)


class ExplorationTests(unittest.TestCase):
    def test_one_low_stakes_task_in_ten_tries_the_cheaper_thin_worker(self):
        """About one difficulty-1 task in ten explores a cheaper thin-record worker."""
        from sisi import routing
        cands = [
            {"worker": "tool/alpha-1", "tool": "tool", "model": "alpha-1", "maker": "alpha",
             "plan": "per-use", "cost": 5.0, "allowance_pct_left": None, "usable": True,
             "aliases": ["tool/alpha-1", "alpha-1"]},
            {"worker": "tool/beta-1", "tool": "tool", "model": "beta-1", "maker": "beta",
             "plan": "per-use", "cost": 5.0, "allowance_pct_left": None, "usable": True,
             "aliases": ["tool/beta-1", "beta-1"]},
        ]
        # Same price: alpha (proven, stronger prior) is the usual pick. Every tenth judged
        # attempt for the kind and difficulty, the thin-record beta gets the task instead.
        cands[0]["standing"] = 90.0
        cands[1]["standing"] = 10.0
        records = [{"kind": "attempt", "id": "e%d" % i, "type": "read", "difficulty": 1,
                    "worker": "tool/alpha-1", "outcome": "accepted", "check": "tests"}
                   for i in range(9)]
        before = routing.choose(cands, records[:-1], {}, "read", 1, now=1000.0)
        self.assertEqual(before["choice"]["worker"], "tool/alpha-1")
        tenth = routing.choose(cands, records, {}, "read", 1, now=1000.0)
        self.assertEqual(tenth["choice"]["worker"], "tool/beta-1")
        self.assertEqual(tenth["explored"], "tool/alpha-1")
        again = routing.choose(cands, records, {}, "read", 1, now=1000.0)
        self.assertEqual(again["choice"]["worker"], "tool/beta-1", "deterministic for one record")


class GenericTests(unittest.TestCase):
    def test_no_model_names_or_prices_in_product_files(self):
        """The product ships no model id, model-family name or price."""
        forbidden = ["haiku", "sonnet", "opus", "fable", "muse-wonder", "muse-ember",
                     "muse-spark", "gpt-", "glm-", "deepseek", "mimo-", "opencode-go/",
                     "_MAKER_ALIASES"]
        for rel in ("sisi/workers.py", "sisi/routing.py", "sisi/brief.py",
                    "canon/orchestration.md", "docs/workers.md"):
            text = open(os.path.join(REPO, rel), encoding="utf-8").read().lower()
            for bad in forbidden:
                self.assertNotIn(bad, text, "%s in %s" % (bad, rel))
            self.assertIsNone(re.search(r"\$\d", text), "a price in %s" % rel)

    def test_guide_prints_the_playbook(self):
        text = open(os.path.join(REPO, "canon", "orchestration.md"), encoding="utf-8").read()
        self.assertLessEqual(len(text.splitlines()), 120)


if __name__ == "__main__":
    unittest.main()
