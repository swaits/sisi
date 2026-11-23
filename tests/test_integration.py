"""The orchestration meter (rule 6) and the contract guard (rule 3) on one tree, and four small fixes.

One before-tool path with one refusal at a time, in a fixed order; one home for the routing decision; the
unit record, `sisi status`, `sisi rule` and the config carrying both sides; deep results that stay fresh
through a pause; a gate send-back that says why the profile applies; a backup copy that survives a file
vanishing; a prompt hook that attaches no recipe to a machine's message.
"""
import json, os, re, shutil, time, unittest
from unittest import mock
from support import *
import test_meter as TM
import test_unitguard as TG
from sisi import contract as C, gate, lifecycle, orchestration, prompt, routing, rulecmd, store, unit as U, unitguard as G
from sisi import watch, workers

SRC = TG.SRC
CONTRACT_LINES = 12


class Both(TG.GuardCase):
    """A project with the contract guard's fixtures and the meter's seeded workers."""

    def setUp(self):
        super().setUp()
        os.makedirs(self.data, exist_ok=True)
        TM.seed_workers(self)
        self.own = "gamma-top"
        self.tick(model=self.own)

    def hook(self, tool, inp, event="PreToolUse", **extra):
        """The real before-tool hook; (reason or None, whole stdout)."""
        d = dict({"session_id": self.sid, "cwd": self.proj, "hook_event_name": event, "tool_name": tool,
                  "tool_input": inp}, **extra)
        r = self.sisi("watch", "--before", "--tool", "claude-code", stdin=json.dumps(d))
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout) if r.stdout.strip() else {}
        hs = out.get("hookSpecificOutput") or {}
        if hs.get("permissionDecision") == "deny":
            reason = hs["permissionDecisionReason"]
            self.assertLessEqual(len(reason.splitlines()), CONTRACT_LINES, reason)
            return reason
        return None

    def read(self, **kw):
        return self.hook("Read", {"file_path": os.path.join(self.proj, "README.md")}, **kw)

    def edit(self, rel=SRC, **kw):
        return self.hook("Edit", {"file_path": os.path.join(self.proj, rel), "old_string": "a", "new_string": "b"}, **kw)

    def agent(self, prompt_text, model=None, **kw):
        inp = {"description": "d", "prompt": prompt_text}
        if model:
            inp["model"] = model
        return self.hook("Agent", inp, **kw)

    def spend_budget(self):
        for _ in range(6):
            self.assertIsNone(self.read())
        self.assertIn("direct tool calls", self.read())  # the meter now refuses every counted call

    def route(self, *args):
        return self.sisi("route", *args, env={"SISI_SESSION_ID": self.sid})

    def foreign_unit(self, ago_s=3 * 86400, goal="redo the old report"):
        c = TG.good_contract(goal=goal, id="old-report")
        self.write_contract(c)
        self.age_unit(c, ago_s, sid="someone-else")
        return C.load(self.contract_path)


BUILD_BRIEF = "Outcome: greet by name\nAcceptance: the test passes\nFiles you may change: src/app.py"
READ_BRIEF = "Outcome: list the callers of greet\nAcceptance: a list\nFiles you may change: none"


