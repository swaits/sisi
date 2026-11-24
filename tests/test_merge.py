"""The two lines of work merged: the discovery of new workers, and the reconciled learning cycle, orchestration
meter and routing. One test class per point where they meet.

Requirements: R-11.5-11 and R-16-11 (the owner alone decides what widens what runs: one approval path for
learning changes, learned tools and allowance probes), R-7.2-1 to R-7.2-3 (a worker learned by use is routed,
guarded, recorded and fallen back from like any other), R-16-8 (every decision and refused attempt is recorded),
R-16-9 (hooks fail open)."""
import contextlib, io, json, os, shutil, subprocess, sys, time, unittest
from unittest import mock

import test_discovery as TD
import test_providers as TP
from support import *
from sisi import cycle, discovery, fallback, orchestration, routing, watch, workers
from sisi import learning as L

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
BIN = os.path.join(REPO, "bin", "sisi")


def shell(cmd, sid="sess-hook"):
    return {"session_id": sid, "cwd": "/tmp", "hook_event_name": "PreToolUse", "tool_name": "Bash",
            "tool_input": {"command": cmd}}


class MergeCase(TD.DiscoveryCase):
    def waiting_driver(self):
        self.exe("fakeagent")
        f = TD.driver_file(os.path.join(self.tmp, "d.json"), run=["fakeagent", "--dangerously-skip-permissions", "-p", "{prompt}"],
                           approvals_off_reason="cannot run unattended without it")
        r = self.sisi("workers", "learn", "fakeagent", "--record", f)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def waiting_probe(self):
        self.exe("authexport", "#!/bin/sh\necho x\n")
        r = self.sisi("workers", "allowance", "zai", "--command", "authexport", "--remaining-path", "left",
                      "--reset-path", "reset")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def waiting_change(self):
        L.save_pending([{"id": "P-0001", "learning": None, "action": {"action": "disable-rule", "rule_id": "nothing"},
                         "reasons": ["a test"], "scope": None}], "test")

    def hook(self, cmd, sid="sess-hook"):
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                watch.before(shell(cmd, sid))
        except SystemExit as e:
            return e.code
        return 0


# ---------------------------------------------------------------- 1. one approval path


