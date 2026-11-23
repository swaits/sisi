import json, unittest
from support import *


class EvidenceTests(SisiCase):
    """R-5.6-1, R-5.6-4: a failed check keeps the lines that identify the failure, not only the tail of its output."""

    NOISE = "for i in $(seq 1 300); do echo \"summary noise $i\"; done"

    def test_a_failure_300_lines_above_the_end_is_in_the_stored_result_and_the_report(self):
        cmd = "echo 'FAIL: test_alpha (mod.T.test_alpha)'; echo 'AssertionError: 1 != 2'; %s; exit 1" % self.NOISE
        r = self.sisi("verify") if self.write_contract(contract([check("t", cmd)])) is None else None
        self.assertEqual(r.returncode, 1)
        row = [x for x in self.results() if x["check"] == "t"][0]
        self.assertEqual(row["status"], "failed")
        self.assertIn("FAIL: test_alpha (mod.T.test_alpha)", row["evidence"])
        self.assertIn("AssertionError: 1 != 2", row["evidence"])
        self.assertLess(len(row["evidence"]), 3100)
        shown = r.stdout[r.stdout.index("FAILED:"):]
        self.assertIn("test_alpha", shown)
        self.assertLess(shown.index("test_alpha"), shown.index("summary noise 300"))

    def test_each_known_runner_keeps_its_failing_test_names(self):
        from sisi import verify as V
        outputs = {
            "unittest": ("FAIL: test_a (m.T.test_a)\n----\nTraceback\nAssertionError: x\n" + "ok\n" * 200 + "FAILED (failures=1)", "test_a (m.T.test_a)"),
            "pytest": ("_____ test_b _____\nE   assert 1 == 2\n" + "x\n" * 200 + "FAILED tests/t.py::test_b - assert 1 == 2", "tests/t.py::test_b"),
            "cargo": ("test tests::c ... FAILED\n---- tests::c stdout ----\nthread 'tests::c' panicked at src/l.rs:1:1:\n" + "x\n" * 200 + "test result: FAILED", "tests::c"),
            "go": ("--- FAIL: TestD (0.00s)\n    d_test.go:9: want 1 got 2\n" + "x\n" * 200 + "FAIL\tpkg", "TestD"),
            "jest": ("  ● suite › case e\n    Expected: 1\n    Received: 2\n" + "x\n" * 200 + "Tests: 1 failed", "case e"),
        }
        for name, (text, want) in outputs.items():
            with self.subTest(name):
                ev = V.evidence(text)
                self.assertIn(want, ev)
                self.assertNotIn("\nx\nx\nx", ev)

    def test_unknown_output_keeps_the_first_and_last_30_lines_bounded_and_scrubbed(self):
        from sisi import verify as V
        text = "\n".join(["line %d" % i for i in range(1, 401)] + ["password=hunter2hunter2"])
        ev = V.evidence(text)
        self.assertIn("line 1\n", ev + "\n")
        self.assertIn("line 30\n", ev + "\n")
        self.assertNotIn("line 31\n", ev + "\n")
        self.assertIn("line 400", ev)
        self.assertNotIn("hunter2", ev)
        self.assertLessEqual(len(V.evidence("y" * 100000)), V.EVIDENCE_CHARS)

    def test_a_timeout_keeps_what_it_had_printed(self):
        c = contract([check("slow", "echo 'FAIL: test_slow (m.T.test_slow)'; sleep 5", timeout_s=0.5)])
        self.write_contract(c)
        self.sisi("verify")
        row = [x for x in self.results() if x["check"] == "slow"][0]
        self.assertEqual(row["status"], "not-run")
        self.assertIn("test_slow", row["evidence"])

    def test_a_passing_check_stores_no_evidence(self):
        self.write_contract(contract([check("ok", "echo fine; test -d .")]))
        self.sisi("verify")
        self.assertEqual([x["evidence"] for x in self.results() if x["check"] == "ok"], [""])


class VerifyTests(SisiCase):
    def run_verify(self, c, *extra):
        self.write_contract(c)
        return self.sisi("verify", *extra)

    def statuses(self):
        return {r["check"]: r["status"] for r in self.results()}

    def test_statuses(self):
        # R-5.6-2, R-5.6-3: five statuses only. A timeout is not-run (timed out) and a
        # human check is not-run (needs human): neither is ever reported as passed.
        c = contract([check("ok", "true"), check("bad", "exit 3"), check("slow", "sleep 5", timeout_s=0.3),
                      check("out", "python3 -c \"print('hello')\"", stdout_contains="hello"), check("out2", "echo hi", stdout_contains="zzz"),
                      check("code", "exit 3", exit=3), human("h5", 5), human("h6", 6)],
                     [check("inv", "true")])
        r = self.run_verify(c)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.statuses(), {"ok": "passed", "bad": "failed", "slow": "not-run", "out": "passed",
                                           "out2": "failed", "code": "passed", "h5": "not-run",
                                           "h6": "not-run", "inv": "passed"})
        self.assertIn("not-run (needs human)", r.stdout)
        self.assertIn("not-run (timed out)", r.stdout)
        reasons = {x["check"]: x.get("reason") for x in self.results()}
        self.assertEqual((reasons["slow"], reasons["h5"]), ("timed out", "needs human"))

    def test_all_good_exit_zero_and_record_fields(self):
        r = self.run_verify(contract([check("ok", "true"), human("h")]))
        self.assertEqual(r.returncode, 0, r.stdout)
        rec = self.results()[0]
        for k in ("contract", "project", "check", "kind", "rung", "status", "duration_s", "ts", "tool"):
            self.assertIn(k, rec)
        r = self.sisi("verify", env={"SISI_TOOL": "codex"})
        self.assertEqual(self.results()[-1]["tool"], "codex")

    def test_invariant_failure_fails(self):
        r = self.run_verify(contract([check("ok", "true")], [check("inv", "false")]))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.statuses()["inv"], "failed")

    def test_runs_in_project_dir(self):
        r = self.run_verify(contract([check("pwd", "pwd", stdout_contains=self.proj)]))
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_no_contract_exit_2(self):
        self.assertEqual(self.sisi("verify").returncode, 2)

    def test_invalid_contract_exit_1(self):
        self.assertEqual(self.run_verify({"id": "x"}).returncode, 1)

    def test_json_output(self):
        r = self.run_verify(contract([check("ok", "true")]), "--json")
        d = json.loads(r.stdout)
        self.assertTrue(d["ok"])
        self.assertEqual(d["results"][0]["status"], "passed")

    def test_timeout_kills_process_group(self):
        marker = self.tmp + "/survivor"
        c = contract([check("slow", "(sleep 0.35; touch %s) & sleep 30" % marker, timeout_s=0.3)])
        self.assertEqual(self.run_verify(c).returncode, 1)
        import time; time.sleep(0.7)
        import os
        self.assertFalse(os.path.exists(marker))


if __name__ == "__main__":
    unittest.main()