class OneRefusalAtATime(Both):
    """Integration point 1."""

    def test_an_edit_with_no_unit_past_the_budget_is_refused_for_the_contract_only(self):
        self.spend_budget()
        msg = self.edit()
        self.assertIn("sisi contract init", msg)
        self.assertNotIn("direct tool calls", msg)
        self.assertNotIn("sisi unit direct", msg)

    def test_delegating_a_build_past_the_budget_with_no_model_and_no_unit_is_refused_for_the_contract(self):
        self.spend_budget()
        for model in (None, self.own):
            msg = self.agent(BUILD_BRIEF, model=model)
            self.assertIn("sisi contract init", msg)
            self.assertIn("acceptance", msg)
            self.assertNotIn("names no model", msg)
            self.assertNotIn("names this session's own model", msg)

    def test_a_routed_build_is_a_build_whatever_the_brief_says(self):
        self.assertEqual(self.route("--kind", "impl", "--difficulty", "2").returncode, 0)
        msg = self.agent("Look into the greeting", model="alpha-small")
        self.assertIn("sisi contract init", msg)

    def test_a_read_only_delegation_goes_to_the_delegation_guard_then_the_meter(self):
        msg = self.agent(READ_BRIEF)  # no model, no unit needed
        self.assertIn("names no model", msg)
        self.assertNotIn("contract", msg)
        self.assertEqual(self.route("--kind", "read", "--difficulty", "1").returncode, 0)
        self.assertIsNone(self.agent(READ_BRIEF, model="alpha-small"))

    def test_with_a_valid_unit_the_contract_guard_is_silent_and_the_meter_speaks(self):
        self.open_unit()
        for _ in range(6):
            self.assertIsNone(self.read())
        self.assertIn("direct tool calls", self.read())
        # an edit is a counted call too: with the unit valid, the meter refuses it
        self.assertIn("direct tool calls", self.edit())
        msg = self.agent(BUILD_BRIEF)
        self.assertIn("names no model", msg)

    def test_workers_and_subagents_are_exempt_from_all_of_it(self):
        for _ in range(12):
            self.assertIsNone(self.read(agent_id="w1"))
        self.assertIsNone(self.edit(agent_id="w1"))
        self.assertIsNone(self.agent(BUILD_BRIEF, agent_id="w1"))
        # a session whose first prompt opens with the brief template's line is a worker too
        orchestration.new_turn("wk", self.proj, orchestration.brief_line() + "\nOutcome: x")
        d = {"session_id": "wk", "cwd": self.proj, "hook_event_name": "PreToolUse", "tool_name": "Edit",
             "tool_input": {"file_path": os.path.join(self.proj, SRC), "old_string": "a", "new_string": "b"}}
        r = self.sisi("watch", "--before", "--tool", "claude-code", stdin=json.dumps(d))
        self.assertEqual(r.stdout.strip(), "")

    def test_no_refusal_is_longer_than_twelve_lines_in_any_state(self):
        for step in (lambda: None, lambda: self.foreign_unit(), self.spend_budget_quiet):
            step()
            for text in (self.edit("auth/login.py"), self.agent(BUILD_BRIEF), self.agent(READ_BRIEF), self.read()):
                self.assertLessEqual(len((text or "").splitlines()), CONTRACT_LINES)

    def spend_budget_quiet(self):
        for _ in range(8):
            self.read()

    def test_every_stage_fails_open_on_its_own(self):
        self.spend_budget()
        with mock.patch.object(G, "check", side_effect=RuntimeError("boom")):
            self.assertEqual(watch.contract_guard({"tool_name": "Edit"}), None)
            self.assertIn("direct tool calls", self.read())  # the meter still answers
        with mock.patch.object(orchestration, "before", side_effect=RuntimeError("boom")):
            self.assertEqual(watch.meter({"tool_name": "Read"}, False), {})
            self.assertIn("sisi contract init", self.edit())  # the contract guard still answers
        with mock.patch.object(watch, "contract_guard", side_effect=RuntimeError("boom")):
            r = self.sisi("watch", "--before", "--tool", "claude-code", stdin=json.dumps(
                {"session_id": self.sid, "cwd": self.proj, "hook_event_name": "PreToolUse", "tool_name": "Read",
                 "tool_input": {"file_path": "/x"}}))
            self.assertEqual(r.returncode, 0)

    def test_a_refused_call_is_not_counted_by_the_meter(self):
        for _ in range(10):
            self.assertIn("sisi contract init", self.edit())
        for _ in range(6):
            self.assertIsNone(self.read())  # the ten refused edits used none of the budget