class OneApprovalPath(MergeCase):
    def setUp(self):
        super().setUp()
        self.waiting_driver()
        self.waiting_probe()
        self.waiting_change()

    def test_one_listing_shows_all_three_kinds_in_full(self):
        out = self.sisi("approve").stdout
        for part in ("P-0001", "drv-fakeagent", "probe-zai", "fakeagent --dangerously-skip-permissions -p {prompt}",
                     "authexport"):
            self.assertIn(part, out)
        line = L.pending_notice(cycle.waiting_count())
        self.assertIn("3 decision(s)", line)

    def test_the_discovery_branchs_own_copy_of_the_owner_logic_is_gone(self):
        for name in ("approve_hook", "_owner_may_decide"):
            self.assertFalse(hasattr(discovery, name), name)
        src = open(os.path.join(REPO, "sisi", "discovery.py"), encoding="utf-8").read()
        for word in ("relay_allowed", "agent_relayed_approval", "_open_terminal", "_stdin_is_tty", "isatty"):
            self.assertNotIn(word, src, word)

    def test_every_kind_needs_the_word_typed_at_the_terminal_and_shows_the_full_action(self):
        for pid in ("drv-fakeagent", "probe-zai"):
            with self.subTest(pid=pid):
                owner = terminal("wrong")
                with owner:
                    r = self.sisi("approve", pid, "--yes")
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("Type the word", owner.fake.text)
                self.assertIn("authexport" if pid.startswith("probe") else "--dangerously-skip-permissions", owner.fake.text)
                self.assertEqual(discovery.load_drivers()["fakeagent"]["state"], "waiting-owner")
                self.assertEqual(discovery.load_providers()["zai"]["allowance"]["state"], "waiting-owner")
        self.assertEqual(self.runs(), [], "nothing ran")
        refused = [r for r in L.load_approvals() if r.get("decision") == "refused"]
        self.assertEqual(sorted(r["id"] for r in refused), ["drv-fakeagent", "probe-zai"])

    def test_the_owners_decision_is_recorded_like_a_change(self):
        with terminal():
            self.assertEqual(self.sisi("approve", "probe-zai", "--yes").returncode, 0)
        with terminal():
            r = self.sisi("approve", "drv-fakeagent", "--yes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(discovery.load_drivers()["fakeagent"]["state"], "usable")
        self.assertEqual(discovery.load_providers()["zai"]["allowance"]["state"], "usable")
        rows = {a["id"]: a for a in L.load_approvals()}
        for pid in ("drv-fakeagent", "probe-zai"):
            self.assertEqual(rows[pid]["decision"], "yes")
            self.assertTrue(rows[pid]["terminal"])
            self.assertIn("action", rows[pid])
        self.assertEqual(rows["drv-fakeagent"]["action"]["command"][:2], ["fakeagent", "--dangerously-skip-permissions"])

    def test_the_owners_no_removes_either_kind_and_is_recorded(self):
        with terminal():
            self.assertEqual(self.sisi("approve", "probe-zai", "--no").returncode, 0)
        with terminal():
            self.assertEqual(self.sisi("approve", "drv-fakeagent", "--no").returncode, 0)
        self.assertEqual(discovery.load_drivers(), {})
        self.assertNotIn("allowance", discovery.load_providers().get("zai", {}))
        self.assertEqual(sorted((a["id"], a["decision"]) for a in L.load_approvals()),
                         [("drv-fakeagent", "no"), ("probe-zai", "no")])

    def test_without_a_terminal_it_is_refused_and_recorded_whatever_the_id(self):
        for pid in ("drv-fakeagent", "probe-zai", "drv-nothing", "whatever"):
            r = self.sisi("approve", pid, "--yes", env={"SISI_SESSION_ID": "sess-7"})
            self.assertEqual(r.returncode, 2, pid)
        self.assertEqual(discovery.load_drivers()["fakeagent"]["state"], "waiting-owner")
        self.assertEqual(self.runs(), [])
        refused = [r for r in L.load_approvals() if r["decision"] == "refused"]
        self.assertEqual(len(refused), 4)
        self.assertTrue(all(r["session"] == "sess-7" for r in refused))

    def test_a_probe_is_never_usable_before_the_owner_decides(self):
        # the definition and the decision are two steps, even for a person typing the definition
        self.assertEqual(discovery.load_providers()["zai"]["allowance"]["state"], "waiting-owner")

    def test_the_hook_refuses_any_id_in_every_wrapping(self):
        ids = ["P-0001", "drv-x", "drv-fakeagent", "probe-zai", "probe-a.b", "whatever", "$ID", "drv-NAMES"]
        wrappers = ['script -qec "sisi approve %s --yes" /dev/null </dev/null', "sh -c 'sisi approve %s --yes'",
                    "/path/to/bin/sisi approve %s --yes", "python3 -m sisi approve %s --no",
                    "env SISI_SESSION_ID=x sisi approve %s --yes", "expect -c 'spawn sisi approve %s --yes; expect eof'",
                    "bash -lc \"cd /tmp && sisi   approve %s --yes\"", "sisi${IFS}approve${IFS}%s${IFS}--yes",
                    "cd x; sisi approve %s --yes; echo done"]
        n = 0
        for pid in ids:
            for w in wrappers:
                cmd = w % pid
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.hook(cmd), 2, cmd)
                    n += 1
        refused = [r for r in L.load_approvals() if r["decision"] == "refused" and r["how"] == "hook"]
        self.assertEqual(len(refused), n)
        self.assertTrue(all(r["session"] == "sess-hook" for r in refused))
        self.assertIn("drv-x", {r["id"] for r in refused})
        self.assertIn("probe-zai", {r["id"] for r in refused})
        self.assertEqual(discovery.load_drivers()["fakeagent"]["state"], "waiting-owner")

    def test_the_listing_and_prose_are_not_refused(self):
        for cmd in ("sisi approve", "sisi approve | head", "grep -n 'sisi approve drv-NAME --yes' SECURITY.md",
                    "grep -rn 'sisi approve ID --yes|--no' docs",
                    "python3 - <<'E'\nprint('give him: sisi approve probe-PROVIDER --yes')\nE",
                    "sisi workers allowance zai --command x"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.hook(cmd), 0, cmd)

    def test_the_hook_process_refuses_with_exit_2(self):
        for cmd in ('sh -c "sisi approve drv-fakeagent --yes"', "%s approve probe-zai --yes" % BIN,
                    'script -qec "sisi approve drv-x --no" /dev/null'):
            r = self.sisi_proc("watch", "--before", stdin=json.dumps(shell(cmd)))
            self.assertEqual(r.returncode, 2, cmd + r.stderr)
            self.assertIn("owner's alone", r.stderr)

    @unittest.skipUnless(os.path.exists("/usr/bin/script") or os.path.exists("/bin/script"), "no script(1)")
    def test_script_gives_a_terminal_but_not_the_owners_hands(self):
        script = "/usr/bin/script" if os.path.exists("/usr/bin/script") else "/bin/script"
        for pid in ("drv-fakeagent", "probe-zai"):
            p = subprocess.run([script, "-qec", "%s %s approve %s --yes" % (sys.executable, BIN, pid), "/dev/null"],
                               cwd=self.proj, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
                               env=dict(os.environ))
            self.assertIn("refused", p.stdout + p.stderr, pid)
        self.assertEqual(discovery.load_drivers()["fakeagent"]["state"], "waiting-owner")
        self.assertEqual(discovery.load_providers()["zai"]["allowance"]["state"], "waiting-owner")
        self.assertEqual(self.runs(), [])

    def test_no_terminal_in_a_real_process_is_refused(self):
        p = self.sisi_proc("approve", "drv-fakeagent", "--yes")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertEqual(discovery.load_drivers()["fakeagent"]["state"], "waiting-owner")


