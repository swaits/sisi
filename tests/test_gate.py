import io, json, os, random, sys, unittest
from unittest import mock
from support import *
from sisi import gate, store


class GateBase(SisiCase):
    sid = "sess-1"

    def call(self, cwd=None, sid=None, **extra):
        """Run the gate in process as the hook would. Returns (action, message)."""
        payload = dict({"session_id": sid or self.sid, "cwd": cwd or self.proj, "hook_event_name": "Stop",
                        "stop_hook_active": False}, **extra)
        return gate.decide(payload)

    def hook(self, payload=None, cwd=None):
        """Run the real hook command: JSON stdin, stdout, exit code."""
        p = dict({"session_id": self.sid, "cwd": self.proj, "hook_event_name": "Stop"}, **(payload or {}))
        return self.sisi("gate", cwd=cwd, stdin=json.dumps(p))

    def set_config(self, **gate_cfg):
        os.makedirs(self.state, exist_ok=True)
        with open(os.path.join(self.state, "config.json"), "w") as f:
            json.dump({"gate": gate_cfg}, f)


class GateContractTests(GateBase):
    def test_pass_allows_with_no_output(self):
        self.write_contract(contract([check("ok", "true")]))
        r = self.hook()
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_fail_blocks_with_claude_format(self):
        self.write_contract(contract([check("bad", "echo boom-output >&2; exit 1")]))
        r = self.hook()
        self.assertEqual(r.returncode, 0)
        d = json.loads(r.stdout)
        self.assertEqual(d["decision"], "block")
        self.assertIn("bad", d["reason"])
        self.assertIn("boom-output", d["reason"])

    def test_timeout_and_floor_block(self):
        self.write_contract(contract([check("slow", "sleep 5", timeout_s=0.2)]))
        self.assertEqual(self.call()[0], "block")
        self.write_contract(contract([check("m", "true", rung=3, kind="money")]))
        a, msg = self.call(sid="other")
        self.assertEqual(a, "block")
        self.assertIn("floor", msg)

    def test_invalid_contract_blocks(self):
        self.write_contract({"id": "x"})
        self.assertEqual(self.call()[0], "block")

    def test_budget_makes_unfinished_checks_timeout(self):
        self.set_config(budget_s=0.4)
        self.write_contract(contract([check("a", "sleep 3", timeout_s=60), check("b", "true")]))
        a, msg = self.call()
        self.assertEqual(a, "block")
        st = {r["check"]: r["status"] for r in self.results()}
        self.assertEqual(st, {"a": "timeout", "b": "timeout"})  # b never ran: counts as timeout

    def test_three_strikes_then_unverified_release_then_reset(self):
        self.write_contract(contract([check("bad", "false")]))
        self.assertEqual([self.call()[0] for _ in range(3)], ["block"] * 3)
        a, msg = self.call()
        self.assertEqual(a, "allow")
        self.assertIn("UNVERIFIED", msg)
        self.assertEqual(self.results()[-1]["status"], "unverified")
        out = self.hook()  # after release the count restarts: blocks again
        self.assertEqual(json.loads(out.stdout)["decision"], "block")

    def test_unverified_release_is_printed(self):
        self.write_contract(contract([check("bad", "false")]))
        for _ in range(3):
            self.hook()
        r = self.hook()
        self.assertIn("UNVERIFIED", json.loads(r.stdout)["systemMessage"])

    def test_pass_resets_count(self):
        self.write_contract(contract([check("c", "test -f %s/ok" % self.tmp)]))
        self.call(); self.call()
        open(os.path.join(self.tmp, "ok"), "w").close()
        self.assertEqual(self.call()[0], "allow")
        os.remove(os.path.join(self.tmp, "ok"))
        self.assertEqual([self.call()[0] for _ in range(3)], ["block"] * 3)  # fresh three strikes

    def test_strikes_are_per_session(self):
        self.write_contract(contract([check("bad", "false")]))
        for _ in range(3):
            self.call(sid="a")
        self.assertEqual(self.call(sid="b")[0], "block")

    def test_stop_hook_active_does_not_bypass(self):
        self.write_contract(contract([check("bad", "false")]))
        self.assertEqual(self.call(stop_hook_active=True)[0], "block")

    def test_disabled_allows(self):
        self.set_config(enabled=False)
        self.write_contract(contract([check("bad", "false")]))
        self.assertEqual(self.call()[0], "allow")

    def test_contract_found_from_subdir_up_to_git_root(self):
        self.git_init()
        self.write_contract(contract([check("bad", "false")]))
        sub = os.path.join(self.proj, "x", "y")
        os.makedirs(sub)
        self.assertEqual(self.call(cwd=sub)[0], "block")