class RoutingDecision(Both):
    """Integration point 2."""

    def decision(self):
        return orchestration._peek(self.sid).get("route")

    def test_the_guard_reads_the_decision_where_route_stores_it(self):
        self.assertIsNone(G.routed_kind(self.sid))
        self.route("--kind", "impl", "--difficulty", "2")
        self.assertEqual(self.decision()["kind"], "impl")
        self.assertEqual(G.routed_kind(self.sid), "impl")
        self.route("--kind", "review", "--difficulty", "2")
        self.assertEqual(G.routed_kind(self.sid), "review")
        self.assertFalse(G.is_building_delegation(self.sid, {"tool_input": {"prompt": "fix and implement everything"}}))

    def test_a_decision_older_than_the_window_is_no_decision_for_the_guard_too(self):
        self.route("--kind", "impl", "--difficulty", "2")
        with orchestration.Meter(self.sid) as m:
            m["route"]["ts"] -= 3600
        self.assertIsNone(G.routed_kind(self.sid))

    def test_route_accepts_only_the_ledgers_kinds_and_says_which(self):
        r = self.route("--kind", "implementation", "--difficulty", "2")
        self.assertNotEqual(r.returncode, 0)
        for k in G.ledger_kinds():
            self.assertIn(k, r.stderr)
        self.assertIsNone(self.decision())  # the record stays clean
        for k in G.ledger_kinds():
            self.assertEqual(self.route("--kind", k, "--difficulty", "1").returncode, 0, k)
            self.assertEqual(self.decision()["kind"], k)

    def test_the_guards_build_kinds_are_ledger_kinds(self):
        self.assertTrue(set(G._list("build_kinds")) <= set(G.ledger_kinds()))

    def test_the_meters_own_texts_name_only_ledger_kinds(self):
        text = orchestration.route_text()
        for k in G.ledger_kinds():
            self.assertIn(k, text)
        self.assertNotIn("implementation", text)


class RetryOf(Both):
    """Integration point 3."""

    def test_the_orchestration_branchs_own_ladder_is_gone(self):
        for name in ("stronger_choice",):
            self.assertFalse(hasattr(workers, name), name)

    def test_retry_of_asks_the_reworked_routing(self):
        att = {"kind": "attempt", "id": "a1", "run_id": None, "ts": 1, "project": "p", "type": "read", "difficulty": 1,
               "worker": "alpha-small", "outcome": "rejected", "check": "read"}
        workers.append_record(att)
        calls = []
        real_choice = routing.retry_choice

        def spy(*a, **kw):
            calls.append((a[3:7], kw.get("floors") is not None))
            return real_choice(*a, **kw)
        with mock.patch.object(routing, "retry_choice", spy):
            r = self.sisi("route", "--retry-of", "a1", env={"SISI_SESSION_ID": self.sid})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(calls, [(("read", 1, "alpha-small", 1), True)])
        self.assertEqual(r.stdout.splitlines()[0], "alpha-small")  # the first retry: the same worker, a better brief
        self.assertIn("improve the brief", r.stdout.lower())

    def test_the_second_rejection_moves_to_strictly_better_evidence(self):
        for i, w in enumerate(("alpha-small", "alpha-small")):
            workers.append_record({"kind": "attempt", "id": "x%d" % i, "run_id": None, "ts": 2 + i, "project": "p", "type": "read",
                                   "difficulty": 1, "worker": w, "outcome": "rejected", "check": "read",
                                   "retry_of": "x0" if i else None})
        r = self.sisi("route", "--retry-of", "x1", env={"SISI_SESSION_ID": self.sid})
        self.assertEqual(r.stdout.splitlines()[0], "beta-large")
        self.assertEqual(G.routed_kind(self.sid), "read")


