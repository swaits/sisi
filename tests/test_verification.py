"""The verification record (SPEC 5.4-5.6, 6.4): five statuses, refusal of checks that cannot fail,
selection by change, reuse on identical inputs, and the rule that nothing that did not run is
ever reported, stored or summarised as passed."""
import json, os, random, subprocess, unittest
from support import *
from sisi import contract as C, unit as U, verify as V


def real(id, cmd, **kw):
    return dict(check(id, cmd), **kw)


class VacuousChecksTests(SisiCase):
    def refused(self, cmd, **extra):
        c = contract([dict({"id": "v", "claim": "c", "kind": "general", "rung": 3, "cmd": cmd,
                            "expect": {"exit": 0}}, **extra)])
        return [e for e in C.validate(c) if "vacuous" in e]

    def test_vacuous_variants_are_refused(self):
        """R-5.6-3: a check that cannot fail shows nothing, so a contract holding one is invalid."""
        for cmd in ("true", ":", "exit 0", "echo ok", "test 1 = 1", "sh -c true", "bash -c 'exit 0'",
                    "[ 1 = 1 ]", "/bin/true", "true && true", "pytest || true", "make test || :",
                    "exit 0 # fine", "env true", "echo ok;", "sh -c \"sh -c ':'\"", "printf done"):
            self.assertTrue(self.refused(cmd), cmd)

    def test_commands_that_can_fail_are_accepted(self):
        for cmd in ("false", "test -f x", "pytest", "grep -q x f", "echo ok > out.txt", "true && false",
                    "sh -c 'test -f x'", "test 1 = 2", "python3 -c 'print(1)'", "cd src && make"):
            self.assertFalse(self.refused(cmd), cmd)
        self.assertFalse(self.refused("echo hi", expect={"exit": 0, "stdout_contains": "zzz"}))

    def test_an_echo_that_already_prints_what_it_expects_is_vacuous(self):
        """R-5.6-3: stdout_contains against a literal echo is a constant."""
        self.assertTrue(self.refused("echo hello", expect={"exit": 0, "stdout_contains": "hello"}))

    def test_vacuous_check_blocks_contract_check_and_verify(self):
        """R-5.6-3: `sisi contract check` and `sisi verify` both refuse, and nothing is recorded as passed."""
        self.write_contract(contract([dict(check("v", "x"), cmd="sh -c true")]))
        self.assertEqual(self.sisi("contract", "check").returncode, 1)
        r = self.sisi("verify")
        self.assertEqual(r.returncode, 1)
        self.assertIn("vacuous", r.stdout)
        self.assertEqual([x for x in self.results() if x["status"] == "passed"], [])

    def test_invariants_are_held_to_the_same_rule(self):
        """R-5.6-3."""
        c = contract([real("ok", "test -f .sisi/contract.json")], [real("inv", "exit 0")])
        self.assertTrue([e for e in C.validate(c) if "vacuous" in e])


class NewFieldsTests(SisiCase):
    def test_new_optional_fields_validate(self):
        """R-10.2-1: the unit's optional fields are validated by `sisi contract check`."""
        c = contract([real("a", "test -f x", covers="x missing", when_changed=["src/**"], mandatory=True,
                           independent=False)])
        c.update(parent="req-1", scope={"in": ["a"], "out": ["b"]}, deferred=[{"what": "w", "why": "y", "safe_because": "s"}],
                 limitations=["l"], plan=["step"], risk={"profile": "logic", "why": "money"},
                 requirements=[{"id": "q1", "kind": "explicit", "text": "t", "decision": "now", "check": "a"}],
                 approach={"chosen": "c", "why": "w", "alternatives": ["x"], "reuses": ["y"]})
        self.assertEqual(C.validate(c), [])
        bad = json.loads(json.dumps(c))
        bad["checks"][0]["when_changed"] = []
        bad["checks"][0]["mandatory"] = "yes"
        bad["risk"]["profile"] = "huge"
        bad["requirements"][0]["check"] = "nope"
        bad["approach"] = {"chosen": 3, "bogus": 1}
        bad["scope"] = {"in": "x"}
        errs = " | ".join(C.validate(bad))
        for part in ("when_changed", "mandatory", "risk.profile", "nope", "approach.chosen", "unknown key 'bogus'", "scope.in"):
            self.assertIn(part, errs)