class CollidingNameIsRefused(MergeCase):
    def test_a_driver_for_a_name_a_builtin_driver_has_is_refused_with_the_reason(self):
        builtin = workers.DRIVERS[0]["name"]
        self.exe(builtin)
        f = TD.driver_file(os.path.join(self.tmp, "d.json"), name=builtin, exe=builtin, run=[builtin, "-p", "{prompt}"])
        r = self.sisi("workers", "learn", builtin, "--record", f)
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertRegex(r.stdout + r.stderr, "built-in|already")
        self.assertEqual(discovery.load_drivers(), {})
        self.assertEqual(self.runs(), [])



# ---------------------------------------------------------------- 2. one description of a host's tools


class OneHostDescription(MergeCase):
    def test_both_modules_read_the_same_file_and_discovery_json_holds_no_hosts(self):
        with open(os.path.join(REPO, "canon", "discovery.json"), encoding="utf-8") as f:
            self.assertNotIn("hosts", json.load(f))
        hosts = discovery.data()["hosts"]
        self.assertEqual(hosts, orchestration.reach_specs())
        h = next(x for x in hosts if x["host"] == "t3-code")
        self.assertRegex("mcp__t3-code__orchestrator_capabilities", h["capability_tool"])
        self.assertRegex("mcp__t3-code__delegate_task", h["delegation_tool"])
        self.assertEqual(h["delegation"]["provider"], "target.providerInstanceId")
        hd = orchestration.host_data("claude-code")
        self.assertIsNotNone(orchestration.delegation_spec(hd, "mcp__t3-code__delegate_task"))
        self.assertEqual(orchestration.delegation_spec(hd, "mcp__t3-code__delegate_task")["model"], h["delegation"]["model"])

    def test_changing_the_one_file_changes_what_both_modules_recognise(self):
        other = {"claude-code": {"refuse": "json-deny", "evidence": "test",
                                 "delegation": {"mcp__other__x_delegate": {"model": "m", "brief": "b", "provider": "p", "reach": "other"}},
                                 "capability": {"^mcp__other__list$": dict(orchestration.hosts()["claude-code"]["capability"]
                                                                          ["mcp__t3-code__orchestrator_capabilities"], reach="other")},
                                 "exempt": {}}}
        with mock.patch.object(orchestration, "hosts", return_value=other):
            discovery._DATA.clear()
            self.addCleanup(discovery._DATA.clear)
            self.feed("mcp__other__list_all", TD.LISTING)  # no such tool in the data: ignored
            self.assertFalse(os.path.exists(discovery.host_state_file()))
            self.feed("mcp__other__list", TD.LISTING)
            self.assertIn("alpha", self.host_state()["hosts"]["other"]["providers"])
            self.assertEqual(orchestration.classify("claude-code", "mcp__other__x_delegate", {}, ""), "delegation")
            self.feed("mcp__other__x_delegate", None, {"p": "gamma", "m": "g-1"})
            self.assertIn("gamma", self.host_state()["hosts"]["other"]["providers"])
        discovery._DATA.clear()