class MeterRouterLines(Both):
    """Integration point 4."""

    def test_reading_is_asked_at_difficulty_one_and_building_at_two(self):
        asked = []

        def fake(kind, difficulty, cwd=None, own_model=None):
            asked.append((kind, difficulty))
            return "w-%s" % kind, "mech", 1
        with mock.patch.object(workers, "recommend", fake):
            picks = orchestration._picks(self.proj, self.own)
        self.assertEqual(asked, [("read", 1), ("impl", 2)])
        self.assertEqual([p[0] for p in picks], ["w-read", "w-impl"])

    def test_a_routine_read_is_not_sent_to_the_dearest_worker(self):
        with open(os.path.join(self.data, "worker-prices.json"), "w") as f:
            json.dump({"models": {"alpha-small": {"cost_per_million_tokens": 1}, "beta-large": {"cost_per_million_tokens": 9}}}, f)
        read, build = orchestration._picks(self.proj, self.own)
        self.assertEqual(read[0], "alpha-small")
        self.spend_budget()
        text = self.read()
        self.assertRegex(text, r"reading and searching: alpha-small")

    def test_the_router_gets_the_floors_of_the_reworked_routing(self):
        seen = {}
        real = routing.choose

        def spy(*a, **kw):
            seen["floors"] = kw.get("floors")
            return real(*a, **kw)
        with mock.patch.object(routing, "choose", spy):
            workers.recommend("impl", 2, self.proj, self.own)
        self.assertIsNotNone(seen["floors"])


class UnitRecordAndStatus(Both):
    """Integration point 5."""

    def refused_unit(self):
        self.open_unit(TG.good_contract(profile="integration"))  # bound, but lacks what its profile needs before building
        self.assertIn("Missing", self.edit())  # a guard refusal, kept with the unit
        for _ in range(3):
            self.read()
        orchestration._event({"project": self.proj}, self.sid, "call")  # a metered call in the window

    def status_block(self):
        out = self.sisi("status").stdout.splitlines()
        i = out.index("units in progress:")
        block = []
        for ln in out[i + 1:]:
            if not ln.strip():
                break
            block.append(ln)
        return block

    def test_the_record_carries_both_sides_additions(self):
        self.refused_unit()
        c = C.load(self.contract_path)
        rec = U.build_record(c, self.proj, "complete", time.time())
        self.assertGreaterEqual(len(rec["guard_refusals"]), 1)
        self.assertIn("direct_calls", rec["orchestration"])
        self.assertGreaterEqual(rec["orchestration"]["direct_calls"]["value"], 1)
        self.assertIn("orch_direct_calls", rec["scorecard"]["parallelism"])
        self.assertEqual(U.summary_line(rec)["guard_refusals"], len(rec["guard_refusals"]))

    def test_the_binding_is_what_the_record_and_status_are_about(self):
        c = self.open_unit()
        rec = U.build_record(c, self.proj, "complete", time.time())
        self.assertEqual(G.author_models(self.proj, c), [self.own])  # the session that opened it, by its model
        self.assertEqual(U.build_record(c, self.proj, "complete", time.time())["guard_refusals"], [])

    def test_status_shows_both_within_four_extra_lines(self):
        self.open_unit(TG.good_contract(profile="integration"))
        before = self.status_block()
        self.refused_unit()
        after = self.status_block()
        self.assertTrue(any("guard refused" in ln for ln in after), after)
        self.assertTrue(any("orchestration (measured)" in ln for ln in after), after)
        self.assertLessEqual(len(after) - len(before), 4)


