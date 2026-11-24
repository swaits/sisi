"""The worker commands and the model facts: the maker, class and release date a cheap worker researched are
recorded with `sisi workers fact`, shown by `sisi workers`, and drive `sisi route`. sisi reads nothing from a name.
Invented ids. Requirement ids: R-7.2-1, R-7.2-3."""
import json, os, stat, subprocess, unittest
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

    def record(self, worker, cls, released=None, maker="abc", models=None):
        args = ["workers", "fact", worker, "--maker", maker, "--class", cls, "--source", "fixture research"]
        if released:
            args += ["--released", released]
        r = self.sisi(*args, env=self.env(models))
        self.assertEqual(r.returncode, 0, r.stderr)

    def route(self, difficulty=1, *extra, models=("abc-old", "abc-new")):
        return self.sisi("route", "--kind", "impl", "--difficulty", str(difficulty), *extra, env=self.env(models))

    def listing(self):
        r = self.sisi("workers", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout


class FactTests(ModelCase):
    def test_a_maker_class_and_release_date_are_recorded_with_their_source_and_shown(self):
        """R-7.2-3: what a cheap worker researched about a model is stored, with its source, and shown."""
        self.seed([("prov/abc-x", 9, 9)])
        self.assertIn("prov/abc-x: no maker and class recorded", self.listing())
        self.record("prov/abc-x", "flash", "2026-11-01")
        stored = json.load(open(os.path.join(self.data, "worker-models.json")))["models"]["prov/abc-x"]
        self.assertEqual((stored["class"], stored["maker"], stored["released"], stored["source"]),
                         ("flash", "abc", "2026-11-01", "fixture research"))
        self.assertIn("prov/abc-x: maker abc, class flash; released 2026-11-01", self.listing())

    def test_bad_input_is_refused_and_nothing_is_recorded(self):
        self.seed([("prov/abc-x", 9, 9)])
        for args in (("--class", "sol"), ("--class", "so l", "--source", "x"), ("--released", "next week", "--source", "x"),
                     ("--released", "2026-13-40", "--source", "x")):
            self.assertEqual(self.sisi("workers", "fact", "prov/abc-x", *args, env=self.env()).returncode, 1, args)
        self.assertFalse(os.path.exists(os.path.join(self.data, "worker-models.json")))

    def test_the_fact_file_is_committed_with_the_other_worker_data(self):
        self.seed([("prov/abc-x", 9, 9)])
        self.record("prov/abc-x", "flash")
        out = subprocess.run(["git", "status", "--porcelain"], cwd=self.data, capture_output=True, text=True).stdout
        self.assertNotIn("worker-models.json", out)


class RouteSupersessionTests(ModelCase):
    def setUp(self):
        super().setUp()
        self.ready = False

    def route(self, difficulty=1, *extra, models=("abc-old", "abc-new")):
        if not self.ready:   # a model is routable once it has a record, a price or a standing
            self.ready = True
            for w, price, rel in (("muse/abc-old", "0.5", "2026-03-01"), ("muse/abc-new", "1", "2026-09-01")):   # the older is the cheaper
                self.sisi("workers", "fact", w, "--price", price, "--source", "fixture", env=self.env(models))
                self.record(w, "standard", rel, models=models)
        return super().route(difficulty, *extra, models=models)

    def test_route_uses_the_newest_version_though_the_older_has_the_record(self):
        """R-7.2-1: the newest usable version of a class is always taken; --explain says what it replaced."""
        self.seed([("muse/abc-old", 30, 30)], difficulty=1)
        r = self.route(1, "--explain")
        self.assertEqual(r.stdout.splitlines()[0], "muse/abc-new", r.stdout)
        self.assertIn("superseded by muse/abc-new", r.stdout)

    def test_the_older_version_is_back_while_the_newer_is_marked_down(self):
        self.seed([("muse/abc-old", 30, 30)], difficulty=1)
        self.route(1)
        env = self.env(("abc-old", "abc-new"))
        self.sisi("workers", "down", "muse/abc-new", "--reason", "limit", "--until", "2099-01-02", env=env)
        self.assertEqual(self.route(1).stdout.splitlines()[0], "muse/abc-old")
        self.sisi("workers", "up", "muse/abc-new", env=env)
        self.assertEqual(self.route(1).stdout.splitlines()[0], "muse/abc-new")

    def test_the_lead_agent_is_asked_once_for_workers_with_nothing_recorded_and_then_not(self):
        models = ("abc-old", "abc-new")
        self.seed([("muse/abc-old", 12, 12), ("muse/abc-new", 12, 12)], difficulty=1)
        r = self.route(1, models=models)   # route() records facts first
        self.assertNotIn("no maker, class", r.stdout)
        self.seed([("muse/abc-zzz", 12, 12)], difficulty=1)
        r = self.sisi("route", "--kind", "impl", "--difficulty", "1", env=self.env(models + ("abc-zzz",)))
        asks = [l for l in r.stdout.splitlines() if "no maker, class and release date are recorded" in l]
        self.assertEqual(len(asks), 1, r.stdout)
        self.assertIn("muse/abc-zzz", asks[0])
        self.assertLessEqual(len(r.stdout.splitlines()), 7, r.stdout)
        self.record("muse/abc-zzz", "flash", "2026-01-01", models=models + ("abc-zzz",))
        self.assertNotIn("no maker, class", self.sisi("route", "--kind", "impl", "--difficulty", "1",
                                                      env=self.env(models + ("abc-zzz",))).stdout)


class RouteInheritanceTests(ModelCase):
    def setUp(self):
        super().setUp()
        self.ready = False

    def route(self, difficulty=1, *extra, models=("abc-old", "abc-new")):
        if not self.ready:
            self.ready = True
            self.record("muse/abc-old", "standard", "2026-03-01", models=models)
            self.record("muse/abc-new", "standard", "2026-09-01", models=models)
        return super().route(difficulty, *extra, models=models)

    def test_a_new_release_with_no_data_of_its_own_gets_ordinary_work_at_once(self):
        """R-7.2-1: discovered, unpriced, unjudged, yet routable and capable through its predecessor's record."""
        self.seed([("muse/abc-old", 12, 12)], difficulty=2)
        r = self.route(2, "--explain")
        self.assertEqual(r.stdout.splitlines()[0], "muse/abc-new", r.stdout)
        self.assertIn("the record of its predecessor muse/abc-old", r.stdout)
        self.assertLessEqual(len(r.stdout.splitlines()), 20, r.stdout)
        self.assertLessEqual(len(self.route(2).stdout.splitlines()), 6)

    def test_once_it_has_a_thick_record_of_its_own_the_inherited_one_stops_applying(self):
        self.seed([("muse/abc-old", 12, 12), ("muse/abc-new", 9, 9)], difficulty=2)
        r = self.route(2, "--explain")
        self.assertEqual(r.stdout.splitlines()[0], "muse/abc-new", r.stdout)
        self.assertNotIn("predecessor", r.stdout)


if __name__ == "__main__":
    unittest.main()