# ---------------------------------------------------------------- 3. a worker learned by discovery is a worker everywhere


class HookCase(MergeCase):
    """Hook calls in the way the host sends them, in process, with a host that lists providers and a learned tool."""
    own = "gamma-top"
    sid = "sess-1"

    def setUp(self):
        super().setUp()
        self.git_init()
        os.makedirs(self.data, exist_ok=True)
        with open(os.path.join(self.data, "workers.json"), "w") as f:
            json.dump({"checked": time.time(), "tools": []}, f)
        self.sisi("tick", "--tool", "claude-code", stdin=json.dumps(
            {"session_id": self.sid, "cwd": self.proj, "hook_event_name": "SessionStart", "source": "startup", "model": self.own}))

    def payload(self, ev, tool, inp, **kw):
        d = {"session_id": self.sid, "cwd": self.proj, "hook_event_name": ev, "tool_name": tool, "tool_input": inp}
        d.update(kw)
        return json.dumps(d)

    def prompt(self, text="fix the parser and explain each module in the project"):
        self.sisi("prompt", "--tool", "claude-code", stdin=json.dumps(
            {"session_id": self.sid, "cwd": self.proj, "hook_event_name": "UserPromptSubmit", "prompt": text}))

    def route(self, kind="read", difficulty="1", *extra):
        r = self.sisi("route", "--kind", kind, "--difficulty", difficulty, *extra, env={"SISI_SESSION_ID": self.sid})
        return r

    def pre(self, tool, inp, **kw):
        r = self.sisi("watch", "--before", "--tool", "claude-code", stdin=self.payload("PreToolUse", tool, inp, **kw))
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout) if r.stdout.strip() else {}
        hs = out.get("hookSpecificOutput") or {}
        return hs.get("permissionDecision") == "deny", hs.get("permissionDecisionReason") or hs.get("additionalContext") or ""

    def host_deleg(self, provider, model, **kw):
        return self.pre("mcp__t3-code__delegate_task", {"target": {"providerInstanceId": provider, "model": model},
                                                        "task": "Outcome: x\nAcceptance: y\nFiles you may change: none"}, **kw)

    def listing(self):
        self.feed(TD.LISTING_TOOL, TD.LISTING)