class RuleStatements(SisiCase):
    """Integration point 6."""

    NEEDS = {"size-by-risk": ("sisi/gate.py", "sisi/risk.py", "sisi/unitguard.py"),
             "define-done": ("sisi/contract.py", "sisi/gate.py", "sisi/unitguard.py", "sisi/scorecard.py"),
             "verify-enough": ("sisi/verify.py", "sisi/gate.py", "sisi/assure.py"),
             "orchestrate": ("sisi/orchestration.py", "sisi/fallback.py", "sisi/routing.py", "sisi/brief.py", "sisi/watch.py")}

    def test_rules_2_3_4_and_6_say_enforced_and_name_where_the_code_lives(self):
        for rid, files in self.NEEDS.items():
            text = rulecmd.enforcement_for(rid)
            self.assertTrue(text.startswith("enforced:"), rid)
            for f in files:
                self.assertIn(f, text, (rid, f))
            for f in re.findall(r"sisi/[a-z_]+\.py", text):
                self.assertTrue(os.path.isfile(os.path.join(REPO, f)), f)

    def test_the_rule_for_orchestration_has_one_statement_per_mechanism_of_both_sides(self):
        text = rulecmd.enforcement_for("orchestrate")
        for part in ("direct tool calls", "names no model", "failed three times", "arriving as a delegation result", "`sisi route` decision",
                     "--retry-of", "one refusal at a time", "judgement of each finished delegation"):
            self.assertEqual(text.count(part), 1, part)
        self.assertNotIn("stronger", text.split("--retry-of")[1][:200].split(";")[0].replace("strictly", ""))


class ConfigDefault(SisiCase):
    """Integration point 7."""

    def test_every_section_of_both_sides_and_valid_json(self):
        with open(os.path.join(REPO, "config.default.json")) as f:
            cfg = json.load(f)
        for section in ("gate", "verify", "retro", "route", "unit", "orchestrate"):
            self.assertIn(section, cfg)
        self.assertEqual(sorted(cfg["orchestrate"]), ["direct_calls", "direct_chars", "enabled", "extension", "route_window_min"])
        self.assertEqual(sorted(cfg["route"]), ["price_blend_input_parts", "standing_floor"])
        self.assertEqual(cfg["unit"], {"stale_hours": 12})
        self.assertEqual(store.config()["orchestrate"]["direct_calls"], 6)


# --------------------------------------------------------------------------- the four fixes

class DeepStaysFreshThroughAPause(TG.GuardCase):
    """Fix A."""

    def test_a_pause_does_not_make_a_fresh_deep_result_stale(self):
        deep = dict(TG.real("slow"), tier="deep", cmd="test -f src/app.py")
        c = TG.good_contract(checks=[TG.real("c1"), deep])
        self.open_unit(c)
        r = self.sisi("verify", "--deep")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        state = json.loads(self.sisi("verify", "--state", "--json").stdout)
        self.assertTrue(state["fresh"], state)
        r = self.sisi("unit", "pause", "waiting for the reviewer", env={"SISI_SESSION_ID": self.sid})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(C.load(self.contract_path)["pauses"])  # the contract file did change
        state = json.loads(self.sisi("verify", "--state", "--json").stdout)
        self.assertTrue(state["fresh"], state)

    def test_a_change_to_the_work_still_makes_it_stale(self):
        deep = dict(TG.real("slow"), tier="deep", cmd="test -f src/app.py")
        self.open_unit(TG.good_contract(checks=[TG.real("c1"), deep]))
        self.sisi("verify", "--deep")
        self.put(SRC, "def greet():\n    return 'yo'\n")
        self.assertFalse(json.loads(self.sisi("verify", "--state", "--json").stdout)["fresh"])


class SendBackSaysWhy(TG.GuardCase):
    """Fix B."""

    def test_the_reason_is_the_contract_when_no_path_gave_one(self):
        self.assertEqual(gate.profile_reason("integration", {"declared": "integration"}, ["no changed paths"]),
                         "the contract declares the integration profile")
        self.assertEqual(gate.profile_reason("integration", {"declared": "integration"}, ["auth code", "x"]), "auth code")
        self.assertIsNone(gate.profile_reason("trivial", {"declared": None}, ["no changed paths"]))

    def test_the_gates_message_does_not_open_with_no_changed_paths(self):
        os.environ["SISI_RETRO_REQUIRED"] = "1"
        self.addCleanup(lambda: os.environ.__setitem__("SISI_RETRO_REQUIRED", "0"))
        self.tick()
        self.open_unit(TG.good_contract(profile="integration"))
        sess = store.load_session(self.sid)
        sess["dirty"] = True
        store.save_session(self.sid, sess)
        action, msg = gate.decide({"session_id": self.sid, "cwd": self.proj, "hook_event_name": "Stop", "stop_hook_active": False})
        self.assertEqual(action, "block", msg)
        self.assertNotIn("no changed paths", msg)
        self.assertIn("because the contract declares the integration profile", msg.splitlines()[0])


