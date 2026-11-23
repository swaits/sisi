"""Rule 3 as a mechanism: a unit is bound to the session that works on it, the first building step is
refused without a valid unit for THIS work, pause cannot skip the contract, the gate judges only the unit
a session holds, and nobody is their own independent evidence.

Requirement ids (docs/spec/requirements.json): R-9-1 (the lifecycle is followed), R-10.1-1 (a unit is one
piece of work, not a leftover), R-10.2-1 (the unit's durable record), R-10.3-1 (closing and pausing
cannot skip what the unit owes), R-5.3-1 and R-5.3-4 (the profile's row is enforced, the floor wins),
R-13.3-4 (independent evaluation is independent of the implementer), R-14.2-1 (stay inside the lines).
The abuse cases are written from the side of an agent that wants to skip."""
import contextlib, io, json, os, subprocess, sys, time, unittest
from unittest import mock
from support import *
from sisi import assure, contract as C, gate, gitutil, store, unit as U, unitguard as G, watch

SRC = "src/app.py"


def real(id, cmd="test -f src/app.py", **kw):
    return dict(check(id, cmd), covers="the source file is missing", **kw)


def good_contract(goal="make the app greet", profile="isolated", **over):
    c = {"id": "work", "parent": None, "goal": goal, "scope": {"in": [], "out": []},
         "requirements": [], "risk": {"profile": profile}, "checks": [real("c1")], "invariants": [],
         "assumptions": [], "questions": [], "deferred": [], "limitations": [], "plan": [], "approach": None,
         "status": "open", "started": store.now(), "pauses": [], "deviations": []}
    c.update(over)
    return c


def full_contract(**over):
    """Carries everything an integration-or-higher unit needs before building."""
    c = good_contract(profile="integration")
    c.update(requirements=[{"id": "r1", "kind": "explicit", "text": "the app greets by name", "decision": "now"}],
             invariants=[dict(check("inv", "test -f README.md"), claim="the readme stays", covers="readme deleted")],
             approach={"chosen": "change the greeting function", "why": "the smallest change",
                       "alternatives": ["a template engine: more moving parts"]})
    c["risk"] = {"profile": "integration", "blast_radius": "only the greeting; nothing else reads it",
                 "rollback": "git revert the commit"}
    c.update(over)
    return c


