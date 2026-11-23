"""Model lines in the worker commands: the class a lead agent records beats the parser, and `sisi workers`
shows maker, class and recency for each routable worker. Fixtures are invented ids shaped like real ones.
Requirement ids: R-7.2-1, R-7.2-3."""
import json, os, unittest
from support import *


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

    def env(self):
        return dict(PATH="")

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


if __name__ == "__main__":
    unittest.main()
