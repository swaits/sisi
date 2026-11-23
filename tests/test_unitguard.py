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


if __name__ == "__main__":
    unittest.main()
