import json, os, random, stat, time, unittest
from support import *

FAKE_CODEX = """#!/bin/sh
case "$1 $2" in
  "debug models") echo '{"models":[{"slug":"alpha-1"},{"slug":"alpha-contributor-x"}]}' ;;
  "exec "*) echo '{"type":"error","error":{"type":"provider.go-limit","message":"monthly usage limit reached","status":429,"retryAfterMs":60000}}' ;;
  *) echo 'codex help' ;;
esac
exit 0
"""

FAKE_MUSE = """#!/bin/sh
case "$1" in
  exec)
    if [ "$2" = "--list-models" ]; then echo "beta-1"; echo "beta-2"; exit 0; fi
    echo "worker final report: done ok" ;;
  usage) echo '{"allowance":{"tier":"flat plan","weekly":{"usedPercent":25},"window":{"usedPercent":10}}}' ;;
  *) echo 'muse help' ;;
esac
exit 0
"""

FAKE_CURSOR = """#!/bin/sh
echo "Error: Authentication required. Run 'agent login' to sign in" >&2
exit 0
"""

FAKE_CLAUDE = """#!/bin/sh
echo "claude final report"
exit 0
"""


class WorkerCase(SisiCase):
    def setUp(self):
        super().setUp()
        self.bindir = os.path.join(self.tmp, "bin")
        os.makedirs(self.bindir)
        for name, body in (("codex", FAKE_CODEX), ("muse", FAKE_MUSE), ("cursor-agent", FAKE_CURSOR),
                           ("claude", FAKE_CLAUDE)):
            p = os.path.join(self.bindir, name)
            with open(p, "w") as f:
                f.write(body)
            os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)

    def env(self, **kw):
        return dict(PATH=self.bindir, **kw)

    def write_data(self, name, obj):
        os.makedirs(self.data, exist_ok=True)
        with open(os.path.join(self.data, name), "w") as f:
            json.dump(obj, f)

    def brief(self):
        p = os.path.join(self.proj, "brief.md")
        open(p, "w").write(
            "You are a worker.\n\n"
            "## Outcome and scope\nDo the toy task.\n\n"
            "## Context and sources of truth\nThis brief.\n\n"
            "## Constraints and interfaces\nNone.\n\n"
            "## Acceptance\nThe final report says done.\n\n"
            "## Deliverables and report format\nA short report.\n\n"
            "## Files you may change\ntoy.txt only.\n\n"
            "## Verification\nNone needed.\n\n"
            "## Budget and escalation\nFive minutes; escalate if blocked.\n")
        return p


