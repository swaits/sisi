import json, os, random, shutil, time, unittest
from support import *
from sisi import contract as C, deep as D, gate, gitutil, verify as V
from test_verifiers import LibCase, vfile, BODY_V


def deepc(id, cmd="true", timeout_s=3600, **kw):
    return dict(check(id, cmd, rung=2, timeout_s=timeout_s, **kw), tier="deep")


class TierContractTests(SisiCase):
    def errs(self, c):
        return C.validate(c)

    def test_fast_default_and_limit(self):
        self.assertEqual(self.errs(contract([check("a", "true", timeout_s=60)])), [])
        e = self.errs(contract([check("a", "true", timeout_s=61)]))
        self.assertTrue(any("deep" in x and "61" in x for x in e), e)
        self.assertTrue(self.errs(contract([check("a", "true")], [check("i", "true", timeout_s=900)])))  # invariants too
        self.assertEqual(self.errs(contract([check("a", "true"), deepc("d")])), [])  # deep may be long

    def test_bad_tier_value(self):
        self.assertTrue(self.errs(contract([dict(check("a", "true"), tier="slow")])))

    def test_fast_limit_is_configurable(self):
        os.makedirs(self.state)
        json.dump({"verify": {"fast_limit_s": 10}}, open(os.path.join(self.state, "config.json"), "w"))
        self.assertTrue(self.errs(contract([check("a", "true", timeout_s=30)])))

    def test_sum_over_gate_budget_is_a_warning_only(self):
        c = contract([check("a%d" % i, "true", timeout_s=50) for i in range(3)])
        self.assertEqual(self.errs(c), [])
        self.assertTrue(C.warnings(c))
        self.assertFalse(C.warnings(contract([check("a", "true"), deepc("d"), deepc("e")])))  # deep not counted

    def test_check_command_prints_warning_and_ok(self):
        self.write_contract(contract([check("a%d" % i, "true", timeout_s=50) for i in range(3)]))
        r = self.sisi("contract", "check")
        self.assertEqual(r.returncode, 0)
        self.assertIn("warning", r.stdout)
        self.write_contract(contract([check("a", "true", timeout_s=999)]))
        r = self.sisi("contract", "check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("deep", r.stdout)

    def test_skeleton_shows_fast_and_deep_placeholders(self):
        self.sisi("contract", "init")
        c = json.load(open(os.path.join(self.proj, ".sisi", "contract.json")))
        self.assertEqual([x.get("tier", "fast") for x in c["checks"]], ["fast", "deep"])
        self.assertTrue(all("PLACEHOLDER" in x["claim"] for x in c["checks"]))
        self.assertEqual(C.validate(c), [])
        self.assertTrue(C.is_unedited_skeleton(c))


class VerifyTierTests(SisiCase):
    def setUp(self):
        super().setUp()
        self.git_init()
        self.fast, self.dp = os.path.join(self.tmp, "fast"), os.path.join(self.tmp, "deep")
        self.write_contract(contract([check("f", "echo x >> %s" % self.fast), deepc("d", "echo x >> %s" % self.dp)]))

    def ran(self, p):
        return os.path.exists(p)

    def test_default_fast_only_deep_only_all(self):
        self.assertEqual(self.sisi("verify").returncode, 0)
        self.assertTrue(self.ran(self.fast) and not self.ran(self.dp))
        os.remove(self.fast)
        self.assertEqual(self.sisi("verify", "--deep").returncode, 0)
        self.assertTrue(self.ran(self.dp) and not self.ran(self.fast))
        os.remove(self.dp)
        self.assertEqual(self.sisi("verify", "--all").returncode, 0)
        self.assertTrue(self.ran(self.dp) and self.ran(self.fast))

    def test_records_carry_tier_and_fingerprint(self):
        self.sisi("verify", "--all")
        fp = gitutil.fingerprint(self.proj, [os.path.join(self.proj, ".sisi", "contract.json")])
        self.assertTrue(fp)
        recs = self.results()
        self.assertEqual({r["tier"] for r in recs}, {"fast", "deep"})
        self.assertEqual({r["fp"] for r in recs}, {fp})

    def test_state_lifecycle_and_line(self):
        st = lambda: self.sisi("verify", "--state").stdout.strip()
        self.assertTrue(st().startswith("deep checks: never-run (1 item)"), st())
        self.sisi("verify", "--deep")
        self.assertTrue(st().startswith("deep checks: fresh-pass (1 item, last run"), st())
        self.assertIn("on the current tree", st())
        with open(os.path.join(self.proj, "new.txt"), "w") as f:
            f.write("change\n")
        self.assertTrue(st().startswith("deep checks: stale-pass"), st())
        self.assertIn("older tree", st())
        self.write_contract(contract([check("f", "true"), deepc("d", "false")]))
        self.sisi("verify", "--deep")
        self.assertTrue(st().startswith("deep checks: failed"), st())
        self.assertIn("failing: d", st())

    def test_every_mode_ends_with_state_line(self):
        for mode in ([], ["--deep"], ["--all"]):
            out = self.sisi("verify", *mode).stdout
            self.assertIn("deep checks:", out.strip().splitlines()[-1], mode)

    def test_state_json_and_no_deep_items(self):
        d = json.loads(self.sisi("verify", "--state", "--json").stdout)
        self.assertEqual((d["state"], d["items"]), ("never-run", 1))
        self.write_contract(contract([check("f", "true")]))
        self.assertIn("none", self.sisi("verify", "--state").stdout)
        self.assertNotIn("deep checks: ", self.sisi("verify").stdout.replace("deep checks: none", ""))

    def test_failed_deep_exit_code_and_modes_conflict(self):
        self.write_contract(contract([check("f", "true"), deepc("d", "false")]))
        self.assertEqual(self.sisi("verify", "--deep").returncode, 1)
        self.assertEqual(self.sisi("verify").returncode, 0)  # fast mode ignores deep
        self.assertEqual(self.sisi("verify", "--deep", "--all").returncode, 1)
        self.assertEqual(self.sisi("verify", "--background").returncode, 1)  # needs --deep


class BackgroundTests(SisiCase):
    def setUp(self):
        super().setUp()
        self.git_init()
        self.counter = os.path.join(self.tmp, "count")
        self.go = os.path.join(self.tmp, "go")  # the deep check waits for this file, so "running" is deterministic
        self.write_contract(contract([check("f", "true"), deepc(
            "d", "echo x >> %s; i=0; while [ ! -f %s ] && [ $i -lt 400 ]; do sleep 0.05; i=$((i+1)); done" % (self.counter, self.go))]))

    def release(self):
        open(self.go, "w").close()

    def wait_state(self, want, timeout=15):
        t = time.time()
        while time.time() - t < timeout:
            s = self.sisi("verify", "--state").stdout
            if s.startswith("deep checks: " + want):
                return s
            time.sleep(0.2)
        self.fail("never reached %s; last: %s" % (want, s))

    def test_detached_run_records_after_parent_exits(self):
        r = self.sisi("verify", "--deep", "--background")
        self.assertEqual(r.returncode, 0)  # returned although the check is still waiting for `go`
        log = r.stdout.split("log: ")[1].split()[0]
        self.assertTrue(log.startswith(self.state))
        self.assertTrue(self.sisi("verify", "--state").stdout.startswith("deep checks: running"))
        lock = json.load(open(os.path.join(self.state, "locks", os.listdir(os.path.join(self.state, "locks"))[0])))
        self.assertEqual(os.getpgid(lock["pid"]), lock["pid"])  # own process group
        self.release()
        self.wait_state("fresh-pass")  # the parent is long gone by now
        deeprecs = [x for x in self.results() if x["tier"] == "deep"]
        self.assertEqual([(x["check"], x["status"]) for x in deeprecs], [("d", "passed")])
        self.assertTrue(deeprecs[0]["fp"])
        self.assertTrue(os.path.exists(log))
        self.assertFalse(os.listdir(os.path.join(self.state, "locks")))  # lock released

    def test_second_request_while_running_says_so_and_exits_0(self):
        self.sisi("verify", "--deep", "--background")
        t = time.time()
        while not os.path.exists(self.counter) and time.time() - t < 15:  # the worker has started its check
            time.sleep(0.05)
        r = self.sisi("verify", "--deep", "--background")
        self.assertEqual(r.returncode, 0)
        self.assertIn("already running", r.stdout)
        with open(os.path.join(self.proj, "edit.txt"), "w") as f:
            f.write("x")
        r = self.sisi("verify", "--deep", "--background")  # tree changed: reported, not killed or restarted
        self.assertIn("older tree", r.stdout)
        self.assertIn("running", self.sisi("verify", "--state").stdout)
        self.release()
        self.wait_state("stale-pass")  # finished run was against the older tree
        self.assertEqual(len(open(self.counter).read().split()), 1)

    def test_foreground_deep_respects_the_lock(self):
        self.sisi("verify", "--deep", "--background")
        r = self.sisi("verify", "--deep")
        self.assertEqual(r.returncode, 0)
        self.assertIn("already running", r.stdout)
        self.release()
        self.wait_state("fresh-pass")

    def test_stale_lock_from_dead_process_is_ignored(self):
        p = D._lock_path(self.proj)
        os.makedirs(os.path.dirname(p))
        json.dump({"pid": 2 ** 22 + 12345, "start": "1", "fp": None, "ts": time.time()}, open(p, "w"))
        self.assertNotIn("running", self.sisi("verify", "--state").stdout)
        self.release()
        self.assertEqual(self.sisi("verify", "--deep").returncode, 0)


class GateDeepTests(SisiCase):
    sid = "gd"

    def setUp(self):
        super().setUp()
        self.git_init()
        self.path = os.path.join(self.proj, ".sisi", "contract.json")

    def gate(self, sid=None):
        return gate.decide({"session_id": sid or self.sid, "cwd": self.proj})

    def hook(self):
        return self.sisi("gate", stdin=json.dumps({"session_id": self.sid, "cwd": self.proj}))

    def fp(self):
        return V.tree_fp(self.proj, self.path)

    def set_deep(self, ok, fp="current"):
        c = json.load(open(self.path))
        res = [{"tier": "deep", "id": x["id"], "status": "passed" if ok else "failed", "tail": "" if ok else "kaboom-deep"}
               for x in D.deep_items(c)]
        D.save_state(self.proj, c["id"], self.fp() if fp == "current" else "older", res, [x["id"] for x in D.deep_items(c)])

    def edit(self, t="x"):
        with open(os.path.join(self.proj, "w.txt"), "a") as f:
            f.write(t + "\n")

    def test_pending_deep_allows_and_tells_the_model_once(self):
        self.write_contract(contract([check("f", "true"), deepc("d", "sleep 100")]))
        t = time.time()
        r = self.hook()
        self.assertLess(time.time() - t, 5)  # never waits for deep items
        out = json.loads(r.stdout)
        ctx = out["hookSpecificOutput"]
        self.assertEqual(ctx["hookEventName"], "Stop")
        self.assertIn("not yet", ctx["additionalContext"])
        self.assertIn("never-run", ctx["additionalContext"])
        self.assertIn("deep", out["systemMessage"])
        self.assertNotIn("decision", out)
        self.assertEqual(self.hook().stdout, "")  # same tree: said once, no loop

    def test_stale_pass_notifies_fresh_pass_is_silent(self):
        self.write_contract(contract([check("f", "true"), deepc("d")]))
        self.set_deep(True)
        self.assertEqual(self.hook().stdout, "")
        self.edit()
        self.assertIn("stale-pass", json.loads(self.hook().stdout)["hookSpecificOutput"]["additionalContext"])

    def test_deep_failure_on_current_tree_blocks_with_tail_and_strikes(self):
        self.write_contract(contract([check("f", "true"), deepc("d")]))
        self.set_deep(False)
        a, msg = self.gate()
        self.assertEqual(a, "block")
        self.assertIn("kaboom-deep", msg)
        self.assertEqual([self.gate()[0] for _ in range(2)], ["block", "block"])  # unchanged tree keeps blocking
        a, msg = self.gate()
        self.assertEqual(a, "allow")
        self.assertIn("UNVERIFIED", msg)

    def test_deep_failure_on_older_tree_does_not_block(self):
        self.write_contract(contract([check("f", "true"), deepc("d")]))
        self.set_deep(False, fp="older")
        self.assertEqual(self.gate()[0], "allow")

    def test_deep_failure_arriving_after_an_allow_is_noticed_on_unchanged_tree(self):
        self.write_contract(contract([check("f", "true"), deepc("d")]))
        self.assertEqual(self.gate()[0], "allow")
        self.assertEqual(self.gate()[0], "allow")  # short-circuit
        self.set_deep(False)  # a background run finished and failed
        self.assertEqual(self.gate()[0], "block")

    def test_deep_rerun_that_passes_unblocks_unchanged_tree(self):
        self.write_contract(contract([check("f", "true"), deepc("d")]))
        self.set_deep(False)
        self.assertEqual(self.gate()[0], "block")
        self.set_deep(True)
        self.assertEqual(self.gate()[0], "allow")

    def test_fast_failure_still_blocks_regardless_of_deep(self):
        self.write_contract(contract([check("f", "false"), deepc("d")]))
        self.set_deep(True)
        self.assertEqual(self.gate()[0], "block")

    def test_running_deep_is_not_a_block(self):
        self.write_contract(contract([check("f", "true"), deepc("d")]))
        ok, _ = D.acquire(self.proj, self.fp())
        self.assertTrue(ok)
        self.addCleanup(D.release, self.proj)
        self.set_deep(False)  # an old failure while a new run is in progress
        self.assertEqual(self.gate()[0], "allow")

    def test_property_deep_never_blocks_by_itself_and_current_failure_always_does(self):
        seeds = [0, 1, random.randrange(2 ** 32)] + [random.randrange(2 ** 32) for _ in range(ITERS - 1)]
        for seed in seeds:
            rng = random.Random(seed)
            for n in range(6 * ITERS):
                deeps = [deepc("d%d" % i, rng.choice(["true", "false", "sleep 100"]), timeout_s=rng.choice([60, 3600, 86400]))
                         for i in range(rng.randint(1, 3))]
                c = contract([check("f", "true")] + ([human("h")] if rng.random() < 0.3 else []), [])
                c["checks"] += deeps
                self.write_contract(c)
                self.edit("%d-%d" % (seed, n))  # new tree for each case
                mode = rng.choice(["unrun", "running", "pass-fresh", "pass-stale", "fail-fresh", "fail-stale"])
                shutil.rmtree(os.path.join(self.state, "deep"), ignore_errors=True)
                shutil.rmtree(os.path.join(self.state, "locks"), ignore_errors=True)
                if mode == "running":
                    D.acquire(self.proj, self.fp())
                elif mode != "unrun":
                    self.set_deep(mode.startswith("pass"), "current" if mode.endswith("fresh") else "older")
                sid = "prop-%d-%d" % (seed, n)
                with self.subTest(seed=seed, n=n, mode=mode):
                    a, msg = self.gate(sid)
                    if mode == "fail-fresh":
                        self.assertEqual(a, "block")
                        self.assertEqual([self.gate(sid)[0] for _ in range(2)], ["block", "block"])
                        self.assertEqual(self.gate(sid)[0], "allow")  # 3-strike release
                    else:
                        self.assertEqual(a, "allow")
                D.release(self.proj)


class TickDeepTests(SisiCase):
    def tick(self):
        return self.sisi("tick", stdin=json.dumps({"session_id": "t", "cwd": self.proj, "source": "startup"})).stdout

    def setUp(self):
        super().setUp()
        self.git_init()

    def test_line_for_not_fresh_states_silent_when_fresh_or_untrusted(self):
        # Session start no longer prints deep-check state; `sisi verify --state` owns it.
        self.write_contract(contract([check("f", "true"), deepc("d")]))
        self.assertEqual(self.tick(), "")
        self.sisi("verify", "--deep")
        self.assertEqual(self.tick(), "")
        with open(os.path.join(self.proj, "n.txt"), "w") as f:
            f.write("x")
        self.assertEqual(self.tick(), "")
        self.write_contract(contract([check("f", "true"), deepc("d", "false")]))
        self.sisi("verify", "--deep")
        self.assertEqual(self.tick(), "")
        self.write_contract(contract([check("f", "true"), deepc("d")]), trusted=False)
        os.remove(os.path.join(self.data, "trusted.json"))
        self.assertEqual(self.tick(), "")

    def test_still_fast(self):
        self.write_contract(contract([check("f", "true"), deepc("d")]))
        self.tick()
        best = 9
        for _ in range(5):
            t = time.perf_counter()
            self.tick()
            best = min(best, time.perf_counter() - t)
        __import__('support').skip_timing_if_busy(self)
        self.assertLess(best, 0.2)


class StatusLintTests(LibCase):
    def test_status_lists_recent_contracts(self):
        self.git_init()
        self.write_contract(contract([check("f", "true"), deepc("d")]))
        self.sisi("verify")
        out = self.sisi("status").stdout
        self.assertIn("recent contracts:", out)
        self.assertRegex(out, r"t\s+fast: pass\s+deep: never-run")
        self.sisi("verify", "--deep")
        self.assertRegex(self.sisi("status").stdout, r"deep: fresh-pass")

    def test_lint_warns_on_long_untiered_example(self):
        def body(extra):
            return BODY_V.replace("## As a contract check\ntext", '## As a contract check\n```json\n{"id": "x", "timeout_s": %s%s}\n```' % extra)
        self.put("prove/slow.md", vfile("slow", body=body(("3600", ""))))
        self.put("prove/ok.md", vfile("ok", body=body(("3600", ', "tier": "deep"'))))
        self.put("prove/quick.md", vfile("quick", body=body(("60", ""))))
        r = self.sisi("verifiers", "lint")
        self.assertEqual(r.returncode, 0, r.stdout)
        warn = [l for l in r.stdout.splitlines() if "no \"tier\": \"deep\"" in l]
        self.assertEqual(len(warn), 1)
        self.assertIn("slow.md", warn[0])


if __name__ == "__main__":
    unittest.main()