class LearnedWorkersEverywhere(HookCase):
    def test_the_meters_router_lines_may_be_a_host_worker_with_its_mechanism(self):
        self.listing()
        self.prompt()
        denied, text = self.pre("mcp__t3-code__delegate_task", {"target": {"model": ""}, "task": "x"})
        self.assertTrue(denied, text)
        self.assertRegex(text, r"alpha/m-[12]")
        self.assertIn("cross-provider delegation", text)
        self.assertIn("target.providerInstanceId=alpha", text)
        self.assertNotIn("beta/", text, "a provider the host says cannot run a task is never offered")

    def test_the_meters_router_lines_may_be_a_learned_tool_with_its_mechanism(self):
        self.learn()
        self.prompt()
        denied, text = self.pre("mcp__t3-code__delegate_task", {"target": {"model": ""}, "task": "x"})
        self.assertTrue(denied, text)
        self.assertRegex(text, r"fakeagent/(default|fa-[12]).*sisi delegate")

    def test_a_delegation_naming_a_host_model_is_recognised_recorded_and_compared_with_the_route(self):
        self.listing()
        self.prompt()
        routed = self.route().stdout.splitlines()[0]
        self.assertRegex(routed, r"^alpha/m-[12]$")
        prov, model = routed.split("/")
        denied, ctx = self.host_deleg(prov, model, tool_use_id="t1")
        self.assertFalse(denied, ctx)
        self.assertIn("recorded as run", ctx)
        run = [r for r in workers.read_records() if r.get("kind") == "run"][-1]
        self.assertEqual(run["worker"], routed, "the ledger names the worker as discovery does: provider/model")
        self.assertIs(run["chosen_against_route"], False)
        self.assertEqual(run["route_worker"], routed)
        self.route()
        denied, ctx = self.host_deleg("beta", model, tool_use_id="t2")  # the same model name under another provider
        self.assertFalse(denied, ctx)
        run = [r for r in workers.read_records() if r.get("kind") == "run"][-1]
        self.assertEqual(run["worker"], "beta/" + model)
        self.assertIs(run["chosen_against_route"], True)
        self.assertIn("you chose beta/%s over the router's %s" % (model, routed), ctx)

    def test_a_host_delegation_naming_the_sessions_own_model_is_refused(self):
        self.listing()
        self.prompt()
        denied, text = self.host_deleg("alpha", self.own)
        self.assertTrue(denied)
        self.assertIn("own model", text)

    def test_a_model_the_owners_own_only_limit_excludes_is_stored_but_never_routable(self):
        r = self.sisi("workers", "only", "alpha", "m-1", "--why", "the owner checked only this one")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.listing()
        self.assertIn("m-2", self.host_state()["hosts"]["t3-code"]["providers"]["alpha"]["models"], "stored")
        self.assertIn("alpha/m-2", {c["worker"] for c in workers.build_candidates()}, "known as a worker")
        for kind, d in (("read", 1), ("impl", 1), ("impl", 2)):
            self.assertNotEqual(self.route(kind, str(d)).stdout.splitlines()[0], "alpha/m-2")
            if d == 1:
                self.assertEqual(self.route(kind, str(d)).stdout.splitlines()[0], "alpha/m-1")
            self.assertNotEqual(workers.recommend(kind, d, self.proj, self.own)[0], "alpha/m-2")
        explained = self.route("read", "1", "--explain").stdout
        self.assertIn("alpha/m-2", explained)
        self.assertRegex(explained, r"(?i)only")

    def test_a_failure_notice_for_a_host_worker_marks_its_provider_down_with_the_errors_own_time(self):
        self.listing()
        when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 7200))
        with orchestration.Meter(self.sid) as m:
            text = fallback.handle(m, self.sid, self.proj, "alpha m-1 failed: usage limit reached, resets at %s" % when,
                                   own_model=self.own)
        self.assertIn("alpha/m-1", text)
        down = workers.read_availability()
        self.assertEqual(down["alpha"]["scope"], "provider")
        self.assertAlmostEqual(down["alpha"]["retry_at"], time.time() + 7200, delta=5)
        picked = self.route().stdout.splitlines()
        self.assertFalse(picked and picked[0].startswith("alpha/"), picked)  # neither of its models is chosen now

    def test_a_learned_tools_own_phrase_is_a_failure_for_the_automatic_fallback(self):
        self.learn()
        text = "fakeagent/fa-1 said: weekly allowance used up for this plan"
        self.assertIsNone(workers.classify_failure(text), "the built-in phrases do not know it")
        with orchestration.Meter(self.sid) as m:
            out = fallback.handle(m, self.sid, self.proj, text, own_model=self.own)
        self.assertIsNotNone(out, "the learned driver's phrase counts")
        self.assertEqual(workers.read_availability()["fakeagent/fa-1"]["reason"], "limit")

    def test_a_learned_worker_and_a_host_worker_are_classified_and_take_part_in_the_newest_version_rule(self):
        self.learn()
        self.listing()
        asked = self.sisi("workers", "classify").stdout
        for w in ("fakeagent/fa-1", "fakeagent/fa-2", "fakeagent/default", "alpha/m-1"):
            self.assertIn(w, asked.splitlines(), w)
        answer = os.path.join(self.tmp, "answer.json")
        with open(answer, "w") as f:
            json.dump({"workers": {"fakeagent/fa-1": {"maker": "fa", "class": "standard", "released": "2026-01-01"},
                                   "fakeagent/fa-2": {"maker": "fa", "class": "standard", "released": "2026-06-01"},
                                   "fakeagent/default": {"maker": "unknown", "class": "unknown", "released": "unknown"},
                                   "alpha/m-1": {"maker": "al", "class": "standard", "released": "2026-03-01"},
                                   "alpha/m-2": {"maker": "al", "class": "standard", "released": "2026-04-01"}}}, f)
        r = self.sisi("workers", "classify", "--record", answer, "--by", "a test")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("fakeagent/fa-1", self.sisi("workers", "classify").stdout.splitlines())
        explained = self.route("read", "1", "--explain").stdout
        self.assertNotEqual(explained.splitlines()[0], "fakeagent/fa-1")
        self.assertIn("superseded by fakeagent/fa-2", explained, "the older version of a learned worker is replaced by the newer")
        self.assertIn("superseded by alpha/m-2", explained, "and so is a host worker's")

    def test_route_retry_of_names_a_learned_worker_with_its_check_line(self):
        self.learn()
        self.sisi("workers", "vouch", "fakeagent/fa-1", "--up-to", "2", "--why", "words")
        workers.append_record({"kind": "attempt", "id": "a1", "run_id": None, "ts": 1, "project": "p", "type": "impl",
                               "difficulty": 2, "worker": "fakeagent/fa-1", "outcome": "rejected", "check": "tests"})
        r = self.sisi("route", "--retry-of", "a1", env={"SISI_SESSION_ID": self.sid})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("fakeagent/"), r.stdout)
        self.assertIn("mechanism:", r.stdout)
        self.assertIn("unproven: check this result", r.stdout)


