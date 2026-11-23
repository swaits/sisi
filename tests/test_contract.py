import os, unittest
from support import *
from sisi import contract as C


class ContractTests(SisiCase):
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

    def test_floors(self):
        weak = contract([check("m", "true", rung=3, kind="money")])
        self.assertEqual(len(C.floor_failures(weak)), 1)
        self.assertEqual(C.floor_failures(contract([check("m", "true", rung=2, kind="money")])), [])
        # one strong check among weak ones satisfies the floor
        self.assertEqual(C.floor_failures(contract([check("m", "true", rung=3, kind="money"),
                                                    check("n", "true", rung=1, kind="money")])), [])
        self.assertEqual(C.floor_failures(contract([check("u", "true", rung=4, kind="ui")])), [])
        for k in ("concurrency", "parsing", "money", "state-machine", "migration"):
            self.assertEqual(C.floors()[k], 2)

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