class SelectionAndReuseTests(SisiCase):
    def setUp(self):
        super().setUp()
        self.git_init()

    def run_verify(self, c):
        self.write_contract(c)
        return self.sisi("verify", "--json")

    def rows(self, r):
        return {x["id"]: x for x in json.loads(r.stdout)["results"]}

    def test_when_changed_selects_by_change(self):
        """R-6.4-1, R-6.4-2, R-5.4-10: a check runs only when a changed path matches; otherwise it is
        skipped with the reason recorded, never reported as passed."""
        os.makedirs(os.path.join(self.proj, "src"))
        open(os.path.join(self.proj, "src", "a.py"), "w").write("x=1\n")
        subprocess.run(["git", "add", "-A"], cwd=self.proj, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "src"], cwd=self.proj, check=True)
        c = contract([real("src", "test -f src/a.py", when_changed=["src/**"]), real("always", "test -f src/a.py")])
        rows = self.rows(self.run_verify(c))
        self.assertEqual(rows["src"]["status"], "skipped")
        self.assertIn("not affected", rows["src"]["reason"])
        self.assertEqual(rows["always"]["status"], "passed")
        open(os.path.join(self.proj, "src", "a.py"), "w").write("x=2\n")
        rows = self.rows(self.sisi("verify", "--json"))
        self.assertEqual(rows["src"]["status"], "passed")

    def test_a_watch_that_matches_nothing_is_not_applicable_and_not_a_pass(self):
        """R-5.6-2: not-applicable is its own status with a reason."""
        c = contract([real("w", "test -f nope", when_changed=["nothing/**"]), real("a", "test -f .sisi/contract.json")])
        rows = self.rows(self.run_verify(c))
        self.assertEqual(rows["w"]["status"], "not-applicable")
        self.assertIn("no file matches", rows["w"]["reason"])

    def test_all_runs_everything(self):
        """R-6.4-3: --all overrides selection."""
        os.makedirs(os.path.join(self.proj, "src"))
        open(os.path.join(self.proj, "src", "a.py"), "w").write("x=1\n")
        c = contract([real("src", "test -f src/a.py", when_changed=["src/**"])])
        self.git_commit_all()
        self.write_contract(c)
        self.assertEqual(self.rows(self.sisi("verify", "--json"))["src"]["status"], "skipped")
        self.assertEqual(self.rows(self.sisi("verify", "--all", "--json"))["src"]["status"], "passed")

    def git_commit_all(self):
        subprocess.run(["git", "add", "-A"], cwd=self.proj, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"], cwd=self.proj, check=True)

    def test_reuse_on_identical_inputs_and_not_after_a_change(self):
        """R-5.4-9: an identical tree reuses the last pass (skipped, never passed); any change to
        the tree, or to the check's command, runs it again."""
        open(os.path.join(self.proj, "f.txt"), "w").write("1")
        c = contract([real("a", "test -f f.txt")])
        first = self.rows(self.run_verify(c))["a"]
        self.assertEqual(first["status"], "passed")
        again = self.rows(self.sisi("verify", "--json"))["a"]
        self.assertEqual(again["status"], "skipped")
        self.assertTrue(again["reason"].startswith("reused: passed at"))
        open(os.path.join(self.proj, "f.txt"), "w").write("22")
        self.assertEqual(self.rows(self.sisi("verify", "--json"))["a"]["status"], "passed")
        c["checks"][0]["cmd"] = "test -f f.txt && test -s f.txt"
        self.assertEqual(self.rows(self.run_verify(c))["a"]["status"], "passed")  # new command: not reused

    def test_a_change_inside_when_changed_is_never_hidden_by_reuse(self):
        """R-5.4-9: reuse keys on the contents of the watched files."""
        open(os.path.join(self.proj, "w.txt"), "w").write("good")
        c = contract([real("w", "grep -q good w.txt", when_changed=["w.txt"])])
        self.assertEqual(self.rows(self.run_verify(c))["w"]["status"], "passed")
        open(os.path.join(self.proj, "w.txt"), "w").write("bad")
        r = self.sisi("verify", "--json")
        self.assertEqual(self.rows(r)["w"]["status"], "failed")
        self.assertEqual(r.returncode, 1)

    def test_a_failure_is_never_reused(self):
        """R-5.6-3."""
        c = contract([real("f", "test -f missing.txt")])
        self.assertEqual(self.rows(self.run_verify(c))["f"]["status"], "failed")
        self.assertEqual(self.rows(self.sisi("verify", "--json"))["f"]["status"], "failed")

    def test_seen_failing_duration_and_time_saved_are_recorded(self):
        """R-5.4-7, R-5.6-1: every result stores its duration and whether the check was seen failing;
        `sisi verify` prints the slowest checks and the time saved."""
        c = contract([real("a", "test -f f.txt")])
        self.write_contract(c)
        self.sisi("verify")  # fails: f.txt missing
        open(os.path.join(self.proj, "f.txt"), "w").write("1")
        r = self.sisi("verify", "--json")
        a = self.rows(r)["a"]
        self.assertTrue(a["seen_failing"])
        self.assertIn("duration_s", a)
        r = self.sisi("verify")
        self.assertIn("time saved by selection and reuse", r.stdout)
        self.assertIn("slowest checks", self.sisi("verify", "--all").stdout)
        self.assertTrue(all("duration_s" in x for x in self.results()))

    def test_text_output_never_presents_a_skip_as_a_pass(self):
        """R-5.6-3."""
        c = contract([real("w", "test -f nope", when_changed=["nothing/**"])])
        self.write_contract(c)
        out = self.sisi("verify").stdout
        self.assertIn("did not run (not a pass)", out)
        self.assertIn("no evidence yet", out)


class WaiverTests(SisiCase):
    def setUp(self):
        super().setUp()
        self.git_init()

    def test_a_waiver_turns_nothing_green_and_the_unit_reads_deviation_everywhere(self):
        """R-10.3-3, R-13.4-2: a waiver records a deviation; the failing check still fails, and the
        unit's status is `deviation` in the record, the summary line, the status report and the list."""
        self.write_contract(contract([real("f", "test -f missing.txt")]))
        self.assertEqual(self.sisi("verify").returncode, 1)
        self.assertEqual(self.sisi("contract", "waive", "--check", "f", "not worth it").returncode, 0)
        self.assertEqual(self.sisi("verify").returncode, 1)  # still failing
        r = self.sisi("unit", "close")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("deviation", r.stdout)
        self.assertIn("must say so", r.stdout)
        rec = json.loads(self.sisi("unit", "show", "t").stdout)
        self.assertEqual(rec["delivery_status"], "deviation")
        self.assertEqual(rec["deviations"][0]["reason"], "not worth it")
        self.assertTrue(rec["scorecard"]["correctness_and_assurance"]["deviation"]["value"])
        self.assertEqual([r["delivery_status"] for r in store_units()], ["deviation"])
        self.assertIn("[deviation]", self.sisi("status").stdout)
        self.assertIn("deviation", self.sisi("unit", "list").stdout)
        self.assertNotIn("delivered", rec["delivery_status"])


def store_units():
    from sisi import store
    return store.read("units")


class NeverRunMandatoryTests(SisiCase):
    def setUp(self):
        super().setUp()
        self.git_init()

    def test_a_mandatory_check_that_never_ran_cannot_close_as_delivered(self):
        """R-5.6-3, R-6.4-3: a `when_changed` glob that matches nothing used to skip a mandatory check
        for ever must not let the unit close as plainly delivered."""
        self.write_contract(contract([real("real", "test -f .sisi/contract.json"),
                                      real("ghost", "test -f nope", when_changed=["nothing/**"])]))
        r = self.sisi("verify")
        self.assertEqual(r.returncode, 0)  # not blocking...
        self.assertIn("no evidence yet", r.stdout)  # ...but said plainly
        self.sisi("unit", "close")
        rec = json.loads(self.sisi("unit", "show", "t").stdout)
        self.assertEqual(rec["delivery_status"], "delivered-with-deferred")
        self.assertEqual([x["id"] for x in rec["never_run_mandatory"]], ["ghost"])

    def test_an_optional_check_may_be_kept_back(self):
        """R-6.4-3: optional confidence-building checks are distinguished from mandatory ones."""
        self.write_contract(contract([real("real", "test -f .sisi/contract.json"),
                                      real("opt", "test -f nope", when_changed=["nothing/**"], mandatory=False)]))
        self.sisi("verify")
        self.sisi("unit", "close")
        self.assertEqual(json.loads(self.sisi("unit", "show", "t").stdout)["delivery_status"], "delivered")

    def test_a_mandatory_check_not_affected_by_the_change_is_a_justified_skip(self):
        """R-5.4-10: selection with the reason recorded is the documented justification."""
        os.makedirs(os.path.join(self.proj, "src"))
        open(os.path.join(self.proj, "src", "a"), "w").write("1")
        subprocess.run(["git", "add", "-A"], cwd=self.proj, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "s"], cwd=self.proj, check=True)
        open(os.path.join(self.proj, "other.txt"), "w").write("1")
        self.write_contract(contract([real("real", "test -f other.txt"), real("src", "test -f src/a", when_changed=["src/**"])]))
        self.sisi("verify")
        self.sisi("unit", "close")
        self.assertEqual(json.loads(self.sisi("unit", "show", "t").stdout)["delivery_status"], "delivered")


