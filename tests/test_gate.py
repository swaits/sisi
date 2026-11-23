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
        self.assertEqual(st, {"a": "not-run", "b": "not-run"})  # a timed out, b never ran: neither passed

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
        c = contract([check("c", "true")])
        c["design"] = {
            "implies": ["A change this size needs its approach recorded so the next agent can "
                        "see why it went this way and what was ruled out."],
            "provided": [{"what": "git already measures the change in this repository",
                          "evidence": "command:git"}],
            "alternatives": [
                {"name": "keep blocking on growth alone", "cost": "no new code to write at all",
                 "risk": "a contract can be gamed with checks that prove nothing real"},
                {"name": "ask the human to approve large changes", "cost": "one prompt per change",
                 "risk": "the human becomes the bottleneck for routine sizeable work"}],
            "chosen": {"name": "contract with a checked design section",
                       "why": "It is the option the owner would pick: the approach is recorded "
                              "and checked mechanically instead of depending on goodwill."},
            "objections": [],
            "challenge": {"by": "a subagent on a different model",
                          "recorded_at": "2026-01-01T00:00:00Z",
                          "objections": ["The design section could become ceremony filled with filler text."],
                          "changes": ["Required evidence that named existing things actually exist."]}}
        self.write_contract(c)
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


def _tool_line(name, inp):
    return {"type": "assistant", "timestamp": "2026-01-01T00:00:00.000Z",
            "message": {"role": "assistant", "content": [{"type": "tool_use", "name": name, "input": inp}]}}


def _human_line():
    return {"type": "user", "timestamp": "2026-01-01T00:00:00.000Z",
            "message": {"role": "user", "content": "do the work please"}}