class GateFailOpenTests(GateBase):
    def test_internal_error_allows_and_logs(self):
        self.write_contract(contract([check("bad", "false")]))
        with mock.patch.object(gate, "decide", side_effect=RuntimeError("kaboom")), \
                mock.patch.object(sys, "stdin", io.StringIO("{}")), mock.patch.object(sys, "stdout", io.StringIO()) as out:
            self.assertEqual(gate.main(), 0)
            self.assertEqual(out.getvalue(), "")
        with open(os.path.join(self.state, "errors.log")) as f:
            self.assertIn("kaboom", f.read())

    def test_unwritable_state_allows(self):
        self.write_contract(contract([check("bad", "false")]))
        os.makedirs(self.state, exist_ok=True)
        open(os.path.join(self.state, "sessions"), "w").close()  # session records can no longer be written
        r = self.hook()
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_garbage_stdin_allows(self):
        r = self.sisi("gate", stdin="not json")
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        r = self.sisi("gate", stdin="")
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_corrupt_session_and_config_files(self):
        os.makedirs(os.path.join(self.state, "sessions"))
        with open(os.path.join(self.state, "sessions", "sess-1.json"), "w") as f:
            f.write("{{{")
        with open(os.path.join(self.state, "config.json"), "w") as f:
            f.write("nope")
        self.write_contract(contract([check("bad", "false")]))
        self.assertEqual(self.hook().returncode, 0)


