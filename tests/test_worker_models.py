"""Model lines in the worker commands: the class a lead agent records beats the parser, and `sisi workers`
shows maker, class and recency for each routable worker. Fixtures are invented ids shaped like real ones.
Requirement ids: R-7.2-1, R-7.2-3."""
import json, os, stat, unittest
from support import *

FAKE_MUSE = """#!/bin/sh
case "$1" in
  exec)
    if [ "$2" = "--list-models" ]; then for m in $MUSE_MODELS; do echo "$m"; done; exit 0; fi
    echo done ;;
  *) echo help ;;
esac
exit 0
"""


class ModelCase(SisiCase):
    def seed(self, spec, type="impl", difficulty=2):
        """spec: [(worker, attempts, accepted)]"""
        os.makedirs(self.data, exist_ok=True)
        n = len(self.rows())
        with open(os.path.join(self.data, "delegations.jsonl"), "a") as f:
            for worker, attempts, accepted in spec:
                for i in range(attempts):
                    n += 1
                    f.write(json.dumps({"kind": "attempt", "id": "m%d" % n, "ts": 1760000000 + n, "project": "p",
                                        "type": type, "difficulty": difficulty, "worker": worker,
                                        "outcome": "accepted" if i < accepted else "rejected",
                                        "check": "tests", "minutes": 5}) + "\n")

    def rows(self):
        p = os.path.join(self.data, "delegations.jsonl")
        return open(p).read().splitlines() if os.path.exists(p) else []

    def env(self, models=None):
        """No tool at all, or a fake `muse` tool that lists `models`."""
        if models is None:
            return dict(PATH="")
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir, exist_ok=True)
        path = os.path.join(bindir, "muse")
        open(path, "w").write(FAKE_MUSE)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        return dict(PATH=bindir, MUSE_MODELS=" ".join(models))

    def route(self, difficulty=1, *extra, models=("abc-5.3", "abc-5.4")):
        r = self.sisi("route", "--kind", "impl", "--difficulty", str(difficulty), *extra, env=self.env(models))
        return r

    def listing(self):
        r = self.sisi("workers", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout


class FactTests(ModelCase):
    def test_a_class_fact_is_recorded_with_its_source_and_shown(self):
        """R-7.2-3: the lead agent's decision about a model is stored, with its source, and shown."""
        self.seed([("prov/abc-6.2-sol", 9, 9), ("prov/abc-5.3", 9, 9)])
        before = self.listing()
        self.assertIn("prov/abc-6.2-sol: class unknown", before)
        self.assertIn("prov/abc-5.3: maker abc, class standard (a guess read from the id)", before)
        r = self.sisi("workers", "fact", "prov/abc-6.2-sol", "--class", "sol", "--released", "2026-11-01",
                      "--source", "lead agent, read the maker's page", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        stored = json.load(open(os.path.join(self.data, "worker-models.json")))["models"]["prov/abc-6.2-sol"]
        self.assertEqual((stored["class"], stored["released"], stored["source"]),
                         ("sol", "2026-11-01", "lead agent, read the maker's page"))
        after = self.listing()
        self.assertIn("prov/abc-6.2-sol: maker abc, class sol (recorded); released 2026-11-01 (recorded), version 6.2", after)

    def test_a_recorded_class_beats_the_parser(self):
        self.seed([("prov/abc-5.3-flash", 9, 9)])
        self.assertIn("class flash (a guess", self.listing())
        self.sisi("workers", "fact", "prov/abc-5.3-flash", "--class", "standard", "--source", "lead", env=self.env())
        self.assertIn("class standard (recorded)", self.listing())

    def test_bad_input_is_refused_and_nothing_is_recorded(self):
        self.seed([("prov/abc-5.3", 9, 9)])
        for args in (("--class", "sol"), ("--class", "so l", "--source", "x"), ("--released", "next week", "--source", "x"),
                     ("--released", "2026-13-40", "--source", "x")):
            r = self.sisi("workers", "fact", "prov/abc-5.3", *args, env=self.env())
            self.assertEqual(r.returncode, 1, args)
        self.assertFalse(os.path.exists(os.path.join(self.data, "worker-models.json")))

    def test_the_fact_file_is_committed_with_the_other_worker_data(self):
        self.seed([("prov/abc-5.3", 9, 9)])
        self.sisi("workers", "fact", "prov/abc-5.3", "--class", "standard", "--source", "lead", env=self.env())
        import subprocess
        out = subprocess.run(["git", "status", "--porcelain"], cwd=self.data, capture_output=True, text=True).stdout
        self.assertNotIn("worker-models.json", out)


class RouteSupersessionTests(ModelCase):
    def setUp(self):
        super().setUp()
        self.priced = False

    def route(self, difficulty=1, *extra, models=("abc-5.3", "abc-5.4")):
        if not self.priced:   # a model is routable once it has a record, a price or a standing
            self.priced = True
            for w, price in (("muse/abc-5.3", "0.5"), ("muse/abc-5.4", "1")):   # the older is the cheaper
                self.sisi("workers", "fact", w, "--price", price, "--source", "fixture", env=self.env(models))
        return super().route(difficulty, *extra, models=models)

    def test_route_uses_the_newest_version_though_the_older_has_the_record(self):
        """R-7.2-1: the newest usable version of a class is always taken; --explain says what it replaced."""
        self.seed([("muse/abc-5.3", 30, 30)], difficulty=1)
        r = self.route(1, "--explain")
        self.assertEqual(r.stdout.splitlines()[0], "muse/abc-5.4", r.stdout)
        self.assertIn("superseded by muse/abc-5.4", r.stdout)

    def test_the_older_version_is_back_while_the_newer_is_marked_down(self):
        self.seed([("muse/abc-5.3", 30, 30)], difficulty=1)
        self.route(1)
        self.sisi("workers", "down", "muse/abc-5.4", "--reason", "limit", "--until", "2099-01-02", env=self.env(("abc-5.3", "abc-5.4")))
        self.assertEqual(self.route(1).stdout.splitlines()[0], "muse/abc-5.3")
        self.sisi("workers", "up", "muse/abc-5.4", env=self.env(("abc-5.3", "abc-5.4")))
        self.assertEqual(self.route(1).stdout.splitlines()[0], "muse/abc-5.4")

    def test_only_recorded_classes_when_the_config_says_so(self):
        self.seed([("muse/abc-5.3", 30, 30)], difficulty=1)
        os.makedirs(self.data, exist_ok=True)
        json.dump({"route": {"supersede_guessed": False}}, open(os.path.join(self.data, "config.json"), "w"))
        self.assertEqual(self.route(1).stdout.splitlines()[0], "muse/abc-5.3")
        for w in ("muse/abc-5.3", "muse/abc-5.4"):
            self.sisi("workers", "fact", w, "--class", "standard", "--source", "lead", env=self.env(("abc-5.3", "abc-5.4")))
        self.assertEqual(self.route(1).stdout.splitlines()[0], "muse/abc-5.4")

    def test_the_lead_agent_is_asked_once_for_a_class_that_cannot_be_read_and_then_not(self):
        """A class read with confidence raises no question; an unreadable one does, in one line, until recorded."""
        models = ("abc-6.2-sol", "abc-6.3-luna")
        self.seed([("muse/abc-6.2-sol", 12, 12), ("muse/abc-6.3-luna", 12, 12)], difficulty=1)
        r = self.route(1, models=models)
        asks = [l for l in r.stdout.splitlines() if "cannot be read from its id" in l]
        self.assertEqual(len(asks), 1, r.stdout)
        self.assertLessEqual(len(r.stdout.splitlines()), 7, r.stdout)
        for w, c in (("muse/abc-6.2-sol", "sol"), ("muse/abc-6.3-luna", "luna")):
            self.sisi("workers", "fact", w, "--class", c, "--maker", "abc", "--source", "lead", env=self.env(models))
        self.assertNotIn("cannot be read", self.route(1, models=models).stdout)
        self.seed([("muse/abc-5.3", 12, 12), ("muse/abc-5.4", 12, 12)], difficulty=1)
        self.assertNotIn("cannot be read", self.route(1).stdout)


if __name__ == "__main__":
    unittest.main()