class GateAttributionTests(GateBase):
    """Two sessions, one folder: the gate judges only this session's own edits (scenarios a-e)."""

    def setUp(self):
        super().setUp()
        os.environ["SISI_RETRO_REQUIRED"] = "1"
        self.addCleanup(lambda: os.environ.__setitem__("SISI_RETRO_REQUIRED", "0"))
        self.git_init()
        self.marker = os.path.join(self.proj, "ok")
        open(self.marker, "w").close()
        with open(os.path.join(self.proj, "work.txt"), "w") as f:
            f.write("base\n")
        self.write_contract(contract([check("c", "test -f ok")]))
        subprocess.run(["git", "add", "-A"], cwd=self.proj, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"],
                       cwd=self.proj, check=True)
        self.tdir = os.path.join(self.tmp, "transcripts")
        os.makedirs(self.tdir)

    def transcript(self, name, lines=()):
        p = os.path.join(self.tdir, name)
        with open(p, "w") as f:
            f.write(json.dumps(_human_line()) + "\n")
            for ln in lines:
                f.write(json.dumps(ln) + "\n")
        return p

    def append_line(self, path, line):
        with open(path, "a") as f:
            f.write((line if isinstance(line, str) else json.dumps(line)) + "\n")

    def tick(self, sid, tp=None):
        p = {"session_id": sid, "cwd": self.proj, "source": "startup"}
        if tp:
            p["transcript_path"] = tp
        return self.sisi("tick", stdin=json.dumps(p))

    def gate_proc(self, sid, tp=None):
        p = {"session_id": sid, "cwd": self.proj, "hook_event_name": "Stop"}
        if tp:
            p["transcript_path"] = tp
        return self.sisi_proc("gate", stdin=json.dumps(p), env={"SISI_RETRO_REQUIRED": "1"})

    def edit_work(self, name="work.txt", text="more\n"):
        with open(os.path.join(self.proj, name), "a") as f:
            f.write(text)

    def gate_unverified(self):
        return [r for r in self.results() if r.get("check") == "gate" and r.get("status") == "unverified"]

    def test_a_other_session_breaks_check_allows_once_per_tree_state(self):
        ta = self.transcript("sess-a.jsonl")
        tb = self.transcript("sess-b.jsonl")
        self.tick("sess-a", ta); self.tick("sess-b", tb)
        # B edits and breaks the check; A edited nothing at all.
        self.append_line(tb, _tool_line("Edit", {"file_path": os.path.join(self.proj, "work.txt")}))
        self.edit_work()
        os.remove(self.marker)
        r = self.gate_proc("sess-a", ta)
        self.assertEqual(r.returncode, 0, r.stdout)
        msg = json.loads(r.stdout)["systemMessage"]
        self.assertIn("NOT satisfied", msg)
        self.assertIn("UNVERIFIED", msg)
        self.assertIn("work.txt", msg)
        self.assertIn("sess-b", msg)  # identified from B's sibling transcript / session record
        self.assertIn("Do not report this work as done", msg)
        self.assertNotIn("Fix the work", msg)
        self.assertNotIn("sisi retro", msg)  # A did no work: never asked for a retro
        self.assertEqual(len(self.gate_unverified()), 1)
        # Same tree again: allowed silently, no second note, no second unverified row.
        r = self.gate_proc("sess-a", ta)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertEqual(len(self.gate_unverified()), 1)
        # The tree moves again: one more note.
        self.edit_work(text="even more\n")
        r = self.gate_proc("sess-a", ta)
        self.assertIn("NOT satisfied", json.loads(r.stdout)["systemMessage"])
        self.assertEqual(len(self.gate_unverified()), 2)

    def test_a_through_another_tools_hook(self):
        # The same logic arrives through hookio: codex carries a transcript path, pi/opencode do not.
        ta = self.transcript("sess-a.jsonl")
        tb = self.transcript("sess-b.jsonl")
        self.tick("sess-a", ta); self.tick("sess-b", tb)
        self.append_line(tb, _tool_line("Edit", {"file_path": os.path.join(self.proj, "work.txt")}))
        self.edit_work()
        os.remove(self.marker)
        p = {"session_id": "sess-a", "transcript_path": ta, "cwd": self.proj, "hook_event_name": "Stop"}
        r = self.sisi("gate", "--tool", "codex", stdin=json.dumps(p))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("NOT satisfied", json.loads(r.stdout)["systemMessage"])
        p2 = {"session_id": "sess-pi", "cwd": self.proj}  # no transcript path: pre-attribution behaviour
        r = self.sisi("gate", "--tool", "pi", stdin=json.dumps(p2))
        self.assertEqual(r.returncode, 2)  # pi blocks by exit code, as before
        self.assertIn("Fix the work", r.stdout)

    def test_b_own_edit_then_other_breaks_is_sent_back(self):
        ta = self.transcript("sess-a.jsonl")
        tb = self.transcript("sess-b.jsonl")
        self.tick("sess-a", ta); self.tick("sess-b", tb)
        self.append_line(ta, _tool_line("Edit", {"file_path": os.path.join(self.proj, "work.txt")}))
        self.edit_work()
        self.append_line(tb, _tool_line("Edit", {"file_path": os.path.join(self.proj, "work.txt")}))
        self.edit_work(text="b was here\n")
        os.remove(self.marker)
        r = self.gate_proc("sess-a", ta)
        d = json.loads(r.stdout)
        self.assertEqual(d["decision"], "block")
        self.assertIn("Fix the work", d["reason"])

    def test_c_native_subagent_edit_asks_parent_for_retro(self):
        ta = self.transcript("sess-a.jsonl")
        self.tick("sess-a", ta)
        subdir = os.path.join(self.tdir, "sess-a", "subagents")
        os.makedirs(subdir)
        with open(os.path.join(subdir, "agent-x1.jsonl"), "w") as f:
            f.write(json.dumps(_human_line()) + "\n")
            f.write(json.dumps(_tool_line("Edit", {"file_path": os.path.join(self.proj, "work.txt")})) + "\n")
        self.edit_work()
        r = self.gate_proc("sess-a", ta)
        d = json.loads(r.stdout)
        self.assertEqual(d["decision"], "block")
        self.assertIn("sisi retro", d["reason"])

    def test_d_shell_edits_count_and_readonly_shell_does_not(self):
        cmds = ["sed -i 's/base/changed/' %s" % os.path.join(self.proj, "work.txt"),
                "echo hi > %s" % os.path.join(self.proj, "shell-out.txt"),
                "git apply changes.diff"]
        for i, cmd in enumerate(cmds):
            sid = "shell-%d" % i
            tp = self.transcript("%s.jsonl" % sid)
            self.tick(sid, tp)
            self.append_line(tp, _tool_line("Bash", {"command": cmd}))
            self.edit_work(text="shell %d\n" % i)  # the file change the command made
            r = self.gate_proc(sid, tp)
            with self.subTest(cmd=cmd):
                d = json.loads(r.stdout)
                self.assertEqual(d["decision"], "block")
                self.assertIn("sisi retro", d["reason"])  # treated as having edited: retro required
        sid = "shell-ro"
        tp = self.transcript("shell-ro.jsonl")
        self.tick(sid, tp)
        self.append_line(tp, _tool_line("Bash", {"command": "ls -la; git status --short; cat work.txt"}))
        self.edit_work(text="someone else\n")  # tree changed, but not by this session
        r = self.gate_proc(sid, tp)
        self.assertEqual((r.returncode, r.stdout), (0, ""))  # passing check, no retro asked

    def test_e_missing_or_corrupt_transcript_is_strict(self):
        tb = self.transcript("sess-b.jsonl")
        self.tick("sess-b", tb)
        self.edit_work()
        os.remove(self.marker)
        missing = os.path.join(self.tdir, "no-such.jsonl")
        r = self.gate_proc("sess-missing", missing)
        self.assertEqual(json.loads(r.stdout)["decision"], "block")  # not waved through as another's work
        bad = os.path.join(self.tdir, "corrupt.jsonl")
        with open(bad, "w") as f:
            f.write("not json at all\n{{{\n")
        r = self.gate_proc("sess-corrupt", bad)
        self.assertEqual(json.loads(r.stdout)["decision"], "block")
        # and with the check passing again, a corrupt transcript still counts as edited for the retro
        open(self.marker, "w").close()
        r = self.gate_proc("sess-corrupt2", bad)
        d = json.loads(r.stdout)
        self.assertEqual(d["decision"], "block")
        self.assertIn("sisi retro", d["reason"])

    def test_shell_classifier(self):
        self.assertTrue(gate._shell_may_write("sed -i 's/a/b/' f.txt"))
        self.assertTrue(gate._shell_may_write("echo x > out.txt"))
        self.assertTrue(gate._shell_may_write("git apply p.diff"))
        self.assertTrue(gate._shell_may_write("python3 scripts/build.py"))
        self.assertIsNone(gate._shell_may_write("echo 'unterminated"))
        self.assertFalse(gate._shell_may_write("ls -la; git status; cat f.txt"))
        self.assertFalse(gate._shell_may_write("sisi verify"))
        self.assertFalse(gate._shell_may_write("grep -rn foo sisi/"))

    def test_offset_reads_only_the_new_tail(self):
        tp = self.transcript("sess-tail.jsonl")
        self.tick("sess-tail", tp)
        a, _ = gate.decide({"session_id": "sess-tail", "cwd": self.proj, "transcript_path": tp})
        self.assertEqual(a, "allow")
        size = os.path.getsize(tp)
        self.assertEqual(store.load_session("sess-tail")["attr_offset"], size)
        self.append_line(tp, {"type": "user", "message": {"role": "user", "content": "x" * 5000}})
        self.append_line(tp, _tool_line("Edit", {"file_path": os.path.join(self.proj, "work.txt")}))
        self.edit_work()
        a, msg = gate.decide({"session_id": "sess-tail", "cwd": self.proj, "transcript_path": tp})
        self.assertEqual(a, "block")  # the edit in the new tail was seen, retro is required
        self.assertIn("sisi retro", msg)
        self.assertEqual(store.load_session("sess-tail")["attr_gen"], 1)  # counted once, not rescanned


