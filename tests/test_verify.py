import json, unittest
from support import *


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
                      check("out", "echo hello", stdout_contains="hello"), check("out2", "echo hi", stdout_contains="zzz"),
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

    def test_floor_fails(self):
        r = self.run_verify(contract([check("m", "true", rung=3, kind="money")]))
        self.assertEqual(r.returncode, 1)
        self.assertIn("floor", r.stdout)
        r = self.run_verify(contract([check("m", "true", rung=2, kind="money")]))
        self.assertEqual(r.returncode, 0)

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