class LearnedProviderFallback(TP.ProviderCase):
    """A provider of a learned tool: the reset time comes from the error, else from the provider's allowance probe."""

    def setUp(self):
        super().setUp()
        self.q = TP.Quota()
        self.addCleanup(self.q.close)
        self.git_init()

    def notice(self, text, worker=None):
        with orchestration.Meter("sess-9") as m:
            return fallback.handle(m, "sess-9", self.proj, text, own_model="gamma-top", worker=worker)

    def test_a_limit_with_no_time_in_it_takes_the_probes_reset_and_marks_only_that_provider(self):
        self.q.windows = [(0, 1000, 4102444800000)]
        self.define_probe(self.q)
        out = self.notice("zai/b failed: weekly allowance used up for this plan")
        self.assertIsNotNone(out)
        down = workers.read_availability()
        self.assertEqual(down["zai"]["retry_at"], 4102444800.0)
        self.assertEqual(down["zai"]["scope"], "provider")
        self.assertNotIn("other", down)
        self.assertNotIn("zai/", self.sisi("route", "--kind", "read", "--difficulty", "1").stdout.splitlines()[0])

    def test_the_errors_own_time_wins_over_the_probe(self):
        self.q.windows = [(0, 1000, 4102444800000)]
        self.define_probe(self.q)
        when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
        self.notice("zai/b failed: weekly allowance used up for this plan, resets at %s" % when)
        self.assertAlmostEqual(workers.read_availability()["zai"]["retry_at"], time.time() + 3600, delta=5)

    def test_the_providers_own_phrase_is_read_by_the_automatic_path(self):
        self.sisi("workers", "signature", "zai", "--match", "re:\\b1113\\b", "--class", "auth")
        self.notice("zai/b failed: error code 1113 from the provider")
        got = workers.read_availability()["zai"]
        self.assertEqual((got["reason"], got["scope"]), ("auth", "provider"))


# ---------------------------------------------------------------- 4. the owner's vouch and capability