class NothingUnrunIsEverPassedTests(SisiCase):
    """A seeded property test: random tree changes, verify runs and closes, against an oracle that
    knows, from an external log, which commands actually ran. Nothing that did not run to a pass on a
    tree where it holds may appear as passed in any result, in the stored rows or in the scorecard."""

    FILES = ("f_a", "f_b", "f_b2", "f_c", "f_d", "g")

    def build(self, n):
        d = os.path.join(self.tmp, "p%d" % n)
        os.makedirs(d)
        self.git_init(d)
        log = os.path.join(self.tmp, "log%d" % n)

        def mk(id, f, wc, mandatory):
            x = {"id": id, "claim": "claim " + id, "kind": "general", "rung": 3, "timeout_s": 10,
                 "cmd": "echo %s >> %s; test -f %s" % (id, log, f), "expect": {"exit": 0}, "mandatory": mandatory}
            if wc:
                x["when_changed"] = wc
            return x
        c = {"id": "t", "goal": "g", "risk": {"profile": "isolated"}, "assumptions": [], "questions": [], "invariants": [],
             "checks": [mk("a", "f_a", None, True), mk("b", "f_b", ["f_b*"], True),
                        mk("c", "f_c", ["nothing/**"], True), mk("d", "f_d", None, False)]}
        self.write_contract(c, d)
        return d, log, {"a": "f_a", "b": "f_b", "c": "f_c", "d": "f_d"}

    def logged(self, log):
        try:
            return open(log).read().split()
        except OSError:
            return []

    def run_sequence(self, rng, n):
        d, log, file_of = self.build(n)
        steps = rng.choice([8, 12, 16])
        for _ in range(steps):
            op = rng.choice(["touch", "touch", "rm", "verify", "verify", "all", "close"])
            if op in ("touch", "rm"):
                p = os.path.join(d, rng.choice(self.FILES))
                if op == "touch":
                    open(p, "w").write(str(rng.random()))
                elif os.path.exists(p):
                    os.remove(p)
                continue
            if op in ("verify", "all"):
                before_rows, before_log = len(self.results()), len(self.logged(log))
                r = self.sisi("verify", *(["--all"] if op == "all" else []), "--json", cwd=d)
                ran = set(self.logged(log)[before_log:])
                new = [x for x in self.results()[before_rows:] if x.get("item") == "check"]
                self.assertEqual({x["check"] for x in new}, set(file_of))
                for x in new:
                    exists = os.path.exists(os.path.join(d, file_of[x["check"]]))
                    if x["status"] == "passed":
                        self.assertIn(x["check"], ran, "passed without running")
                        self.assertTrue(exists, "passed where the check cannot hold")
                    if x["check"] in ran:
                        self.assertEqual(x["status"], "passed" if exists else "failed")
                    else:
                        self.assertIn(x["status"], ("skipped", "not-applicable", "not-run"))
                        if str(x.get("reason")).startswith("reused"):
                            self.assertTrue(exists, "reused a pass on a tree where the check fails")
                        self.assertTrue(x.get("reason"), "a status other than passed or failed carries a reason")
                self.assertEqual(r.returncode == 0, not any(x["status"] == "failed" for x in new))
            else:
                r = self.sisi("unit", "close", cwd=d)
                path = os.path.join(d, ".sisi", "units", "t.json")
                if r.returncode == 0:
                    rec = json.load(open(path))
                    latest = {x["id"]: x for x in rec["final_verification"]}
                    passed_now = sorted(i for i, x in latest.items() if x["status"] == "passed")
                    card = rec["scorecard"]["correctness_and_assurance"]["results_by_status"]["value"]
                    self.assertEqual(card.get("passed", 0), len(passed_now))
                    if rec["delivery_status"] == "delivered":
                        for cid in ("a", "b", "c"):  # mandatory checks
                            ever = any(x["check"] == cid and x["status"] == "passed" for x in rec["verification"])
                            just = latest[cid]["status"] == "skipped" and "not affected" in (latest[cid]["reason"] or "")
                            self.assertTrue(ever or just, "delivered with %s never run to a pass" % cid)
                            self.assertNotEqual(latest[cid]["status"], "failed")
                    return
                else:
                    self.assertFalse(os.path.exists(path))

    def test_property_over_generated_sequences(self):
        """R-5.6-2, R-5.6-3: nothing that did not run is ever reported, stored or summarised as passed."""
        seeds = [1, random.randrange(2 ** 32)] + [random.randrange(2 ** 32) for _ in range(ITERS)]
        for n, seed in enumerate(seeds):
            with self.subTest(seed=seed):
                self.run_sequence(random.Random(seed), n)


if __name__ == "__main__":
    unittest.main()