class NoDeadlockAfterARefusedEdit(TG.GuardCase):
    """Found by the live check: the transcript shows an edit the hook refused, the guard counted it as a change, and
    from then on every shell command was refused, `sisi contract init 2>&1 | head` included."""

    def transcript_shows_edit(self, rel=SRC):
        sess = store.load_session(self.sid)
        sess["attr_since_pass"] = [os.path.join(self.proj, rel)]
        store.save_session(self.sid, sess)

    def test_an_edit_the_tree_never_saw_is_not_a_change(self):
        self.assertIn("sisi contract init", self.edit())
        self.transcript_shows_edit()
        self.assertIsNone(self.bash("python3 -c 'print(1)'"))
        self.assertEqual(G.session_paths(store.load_session(self.sid)), [])

    def test_an_edit_the_tree_did_see_still_is(self):
        self.put(SRC, "def greet():\n    return 'yo'\n")
        self.transcript_shows_edit()
        msg = self.bash("python3 -c 'print(1)'")
        self.assertIn("already changed", msg)
        self.assertIn("sisi contract init", msg)

    def test_the_way_out_is_never_refused_even_piped_through_a_filter(self):
        self.put(SRC, "def greet():\n    return 'yo'\n")
        self.transcript_shows_edit()
        for cmd in ("sisi contract init", "sisi contract init 2>&1 | head -60", "sisi unit continue 2>&1 | tail -5",
                    "sisi contract check | grep -n goal"):
            self.assertIsNone(self.bash(cmd), cmd)
        for cmd in ("sisi contract init > notes.txt", "sisi contract init | tee notes.txt"):
            self.assertIsNotNone(self.bash(cmd), cmd)

    def test_a_write_named_by_a_shell_variable_is_ordinary_source(self):
        """Found by the live check: `for f in src/*; do sed -i ... "$f"; done` slipped through as a trivial change."""
        msg = self.bash('for f in src/*.py; do sed -i "s/a/b/" "$f"; done')
        self.assertIn("sisi contract init", msg)
        self.assertIn("does not name", msg)
        self.assertLessEqual(len(msg.splitlines()), 12)
        self.open_unit()
        self.assertIsNone(self.bash('for f in src/*.py; do sed -i "s/a/b/" "$f"; done'))

    def test_a_line_that_cannot_be_split_but_plainly_writes_is_ordinary_source(self):
        cmd = ("for i in 01 02; do sed -i \"s/a$i/b/\" src/mod$i.py; done && python3 -c \"\nimport sys\nprint(f'x{1}')\n\" ; "
               "git diff | grep '^[-+] ' \"")  # an unbalanced quote: no tokenizer reads it
        self.assertEqual(G.shell_targets(cmd, self.proj), [G.UNPARSED])
        self.assertIn("sisi contract init", self.bash(cmd))
        self.assertEqual(G.shell_targets('echo "unbalanced; ls', self.proj), [])  # nothing plainly writing: left to the snapshot

    def test_a_cache_folder_is_as_ignorable_as_the_files_in_it(self):
        self.assertIsNone(self.bash("rm -rf src/__pycache__"))