class DiscoveryTests(WorkerCase):
    def test_workers_lists_tools_models_and_reasons(self):
        r = self.sisi("workers", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("codex", r.stdout)
        self.assertIn("alpha-1", r.stdout)
        self.assertIn("beta-1", r.stdout)
        self.assertIn("allowance left", r.stdout)  # muse usage reported 75% weekly left
        self.assertIn("cursor-agent", r.stdout)
        self.assertIn("not logged in", r.stdout.lower())
        self.assertIn("models learned by use", r.stdout)  # tools with no listing command

    def test_discovery_is_cached_in_personal_store(self):
        self.sisi("workers", env=self.env())
        cache = json.load(open(os.path.join(self.data, "workers.json")))
        self.assertIn("checked", cache)
        tools = {t["name"]: t for t in cache["tools"]}
        self.assertIn("alpha-1", tools["codex"]["models"])
        self.assertFalse(tools["cursor-agent"]["usable"])


class LedgerImportTests(WorkerCase):
    def test_existing_ledger_imported_once_losslessly(self):
        src = os.path.join(self.tmp, "orch-log.jsonl")
        rows = [
            {"kind": "attempt", "id": "abc123", "ts": 1700000000, "project": "p", "type": "impl",
             "difficulty": 2, "worker": "beta-1", "outcome": "accepted", "check": "tests",
             "minutes": 3, "tokens": None, "retry_of": None, "note": "keep me", "extra": [1, 2]},
            {"kind": "attempt", "id": "def456", "ts": 1700000100, "project": "p", "type": "impl",
             "difficulty": 2, "worker": "beta-1", "outcome": "rejected", "check": "read",
             "minutes": 4, "tokens": 9, "retry_of": "abc123", "note": None},
            {"kind": "amend", "id": "abc123", "ts": 1700000200, "note": "later wrong"},
        ]
        with open(src, "w") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
        before = open(src).read()
        r = self.sisi("workers", env=self.env(SISI_LEDGER=src))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("imported 3 rows", r.stdout)
        self.assertEqual(open(src).read(), before, "the original ledger must not be modified")
        got = [json.loads(l) for l in open(os.path.join(self.data, "delegations.jsonl"))]
        self.assertEqual(len(got), 3)
        for want, have in zip(rows, got):
            for k, v in want.items():
                self.assertEqual(have.get(k), v, k)
        # a second run imports nothing more
        self.sisi("workers", env=self.env(SISI_LEDGER=src))
        got2 = [json.loads(l) for l in open(os.path.join(self.data, "delegations.jsonl"))]
        self.assertEqual(len(got2), 3)


class RouteTests(WorkerCase):
    def test_route_explains_and_skips_contributor_and_logged_out(self):
        r = self.sisi("route", "--kind", "impl", "--difficulty", "2", "--explain", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("contributor-x", r.stdout.splitlines()[0])
        self.assertIn("contributor", r.stdout)  # named as passed over
        self.assertIn("cursor-agent", r.stdout)

    def test_route_review_picks_another_maker(self):
        r = self.sisi("route", "--kind", "review", "--difficulty", "1", "--review-of", "codex/alpha-1",
                      "--explain", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("alpha", r.stdout.splitlines()[0])


class DelegateTests(WorkerCase):
    def test_limit_with_success_exit_is_unavailability_and_retries_next(self):
        r = self.sisi("delegate", "--kind", "impl", "--difficulty", "2", "--brief", self.brief(),
                      "--worker", "codex/alpha-1", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("worker final report: done ok", r.stdout)  # fell through to muse
        self.assertIn("sisi delegate judge", r.stdout)
        avail = json.load(open(os.path.join(self.data, "worker-availability.json")))
        self.assertTrue(any("alpha" in k or k == "codex" for k in avail), avail)
        entries = list(avail.values())
        self.assertEqual(entries[0]["reason"], "limit")
        self.assertGreater(entries[0]["retry_at"], time.time())
        # the limit failure is not recorded as bad work
        recs = [json.loads(l) for l in open(os.path.join(self.data, "delegations.jsonl"))]
        attempts = [x for x in recs if x.get("kind") == "attempt"]
        self.assertEqual(attempts, [])
        runs = [x for x in recs if x.get("kind") == "run"]
        self.assertEqual(len(runs), 1)
        self.assertTrue(os.path.isfile(runs[0]["transcript"]))

    def test_unjudged_run_shows_then_judge_records_attempt(self):
        r = self.sisi("delegate", "--kind", "read", "--difficulty", "1", "--brief", self.brief(),
                      "--worker", "muse/beta-1", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        w = self.sisi("workers", env=self.env())
        self.assertIn("waiting for a judgement", w.stdout)
        recs = [json.loads(l) for l in open(os.path.join(self.data, "delegations.jsonl"))]
        run = [x for x in recs if x.get("kind") == "run"][0]
        j = self.sisi("delegate", "judge", run["id"], "--outcome", "accepted", "--check", "tests",
                      "--minutes", "2", env=self.env())
        self.assertEqual(j.returncode, 0, j.stderr)
        recs = [json.loads(l) for l in open(os.path.join(self.data, "delegations.jsonl"))]
        attempts = [x for x in recs if x.get("kind") == "attempt"]
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["type"], "read")
        self.assertEqual(attempts[0]["check"], "tests")
        w2 = self.sisi("workers", env=self.env())
        self.assertNotIn("waiting for a judgement", w2.stdout)

    def test_no_bypass_flag_is_passed(self):
        marker = os.path.join(self.tmp, "argv.txt")
        p = os.path.join(self.bindir, "muse")
        open(p, "w").write("#!/bin/sh\necho \"$@\" > %s\ncase \"$1\" in exec) [ \"$2\" = \"--list-models\" ] && echo beta-1 && exit 0;; esac\necho ok-report\n" % marker)
        os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
        r = self.sisi("delegate", "--kind", "read", "--difficulty", "1", "--brief", self.brief(),
                      "--worker", "muse/beta-1", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = open(marker).read()
        for bad in ("--yolo", "--disable-approval", "--disable-sandbox", "bypass", "dangerously"):
            self.assertNotIn(bad, argv)


class SessionModelTests(WorkerCase):
    def seed_strength(self, scores):
        self.write_data("model-strength.json", {"models": {
            m: {"score": s, "source": "test fixture", "date": "2000-01-01"} for m, s in scores.items()}})
        self.write_data("workers.json", {"checked": time.time(), "tools": [
            {"name": "muse", "usable": True, "models": ["beta-1", "beta-2"]},
            {"name": "codex", "usable": True, "models": ["alpha-1"]}]})

    def tick(self, payload):
        return self.sisi("tick", stdin=json.dumps(payload))

    def test_hookio_keeps_model(self):
        from sisi import hookio
        n = hookio.normalize("codex", {"session_id": "s", "cwd": "/w", "model": "alpha-1"})
        self.assertEqual(n.get("model"), "alpha-1")

    def test_tick_stores_model_and_strong_line(self):
        self.seed_strength({"beta-1": 95, "alpha-1": 60})
        r = self.tick({"session_id": "strong-1", "cwd": self.proj, "source": "startup", "model": "beta-1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = json.load(open(os.path.join(self.state, "sessions", "strong-1.json")))
        self.assertEqual(rec.get("model"), "beta-1")
        self.assertIn("sisi delegate", r.stdout)
        self.assertIn("strongest", r.stdout)

    def test_tick_weak_line_names_stronger(self):
        self.seed_strength({"beta-1": 95, "alpha-1": 60})
        r = self.tick({"session_id": "weak-1", "cwd": self.proj, "source": "startup", "model": "alpha-1"})
        self.assertIn("do the work yourself", r.stdout)
        self.assertIn("beta-1", r.stdout)

    def test_tick_subagent_gets_no_delegation_line(self):
        self.seed_strength({"beta-1": 95})
        r = self.tick({"session_id": "sub-1", "cwd": self.proj, "source": "startup",
                       "model": "beta-1", "agent_id": "agent-7"})
        self.assertNotIn("sisi delegate", r.stdout)
        self.assertNotIn("do the work yourself", r.stdout)

    def test_tick_unknown_strength_says_so(self):
        r = self.tick({"session_id": "unk-1", "cwd": self.proj, "source": "startup", "model": "mystery-9"})
        self.assertIn("unknown", r.stdout.lower())


class RoutingPropertyTests(unittest.TestCase):
    def test_choice_invariants_over_generated_records(self):
        from sisi import routing
        rng = random.Random(20261123)
        makers = ["alpha", "beta", "gamma"]
        for _ in range(200 * ITERS):
            cands, records, avail = [], [], {}
            now = 1000000.0
            for i in range(rng.randint(0, 7)):
                maker = rng.choice(makers)
                model = "%s-m%d%s" % (maker, i, "-contributor-z" if rng.random() < 0.15 else "")
                w = "tool%d/%s" % (i, model)
                cands.append({"worker": w, "tool": "tool%d" % i, "model": model, "maker": maker,
                              "plan": rng.choice(["flat", "per-use", None]),
                              "cost": rng.choice([None, 1.0, 5.0, 20.0]),
                              "allowance_pct_left": rng.choice([None, 0, 40, 90]),
                              "usable": True, "aliases": [w, model]})
                if rng.random() < 0.3:
                    avail[w] = {"reason": "limit", "retry_at": now + 3600, "fails": 1}
                for _ in range(rng.randint(0, 12)):
                    records.append({"kind": "attempt", "id": "r%d" % rng.randint(0, 10 ** 6),
                                    "type": "impl", "difficulty": rng.choice([1, 2, 3]),
                                    "worker": w, "outcome": rng.choice(["accepted", "rejected"]),
                                    "check": "tests", "ts": now - 100})
            author = rng.choice(cands)["worker"] if cands and rng.random() < 0.5 else None
            a = routing.choose(cands, records, avail, "impl", rng.choice([1, 2, 3]),
                               review_of=author, now=now)
            b = routing.choose(cands, records, avail, "impl", 2, review_of=author, now=now)
            again = routing.choose(cands, records, avail, "impl", 2, review_of=author, now=now)
            self.assertEqual((b["choice"] or {}).get("worker"), (again["choice"] or {}).get("worker"),
                             "choice must be deterministic for the same record")
            if a["choice"] is None:
                continue
            w = a["choice"]["worker"]
            self.assertNotIn("contributor", w)
            self.assertNotIn(w, avail, "never picks an unavailable worker")
            if author:
                author_maker = next(c["maker"] for c in cands if c["worker"] == author)
                others = [c for c in cands if c["maker"] != author_maker
                          and "contributor" not in c["worker"] and c["worker"] not in avail
                          and not (c["plan"] == "flat" and c["allowance_pct_left"] == 0)]
                if others:
                    self.assertNotEqual(a["choice"]["maker"], author_maker)


if __name__ == "__main__":
    unittest.main()
