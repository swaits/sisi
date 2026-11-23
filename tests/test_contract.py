import os, unittest
from support import *
from sisi import contract as C


class ContractTests(SisiCase):
    def test_the_contract_must_state_its_risk_profile(self):
        """R-5.3-1: `risk.profile` is the agent's own judgement and is required; init writes the floor as its start."""
        good = contract([check("a", "true")])
        for name, risk in (("missing", None), ("empty object", {}), ("unknown", {"profile": "huge"})):
            with self.subTest(name):
                c = dict(good)
                c.pop("risk")
                if risk is not None:
                    c["risk"] = risk
                errs = C.validate(c)
                self.assertTrue(any("risk" in e and "sisi risk" in e and "integration" in e and "release" in e
                                    for e in errs), errs)
        self.assertEqual(C.validate(good), [])
        self.git_init()
        self.assertEqual(self.sisi("contract", "init").returncode, 0)
        c = C.load(os.path.join(self.proj, ".sisi", "contract.json"))
        self.assertIn(c["risk"]["profile"], C.RISK_PROFILES)
        with open(os.path.join(self.proj, "migrations_001.sql"), "w") as f:
            f.write("alter table t add column c int;\n")
        os.remove(os.path.join(self.proj, ".sisi", "contract.json"))
        self.assertEqual(self.sisi("contract", "init").returncode, 0)
        floor = self.sisi("risk", "--json")
        import json as _j
        self.assertEqual(C.load(os.path.join(self.proj, ".sisi", "contract.json"))["risk"]["profile"],
                         _j.loads(floor.stdout)["floor"])
        self.assertNotEqual(_j.loads(floor.stdout)["floor"], "trivial")
        c = C.load(os.path.join(self.proj, ".sisi", "contract.json"))
        c["risk"] = {}
        C.save(os.path.join(self.proj, ".sisi", "contract.json"), c)
        r = self.sisi("contract", "check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("risk.profile", r.stdout)

    def test_skeleton_is_valid_but_fails(self):
        c = C.skeleton("goal")
        self.assertEqual(C.validate(c), [])
        self.assertEqual(self.sisi("contract", "init", "--goal", "make x").returncode, 0)
        self.assertEqual(self.sisi("contract", "check").returncode, 0)
        self.assertEqual(self.sisi("verify").returncode, 1)  # placeholder must not pass
        self.assertEqual(self.sisi("contract", "init").returncode, 1)  # no clobbering

    def test_validation_errors(self):
        good = contract([check("a", "true")])
        self.assertEqual(C.validate(good), [])
        bad = {
            "not an object": [],
            "no checks": dict(good, checks=[]),
            "empty goal": dict(good, goal=" "),
            "bad kind": contract([check("a", "true", kind="nope")]),
            "rung 0": contract([check("a", "true", rung=0)]),
            "rung 7": contract([check("a", "true", rung=7)]),
            "rung bool": contract([check("a", "true", rung=True)]),
            "rung 3 no cmd": contract([human("a", rung=3)]),
            "rung 5 with cmd": contract([dict(check("a", "true"), rung=5)]),
            "no expect.exit": contract([dict(check("a", "true"), expect={})]),
            "bad timeout": contract([check("a", "true", timeout_s=0)]),
            "duplicate ids": contract([check("a", "true"), check("a", "true")]),
            "dup across invariant": contract([check("a", "true")], [check("a", "true")]),
            "invariant no cmd": contract([check("a", "true")], [{"id": "i", "claim": "c", "expect": {"exit": 0}}]),
            "assumptions not strings": dict(good, assumptions=[1]),
            "question w/o default": dict(good, questions=[{"q": "?"}]),
        }
        for name, c in bad.items():
            with self.subTest(name):
                self.assertTrue(C.validate(c), name)

    def test_rung_5_6_valid_without_cmd(self):
        self.assertEqual(C.validate(contract([check("a", "true"), human("h", 5), human("i", 6)])), [])

    def test_find_stops_at_git_root(self):
        self.git_init()
        self.write_contract(contract([check("a", "true")]))
        sub = os.path.join(self.proj, "a", "b")
        os.makedirs(sub)
        self.assertEqual(C.find(sub), os.path.join(self.proj, ".sisi", "contract.json"))
        outer = self.tmp  # a contract above the git root must not be found
        self.write_contract(contract([check("a", "true")]), outer)
        os.remove(os.path.join(self.proj, ".sisi", "contract.json"))
        self.assertIsNone(C.find(sub))


if __name__ == "__main__":
    unittest.main()