class CopySurvivesVanishingFiles(SisiCase):
    """Fix C."""

    def setUp(self):
        super().setUp()
        self.src = os.path.join(self.tmp, "src")
        for rel in ("a.txt", "b.lock", "sub/c.txt", "sub/d.lock"):
            p = os.path.join(self.src, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(rel)
        self.out = os.path.join(self.tmp, "backup")

    def test_a_file_removed_mid_copy_is_left_out(self):
        real = shutil.copy2

        def racy(s, d, *a, **kw):
            if s.endswith(".lock"):
                os.unlink(s)  # gone between the listing and the copy
            return real(s, d, *a, **kw)
        with mock.patch.object(lifecycle.shutil, "copy2", racy):
            lifecycle._copy_into(self.src, self.out, "data")
        got = sorted(os.path.relpath(os.path.join(dp, n), self.out) for dp, _d, fs in os.walk(self.out) for n in fs)
        self.assertEqual(got, ["data/a.txt", "data/sub/c.txt"])

    def test_a_folder_removed_mid_copy_is_left_out(self):
        real = os.listdir

        def racy(p):
            if p.endswith("sub"):
                shutil.rmtree(p)
            return real(p)
        with mock.patch.object(lifecycle.os, "listdir", racy):
            lifecycle._copy_into(self.src, self.out, "data")
        self.assertTrue(os.path.isfile(os.path.join(self.out, "data", "a.txt")))

    def test_a_real_error_is_still_an_error(self):
        with mock.patch.object(lifecycle.shutil, "copy2", side_effect=PermissionError("no")):
            with self.assertRaises(PermissionError):
                lifecycle._copy_into(self.src, self.out, "data")


class NoRecipeForAMachine(SisiCase):
    """Fix D."""

    def mk(self):
        from sisi import learning as L
        f = dict(moment="the tagged build shipped with a changelog for the previous version",
                 cause="nobody compared the tag, the manifest version and the changelog before publishing",
                 change="Before publishing, check the tag, the manifest version and the changelog agree")
        return L.new_record(f["moment"], f["cause"], "correctness", "promote", self.proj, "u-test", change=f["change"],
                            mechanism="policy", scope="project", expect="caught before delivery", validate="replay")["id"]

    def ask(self, text, tool=None):
        args = ["prompt"] + (["--tool", tool] if tool else [])
        r = self.sisi(*args, stdin=json.dumps({"prompt": text, "session_id": "s1", "cwd": self.proj}))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else ""

    NOTICES = ('Delegated task "cut a new release and tag it" [completed]: tagged v2 and published the release notes',
               'Delegated task "cut a new release and tag it" [failed]: API error 429, usage limit reached',
               '[failed]: cut a new release and tag it, the worker hit a usage limit',
               '<task-notification>\n<status>completed</status>\n<summary>cut a new release and tag it</summary>\n</task-notification>',
               'Scheduled wake-up: cut a new release and tag it when the build is green')

    def test_a_person_gets_the_recipe(self):
        self.mk()
        self.assertIn("recipe `release`", self.ask("cut a new release and tag it"))

    def test_a_machines_notice_gets_no_recipe(self):
        self.mk()
        for text in self.NOTICES:
            with self.subTest(text=text[:40]):
                self.assertNotIn("recipe", self.ask(text))

    def test_learnings_in_scope_still_go_through_for_a_notice(self):
        lid = self.mk()
        ctx = self.ask('Delegated task "publish the release: check the tag, the manifest version and the changelog" '
                       '[completed]: ready to publish')
        self.assertIn(lid, ctx)
        self.assertNotIn("Done means", ctx)

    def test_the_test_is_the_one_delivery_uses_and_it_defaults_to_no_recipe(self):
        from sisi import harvest
        for text in self.NOTICES:
            self.assertIsNone(harvest.typed_text({}, queued_prompt=text)[0], text)
        self.assertTrue(prompt.is_request("cut a new release and tag it"))
        with mock.patch.object(harvest, "typed_text", side_effect=RuntimeError("cannot tell")):
            self.assertFalse(prompt.is_request("cut a new release and tag it"))
        self.assertFalse(prompt.is_request("cut a new release and tag it", {"origin": {"kind": "task-notification"}}))


if __name__ == "__main__":
    unittest.main()