class GateNoContractTests(GateBase):
    def start(self, sid=None):
        self.sisi("tick", stdin=json.dumps({"session_id": sid or self.sid, "cwd": self.proj, "source": "startup"}))

    def grow(self, n_lines=0, n_files=1):
        for i in range(n_files):
            with open(os.path.join(self.proj, "f%d.txt" % i), "w") as f:
                f.write("x\n" * (n_lines // max(n_files, 1) + 1))

    def test_not_a_git_repo_allows(self):
        self.grow(500, 5)
        self.assertEqual(self.call()[0], "allow")

    def test_small_change_allows(self):
        self.git_init(); self.start()
        self.grow(10, 1)
        self.assertEqual(self.call()[0], "allow")

    def test_many_files_blocks(self):
        self.git_init(); self.start()
        self.grow(4, 5)
        self.assertEqual(self.call()[0], "block")

    def test_preexisting_dirt_does_not_count(self):
        self.git_init()
        self.grow(500, 6)
        self.start()
        self.assertEqual(self.call()[0], "allow")
        with open(os.path.join(self.proj, "new.txt"), "w") as f:
            f.write("y\n" * 100)
        self.assertEqual(self.call()[0], "block")

    def test_committed_growth_still_counts(self):
        self.git_init(); self.start()
        self.grow(100, 1)
        subprocess.run(["git", "add", "-A"], cwd=self.proj, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c"], cwd=self.proj, check=True)
        self.assertEqual(self.call()[0], "block")

    def test_waive_allows_and_records(self):
        self.git_init(); self.start()
        self.grow(100, 1)
        r = self.sisi("contract", "waive", "typo fix")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.call()[0], "allow")
        w = store.read("waivers")
        self.assertEqual(w[0]["reason"], "typo fix")
        self.assertIn("project", w[0])

    def test_waiver_before_session_does_not_count(self):
        self.git_init()
        self.sisi("contract", "waive", "old")
        w = store.read("waivers")
        w[0]["ts"] = "2000-01-01T00:00:00Z"
        os.remove(os.path.join(self.state, "waivers.jsonl"))
        store.append("waivers", w[0])
        self.start(); self.grow(100, 1)
        self.assertEqual(self.call()[0], "block")

    def test_contract_created_after_block_is_enforced(self):
        self.git_init(); self.start(); self.grow(100, 1)
        self.call()
        self.write_contract(contract([check("bad", "false")]))
        self.assertEqual(self.call()[0], "block")


class GatePropertyTests(GateBase):
    """The gate cannot be passed with a failing, timed-out or unrun check short of the 3-strike release."""

    CMDS = [("true", 0, "passed")] * 3 + [("exit 1", 0, "failed"), ("exit 7", 7, "passed"), ("exit 7", 0, "failed")] \
        + [("sleep 3", 0, "timeout")] * 1

    def gen(self, rng):
        checks, invs, expect_ok = [], [], True
        floors = {"money": 2, "parsing": 2, "ui": None}
        kinds = {}
        for i in range(rng.randint(1, 5)):
            kind = rng.choice(["general", "money", "parsing", "ui", "state-machine"])
            if rng.random() < 0.2:
                rung = rng.choice([5, 6])
                checks.append(human("h%d" % i, rung, kind))
                kinds.setdefault(kind, []).append(rung)
                continue
            cmd, exit_, status = rng.choice(self.CMDS)
            rung = rng.randint(1, 4)
            checks.append(check("c%d" % i, cmd, rung=rung, kind=kind, exit=exit_, timeout_s=0.08))
            kinds.setdefault(kind, []).append(rung)
            if status != "passed":
                expect_ok = False
        for i in range(rng.randint(0, 2)):
            cmd, exit_, status = rng.choice(self.CMDS)
            invs.append(check("i%d" % i, cmd, exit=exit_, timeout_s=0.08))
            if status != "passed":
                expect_ok = False
        for kind, rungs in kinds.items():
            if kind in ("money", "parsing", "state-machine") and min(rungs) > 2:
                expect_ok = False
        if not invs and not any("cmd" in c for c in checks):
            expect_ok = False  # nothing runnable: the contract is invalid and must not pass
        return contract(checks, invs), expect_ok

    def test_generated_contracts(self):
        seeds = [0, random.randrange(2**32)] + [random.randrange(2**32) for _ in range(ITERS - 1)]
        for seed in seeds:
            rng = random.Random(seed)
            for n in range(4 * ITERS):
                c, expect_ok = self.gen(rng)
                sid = "p-%d-%d" % (seed, n)
                self.write_contract(c)
                with self.subTest(seed=seed, n=n, contract=c):
                    first = self.call(sid=sid)[0]
                    self.assertEqual(first, "allow" if expect_ok else "block")
                    if not expect_ok:
                        acts = [first] + [self.call(sid=sid)[0] for _ in range(2)]
                        self.assertEqual(acts, ["block"] * 3)  # never passes early
                        a, msg = self.call(sid=sid)
                        self.assertEqual(a, "allow")
                        self.assertIn("UNVERIFIED", msg)


class GateUnchangedTreeTests(GateBase):
    """Fix 1: a turn that changed nothing is not punished, and not re-checked."""

    def setUp(self):
        super().setUp()
        self.git_init()
        self.counter = os.path.join(self.tmp, "runs")

    def counting(self, cmd="true"):
        return check("c", "echo x >> %s; %s" % (self.counter, cmd))

    def runs(self):
        return len(open(self.counter).read().split()) if os.path.exists(self.counter) else 0

    def tick(self):
        self.sisi("tick", stdin=json.dumps({"session_id": self.sid, "cwd": self.proj, "source": "startup"}))

    def edit(self, text="x"):
        with open(os.path.join(self.proj, "work.txt"), "a") as f:
            f.write(text + "\n")

    def test_unchanged_since_baseline_allows_without_running(self):
        self.write_contract(contract([self.counting("false")]))
        self.tick()
        self.assertEqual(self.call()[0], "allow")
        self.assertEqual(self.runs(), 0)

    def test_unchanged_since_last_allow_not_rerun(self):
        self.write_contract(contract([self.counting()]))
        self.tick()
        self.edit()
        self.assertEqual(self.call()[0], "allow")
        self.assertEqual(self.runs(), 1)
        self.assertEqual(self.call()[0], "allow")
        self.assertEqual(self.runs(), 1)
        self.edit()  # a change runs the checks again
        self.call()
        self.assertEqual(self.runs(), 2)

    def test_unchanged_after_block_keeps_blocking_and_counts_strikes(self):
        self.write_contract(contract([self.counting("false")]))
        self.tick()
        self.edit()
        acts = [self.call() for _ in range(3)]
        self.assertEqual([a for a, _ in acts], ["block"] * 3)
        self.assertEqual(self.runs(), 1)  # only the first call ran the checks
        self.assertIn("send-back 2 of 3", acts[1][1])
        a, msg = self.call()
        self.assertEqual(a, "allow")
        self.assertIn("UNVERIFIED", msg)
        self.assertEqual(self.call()[0], "allow")  # released tree, still unchanged: allowed

    def test_fixing_the_work_reruns(self):
        marker = os.path.join(self.proj, "fixed")
        self.write_contract(contract([check("c", "test -f %s" % marker)]))
        self.tick()
        self.edit()
        self.assertEqual(self.call()[0], "block")
        open(marker, "w").close()
        self.assertEqual(self.call()[0], "allow")

    def test_fixing_a_gitignored_contract_reruns(self):
        with open(os.path.join(self.proj, ".git", "info", "exclude"), "a") as f:
            f.write(".sisi/\n")
        self.write_contract(contract([check("c", "false")]))
        self.tick()
        self.edit()
        self.assertEqual(self.call()[0], "block")
        self.write_contract(contract([check("c", "true")]))
        self.assertEqual(self.call()[0], "allow")


class GateTrustTests(GateBase):
    """Fix 2: a contract that arrived with a clone is never executed without approval."""

    def setUp(self):
        super().setUp()
        self.marker = os.path.join(self.tmp, "ran")
        self.write_contract(contract([check("evil", "touch %s; false" % self.marker)]), trusted=False)

    def test_gate_allows_with_one_notice_and_runs_nothing(self):
        r = self.hook()
        self.assertEqual(r.returncode, 0)
        msg = json.loads(r.stdout)["systemMessage"]
        self.assertIn("untrusted", msg)
        self.assertIn("sisi contract trust", msg)
        self.assertEqual(self.hook().stdout, "")  # notice only once per session
        self.assertFalse(os.path.exists(self.marker))

    def test_verify_refuses_with_distinct_exit(self):
        r = self.sisi("verify")
        self.assertEqual(r.returncode, 3)
        self.assertIn("untrusted", r.stdout)
        self.assertFalse(os.path.exists(self.marker))

    def test_trust_then_untrust(self):
        self.assertEqual(self.sisi("contract", "trust").returncode, 0)
        self.assertEqual(json.loads(self.hook().stdout)["decision"], "block")
        self.assertTrue(os.path.exists(self.marker))
        os.remove(self.marker)
        self.sisi("contract", "untrust")
        self.assertEqual(self.sisi("verify").returncode, 3)
        self.assertFalse(os.path.exists(self.marker))

    def test_init_trusts_the_project(self):
        d = os.path.join(self.tmp, "other")
        os.makedirs(d)
        self.sisi("contract", "init", cwd=d)
        self.assertEqual(self.sisi("verify", cwd=d).returncode, 1)  # ran (placeholder fails), not refused

    def test_trust_follows_realpath(self):
        link = os.path.join(self.tmp, "link")
        os.symlink(self.proj, link)
        self.sisi("contract", "trust", cwd=link)
        self.assertEqual(self.sisi("verify").returncode, 1)


class GateEmptyContractTests(GateBase):
    """Fix 3: a contract with nothing runnable must not pass."""

    def test_only_human_or_empty_is_invalid_everywhere(self):
        for name, c in (("human only", contract([human("h5", 5), human("h6", 6)])), ("empty", contract([]))):
            with self.subTest(name):
                self.write_contract(c)
                r = self.sisi("contract", "check")
                self.assertEqual(r.returncode, 1)
                self.assertIn("runnable", r.stdout)
                self.assertEqual(self.sisi("verify").returncode, 1)
                self.assertIn("runnable", self.sisi("verify").stdout)
                self.assertEqual(self.call(sid=name)[0], "block")

    def test_waive_is_the_way_out(self):
        self.git_init()
        self.write_contract(contract([human("h")]))
        self.assertEqual(self.call()[0], "block")

    def test_skeleton_is_honest_and_does_not_trap_question_turns(self):
        self.git_init()
        self.sisi("tick", stdin=json.dumps({"session_id": self.sid, "cwd": self.proj, "source": "startup"}))
        r = self.sisi("contract", "init")
        self.assertIn("SKELETON", r.stdout)
        self.assertIn("real command", r.stdout)
        self.assertEqual(self.sisi("verify").returncode, 1)
        self.assertEqual(self.call()[0], "allow")  # nothing changed but the skeleton itself
        with open(os.path.join(self.proj, "big.txt"), "w") as f:
            f.write("x\n" * 100)
        a, msg = self.call()
        self.assertEqual(a, "block")  # growth rule applies while the contract is still a skeleton
        self.assertIn("contract", msg)


class GateGrowthTests(GateBase):
    """Fix 4: growth without contract keeps blocking like a failing contract."""

    def setUp(self):
        super().setUp()
        self.git_init()
        self.sisi("tick", stdin=json.dumps({"session_id": self.sid, "cwd": self.proj, "source": "startup"}))

    def grow(self, name, n):
        with open(os.path.join(self.proj, name), "a") as f:
            f.write("x\n" * n)

    def test_blocks_up_to_three_then_unverified(self):
        self.grow("a.txt", 100)
        self.assertEqual([self.call()[0] for _ in range(3)], ["block"] * 3)
        a, msg = self.call()
        self.assertEqual(a, "allow")
        self.assertIn("UNVERIFIED", msg)
        self.assertEqual(self.results()[-1]["status"], "unverified")
        self.grow("a.txt", 1)  # still over the threshold, still no contract: strikes start again
        self.assertEqual(self.call()[0], "block")

    def test_contract_ends_it(self):
        self.grow("a.txt", 100)
        self.assertEqual(self.call()[0], "block")
        self.write_contract(contract([check("c", "true")]))
        self.assertEqual(self.call()[0], "allow")

    def test_waiver_covers_tree_at_that_moment_only(self):
        self.grow("a.txt", 100)
        self.assertEqual(self.call()[0], "block")
        self.assertEqual(self.sisi("contract", "waive", "generated file").returncode, 0)
        self.assertEqual(self.call()[0], "allow")
        self.grow("a.txt", 10)  # small growth after the waiver point
        self.assertEqual(self.call()[0], "allow")
        self.grow("a.txt", 100)  # big growth after the waiver point
        self.assertEqual(self.call()[0], "block")
        self.sisi("contract", "waive", "again")
        self.assertEqual(self.call()[0], "allow")


if __name__ == "__main__":
    unittest.main()