class VouchAgainstTheReconciledRouting(unittest.TestCase):
    def cand(self, worker, **kw):
        c = {"worker": worker, "tool": worker.split("/")[0], "model": worker, "usable": True, "plan": "flat", "cost": 1.0,
             "unproven": True, "unproven_ok": True}
        c.update(kw)
        return c

    def attempts(self, worker, n, kind, difficulty, outcome="accepted"):
        return [{"kind": "attempt", "id": "%s%d" % (worker, i), "ts": 1, "type": kind, "difficulty": difficulty,
                 "worker": worker, "outcome": outcome, "check": "tests"} for i in range(n)]

    def test_a_vouch_at_difficulty_three_ranks_with_judged_proof_before_a_benchmark(self):
        vouched = self.cand("zai/a", vouch={"level": 3, "why": "tried it", "date": "2026-11-23", "relayed": False}, cost=5.0)
        bench = dict(self.cand("big/b", unproven=False, unproven_ok=False), standing=99.0, cost=1.0)
        for d in (2, 3):
            r = routing.choose([bench, vouched], [], {}, "impl", d, now=1.0)
            self.assertEqual(r["choice"]["worker"], "zai/a", d)
            self.assertTrue(r["judged_first"])
            self.assertIn("evidence (the owner's word)", "\n".join(routing.explain_choice(r, "impl", d)))

    def test_it_ranks_with_a_judged_record_and_a_thick_bad_record_overrides_it_at_both_levels(self):
        proven = self.cand("old/p", unproven=False, unproven_ok=False, cost=9.0)
        for d in (2, 3):
            recs = self.attempts("old/p", 8, "impl", d)
            vouched = self.cand("zai/a", vouch={"level": 3, "why": "w", "date": "d", "relayed": False}, cost=1.0)
            self.assertEqual(routing.choose([vouched, proven], recs, {}, "impl", d, now=1.0)["choice"]["worker"], "zai/a")
            bad = recs + self.attempts("zai/a", 8, "impl", d, outcome="rejected")
            self.assertEqual(routing.choose([vouched, proven], bad, {}, "impl", d, now=1.0)["choice"]["worker"], "old/p")

    def test_the_routing_module_is_pure(self):
        src = open(os.path.join(REPO, "sisi", "routing.py"), encoding="utf-8").read()
        for word in ("import os", "import subprocess", "open(", "from . import store", "from . import workers", "from . import discovery",
                     "import json", "time.time()"):
            self.assertNotIn(word, src, word)


# ---------------------------------------------------------------- 6. the session-start lines stay few


class SessionStartStaysShort(HookCase):
    def start(self, sid="sess-start"):
        r = self.sisi("tick", "--tool", "claude-code", stdin=json.dumps(
            {"session_id": sid, "cwd": self.proj, "hook_event_name": "SessionStart", "source": "startup", "model": self.own}))
        return r.stdout

    def test_the_worst_case_prints_at_most_five_lines_and_nine_hundred_characters(self):
        # a decision waiting of each kind, a cycle due, new workers AND new tools, worker facts missing, wiring broken
        self.waiting_driver()
        self.waiting_probe()
        self.waiting_change()
        discovery.new_tools(now=1.0)  # the first look stores the list
        time.sleep(0.02)
        self.exe("brandnewtool")
        self.exe("anotheragent")
        self.listing()
        with open(os.path.join(self.data, "workers.json"), "w") as f:
            json.dump({"checked": time.time(), "tools": [], "new_unannounced": ["longprovider/a-very-long-model-name-1", "p/m2", "p/m3", "p/m4"]}, f)
        with mock.patch("sisi.cycle.due_count", return_value=12), \
                mock.patch("sisi.wiring.quick_problem", return_value="the generated rulebook is out of date (run `sisi update` to rebuild)"):
            out = self.start()
        lines = [l for l in out.splitlines() if l.strip()]
        shown = [l for l in lines if not l.startswith("sisi: this session's model")]  # the standing orchestration reminder is not a notice
        self.assertLessEqual(len(shown), 5, out)
        self.assertLess(sum(len(l) for l in shown), 900, "%d characters: %s" % (sum(len(l) for l in shown), out))
        self.assertEqual(sum(1 for l in shown if "wait for the owner" in l), 1, "all three kinds in ONE line")
        self.assertIn("3 decision(s)", out)
        self.assertEqual(sum(1 for l in shown if "unproven" in l and "new " in l), 1, "new workers and new tools in ONE line")
        self.assertIn("brandnewtool", out)
        self.assertIn("longprovider", out)
        self.assertEqual(sum(1 for l in shown if "worker facts" in l), 1)
        self.assertEqual(sum(1 for l in shown if "learning cycle is due" in l), 1)
        self.assertEqual(sum(1 for l in shown if "Run `sisi doctor`" in l), 1)

    def test_each_line_is_printed_only_when_true(self):
        out = self.start("sess-quiet")
        for word in ("wait for the owner", "learning cycle", "new worker", "new command-line", "doctor"):
            self.assertNotIn(word, out, word)


if __name__ == "__main__":
    unittest.main()