class GuardCase(SisiCase):
    sid = "me"
    model = "model-a"

    def setUp(self):
        super().setUp()
        self.git_init()
        self.put("README.md", "# app\n")
        self.put(SRC, "def greet():\n    return 'hi'\n")
        self.git_commit()
        self.contract_path = os.path.join(self.proj, C.REL)

    # ----- project helpers
    def put(self, rel, text="x\n"):
        p = os.path.join(self.proj, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
        return p

    def git_commit(self):
        subprocess.run(["git", "add", "-A"], cwd=self.proj, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c"], cwd=self.proj, check=True)

    def tick(self, sid=None, model=None, **extra):
        """The session-start hook for this session."""
        self.sisi("tick", stdin=json.dumps(dict({"session_id": sid or self.sid, "cwd": self.proj, "source": "startup",
                                                 "model": model or self.model}, **extra)))

    def open_unit(self, c=None, bind=True, sid=None):
        self.write_contract(c or good_contract())
        c = C.load(self.contract_path)
        if bind:
            G.bind(sid or self.sid, self.proj, c, "init")
        return c

    # ----- the hook
    def payload(self, tool, inp, sid=None, **extra):
        return dict({"session_id": sid or self.sid, "cwd": self.proj, "hook_event_name": "PreToolUse",
                     "tool_name": tool, "tool_input": inp}, **extra)

    def before(self, tool, inp, sid=None, **extra):
        """Run the before-tool guard as the hook would. Returns the refusal text, or None when the call goes through."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            refused = G.before(self.payload(tool, inp, sid, **extra))
        if not refused:
            self.assertEqual(out.getvalue(), "")
            return None
        d = json.loads(out.getvalue())["hookSpecificOutput"]
        self.assertEqual((d["hookEventName"], d["permissionDecision"]), ("PreToolUse", "deny"))
        return d["permissionDecisionReason"]

    def edit(self, rel=SRC, **kw):
        return self.before("Edit", {"file_path": os.path.join(self.proj, rel), "old_string": "a", "new_string": "b"}, **kw)

    def bash(self, cmd, **kw):
        return self.before("Bash", {"command": cmd}, **kw)

    def refusals(self):
        return store.read(G.REFUSALS)

    def age_unit(self, c, ago_s, sid=None):
        """The unit was started and last active `ago_s` seconds ago; the session is (still) bound to it."""
        c["started"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - ago_s))
        C.save(self.contract_path, c)
        G.bind(sid or self.sid, self.proj, c, "init")
        G._save(G._act_path(G.unit_key(self.proj, c)), {"project": os.path.realpath(self.proj), "id": c["id"],
                                                       "started": c.get("started"), "last": time.time() - ago_s})
        return c


class BindingTests(GuardCase):
    """Item 1: a unit is bound to the session that works on it (R-10.1-1)."""

    def init(self, sid="me", goal="make the app greet"):
        r = self.sisi("contract", "init", "--goal", goal, env={"SISI_SESSION_ID": sid})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return C.load(self.contract_path)

    def test_the_session_that_opens_a_unit_is_bound_to_it_and_another_is_not(self):
        c = self.init("me")
        self.assertTrue(G.is_bound(store.load_session("me"), self.proj, c))
        self.assertFalse(G.is_bound(store.load_session("other"), self.proj, c))

    def test_continue_binds_the_session_and_says_the_goal_the_age_and_what_is_owed(self):
        c = good_contract(goal="reshape the greeting")
        c["started"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3 * 86400))
        self.write_contract(c)
        self.assertFalse(G.is_bound(store.load_session("other"), self.proj, C.load(self.contract_path)))
        r = self.sisi("unit", "continue", env={"SISI_SESSION_ID": "other"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("reshape the greeting", r.stdout)
        self.assertIn("3 days ago", r.stdout)
        self.assertIn("c1 (not-run)", r.stdout)
        self.assertTrue(G.is_bound(store.load_session("other"), self.proj, C.load(self.contract_path)))

    def test_continue_without_a_unit_or_on_a_closed_one_is_refused(self):
        self.assertNotEqual(self.sisi("unit", "continue", env={"SISI_SESSION_ID": "s"}).returncode, 0)
        self.write_contract(good_contract(status="closed"))
        r = self.sisi("unit", "continue", env={"SISI_SESSION_ID": "s"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("closed", r.stdout)

    def test_a_unit_with_no_activity_for_stale_hours_needs_continue_again(self):
        c = self.init("me")
        self.assertEqual(G.bound_fresh(store.load_session("me"), self.proj, c)[0], "ok")
        self.age_unit(c, 13 * 3600, "me")
        self.assertEqual(G.bound_fresh(store.load_session("me"), self.proj, c)[0], "stale")
        r = self.sisi("unit", "continue", env={"SISI_SESSION_ID": "me"})
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(G.bound_fresh(store.load_session("me"), self.proj, c)[0], "ok")

    def test_stale_hours_is_configurable(self):
        c = self.age_unit(self.init("me"), 2 * 3600, "me")
        self.assertEqual(G.bound_fresh(store.load_session("me"), self.proj, c)[0], "ok")  # the default is 12 hours
        os.makedirs(self.data, exist_ok=True)
        with open(os.path.join(self.data, "config.json"), "w") as f:
            json.dump({"unit": {"stale_hours": 1}}, f)
        self.assertEqual(G.bound_fresh(store.load_session("me"), self.proj, c)[0], "stale")

    def test_a_verification_run_counts_as_activity(self):
        c = self.age_unit(self.init("me"), 30 * 3600, "me")
        self.assertEqual(G.bound_fresh(store.load_session("me"), self.proj, c)[0], "stale")
        store.append("results", {"ts": store.now(), "contract": c["id"], "project": self.proj, "check": "c1",
                                 "item": "check", "status": "passed", "run": "r1"})
        self.assertEqual(G.bound_fresh(store.load_session("me"), self.proj, c)[0], "ok")

    def test_contract_init_on_an_open_unit_names_all_three_ways_on(self):
        self.init("me")
        r = self.sisi("contract", "init", env={"SISI_SESSION_ID": "me"})
        self.assertEqual(r.returncode, 1)
        for way in ("sisi unit continue", "sisi unit park", "sisi unit close --abandon"):
            self.assertIn(way, r.stdout)
        self.assertEqual(C.load(self.contract_path)["goal"], "make the app greet")  # the old unit is untouched

    def test_park_sets_the_unit_aside_keeping_its_contract_and_what_it_owes(self):
        c = self.init("me")
        r = self.sisi("unit", "park", "the owner asked for something else first", env={"SISI_SESSION_ID": "me"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.contract_path))
        with open(os.path.join(self.proj, ".sisi", "parked", "proj.json")) as f:
            rec = json.load(f)
        self.assertEqual(rec["contract"]["goal"], c["goal"])
        self.assertEqual(rec["parked"]["why"], "the owner asked for something else first")
        self.assertEqual(rec["parked"]["owes"], [["c1", "not-run"], ["deep-example", "not-run"]])
        self.assertIn("c1", r.stdout)

    def test_park_needs_a_reason_and_an_open_unit(self):
        self.assertNotEqual(self.sisi("unit", "park", "why").returncode, 0)
        self.init("me")
        self.assertEqual(self.sisi("unit", "park").returncode, 1)
        self.assertTrue(os.path.exists(self.contract_path))

    def test_status_and_unit_list_show_a_parked_unit_with_its_age_and_what_it_owes(self):
        self.init("me")
        self.sisi("unit", "park", "waiting for the owner", env={"SISI_SESSION_ID": "me"})
        st = self.sisi("status").stdout
        self.assertIn("parked", st)
        self.assertIn("proj", st)
        self.assertIn("waiting for the owner", st)
        self.assertIn("c1 (not-run)", st)
        ls = self.sisi("unit", "list").stdout
        self.assertIn("parked", ls)
        self.assertIn("c1 (not-run)", ls)

    def test_resume_brings_a_parked_unit_back_when_no_unit_is_open_and_binds_the_session(self):
        self.init("me")
        self.sisi("unit", "park", "later", env={"SISI_SESSION_ID": "me"})
        self.init("me", goal="other work")  # new work while the first is parked: it gets its own id
        self.assertNotEqual(C.load(self.contract_path)["id"], "proj")
        r = self.sisi("unit", "resume", "proj", env={"SISI_SESSION_ID": "me"})
        self.assertEqual(r.returncode, 1, "a unit is open: resume must wait")
        self.assertIn("sisi unit park", r.stdout)
        self.sisi("unit", "close", "--abandon", "dropped", env={"SISI_SESSION_ID": "me"})
        r = self.sisi("unit", "resume", "proj", env={"SISI_SESSION_ID": "third"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        c = C.load(self.contract_path)
        self.assertEqual((c["id"], c["goal"]), ("proj", "make the app greet"))
        self.assertTrue(G.is_bound(store.load_session("third"), self.proj, c))
        self.assertFalse(os.path.exists(os.path.join(self.proj, ".sisi", "parked", "proj.json")))

    def test_resume_of_an_unknown_id_says_so(self):
        r = self.sisi("unit", "resume", "nope")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no parked unit", r.stdout)


class RefusalTests(GuardCase):
    """Item 2: the first building step is refused without a valid unit for this work (R-9-1, R-5.3-1)."""

    def refused(self, msg, *needles):
        self.assertIsNotNone(msg, "the call was let through")
        self.assertLessEqual(len(msg.splitlines()), 12, msg)
        for n in needles:
            self.assertIn(n, msg)
        return msg

    def foreign_unit(self, ago_s=3 * 86400, goal="redo the old report"):
        c = good_contract(goal=goal, id="old-report")
        self.write_contract(c)
        self.age_unit(c, ago_s, sid="someone-else")
        return C.load(self.contract_path)

    # ---- no unit at all
    def test_a_source_edit_with_no_unit_is_refused_naming_what_to_run(self):
        msg = self.refused(self.edit(), "sisi contract init", "src/app.py", "isolated", "rule 3")
        self.assertIn("goal", msg)
        self.assertIn("Then retry", msg)

    def test_the_refusal_is_stored_with_what_and_when(self):
        self.edit()
        (r,) = self.refusals()
        self.assertEqual((r["state"], r["unit"], r["session"]), ("none", None, "me"))
        self.assertIn("src/app.py", r["what"])
        self.assertRegex(r["ts"], r"^\d{4}-\d\d-\d\dT")

    def test_a_trivial_change_is_never_refused(self):
        self.assertIsNone(self.edit("README.md"))
        self.assertIsNone(self.edit("docs/notes.md"))
        self.assertEqual(self.refusals(), [])

    def test_writes_under_dot_sisi_and_outside_the_project_are_never_refused(self):
        self.assertIsNone(self.before("Write", {"file_path": os.path.join(self.proj, ".sisi", "risk.json"), "content": "{}"}))
        self.assertIsNone(self.before("Write", {"file_path": os.path.join(self.tmp, "elsewhere", "x.py"), "content": "x"}))
        self.assertIsNone(self.bash("echo x > %s" % os.path.join(self.tmp, "elsewhere.py")))
        self.assertIsNone(self.bash("echo x > .sisi/notes.py"))
        self.assertEqual(self.refusals(), [])

    def test_reading_tools_and_read_only_commands_are_not_counted(self):
        self.assertIsNone(self.before("Read", {"file_path": os.path.join(self.proj, SRC)}))
        self.assertIsNone(self.before("Grep", {"pattern": "greet"}))
        self.assertIsNone(self.bash("git status && ls src"))
        self.assertIsNone(self.bash("python3 -m pytest -q"))  # runs tests: no known write target

    def test_sisi_commands_that_resolve_a_refusal_are_never_refused(self):
        self.assertIsNone(self.bash("sisi contract init --goal 'x'"))
        self.assertIsNone(self.bash("sisi unit park 'why' && sisi unit continue"))

    # ---- a valid unit
    def test_with_a_valid_bound_unit_the_edit_goes_through(self):
        self.open_unit()
        self.assertIsNone(self.edit())
        self.assertEqual(self.refusals(), [])

    # ---- abuse: a stale or foreign unit from other work
    def test_a_stale_unit_from_another_session_is_named_with_its_goal_and_age_and_the_three_ways_on(self):
        self.foreign_unit()
        msg = self.refused(self.edit(), "old-report", "redo the old report", "3 days ago", "sisi unit continue",
                           "sisi unit park", "sisi unit close --abandon", "sisi contract init")
        self.assertNotIn("c1", msg, "it must not list the foreign unit's checks")
        self.assertEqual(C.load(self.contract_path)["goal"], "redo the old report")

    def test_a_fresh_unit_another_session_opened_is_foreign_too(self):
        self.write_contract(good_contract())
        G.bind("someone-else", self.proj, C.load(self.contract_path), "init")
        self.refused(self.edit(), "sisi unit continue")

    def test_continue_then_the_edit_goes_through_and_a_bound_but_stale_unit_asks_for_continue_again(self):
        c = self.foreign_unit()
        self.refused(self.edit(), "sisi unit continue")
        self.assertEqual(self.sisi("unit", "continue", env={"SISI_SESSION_ID": "me"}).returncode, 0)
        self.assertIsNone(self.edit())
        self.age_unit(C.load(self.contract_path), 20 * 3600, "me")
        self.refused(self.edit(), "no activity since", "sisi unit continue")

    def test_the_refusal_is_recorded_against_the_unit_the_session_holds(self):
        c = self.open_unit(good_contract(checks=[dict(real("c1"), cmd="true")]))  # a vacuous check: invalid
        self.edit()
        (r,) = self.refusals()
        self.assertEqual((r["unit"], r["state"]), ("work", "invalid"))

    # ---- abuse: an invalid contract
    def test_contract_init_that_leaves_the_placeholder_checks_is_still_refused(self):
        r = self.sisi("contract", "init", "--goal", "make the app greet", env={"SISI_SESSION_ID": "me"})
        self.assertEqual(r.returncode, 0)
        self.refused(self.edit(), "placeholder")

    def test_one_placeholder_check_left_among_real_ones_is_refused(self):
        self.sisi("contract", "init", "--goal", "make the app greet", env={"SISI_SESSION_ID": "me"})
        c = C.load(self.contract_path)
        c["checks"][0] = real("c1")
        c["risk"]["profile"] = "isolated"
        C.save(self.contract_path, c)  # the deep placeholder is still there
        self.refused(self.edit(), "placeholder")
        c["checks"] = c["checks"][:1]
        C.save(self.contract_path, c)
        self.assertIsNone(self.edit())

    def test_a_placeholder_goal_is_refused(self):
        self.open_unit(good_contract(goal="TODO: one sentence describing the outcome"))
        self.refused(self.edit(), "goal")

    def test_a_vacuous_check_is_refused_with_contract_check_named(self):
        self.open_unit(good_contract(checks=[dict(real("c1"), cmd="true")]))
        self.refused(self.edit(), "cannot fail")

    def test_declaring_trivial_on_a_source_path_with_no_reason_is_still_refused(self):
        self.open_unit(good_contract(profile="trivial"))
        self.refused(self.edit(), "below the floor", "risk")
        c = C.load(self.contract_path)
        c["risk"]["why"] = "a one-word string change that cannot affect behaviour"
        C.save(self.contract_path, c)
        self.assertIsNone(self.edit(), "a reason on the record lowers it, as the gate allows")

    def test_integration_work_needs_the_requirement_list_the_risk_note_and_the_approach_before_building(self):
        c = good_contract()
        c["checks"] = [real("c1")]
        self.open_unit(c)
        msg = self.refused(self.edit("package.json"), "requirement list", "risk note", "approach")
        self.assertNotIn("independent", msg)
        self.open_unit(full_contract())
        self.assertIsNone(self.edit("package.json"))

    def test_independent_evidence_and_the_retro_are_not_asked_before_building(self):
        self.open_unit(full_contract(risk={"profile": "data", "blast_radius": "the stored rows", "rollback": "restore backup"}))
        self.assertIsNone(self.edit("db/schema.sql"))

    # ---- abuse: shell writes
    def test_a_shell_redirect_tee_sed_and_a_heredoc_are_refused(self):
        for cmd in ("echo 'x = 1' > src/app.py", "echo x | tee src/app.py", "sed -i 's/hi/yo/' src/app.py",
                    "cat > src/app.py <<'EOF'\nx = 1\nEOF", "cp /tmp/new.py src/app.py", "printf x >> src/app.py"):
            self.refused(self.bash(cmd), "src/app.py", "sisi contract init")

    def test_python_dash_c_slips_past_the_text_but_the_snapshot_refuses_the_next_call(self):
        cmd = "python3 -c \"open('src/app.py', 'w').write('x = 1')\""
        self.assertIsNone(self.bash(cmd))
        payload = self.payload("Bash", {"command": cmd})
        watch.before(payload)  # the stat-only snapshot before it ran
        self.put(SRC, "x = 1\n")
        watch.after(payload)
        G.after(payload)
        self.refused(self.edit("README.md"), "src/app.py", "sisi contract init")
        self.refused(self.bash("echo hi > notes.py"))

    def test_the_slip_is_forgiven_once_a_valid_unit_stands_behind_it(self):
        cmd = "python3 -c \"open('src/app.py', 'w').write('x = 1')\""
        payload = self.payload("Bash", {"command": cmd})
        watch.before(payload)
        self.put(SRC, "x = 1\n")
        watch.after(payload)
        G.after(payload)
        self.refused(self.edit("README.md"))
        self.open_unit()
        self.assertIsNone(self.edit("README.md"))
        self.assertEqual(store.load_session("me").get("ug_paths"), [])

    def test_a_slip_by_a_read_only_followup_is_not_refused(self):
        payload = self.payload("Bash", {"command": "python3 gen.py"})
        watch.before(payload)
        self.put("gen_out.py", "x = 1\n")
        watch.after(payload)
        G.after(payload)
        self.assertIsNone(self.before("Read", {"file_path": os.path.join(self.proj, SRC)}))
        self.assertIsNone(self.bash("git status"))

    def test_build_output_that_a_run_leaves_behind_is_not_a_slip(self):
        payload = self.payload("Bash", {"command": "python3 gen.py"})
        watch.before(payload)
        self.put("src/__pycache__/app.cpython-312.pyc", "bin")
        watch.after(payload)
        G.after(payload)
        self.assertIsNone(self.edit("README.md"))

    # ---- abuse: rewriting another unit's contract
    def test_writing_the_contract_file_of_a_unit_the_session_does_not_hold_is_refused(self):
        self.foreign_unit()
        msg = self.refused(self.before("Write", {"file_path": self.contract_path, "content": "{}"}),
                           "old-report", "sisi unit park")
        self.assertEqual(C.load(self.contract_path)["goal"], "redo the old report")
        self.refused(self.bash("echo '{}' > .sisi/contract.json"), "sisi unit park")
        self.refused(self.before("Edit", {"file_path": self.contract_path, "old_string": "a", "new_string": "b"}))

    def test_writing_a_contract_when_none_is_open_is_allowed_and_binds_the_writer(self):
        self.assertIsNone(self.before("Write", {"file_path": self.contract_path, "content": "{}"}))
        self.write_contract(good_contract())
        G.after(self.payload("Write", {"file_path": self.contract_path, "content": "{}"}))
        self.assertTrue(G.is_bound(store.load_session("me"), self.proj, C.load(self.contract_path)))
        self.assertIsNone(self.before("Edit", {"file_path": self.contract_path, "old_string": "a", "new_string": "b"}))

    # ---- who is exempt, and failure
    def test_worker_and_subagent_sessions_are_never_refused(self):
        self.assertIsNone(self.edit(agent_id="a1"))
        self.assertIsNone(self.edit(agent_transcript_path="/x/subagents/agent-a1.jsonl"))
        self.tick("sub", subagent=None)
        s = store.load_session("sub")
        s["subagent"] = True
        store.save_session("sub", s)
        self.assertIsNone(self.edit(sid="sub"))
        with mock.patch.dict(os.environ, {"SISI_WORKER_RUN": "1"}):
            self.assertIsNone(self.edit())
        self.assertEqual(self.refusals(), [])

    def test_an_error_inside_the_guard_lets_the_call_through(self):
        with mock.patch.object(G, "verdict", side_effect=RuntimeError("boom")):
            self.assertIsNone(self.edit())
        with mock.patch.object(G, "_before", side_effect=RuntimeError("boom")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertFalse(G.before(self.payload("Edit", {"file_path": os.path.join(self.proj, SRC)})))
            self.assertEqual(out.getvalue(), "")
            r = self.sisi("watch", "--before", stdin=json.dumps(self.payload("Edit", {"file_path": os.path.join(self.proj, SRC)})))
            self.assertEqual(r.returncode, 0)

    def test_outside_a_repository_nothing_is_measured_and_nothing_is_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.py")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                refused = G.before({"session_id": "me", "cwd": d, "tool_name": "Write", "tool_input": {"file_path": p}})
            self.assertFalse(refused)

    def test_the_real_hook_command_prints_the_hosts_refusal_and_runs_nothing_else(self):
        r = self.sisi("watch", "--before", stdin=json.dumps(self.payload("Write", {"file_path": os.path.join(self.proj, SRC), "content": "x"})))
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(d["permissionDecision"], "deny")
        self.assertIn("sisi contract init", d["permissionDecisionReason"])
        r = self.sisi("watch", "--before", stdin=json.dumps(self.payload("Write", {"file_path": os.path.join(self.proj, "README.md"), "content": "x"})))
        self.assertEqual(r.stdout, "")

    def test_the_refusal_is_not_longer_than_twelve_lines_in_any_state(self):
        for build in (lambda: None, lambda: self.foreign_unit(),
                      lambda: self.open_unit(good_contract(profile="critical", checks=[dict(real("c1"), cmd="true")]))):
            build()
            self.assertLessEqual(len((self.edit("auth/login.py") or "").splitlines()), 12)


class DelegationTests(GuardCase):
    """Item 3: delegating a build needs the unit too (R-9-1; the contract is where a brief's acceptance comes from)."""

    def spawn(self, prompt, tool="Agent", **kw):
        return self.before(tool, {"description": "worker", "prompt": prompt, "subagent_type": "general-purpose"}, **kw)

    def route(self, kind):
        s = store.load_session(self.sid)
        s["route"] = {"kind": kind}
        store.save_session(self.sid, s)

    def test_delegating_a_build_with_no_unit_is_refused_and_says_where_the_acceptance_comes_from(self):
        for tool in ("Agent", "Task"):
            msg = self.spawn("Implement the new greeting in src/app.py and fix the tests", tool=tool)
            self.assertIsNotNone(msg)
            self.assertIn("sisi contract init", msg)
            self.assertIn("acceptance", msg)
            self.assertLessEqual(len(msg.splitlines()), 12)
        self.assertEqual(len(self.refusals()), 2)

    def test_a_read_only_search_is_allowed(self):
        self.assertIsNone(self.spawn("Search the codebase for every caller of greet and list them"))
        self.assertIsNone(self.spawn("Find where the config is read. Do not modify any file."))
        self.assertEqual(self.refusals(), [])

    def test_the_routing_kind_decides_when_one_is_recorded(self):
        for kind in ("impl", "impl-multi", "edit", "tests", "debug"):
            self.route(kind)
            self.assertIsNotNone(self.spawn("look into the greeting"), kind)
        for kind in ("review", "search", "research"):
            self.route(kind)
            self.assertIsNone(self.spawn("fix and implement everything"), kind)

    def test_with_a_valid_bound_unit_the_delegation_goes_through(self):
        self.open_unit()
        self.assertIsNone(self.spawn("Implement the new greeting in src/app.py"))

    def test_with_another_sessions_unit_it_is_refused_with_the_three_ways_on(self):
        self.write_contract(good_contract(goal="old work"))
        G.bind("someone", self.proj, C.load(self.contract_path), "init")
        msg = self.spawn("Implement the new greeting")
        self.assertIn("sisi unit park", msg)
        self.assertIn("old work", msg)

    def test_a_worker_session_delegating_is_not_refused(self):
        self.assertIsNone(self.spawn("Implement the new greeting", agent_id="w1"))

    def test_a_guard_error_lets_the_delegation_through(self):
        with mock.patch.object(G, "is_building_delegation", side_effect=RuntimeError("x")):
            self.assertIsNone(self.spawn("Implement the new greeting"))


class PauseTests(GuardCase):
    """Item 4: pause is for waiting, not for skipping (R-10.3-1, R-14.2-1)."""

    def pause(self, sid="me", why="waiting for the reviewer"):
        return self.sisi("unit", "pause", why, env={"SISI_SESSION_ID": sid} if sid else {})

    def test_pausing_with_no_unit_is_refused(self):
        r = self.pause()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("never the contract", r.stdout)
        self.assertIn("sisi contract init", r.stdout)

    def test_pausing_a_unit_this_session_does_not_hold_is_refused_and_the_unit_is_untouched(self):
        self.write_contract(good_contract(goal="old work"))
        G.bind("someone", self.proj, C.load(self.contract_path), "init")
        with open(self.contract_path) as f:
            before = f.read()
        r = self.pause()
        self.assertNotEqual(r.returncode, 0)
        for way in ("sisi unit continue", "sisi unit park"):
            self.assertIn(way, r.stdout)
        self.assertLessEqual(len(r.stdout.splitlines()), 12)
        with open(self.contract_path) as f:
            self.assertEqual(f.read(), before)

    def test_pausing_without_a_known_session_is_refused(self):
        self.open_unit()
        self.assertNotEqual(self.pause(sid=None).returncode, 0)

    def test_pausing_a_unit_missing_what_building_needs_is_refused(self):
        """The placeholder skeleton is not a unit to hide behind."""
        self.sisi("contract", "init", "--goal", "make the app greet", env={"SISI_SESSION_ID": "me"})
        r = self.pause()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("placeholder", r.stdout)
        self.assertEqual(C.load(self.contract_path)["status"], "open")

    def test_pausing_an_integration_unit_without_its_requirement_list_is_refused(self):
        c = good_contract()
        self.open_unit(c)
        self.put("package.json", "{}\n")  # the work already touches a manifest: the floor is integration
        r = self.pause()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("requirement list", r.stdout)

    def test_a_valid_unit_this_session_holds_can_be_paused(self):
        self.open_unit()
        r = self.pause()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(C.load(self.contract_path)["status"], "paused")

    def test_every_refused_pause_is_recorded(self):
        self.pause()
        self.write_contract(good_contract())
        self.pause()
        self.assertEqual([r["tool"] for r in self.refusals()], ["pause", "pause"])
        self.assertTrue(all("pause" in r["what"] for r in self.refusals()))


class GateUnitTests(GuardCase):
    """Items 4 and 5: the gate judges only the unit the session holds, whatever is paused (R-5.3-1, R-10.1-1)."""

    def setUp(self):
        super().setUp()
        os.environ["SISI_RETRO_REQUIRED"] = "1"
        self.addCleanup(lambda: os.environ.__setitem__("SISI_RETRO_REQUIRED", "0"))
        self.tick()

    def stop(self, sid=None):
        return gate.decide({"session_id": sid or self.sid, "cwd": self.proj, "hook_event_name": "Stop", "stop_hook_active": False})

    def failing_foreign_unit(self, **kw):
        c = good_contract(goal="redo the old report", id="old-report", checks=[dict(real("oldcheck"), cmd="false")], **kw)
        self.write_contract(c)
        G.bind("someone-else", self.proj, C.load(self.contract_path), "init")

    def test_a_foreign_units_failing_checks_are_not_what_the_session_is_sent_back_for(self):
        self.failing_foreign_unit()
        self.put(SRC, "def greet():\n    return 'yo'\n")
        a, msg = self.stop()
        self.assertEqual(a, "block")
        for way in ("sisi unit continue", "sisi unit park", "sisi contract init"):
            self.assertIn(way, msg)
        self.assertIn("old-report", msg)
        self.assertNotIn("oldcheck", msg)
        self.assertNotIn("Failing checks", msg)
        self.assertEqual([r for r in self.results() if r.get("contract") == "old-report"], [], "its checks must not run")

    def test_a_trivial_change_with_a_foreign_unit_open_is_not_judged_at_all(self):
        self.failing_foreign_unit()
        self.put("README.md", "# app\nmore words\n")
        self.assertEqual(self.stop(), ("allow", None))
        self.assertEqual(self.results(), [])

    def test_a_stale_unit_the_session_was_bound_to_asks_for_continue_not_for_its_checks(self):
        self.write_contract(good_contract(checks=[dict(real("c1"), cmd="false")]))
        self.age_unit(C.load(self.contract_path), 20 * 3600, "me")
        self.put(SRC, "def greet():\n    return 'yo'\n")
        a, msg = self.stop()
        self.assertEqual(a, "block")
        self.assertIn("no activity since", msg)
        self.assertIn("sisi unit continue", msg)
        self.assertEqual(self.results(), [])

    def test_the_send_backs_run_out_as_unverified_and_the_foreign_unit_is_left_exactly_as_it_was(self):
        self.failing_foreign_unit()
        with open(self.contract_path) as f:
            before = f.read()
        self.put(SRC, "def greet():\n    return 'yo'\n")
        outs = [self.stop() for _ in range(4)]
        self.assertEqual([o[0] for o in outs[:3]], ["block"] * 3)
        self.assertEqual(outs[3][0], "allow")
        self.assertIn("UNVERIFIED", outs[3][1])
        with open(self.contract_path) as f:
            self.assertEqual(f.read(), before)

    def test_a_paused_foreign_unit_does_not_silence_the_gate_for_another_session(self):
        c = good_contract(goal="redo the old report", id="old-report")
        c["status"] = "paused"
        c["pauses"] = [{"what": "a review", "since": store.now(), "until": None}]
        self.write_contract(c)
        G.bind("someone-else", self.proj, C.load(self.contract_path), "init")
        self.put(SRC, "def greet():\n    return 'yo'\n")
        a, msg = self.stop()
        self.assertEqual(a, "block")
        self.assertIn("sisi unit continue", msg)
        self.assertEqual(C.load(self.contract_path)["status"], "paused")  # not resumed, not touched

    def test_a_paused_unit_silences_only_the_session_bound_to_it_and_only_while_valid(self):
        self.open_unit()
        self.put(SRC, "def greet():\n    return 'yo'\n")
        self.assertEqual(self.sisi("unit", "pause", "waiting for the reviewer", env={"SISI_SESSION_ID": "me"}).returncode, 0)
        self.assertEqual(self.stop(), ("allow", None))
        # the unit is broken after the pause (a vacuous check): the pause no longer hides anything
        c = C.load(self.contract_path)
        c["checks"] = [dict(real("c1"), cmd="true")]
        C.save(self.contract_path, c)
        self.put(SRC, "def greet():\n    return 'hey'\n")
        a, msg = self.stop()
        self.assertEqual(a, "block")
        self.assertIn("cannot fail", msg)

    def test_with_no_unit_at_all_a_source_change_is_still_sent_back_for_a_contract(self):
        self.put(SRC, "def greet():\n    return 'yo'\n")
        a, msg = self.stop()
        self.assertEqual(a, "block")
        self.assertIn("a contract for this isolated change", msg)

    def test_the_session_that_holds_the_unit_is_judged_as_before(self):
        self.open_unit(good_contract(checks=[dict(real("c1"), cmd="false")]))
        self.put(SRC, "def greet():\n    return 'yo'\n")
        a, msg = self.stop()
        self.assertEqual(a, "block")
        self.assertIn("c1", msg)


class IndependenceTests(GuardCase):
    """Item 6: nobody is their own independent evidence (R-13.3-4)."""

    def data_unit(self, by, independent=True, model="model-a"):
        self.tick(model=model)
        ch = dict(real("review"), independent=independent)
        if by is not None:
            ch["by"] = by
        c = full_contract(risk={"profile": "data", "blast_radius": "the stored rows", "rollback": "restore backup"})
        c["checks"] = [real("c1"), ch]
        self.write_contract(c)
        c = C.load(self.contract_path)
        G.bind(self.sid, self.proj, c, "init")
        return c

    def counted(self, c):
        res = [{"id": "review", "status": "passed"}]
        return assure.independent_evidence(self.proj, c, res)

    def test_a_self_reference_in_by_is_not_independent_evidence(self):
        for by in ("my own review", "me", "myself", "self", "I checked it", "the author", "this session", "own", "", "  ", None):
            c = self.data_unit(by)
            self.assertEqual(self.counted(c), [], repr(by))

    def test_the_sessions_own_model_named_in_by_is_not_independent(self):
        c = self.data_unit("model-a re-reading its own diff", model="model-a")
        self.assertEqual(self.counted(c), [])

    def test_something_else_named_in_by_counts_when_the_check_passes(self):
        c = self.data_unit("a separate reviewer agent running model-b", model="model-a")
        self.assertEqual(len(self.counted(c)), 1)
        self.assertEqual(self.counted(c)[0], "check review by a separate reviewer agent running model-b")

    def test_a_failing_or_unmarked_check_does_not_count_either(self):
        c = self.data_unit("a separate reviewer agent")
        self.assertEqual(assure.independent_evidence(self.proj, c, [{"id": "review", "status": "failed"}]), [])
        c = self.data_unit("a separate reviewer agent", independent=False)
        self.assertEqual(self.counted(c), [])

    def test_the_missing_list_says_why_the_claim_was_not_counted(self):
        c = self.data_unit("my own review")
        miss = assure.missing("data", c, self.proj, [{"id": "review", "status": "passed"}], C.validate(c))
        (what, how), = [m for m in miss if "independent" in m[0]]
        self.assertIn("review by 'my own review'", what)
        self.assertIn("by", how)

    def ledger(self, **row):
        base = {"type": "review", "outcome": "accepted", "check": "tests", "worker": "model-b"}
        return mock.patch("sisi.workers.delegations_for_project", return_value={"delegations": [dict(base, **row)]})

    def test_a_review_by_the_sessions_own_model_does_not_count_and_another_workers_does(self):
        c = self.data_unit("a separate reviewer agent", independent=False)
        with self.ledger(worker="model-a"):
            self.assertEqual(assure.independent_evidence(self.proj, c, []), [])
        with self.ledger(worker="provider/model-a"):
            self.assertEqual(assure.independent_evidence(self.proj, c, []), [])
        with self.ledger(worker="model-b"):
            self.assertEqual(assure.independent_evidence(self.proj, c, []), ["review by model-b"])

    def test_a_review_judged_with_no_check_or_not_accepted_does_not_count(self):
        c = self.data_unit("x", independent=False)
        for row in ({"check": "none"}, {"check": None}, {"outcome": "rejected"}, {"type": "impl"}):
            with self.ledger(**row):
                self.assertEqual(assure.independent_evidence(self.proj, c, []), [], row)

    def test_the_gate_still_sends_back_a_data_unit_whose_only_evidence_is_the_author(self):
        os.environ["SISI_RETRO_REQUIRED"] = "1"
        self.addCleanup(lambda: os.environ.__setitem__("SISI_RETRO_REQUIRED", "0"))
        self.data_unit("my own review")
        self.put("db/schema.sql", "create table t (id integer);\n")
        self.put("db/schema.sql", "create table t (id integer);\n")
        a, msg = gate.decide({"session_id": "me", "cwd": self.proj, "hook_event_name": "Stop"})
        self.assertEqual(a, "block")
        self.assertIn("independent evidence", msg)


class RecordTests(GuardCase):
    """Item 6: every refusal is kept in the unit record, and `sisi status` counts them (R-10.2-1)."""

    def test_the_closed_units_record_holds_each_refusal_with_what_and_when(self):
        c = self.open_unit(good_contract(checks=[dict(real("c1"), cmd="true")]))  # invalid: building is refused
        self.edit()
        self.edit()
        self.assertIn("2 building step", self.sisi("status").stdout)
        c = C.load(self.contract_path)
        c["checks"] = [real("c1")]
        C.save(self.contract_path, c)
        self.assertEqual(self.sisi("verify", env={"SISI_SESSION_ID": "me"}).returncode, 0)
        r = self.sisi("unit", "close", env={"SISI_SESSION_ID": "me"})
        self.assertEqual(r.returncode, 0, r.stdout)
        with open(os.path.join(self.proj, ".sisi", "units", "work.json")) as f:
            rec = json.load(f)
        self.assertEqual(len(rec["guard_refusals"]), 2)
        self.assertEqual(rec["guard_refusals"][0]["state"], "invalid")
        self.assertIn("src/app.py", rec["guard_refusals"][0]["what"])
        self.assertTrue(rec["guard_refusals"][0]["ts"])
        self.assertIn("the guard refused 2 building step", self.sisi("status").stdout)

    def test_the_rule_listing_shows_rules_two_and_three_as_enforced_with_these_mechanisms(self):
        for n in ("2", "3"):
            out = self.sisi("rule", n).stdout
            self.assertIn("enforced:", out)
            self.assertIn("before-tool hook", out) if n == "2" else self.assertIn("sisi unit continue", out)
        three = self.sisi("rule", "3").stdout
        for part in ("`sisi unit pause` is refused", "never judges a session's changes", "every refusal is kept"):
            self.assertIn(part, three)
        self.assertIn("review counts only from a worker other than the author", self.sisi("rule", "4").stdout)


if __name__ == "__main__":
    unittest.main()