class GateWatchTests(GateBase):
    """Measured shell attribution: before/after tree snapshots, not command-text guesses."""

    def setUp(self):
        super().setUp()
        os.environ["SISI_RETRO_REQUIRED"] = "1"
        self.addCleanup(lambda: os.environ.__setitem__("SISI_RETRO_REQUIRED", "0"))
        self.git_init()
        self.marker = os.path.join(self.proj, "ok")
        open(self.marker, "w").close()
        with open(os.path.join(self.proj, "work.txt"), "w") as f:
            f.write("base\n")
        with open(os.path.join(self.proj, "noop.py"), "w") as f:
            f.write("print('nothing written')\n")
        with open(os.path.join(self.proj, "gen.py"), "w") as f:
            f.write("open('generated.txt', 'w').write('made\\n')\n")
        self.write_contract(contract([check("c", "test -f ok")]))
        subprocess.run(["git", "add", "-A"], cwd=self.proj, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"],
                       cwd=self.proj, check=True)
        self.tdir = os.path.join(self.tmp, "transcripts")
        os.makedirs(self.tdir)

    def transcript(self, name):
        p = os.path.join(self.tdir, name)
        with open(p, "w") as f:
            f.write(json.dumps(_human_line()) + "\n")
        return p

    def append_line(self, path, line):
        with open(path, "a") as f:
            f.write(json.dumps(line) + "\n")

    def tick(self, sid, tp):
        return self.sisi("tick", stdin=json.dumps({"session_id": sid, "cwd": self.proj,
                                                   "source": "startup", "transcript_path": tp}))

    def gate_proc(self, sid, tp=None):
        p = {"session_id": sid, "cwd": self.proj, "hook_event_name": "Stop"}
        if tp:
            p["transcript_path"] = tp
        return self.sisi_proc("gate", stdin=json.dumps(p), env={"SISI_RETRO_REQUIRED": "1"})

    def watch(self, sid, tp, command, during=None, after=True):
        """Simulate the Pre/PostToolUse pair around the command's real effect. Returns nothing."""
        self.append_line(tp, _tool_line("Bash", {"command": command}))
        base = {"session_id": sid, "cwd": self.proj, "transcript_path": tp,
                "tool_name": "Bash", "tool_input": {"command": command}}
        r = self.sisi_proc("watch", stdin=json.dumps(dict(base, hook_event_name="PreToolUse")),
                           env={"SISI_RETRO_REQUIRED": "1"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        if during is not None:
            during()
        if after:
            r = self.sisi_proc("watch", stdin=json.dumps(dict(base, hook_event_name="PostToolUse")),
                               env={"SISI_RETRO_REQUIRED": "1"})
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def run_in_proj(self, *argv):
        return subprocess.run(argv, cwd=self.proj, check=True, capture_output=True, text=True)

    def test_orchestrator_that_only_runs_commands_is_never_the_editor(self):
        ta, tb = self.transcript("orch-a.jsonl"), self.transcript("sess-b.jsonl")
        self.tick("orch-a", ta); self.tick("sess-b", tb)
        self.assertEqual(self.gate_proc("orch-a", ta).stdout, "")  # passing stop: records the pass state
        cmds = [("python3 noop.py", lambda: self.run_in_proj(sys.executable, "noop.py")),
                ("git commit -qm x", lambda: self.run_in_proj("git", "commit", "-q", "--allow-empty", "-m", "x")),
                ("gh run list", None),
                ("sisi retro --aim speed --moment m", None),
                ("python3 ~/.claude/orchestrator/orch.py log --type impl", None)]
        for cmd, during in cmds:
            self.watch("orch-a", ta, cmd, during=during)
        self.assertFalse(store.load_session("orch-a").get("attr_since_pass"))
        # Another session edits and breaks the check.
        self.append_line(tb, _tool_line("Edit", {"file_path": os.path.join(self.proj, "work.txt")}))
        with open(os.path.join(self.proj, "work.txt"), "a") as f:
            f.write("worker edit\n")
        os.remove(self.marker)
        r = self.gate_proc("orch-a", ta)
        msg = json.loads(r.stdout)["systemMessage"]
        self.assertIn("NOT satisfied", msg)
        self.assertIn("work.txt", msg)
        self.assertNotIn("Fix the work", msg)
        self.assertNotIn("sisi retro", msg)
        self.assertEqual(len([x for x in self.results() if x.get("status") == "unverified"]), 1)
        self.assertEqual(self.gate_proc("orch-a", ta).stdout, "")  # second stop: silent

    def test_command_that_writes_a_project_file_is_an_edit_of_that_path(self):
        tp = self.transcript("gen-a.jsonl")
        self.tick("gen-a", tp)
        self.assertEqual(self.gate_proc("gen-a", tp).stdout, "")
        self.watch("gen-a", tp, "python3 gen.py", during=lambda: self.run_in_proj(sys.executable, "gen.py"))
        self.assertIn("generated.txt", store.load_session("gen-a").get("attr_since_pass", []))
        tb = self.transcript("sess-b.jsonl")
        self.tick("sess-b", tb)
        self.append_line(tb, _tool_line("Edit", {"file_path": os.path.join(self.proj, "work.txt")}))
        with open(os.path.join(self.proj, "work.txt"), "a") as f:
            f.write("worker edit\n")
        os.remove(self.marker)
        d = json.loads(self.gate_proc("gen-a", tp).stdout)
        self.assertEqual(d["decision"], "block")  # a path it is attributed with changed since the pass
        self.assertIn("Fix the work", d["reason"])
        open(self.marker, "w").close()  # checks pass again, and this session edited: retro required
        d = json.loads(self.gate_proc("gen-a", tp).stdout)
        self.assertEqual(d["decision"], "block")
        self.assertIn("sisi retro", d["reason"])

    def test_command_that_writes_only_outside_the_project_is_not_an_edit(self):
        tp = self.transcript("out-a.jsonl")
        self.tick("out-a", tp)
        self.assertEqual(self.gate_proc("out-a", tp).stdout, "")
        outside = os.path.join(self.tmp, "outside.txt")
        gen = os.path.join(self.proj, "gen_out.py")
        with open(gen, "w") as f:
            f.write("open(%r, 'w').write('elsewhere\\n')\n" % outside)
        self.watch("out-a", tp, "python3 gen_out.py", during=lambda: self.run_in_proj(sys.executable, "gen_out.py"))
        self.assertTrue(os.path.exists(outside))
        self.assertFalse(store.load_session("out-a").get("attr_since_pass"))
        self.assertEqual(self.gate_proc("out-a", tp).stdout, "")  # no retro asked

    def test_other_agents_write_inside_the_window_is_attributed_to_this_session(self):
        tp = self.transcript("win-a.jsonl")
        self.tick("win-a", tp)
        self.assertEqual(self.gate_proc("win-a", tp).stdout, "")

        def during():
            with open(os.path.join(self.proj, "work.txt"), "a") as f:
                f.write("written by another agent mid-command\n")
            os.remove(self.marker)

        self.watch("win-a", tp, "python3 noop.py", during=during)
        self.assertIn("work.txt", store.load_session("win-a").get("attr_since_pass", []))
        d = json.loads(self.gate_proc("win-a", tp).stdout)
        self.assertEqual(d["decision"], "block")  # documented strict error: the window is this session's
        self.assertIn("Fix the work", d["reason"])

    def test_missing_after_record_is_strict(self):
        tp = self.transcript("kill-a.jsonl")
        self.tick("kill-a", tp)
        self.assertEqual(self.gate_proc("kill-a", tp).stdout, "")
        self.watch("kill-a", tp, "python3 gen.py", after=False)  # killed: no PostToolUse ever arrives
        with open(os.path.join(self.proj, "work.txt"), "a") as f:
            f.write("worker edit\n")
        os.remove(self.marker)
        d = json.loads(self.gate_proc("kill-a", tp).stdout)
        self.assertEqual(d["decision"], "block")
        self.assertIn("Fix the work", d["reason"])
        tp2 = self.transcript("kill-b.jsonl")
        self.tick("kill-b", tp2)
        open(self.marker, "w").close()  # tree passes again
        self.watch("kill-b", tp2, "python3 gen.py", after=False)
        d = json.loads(self.gate_proc("kill-b", tp2).stdout)
        self.assertEqual(d["decision"], "block")
        self.assertIn("sisi retro", d["reason"])  # strict for the retro too

    def test_snapshot_and_classifier(self):
        from sisi import gitutil
        s0 = gitutil.snapshot(self.proj)
        with open(os.path.join(self.proj, "work.txt"), "a") as f:
            f.write("changed\n")
        self.assertIn("work.txt", gitutil.snapshot_diff(s0, gitutil.snapshot(self.proj)))
        subprocess.run(["git", "add", "-A"], cwd=self.proj, check=True)
        s1 = gitutil.snapshot(self.proj)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c"],
                       cwd=self.proj, check=True)
        self.assertEqual(gitutil.snapshot_diff(s1, gitutil.snapshot(self.proj)), [])  # commit: .git only
        with open(os.path.join(self.proj, ".gitignore"), "w") as f:
            f.write("ignored.txt\n")
        s2 = gitutil.snapshot(self.proj)
        open(os.path.join(self.proj, "ignored.txt"), "w").close()
        self.assertNotIn("ignored.txt", gitutil.snapshot_diff(s2, gitutil.snapshot(self.proj)))
        self.assertFalse(gate._shell_may_write("git commit -qm x"))
        self.assertFalse(gate._shell_may_write("gh run list"))
        self.assertFalse(gate._shell_may_write("sisi retro --aim speed --moment m"))
        self.assertFalse(gate._shell_may_write("sisi verify"))
        self.assertTrue(gate._shell_may_write("sisi contract init"))
        self.assertTrue(gate._shell_may_write("python3 ~/.claude/orchestrator/orch.py log --type impl"))
        self.assertTrue(gate._shell_may_write("python3 tests/run_parallel.py"))


class GateSingleSessionEquivalenceTests(GateBase):
    """(f) One session only: with a transcript that records its own edits, every decision matches
    the pre-attribution gate (the same decide() called with no transcript path) on a twin project."""

    def twin(self, name):
        d = os.path.join(self.tmp, name)
        os.makedirs(d)
        self.git_init(d)
        with open(os.path.join(d, "work.txt"), "w") as f:
            f.write("base\n")
        open(os.path.join(d, "ok"), "w").close()
        self.write_contract(contract([check("c", "test -f ok")]), d=d)
        return d

    def retro_for(self, proj, sid, n):
        r = self.sisi("retro",
                      "--finding", "`cargo test` twin run %d took 4 minutes with no fuzz verifier in project" % n,
                      "--cause", "the recipe never named a fuzz verifier for parsers",
                      "--impact", "time", "--disposition", "promote",
                      "--change", "Add the fuzz verifier to the parser-or-codec recipe Checks, twin variant %d" % n,
                      "--mechanism", "verification", "--expect", "parser work gets a fuzz check",
                      "--validate", "run the recipe checks on a parser change",
                      cwd=proj, env={"SISI_SESSION_ID": sid})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_seeded_sequences_match_the_reference(self):
        os.environ["SISI_RETRO_REQUIRED"] = "1"
        self.addCleanup(lambda: os.environ.__setitem__("SISI_RETRO_REQUIRED", "0"))
        ref_proj, new_proj = self.twin("refproj"), self.twin("newproj")
        tp = os.path.join(self.tmp, "twin-new.jsonl")
        with open(tp, "w") as f:
            f.write(json.dumps(_human_line()) + "\n")
        self.sisi("tick", stdin=json.dumps({"session_id": "twin-ref", "cwd": ref_proj, "source": "startup"}))
        self.sisi("tick", stdin=json.dumps({"session_id": "twin-new", "cwd": new_proj, "source": "startup",
                                            "transcript_path": tp}))
        n_retro = [0]

        def both(fn):
            fn(ref_proj)
            fn(new_proj)

        def append_both(text):
            for p in (ref_proj, new_proj):
                with open(os.path.join(p, "work.txt"), "a") as f:
                    f.write(text)

        def stop_pair(step):
            a_ref, m_ref = gate.decide({"session_id": "twin-ref", "cwd": ref_proj})
            a_new, m_new = gate.decide({"session_id": "twin-new", "cwd": new_proj, "transcript_path": tp})
            self.assertEqual(a_new, a_ref, "step %r" % (step,))
            self.assertEqual(("sisi retro" in (m_new or "")), ("sisi retro" in (m_ref or "")), "step %r" % (step,))
            self.assertEqual(("Fix the work" in (m_new or "")), ("Fix the work" in (m_ref or "")), "step %r" % (step,))

        for seed in (0, 1, 2):
            rng = random.Random(seed)
            for step in range(12):
                op = rng.choice(["edit", "edit", "break", "fix", "verify", "retro"])
                if op == "edit":
                    append_both("s%d-%d\n" % (seed, step))
                    with open(tp, "a") as f:
                        f.write(json.dumps(_tool_line("Edit", {"file_path": os.path.join(new_proj, "work.txt")})) + "\n")
                elif op == "break":
                    both(lambda p: os.path.exists(os.path.join(p, "ok")) and os.remove(os.path.join(p, "ok")))
                    append_both("break\n")
                    with open(tp, "a") as f:
                        f.write(json.dumps(_tool_line("Edit", {"file_path": os.path.join(new_proj, "work.txt")})) + "\n")
                elif op == "fix":
                    both(lambda p: open(os.path.join(p, "ok"), "w").close())
                    with open(tp, "a") as f:
                        f.write(json.dumps(_tool_line("Write", {"file_path": os.path.join(new_proj, "ok")})) + "\n")
                elif op == "verify":
                    self.sisi("verify", cwd=ref_proj)
                    self.sisi("verify", cwd=new_proj)
                elif op == "retro":
                    n_retro[0] += 1
                    self.retro_for(ref_proj, "twin-ref", n_retro[0])
                    self.retro_for(new_proj, "twin-new", n_retro[0])
                stop_pair((seed, step, op))


if __name__ == "__main__":
    unittest.main()
