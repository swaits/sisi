"""The direct-work meter, the delegation guard and the repeat-failure stop (rule 6, SPEC section 7; R-7.1-1,
R-7.2-2, R-6.3-1, R-6.3-3, R-15-4). Every test is written from the side of an agent trying to keep working
directly; hook input is what Claude Code sends, the output is what the host reads."""
import json, os, subprocess, time, unittest
from unittest import mock
from support import *

from sisi import orchestration, store, workers


def seed_workers(case, names=("alpha-small", "beta-large")):
    """A ledger with two usable workers (host-native, judged), the first the cheaper."""
    for i, w in enumerate(names):
        for t in ("research", "implementation"):
            workers.append_record({"kind": "attempt", "id": "%s%s" % (w[:3], t[:2]), "run_id": None, "ts": 1,
                                   "project": "p", "type": t, "difficulty": 1, "worker": w,
                                   "outcome": "accepted", "check": "read"})
    with open(os.path.join(case.data, "worker-prices.json"), "w") as f:
        json.dump({"models": {names[0]: {"cost_per_million_tokens": 1}, names[1]: {"cost_per_million_tokens": 9}}}, f)
    # a fresh discovery cache (no command-line tool installed): no test ever runs a real tool's model listing
    with open(os.path.join(case.data, "workers.json"), "w") as f:
        json.dump({"checked": time.time(), "tools": [{"name": "opencode", "installed": False, "models": [], "usable": False}]}, f)


class MeterBase(SisiCase):
    def setUp(self):
        super().setUp()
        self.git_init()
        os.makedirs(self.data, exist_ok=True)
        seed_workers(self)
        self.sid = "sess-1"
        self.own = "gamma-top"
        self.tick()

    def payload(self, ev, tool, inp=None, **kw):
        d = {"session_id": self.sid, "cwd": self.proj, "hook_event_name": ev, "tool_name": tool,
             "tool_input": inp or {}}
        d.update(kw)
        return json.dumps(d)

    def tick(self, sid=None, **kw):
        d = {"session_id": sid or self.sid, "cwd": self.proj, "hook_event_name": "SessionStart",
             "source": "startup", "model": self.own}
        d.update(kw)
        self.sisi("tick", "--tool", "claude-code", stdin=json.dumps(d))

    def prompt(self, text="fix the parser and explain each module in the project", sid=None, route=True):
        """A prompt reaches the session; by default the agent has also asked `sisi route` (a delegation needs that)."""
        r = self.sisi("prompt", "--tool", "claude-code", stdin=json.dumps(
            {"session_id": sid or self.sid, "cwd": self.proj, "hook_event_name": "UserPromptSubmit", "prompt": text}))
        if route and not text.startswith("<task-notification>") and not text.startswith("[failed]") \
                and not text.startswith("You are a worker"):
            self.route(sid=sid)
        return r

    def route(self, kind="research", difficulty="1", *extra, sid=None):
        return self.sisi("route", "--kind", kind, "--difficulty", difficulty, *extra,
                         env={"SISI_SESSION_ID": sid or self.sid})

    def pre(self, tool="Read", inp=None, **kw):
        """The decoded hook output of one before-tool call: (denied, reason, whole output)."""
        r = self.sisi("watch", "--before", "--tool", "claude-code",
                      stdin=self.payload("PreToolUse", tool, inp or {"file_path": "/x"}, **kw))
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout) if r.stdout.strip() else {}
        hs = out.get("hookSpecificOutput") or {}
        return hs.get("permissionDecision") == "deny", hs.get("permissionDecisionReason") or hs.get("additionalContext"), out

    def post(self, tool="Read", inp=None, response="x", event="PostToolUse", **kw):
        return self.sisi("watch", "--after", "--tool", "claude-code",
                         stdin=self.payload(event, tool, inp or {"file_path": "/x"}, tool_response=response, **kw))

    def events(self, ev=None):
        rows = store.read(orchestration.EVENTS)
        return [r for r in rows if ev is None or r["ev"] == ev]

    def read_n(self, n, tool="Read"):
        return [self.pre(tool)[0] for _ in range(n)]


class BudgetTests(MeterBase):
    def test_fifty_reads_in_one_turn(self):
        """R-7.2-2: the seventh counted call is refused, and so is every one after it, with a message of at most
        12 lines that gives the count, rule 6, the router's workers and both ways on."""
        self.prompt()
        denied = self.read_n(50)
        self.assertEqual(denied[:6], [False] * 6)
        self.assertEqual(denied[6:], [True] * 44)
        _d, reason, _o = self.pre()
        self.assertLessEqual(len(reason.splitlines()), 12)
        self.assertIn("6 direct tool calls", reason)
        self.assertIn("rule 6", reason)
        self.assertIn("alpha-small", reason)                      # the router's pick, by calling the routing code
        self.assertIn("host's own subagent tool", reason)          # its mechanism line
        self.assertIn("sisi delegate brief", reason)
        self.assertIn('sisi unit direct "<reason>"', reason)
        self.assertEqual(len(self.events("refusal")), 45)

    def test_one_shell_command_printing_twenty_files_trips_the_character_budget(self):
        """A single call whose result is huge uses the character budget: the very next counted call is refused."""
        self.prompt()
        self.assertFalse(self.pre("Bash", {"command": "cat src/*"})[0])
        self.post("Bash", {"command": "cat src/*"}, response={"stdout": "x" * 31000, "stderr": ""})
        denied, reason, _ = self.pre("Read")
        self.assertTrue(denied)
        self.assertIn("1 direct tool calls", reason.replace("1 direct tool call ", "1 direct tool calls "))
        self.assertIn("31000 characters", reason)

    def test_a_tool_sisi_has_never_heard_of_counts(self):
        """Legwork through a tool named nowhere in the data still counts."""
        self.prompt()
        denied = [self.pre("mcp__some__brandnew_tool", {"q": "x"})[0] for _ in range(8)]
        self.assertEqual(denied, [False] * 6 + [True] * 2)

    def test_exempt_tools_and_sisi_commands_are_never_counted_or_refused(self):
        self.prompt()
        self.read_n(6)
        for tool in ("AskUserQuestion", "TodoWrite", "EnterPlanMode", "SendMessage"):
            self.assertFalse(self.pre(tool, {})[0], tool)
        for cmd in ("sisi route --kind research --difficulty 1", 'sisi unit direct "a; b"', "FOO=1 sisi delegate brief",
                    "python3 /opt/x/bin/sisi status", "sisi status && sisi risk"):
            self.assertFalse(self.pre("Bash", {"command": cmd})[0], cmd)
        self.assertTrue(self.pre("Read")[0])

    def test_a_command_that_only_starts_with_sisi_still_counts(self):
        """`sisi x && cat everything` is legwork with a sisi command in front."""
        self.prompt()
        self.read_n(6)
        self.assertTrue(self.pre("Bash", {"command": "sisi status && cat src/*"})[0])
        self.assertTrue(self.pre("Bash", {"command": "echo sisi"})[0])

    def test_the_turn_resets_at_each_prompt(self):
        self.prompt()
        self.read_n(7)
        self.assertTrue(self.pre()[0])
        self.prompt("now fix the second bug in the parser as well please")
        self.assertFalse(self.pre()[0])

    def test_limits_come_from_config(self):
        os.makedirs(self.data, exist_ok=True)
        with open(os.path.join(self.data, "config.json"), "w") as f:
            json.dump({"orchestrate": {"direct_calls": 2}}, f)
        self.prompt()
        self.assertEqual(self.read_n(4), [False, False, True, True])

    def test_a_hook_that_raises_lets_the_call_through(self):
        """Fail open: a crash inside the meter never blocks the user's tool."""
        self.prompt()
        self.read_n(6)
        with mock.patch.object(orchestration, "before", side_effect=RuntimeError("boom")):
            denied, _r, out = self.pre()
        self.assertFalse(denied)
        self.assertEqual(out, {})
        with mock.patch.object(orchestration.Meter, "__enter__", side_effect=OSError("disk")):
            self.assertFalse(self.pre()[0])


class ExtensionTests(MeterBase):
    def test_a_generic_reason_is_refused_a_specific_one_grants_the_extension(self):
        """R-6.3-3: 'because it is easier' is not a reason; a specific one extends the turn by ten calls and is stored."""
        self.prompt()
        self.read_n(7)
        for generic in ("because it is easier", "faster", "it is simpler and quicker to just do it myself"):
            r = self.sisi("unit", "direct", generic)
            self.assertEqual(r.returncode, 1, generic)
            self.assertIn("generic", r.stdout)
        self.assertTrue(self.pre()[0])
        r = self.sisi("unit", "direct", "the fix is one line in parser.py and a brief would be longer than the change")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.read_n(10), [False] * 10)
        self.assertTrue(self.pre()[0])
        ext = self.events("extension")
        self.assertEqual(len(ext), 1)
        self.assertIn("parser.py", ext[0]["reason"])

    def test_many_extensions_are_each_recorded_and_visible_in_status(self):
        """Splitting legwork across the allowed calls and many extensions: nothing hides, every extension and its
        reason is stored and `sisi status` shows it for the open unit."""
        self.write_contract(contract([check("c", "true")]))
        self.prompt()
        for i in range(4):
            self.read_n(7 if i == 0 else 11)
            r = self.sisi("unit", "direct", "step %d of the parser migration reads src/part%d.py once" % (i, i))
            self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(len(self.events("extension")), 4)
        out = self.sisi("status").stdout
        self.assertIn("4 extension(s)", out)
        self.assertIn("src/part3.py", out)
        self.assertIn("orchestration (measured)", out)

    def test_the_same_reason_twice_in_a_turn_is_refused(self):
        self.prompt()
        self.read_n(7)
        why = "the fix is one line in parser.py and a brief would be longer"
        self.assertEqual(self.sisi("unit", "direct", why).returncode, 0)
        self.assertEqual(self.sisi("unit", "direct", why).returncode, 1)

    def test_the_character_budget_grows_with_an_extension(self):
        self.prompt()
        self.pre("Bash", {"command": "cat a"})
        self.post("Bash", {"command": "cat a"}, response="y" * 31000)
        self.assertTrue(self.pre()[0])
        self.sisi("unit", "direct", "the two config files hold 40 lines each, a brief costs more")
        self.assertFalse(self.pre()[0])


class WhoIsMeteredTests(MeterBase):
    def test_a_host_marked_subagent_call_is_never_counted_or_refused(self):
        self.prompt()
        self.read_n(7)
        denied, _r, _o = self.pre("Read", agent_id="sub-1")
        self.assertFalse(denied)
        self.assertEqual(self.events("call")[-1]["ev"], "call")
        self.assertEqual(len(self.events("call")), 6)  # the subagent's call is not in the count

    def test_a_session_started_by_sisi_delegate_is_never_refused(self):
        self.prompt()
        with mock.patch.dict(os.environ, {"SISI_WORKER_RUN": "1"}):
            self.assertEqual(self.read_n(20), [False] * 20)

    def test_a_session_the_host_started_as_a_subagent_is_never_refused(self):
        self.tick("sub-sess", agent_id="a1")
        self.sid = "sub-sess"
        self.prompt()
        self.assertEqual(self.read_n(20), [False] * 20)

    def test_a_first_prompt_that_opens_with_the_brief_line_makes_a_worker(self):
        """Compared case-insensitively on the first 200 characters."""
        from sisi import brief
        line = brief.template().splitlines()[0]
        self.prompt(line.upper() + "\n\n## Outcome and scope\nfind the bug")
        self.assertEqual(self.read_n(20), [False] * 20)

    def test_a_main_prompt_that_only_mentions_worker_later_is_still_metered(self):
        from sisi import brief
        line = brief.template().splitlines()[0]
        self.prompt("fix the parser, and remember this: " + line + " you are a worker of mine")
        self.assertEqual(self.read_n(8), [False] * 6 + [True] * 2)
        # nor does a brief line in the second prompt change a session that began as a main thread
        self.prompt(line + " again please do this")
        self.assertEqual(self.read_n(8), [False] * 6 + [True] * 2)

    def test_no_refusal_when_no_other_worker_is_usable(self):
        """Counts and records, never refuses: the ledger knows only the session's own model."""
        os.unlink(workers.ledger_path())
        workers.append_record({"kind": "attempt", "id": "x", "run_id": None, "ts": 1, "project": "p", "type": "research",
                               "difficulty": 1, "worker": self.own, "outcome": "accepted", "check": "read"})
        self.prompt()
        self.assertEqual(self.read_n(10), [False] * 10)
        self.assertEqual(len(self.events("call")), 10)
        self.assertTrue(self.events("unrefused"))
        self.assertEqual(self.events("refusal"), [])


class DelegationGuardTests(MeterBase):
    def deleg(self, **kw):
        inp = {"description": "read the code", "prompt": "Outcome: list what each file does.", "subagent_type": "general-purpose"}
        inp.update(kw)
        return self.pre("Agent", inp)

    def test_a_delegation_naming_no_model_is_refused_with_the_recommendation(self):
        self.prompt()
        denied, reason, _ = self.deleg()
        self.assertTrue(denied)
        self.assertIn("names no model", reason)
        self.assertIn("alpha-small", reason)
        self.assertIn('sisi unit direct "<reason>"', reason)
        self.assertLessEqual(len(reason.splitlines()), 12)

    def test_the_same_expensive_model_named_explicitly_is_refused(self):
        self.prompt()
        denied, reason, _ = self.deleg(model="gamma")  # an alias of the session's own model
        self.assertTrue(denied)
        self.assertIn("own model", reason)
        denied, _r, _o = self.deleg(model="gamma-top")
        self.assertTrue(denied)

    def test_a_recorded_reason_allows_the_same_model_delegation(self):
        self.prompt()
        self.assertTrue(self.deleg()[0])
        self.sisi("unit", "direct", "the review must see exactly what this session saw, 3 files")
        self.assertFalse(self.deleg()[0])

    def test_a_delegation_to_another_model_is_allowed_recorded_and_its_brief_advised(self):
        self.prompt()
        denied, ctx, _ = self.deleg(model="alpha-small", prompt="read the files and tell me what they do")
        self.assertFalse(denied)
        self.assertIn("recorded as run", ctx)
        self.assertIn("no outcome and scope", ctx)               # missing parts are advice, never a refusal
        runs = [r for r in workers.read_records() if r.get("kind") == "run"]
        self.assertEqual(len(runs), 1)
        self.assertEqual((runs[0]["worker"], runs[0]["status"], runs[0]["session"]), ("alpha-small", "pending", self.sid))

    def test_delegations_are_not_counted_as_direct_calls(self):
        self.prompt()
        for _ in range(10):
            self.assertFalse(self.deleg(model="alpha-small")[0])
        self.assertFalse(self.pre()[0])


class DelegationRecordTests(MeterBase):
    """Item 4: a host delegation writes itself to the ledger; the gate asks for the judgement once."""

    def deleg_pre(self, tool_use_id="tu1", model="alpha-small"):
        return self.pre("Agent", {"description": "d", "prompt": "Outcome: x\nAcceptance: y\nFiles you may change: none",
                                  "model": model}, tool_use_id=tool_use_id)

    def deleg_post(self, response, tool_use_id="tu1", event="PostToolUse"):
        return self.post("Agent", {"description": "d", "prompt": "p", "model": "alpha-small"}, response=response,
                         event=event, tool_use_id=tool_use_id)

    def stop(self):
        r = self.sisi("gate", "--tool", "claude-code", stdin=json.dumps(
            {"session_id": self.sid, "cwd": self.proj, "hook_event_name": "Stop", "stop_hook_active": False}))
        return json.loads(r.stdout) if r.stdout.strip() else {}

    def runs(self):
        return workers.merged_runs()

    def test_a_synchronous_delegation_is_written_pending_then_completed_with_tokens(self):
        self.prompt()
        _d, ctx, _ = self.deleg_pre()
        run = self.runs()[0]
        self.assertIn(run["id"], ctx)                               # the id is printed
        self.assertEqual((run["status"], run["worker"], run["session"]), ("pending", "alpha-small", self.sid))
        self.assertEqual(workers.unjudged_runs(), [])               # in flight: nothing to judge yet
        self.deleg_post({"status": "completed", "totalTokens": 4321, "totalDurationMs": 90000})
        run = self.runs()[0]
        self.assertEqual((run["status"], run["tokens"], run["tokens_class"], run["minutes"]), ("waiting", 4321, "measured", 1.5))
        self.assertEqual([r["id"] for r in workers.unjudged_runs()], [run["id"]])
        r = self.sisi("delegate", "judge", run["id"], "--outcome", "accepted", "--check", "read",
                      "--type", "research", "--difficulty", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(workers.unjudged_runs(), [])
        att = [x for x in workers.read_records() if x.get("kind") == "attempt" and x.get("run_id") == run["id"]][0]
        self.assertEqual((att["type"], att["difficulty"], att["tokens"], att["minutes"]), ("research", 1, 4321, 1.5))

    def test_an_async_launch_stays_pending_until_the_hosts_notice_arrives(self):
        """The host answers an async launch at once; the run is finished only when its notice comes as a prompt."""
        self.prompt()
        self.deleg_pre(tool_use_id="toolu_A")
        self.read_n(3)
        self.deleg_post({"isAsync": True, "status": "async_launched", "agentId": "agent9", "resolvedModel": "alpha-small-2"},
                        tool_use_id="toolu_A")
        self.assertEqual(self.runs()[0]["status"], "pending")      # still running: nothing to judge or ask for
        self.assertEqual(workers.unjudged_runs(), [])
        note = ("<task-notification>\n<task-id>agent9</task-id>\n<tool-use-id>toolu_A</tool-use-id>\n"
                "<status>completed</status>\n<result>done</result>\n<usage><subagent_tokens>7302</subagent_tokens>"
                "<tool_uses>1</tool_uses><duration_ms>1612</duration_ms></usage>\n</task-notification>")
        self.prompt(note)
        run = self.runs()[0]
        self.assertEqual((run["status"], run["tokens"], run["tokens_class"]), ("waiting", 7302, "measured"))
        # a notice is the host reporting, not a new request: it gives no new budget
        self.assertEqual(self.read_n(5), [False] * 3 + [True] * 2)

    def test_the_gate_asks_for_the_judgements_once_per_set_of_runs(self):
        self.prompt()
        self.deleg_pre("t1")
        self.deleg_post({"status": "completed"}, "t1")
        out = self.stop()
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("not judged yet", out["reason"])
        rid = self.runs()[0]["id"]
        self.assertIn(rid, out["reason"])
        self.assertIn("sisi delegate judge", out["reason"])
        self.assertEqual(self.stop(), {})                            # the same set is not asked again
        self.deleg_pre("t2")
        self.deleg_post({"status": "completed"}, "t2")
        out = self.stop()                                            # a new set is
        self.assertEqual(out.get("decision"), "block")
        for r in self.runs():
            self.sisi("delegate", "judge", r["id"], "--outcome", "accepted", "--check", "read", "--type", "research", "--difficulty", "1")
        self.assertEqual(self.stop(), {})

    def test_another_sessions_runs_are_not_asked_for(self):
        workers.append_record({"kind": "run", "id": "other1", "ts": 1, "worker": "alpha-small", "session": "someone-else",
                               "status": "waiting"})
        self.assertEqual(self.stop(), {})


class RepeatFailureTests(MeterBase):
    """Item 5 (R-15-4): the fourth identical failing command with no file changed is refused once."""

    def fail(self, cmd="make build"):
        denied, reason, _ = self.pre("Bash", {"command": cmd})
        if not denied:
            self.post("Bash", {"command": cmd}, response=None, event="PostToolUseFailure", error="Exit code 2")
        return denied, reason

    def test_the_fourth_identical_attempt_is_refused_once(self):
        self.prompt()
        self.assertEqual([self.fail()[0] for _ in range(3)], [False] * 3)
        denied, reason = self.fail("make   build")                    # whitespace-normalised
        self.assertTrue(denied)
        self.assertIn("will not produce new information", reason)
        self.assertIn("failed 3 times", reason)
        self.assertLessEqual(len(reason.splitlines()), 12)
        self.assertFalse(self.fail()[0])                              # once: the next is let through
        self.assertEqual([e["why"] for e in self.events("refusal")], ["repeat"])

    def test_a_changed_file_between_failures_resets_the_count(self):
        self.prompt()
        self.fail(); self.fail()
        open(os.path.join(self.proj, "fix.txt"), "w").write("a fix")
        self.fail()                                                    # first failure of the new state
        self.assertFalse(self.fail()[0])
        self.assertFalse(self.fail()[0])
        self.assertTrue(self.fail()[0])

    def test_a_success_in_between_resets_it(self):
        self.prompt()
        self.fail(); self.fail()
        self.post("Bash", {"command": "make build"}, response={"stdout": "ok", "exit_code": 0})
        self.fail(); self.fail()
        self.assertFalse(self.fail()[0])

    def test_another_command_is_not_affected(self):
        self.prompt()
        for _ in range(3):
            self.fail()
        self.assertFalse(self.fail("make test")[0])

    def test_a_new_turn_starts_the_count_again(self):
        self.prompt()
        for _ in range(3):
            self.fail()
        self.prompt("the build is still broken, please look at it again now")
        self.assertFalse(self.fail()[0])

    def test_workers_are_not_stopped(self):
        self.prompt()
        for _ in range(3):
            self.fail()
        self.assertFalse(self.pre("Bash", {"command": "make build"}, agent_id="a1")[0])


class RecordTests(MeterBase):
    """Item 6: the unit record and `sisi status` show orchestration, each value classed measured."""

    def start_unit(self):
        from sisi import contract as C
        self.assertEqual(self.sisi("contract", "init", "--goal", "make the thing").returncode, 0)
        p = os.path.join(self.proj, ".sisi", "contract.json")
        c = C.load(p)
        c["checks"] = [check("works", "test -f done.txt")]
        C.save(p, c)

    def finish_and_close(self):
        open(os.path.join(self.proj, "done.txt"), "w").write("x")
        self.assertEqual(self.sisi("verify").returncode, 0)
        r = self.sisi("unit", "close")
        self.assertEqual(r.returncode, 0, r.stdout)
        return json.load(open(os.path.join(self.proj, ".sisi", "units", "proj.json")))

    def test_the_closed_unit_carries_the_orchestration_part(self):
        self.start_unit()
        self.prompt()
        self.read_n(8)                                                 # 6 counted, 2 refused
        self.sisi("unit", "direct", "the two config files hold 40 lines each, a brief costs more")
        self.read_n(2)
        self.pre("Agent", {"description": "d", "prompt": "p", "model": "alpha-small"}, tool_use_id="x1")
        rec = self.finish_and_close()
        o = rec["orchestration"]
        self.assertEqual(o["direct_calls"], {"value": 8, "class": "measured"})
        self.assertEqual(o["refusals"], {"value": 2, "class": "measured"})
        self.assertEqual(o["extensions"], {"value": 1, "class": "measured"})
        self.assertIn("40 lines", o["extension_reasons"]["value"][0])
        self.assertEqual(o["delegations_started"]["value"], 1)
        self.assertEqual((o["delegations_judged"]["value"], o["delegations_unjudged"]["value"]), (0, 1))
        self.assertEqual(o["delegated_share"], {"value": 0.111, "class": "measured"})    # 1 of 9 tool calls
        self.assertEqual(rec["scorecard"]["parallelism"]["orch_direct_calls"]["class"], "measured")
        out = self.sisi("status").stdout
        self.assertIn("orch_direct_calls 8 (measured)", out)
        self.assertIn("orch_extension_reasons", out)

    def test_status_shows_it_for_the_unit_in_progress(self):
        self.start_unit()
        self.prompt()
        self.read_n(7)
        out = self.sisi("status").stdout
        self.assertIn("orchestration (measured): 6 direct calls", out)
        self.assertIn("1 refusals", out)

    def test_a_unit_with_nothing_metered_says_unavailable_not_zero(self):
        self.start_unit()
        rec = self.finish_and_close()
        self.assertEqual(rec["orchestration"]["direct_calls"]["class"], "unavailable")

    def test_rule_six_is_listed_as_enforced_and_names_the_mechanisms(self):
        out = self.sisi("rule").stdout
        line = next(l for l in out.splitlines() if "orchestrate" in l)
        self.assertIn("enforced", line)
        self.assertNotIn("not enforced", line)
        detail = self.sisi("rule", "orchestrate").stdout
        for phrase in ("direct tool calls", "sisi unit direct", "names no model", "judg", "unavailable worker",
                       "question-dialog call"):
            self.assertIn(phrase, detail)


FUTURE = "2036-11-30T05:00:00Z"


def future_ts():
    return workers._parse_time(FUTURE)


class FallbackTests(MeterBase):
    """Item 9 (R-7.2-1, R-7.2-2, R-15-1, R-15-5, R-17-3): a worker's unavailability is recorded and the fallback handed
    over where it arrives; the person is not asked."""

    QUOTA = ("[failed]: API error 429 [request_id=req_011]: Subscription quota exhausted. "
             "Your usage window resets at " + FUTURE)

    def setUp(self):
        super().setUp()
        # one prefixed provider (a command-line tool's model) besides the two host-native workers
        with open(os.path.join(self.data, "workers.json"), "w") as f:
            json.dump({"checked": time.time(), "tools": [{"name": "opencode", "installed": True, "usable": True,
                                                          "models": ["provx/model-1"]}]}, f)
        with open(os.path.join(self.data, "worker-prices.json"), "w") as f:
            json.dump({"models": {"provx/model-1": {"cost_per_million_tokens": 0.1},
                                  "alpha-small": {"cost_per_million_tokens": 1},
                                  "beta-large": {"cost_per_million_tokens": 9}}}, f)
        for t in ("research", "implementation"):
            workers.append_record({"kind": "attempt", "id": "px" + t[:2], "run_id": None, "ts": 1, "project": "p", "type": t,
                                   "difficulty": 1, "worker": "provx/model-1", "outcome": "accepted", "check": "read"})

    def context(self, r):
        out = json.loads(r.stdout) if r.stdout.strip() else {}
        return (out.get("hookSpecificOutput") or {}).get("additionalContext") or ""

    def notice(self, text=None, use_id="toolu_Q", task="agentQ", status="failed"):
        body = text or self.QUOTA
        return ("<task-notification>\n<task-id>%s</task-id>\n<tool-use-id>%s</tool-use-id>\n<status>%s</status>\n"
                "<summary>Agent \"read the code\" failed</summary>\n<result>%s</result>\n</task-notification>"
                % (task, use_id, status, body))

    def launch(self, model="provx/model-1", use_id="toolu_Q"):
        self.pre("Agent", {"description": "read the code", "prompt": "Outcome: x", "model": model}, tool_use_id=use_id)
        self.post("Agent", {"description": "d", "prompt": "p", "model": model},
                  response={"isAsync": True, "status": "async_launched", "agentId": "agentQ"}, tool_use_id=use_id)

    def down(self):
        return workers.read_availability()

    def test_the_quota_notice_through_the_prompt_hook_marks_the_provider_down_and_hands_over_the_fallback(self):
        self.prompt()
        self.launch()
        ctx = self.context(self.prompt(self.notice()))
        entry = self.down()["provx"]                                  # the provider, not one model
        self.assertEqual((entry["retry_at"], entry["reason"]), (future_ts(), "limit"))
        self.assertIn("quota exhausted", entry["note"].lower())
        lines = ctx.splitlines()
        self.assertLessEqual(len(lines), 6)
        self.assertIn("provx/model-1 is unavailable", ctx)
        self.assertIn("2036-11-30 05:00 UTC", ctx)
        self.assertIn("alpha-small", ctx)                              # every prefixed provider is down: host-native
        self.assertIn("host's own subagent tool", ctx)
        self.assertIn("Do not ask the person, and do not report this to them", ctx)
        self.assertNotIn("tell them", ctx.lower())                    # worker availability is internal (SPEC 9.7, 17)
        self.assertIn("Cancel or interrupt", ctx)

    def test_the_same_through_a_delegation_tool_result(self):
        self.prompt()
        self.pre("Agent", {"description": "d", "prompt": "Outcome: x", "model": "provx/model-1"}, tool_use_id="t9")
        r = self.post("Agent", {"description": "d", "prompt": "p", "model": "provx/model-1"}, response=self.QUOTA, tool_use_id="t9")
        ctx = self.context(r)
        self.assertEqual(self.down()["provx"]["retry_at"], future_ts())
        self.assertIn("alpha-small", ctx)
        self.assertLessEqual(len(ctx.splitlines()), 6)
        run = workers.merged_runs()[0]
        self.assertEqual(run["status"], "superseded")                   # never asked to be judged
        self.assertEqual(workers.unjudged_runs(), [])

    def test_a_failing_sisi_delegate_run_hands_over_the_fallback_under_the_event_name_the_host_expects(self):
        """Found by the live check: the host rejects hook output whose event name is not the event it answers."""
        self.prompt()
        out = ("fakeprov/model-1 is unavailable (limit: API error 429: Subscription quota exhausted. Your usage window resets at "
               + FUTURE + "); trying the next choice\nsisi: no usable worker remains for kind research at difficulty 1")
        r = self.sisi("watch", "--after", "--tool", "claude-code", stdin=self.payload(
            "PostToolUseFailure", "Bash", {"command": "sisi delegate --kind research --difficulty 1 --brief b.md"},
            error="Exit code 1\n" + out))
        hs = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(hs["hookEventName"], "PostToolUseFailure")
        self.assertIn("Next for the same kind of work (research, difficulty 1)", hs["additionalContext"])
        self.assertIn("Do not ask the person", hs["additionalContext"])
        self.assertEqual(self.down(), {})          # `sisi delegate` recorded it itself; the hook does not do it twice
        # the same inside a longer command line (writing the brief and running it in one call)
        r = self.sisi("watch", "--after", "--tool", "claude-code", stdin=self.payload(
            "PostToolUseFailure", "Bash", {"command": "cat > b.md <<'EOF'\nx\nEOF\nsisi delegate --kind research --difficulty 1 --brief b.md"},
            error="Exit code 1\n" + out))
        self.assertIn("Fall back now", json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"])

    def test_sisi_delegate_itself_tells_the_agent_to_fall_back_when_only_host_workers_remain(self):
        """Found by the live check: a small model stopped at "no usable worker remains"; the command's own output now
        carries the instruction, and the reset time in the message is what is recorded."""
        fake = os.path.join(self.tmp, "fakebin")
        os.makedirs(fake)
        with open(os.path.join(fake, "opencode"), "w") as f:
            f.write("#!/bin/sh\necho 'API error 429: Subscription quota exhausted. Your usage window resets at %s' >&2\nexit 1\n" % FUTURE)
        os.chmod(os.path.join(fake, "opencode"), 0o755)
        brief = os.path.join(self.proj, "brief.md")
        with open(brief, "w") as f:
            f.write("## Outcome and scope\nlist files\n## Acceptance\none per line\n## Files you may change\nnone\n")
        r = self.sisi("delegate", "--kind", "research", "--difficulty", "1", "--brief", brief,
                      env={"PATH": fake + os.pathsep + os.environ["PATH"]})
        text = r.stdout + r.stderr
        self.assertIn("Fall back now with the same brief", text)
        self.assertIn("Do not ask the person and do not report this to them", text)
        self.assertIn("host's own subagent tool", text)
        self.assertEqual(self.down()["provx"]["retry_at"], future_ts())

    def transcript(self, final):
        path = os.path.join(self.tmp, "t.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "list the files"}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": final}]}}) + "\n")
        return path

    def stop_with(self, final):
        r = self.sisi("gate", "--tool", "claude-code", stdin=json.dumps(
            {"session_id": self.sid, "cwd": self.proj, "hook_event_name": "Stop", "transcript_path": self.transcript(final)}))
        return json.loads(r.stdout) if r.stdout.strip() else {}

    def test_a_final_message_that_names_the_unavailable_worker_is_sent_back_once(self):
        """The person is not told which worker is out (SPEC 9.7, 17): judged on the recorded names, once."""
        self.prompt()
        self.launch()
        self.prompt(self.notice())
        self.pre("Agent", {"description": "d", "prompt": "Outcome: x", "model": "alpha-small"}, tool_use_id="fb1")   # fell back
        out = self.stop_with("Done. The provx provider hit its quota so I did it myself.")
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("internal", out["reason"])
        self.assertIn("provx", out["reason"])
        self.assertEqual(self.stop_with("Done. The provx provider was out."), {})            # once: never a trap

    def test_the_failure_words_are_covered_too(self):
        """The provider's name need not appear: "quota" or "fallback" after an unavailability is the same leak."""
        self.prompt()
        self.launch()
        self.prompt(self.notice())
        self.pre("Agent", {"description": "d", "prompt": "Outcome: x", "model": "alpha-small"}, tool_use_id="fb5")
        out = self.stop_with("Here are the files, from a subagent after the first worker hit its quota.")
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("quota", out["reason"])

    def test_the_hosts_own_copy_of_the_final_message_is_used_when_it_is_sent(self):
        """Found by the live check: the transcript may not hold the final message yet when the stop hook runs."""
        self.prompt()
        self.launch()
        self.prompt(self.notice())
        self.pre("Agent", {"description": "d", "prompt": "Outcome: x", "model": "alpha-small"}, tool_use_id="fb3")
        r = self.sisi("gate", "--tool", "claude-code", stdin=json.dumps(
            {"session_id": self.sid, "cwd": self.proj, "hook_event_name": "Stop",
             "last_assistant_message": "The provx provider hit its quota, so I did it myself."}))
        self.assertEqual(json.loads(r.stdout).get("decision"), "block")

    def test_ending_the_turn_with_no_fallback_started_is_sent_back_twice_at_most(self):
        """Found by the live check: a small model read the instruction and still stopped. State-based, once."""
        self.prompt()
        self.launch()
        self.prompt(self.notice())
        out = self.stop_with("Here are the 14 files.")
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("has not been given to another worker", out["reason"])
        self.assertIn("alpha-small", out["reason"])
        self.assertLessEqual(len(out["reason"].splitlines()), 6)
        self.assertEqual(self.stop_with("Here are the 14 files.").get("decision"), "block")   # a model may ignore it once
        self.assertEqual(self.stop_with("Here are the 14 files."), {})        # bounded: never a trap

    def test_no_send_back_when_the_fallback_was_started(self):
        self.prompt()
        self.launch()
        self.prompt(self.notice())
        self.pre("Agent", {"description": "d", "prompt": "Outcome: x", "model": "alpha-small"}, tool_use_id="fb2")
        self.assertEqual(self.stop_with("Here are the 14 files."), {})

    def test_no_send_back_when_nothing_usable_is_left(self):
        os.unlink(workers.ledger_path())
        os.unlink(os.path.join(self.data, "workers.json"))
        workers.append_record({"kind": "attempt", "id": "only", "run_id": None, "ts": 1, "project": "p", "type": "research",
                               "difficulty": 1, "worker": "alpha-small", "outcome": "accepted", "check": "read"})
        self.prompt()
        self.prompt(self.notice("[failed]: alpha-small: API error 429: Subscription quota exhausted. Your usage window resets at " + FUTURE))
        self.assertEqual(self.stop_with("Done myself."), {})

    def test_a_final_message_that_does_not_name_it_is_left_alone(self):
        self.prompt()
        self.launch()
        self.prompt(self.notice())
        self.pre("Agent", {"description": "d", "prompt": "Outcome: x", "model": "alpha-small"}, tool_use_id="fb4")
        self.assertEqual(self.stop_with("Here are the 14 files, one per line."), {})

    def test_no_unavailability_no_report_check(self):
        self.prompt()
        self.assertEqual(self.stop_with("provx was great"), {})

    def test_a_tool_failure_event_for_the_delegation_counts_too(self):
        self.prompt()
        self.pre("Agent", {"description": "d", "prompt": "Outcome: x", "model": "provx/model-1"}, tool_use_id="t8")
        self.sisi("watch", "--after", "--tool", "claude-code", stdin=self.payload(
            "PostToolUseFailure", "Agent", {"description": "d", "model": "provx/model-1"}, error="API error 429: quota exhausted", tool_use_id="t8"))
        self.assertIn("provx", self.down())

    def test_a_rejected_or_failed_on_its_merits_result_marks_nothing_down(self):
        """Unavailability is never a quality judgement, and a failure of the work itself is not unavailability."""
        self.prompt()
        self.pre("Agent", {"description": "d", "prompt": "Outcome: x", "model": "provx/model-1"}, tool_use_id="m1")
        r = self.post("Agent", {"description": "d", "model": "provx/model-1"},
                      response="Failed: 3 tests still fail: assertion error in parser.py line 40", tool_use_id="m1")
        self.assertEqual(self.context(r).count("unavailable"), 0)
        self.pre("Agent", {"description": "d", "prompt": "Outcome: x", "model": "provx/model-1"}, tool_use_id="m2")
        report = "I added a rate limit handler and a usage limit warning to the client. " + "Details. " * 200
        r = self.post("Agent", {"description": "d", "model": "provx/model-1"}, response=report, tool_use_id="m2")
        self.assertEqual(self.context(r).count("unavailable"), 0)
        run = workers.merged_runs()[0]
        self.sisi("delegate", "judge", run["id"], "--outcome", "rejected", "--check", "tests", "--type", "research", "--difficulty", "1")
        self.assertEqual(self.down(), {})
        ctx = self.context(self.prompt(self.notice("Tests failed: the patch does not compile", status="failed")))
        self.assertEqual((self.down(), ctx.count("unavailable")), ({}, 0))

    def test_the_question_dialog_is_refused_once_after_an_unavailability(self):
        """State, not wording: any dialog call right after the unavailability is refused once; the second is allowed."""
        self.prompt()
        self.launch()
        self.prompt(self.notice())
        denied, reason, _ = self.pre("AskUserQuestion", {"questions": [{"question": "When should this run?"}]})
        self.assertTrue(denied)
        self.assertIn("alpha-small", reason)
        self.assertIn("do not ask the person", reason.lower())
        self.assertIn("do not report this to them", reason.lower())
        self.assertFalse(self.pre("AskUserQuestion", {"questions": [{"question": "something else"}]})[0])
        self.assertEqual([e["why"] for e in self.events("refusal")], ["question-after-unavailable"])

    def test_a_question_with_no_unavailability_is_never_refused(self):
        self.prompt()
        self.assertFalse(self.pre("AskUserQuestion", {"questions": []})[0])

    def test_starting_the_fallback_clears_the_state(self):
        self.prompt()
        self.launch()
        self.prompt(self.notice())
        self.pre("Agent", {"description": "d", "prompt": "Outcome: x", "model": "alpha-small"}, tool_use_id="fb")
        self.assertFalse(self.pre("AskUserQuestion", {"questions": []})[0])

    def test_nothing_usable_says_so_with_the_earliest_due_time_and_does_not_refuse_the_dialog(self):
        os.unlink(workers.ledger_path())
        os.unlink(os.path.join(self.data, "workers.json"))
        workers.append_record({"kind": "attempt", "id": "only", "run_id": None, "ts": 1, "project": "p", "type": "research",
                               "difficulty": 1, "worker": "alpha-small", "outcome": "accepted", "check": "read"})
        self.prompt()
        ctx = self.context(self.prompt(self.notice("[failed]: alpha-small: API error 429: Subscription quota exhausted. "
                                                   "Your usage window resets at " + FUTURE, use_id="zz")))
        self.assertIn("No other worker is usable now", ctx)
        self.assertIn("earliest due: alpha-small at 2036-11-30 05:00 UTC", ctx)
        self.assertIn("only if what they receive, or when, changes", ctx)      # the one case the person hears of it
        self.assertIn("not about the workers", ctx)
        self.assertLessEqual(len(ctx.splitlines()), 6)
        self.assertFalse(self.pre("AskUserQuestion", {"questions": []})[0])

    def test_a_worker_that_cannot_be_identified_records_nothing_but_still_hands_over_the_fallback(self):
        self.prompt()
        ctx = self.context(self.prompt("[failed]: API error 429: Subscription quota exhausted. Your usage window resets at " + FUTURE))
        self.assertEqual(self.down(), {})
        self.assertIn("a delegated worker is unavailable", ctx)
        self.assertIn("do not ask the person", ctx.lower())
        self.assertTrue(self.pre("AskUserQuestion", {"questions": []})[0])   # the agent was told to fall back

    def test_a_session_that_is_itself_a_worker_gets_none_of_this(self):
        from sisi import brief
        self.prompt(brief.template().splitlines()[0] + "\n\n## Outcome and scope\nfix it")
        ctx = self.context(self.prompt(self.notice()))
        self.assertEqual((ctx, self.down()), ("", {}))
        self.assertFalse(self.pre("AskUserQuestion", {"questions": []})[0])

    def test_a_date_only_reset_and_a_missing_one_are_both_handled(self):
        self.assertEqual(workers.parse_reset("quota exhausted, resets on 2036-12-01"), workers._parse_time("2036-12-01"))
        self.assertIsNone(workers.parse_reset("quota exhausted, resets at 2001-01-01T00:00:00Z"))   # in the past
        self.assertIsNone(workers.parse_reset("rate limit, try later"))
        self.prompt()
        self.launch()
        self.prompt(self.notice("[failed]: API error 429: usage limit reached, try again later"))
        e = self.down()["provx"]
        self.assertGreater(e["retry_at"], time.time())                     # the existing widening wait

    def test_the_new_signatures_classify(self):
        for text, reason in (("API error 429 quota exhausted", "limit"), ("HTTP 403 Forbidden", "auth"),
                             ("billing: payment required", "limit"), ("provider not connected", "missing"),
                             ("tool not found: opencode", "missing"), ("Subscription quota exhausted", "limit")):
            self.assertEqual(workers.classify_failure(text)[0], reason, text)
        self.assertIsNone(workers.classify_failure("assertion error in parser.py"))


class RouteDecisionTests(MeterBase):
    """Item 10a/10b (R-7.2-2, R-7.2-3, R-7.5-2, R-13.2-1, R-15-4): the router is consulted before a delegation and the
    guess is recorded; a retry after a rejection is stronger, not the same."""

    def deleg(self, model="alpha-small", use_id="d1"):
        return self.pre("Agent", {"description": "d", "prompt": "Outcome: x\nAcceptance: y\nFiles you may change: none",
                                  "model": model}, tool_use_id=use_id)

    def finish(self, use_id, model="alpha-small"):
        self.post("Agent", {"description": "d", "prompt": "p", "model": model}, response={"status": "completed"}, tool_use_id=use_id)
        return [r for r in workers.merged_runs()][-1]

    def judge(self, run, outcome, *extra):
        r = self.sisi("delegate", "judge", run["id"], "--outcome", outcome, "--check", "read", *extra)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout.splitlines()

    def test_a_delegation_with_no_routing_decision_is_refused_once_and_allowed_after_route(self):
        self.prompt(route=False)
        denied, reason, _ = self.deleg()
        self.assertTrue(denied)
        self.assertIn("sisi route --kind K --difficulty N", reason)
        self.assertIn("research", reason)                              # the kinds, in one line
        self.assertEqual(len(reason.splitlines()), 1)
        self.assertEqual(workers.merged_runs(), [])                     # nothing was started or recorded
        self.assertFalse(self.deleg(use_id="d2")[0])                    # once: the next one goes through unrecorded as routed
        self.assertIsNone(workers.merged_runs()[0]["type"])

    def test_after_sisi_route_the_delegation_is_allowed_and_its_run_carries_the_guess(self):
        self.prompt(route=False)
        self.route("implementation", "2")
        denied, ctx, _ = self.deleg()
        self.assertFalse(denied)
        self.assertIn("(implementation, difficulty 2)", ctx)
        self.assertNotIn("--type", ctx)                                # judge needs only the outcome and the check
        run = self.finish("d1")
        self.assertEqual((run["type"], run["difficulty"], run["route_worker"], run["chosen_against_route"]),
                         ("implementation", 2, "alpha-small", False))
        self.judge(run, "accepted")
        att = [r for r in workers.read_records() if r.get("kind") == "attempt" and r.get("run_id") == run["id"]][0]
        self.assertEqual((att["type"], att["difficulty"]), ("implementation", 2))

    def test_a_stale_decision_is_no_decision(self):
        self.prompt(route=False)
        self.route()
        with orchestration.Meter(self.sid) as m:
            m["route"]["ts"] -= 16 * 60                                  # older than the 15-minute window
        self.assertTrue(self.deleg()[0])

    def test_the_window_is_configurable(self):
        with open(os.path.join(self.data, "config.json"), "w") as f:
            json.dump({"orchestrate": {"route_window_min": 60}}, f)
        self.prompt(route=False)
        self.route()
        with orchestration.Meter(self.sid) as m:
            m["route"]["ts"] -= 30 * 60
        self.assertFalse(self.deleg()[0])

    def test_naming_another_worker_than_the_router_is_allowed_recorded_and_counted(self):
        self.prompt(route=False)
        self.route()
        self.assertFalse(self.deleg("beta-large", "o1")[0])              # the router named alpha-small
        over = self.finish("o1", "beta-large")
        self.assertEqual((over["chosen_against_route"], over["route_worker"], over["worker"]), (True, "alpha-small", "beta-large"))
        self.assertFalse(self.deleg("alpha-small", "f1")[0])
        followed = self.finish("f1")
        self.assertFalse(followed["chosen_against_route"])
        self.judge(over, "accepted")
        self.judge(followed, "rejected")
        out = self.sisi("workers").stdout
        line = next(l for l in out.splitlines() if l.startswith("Router overridden"))
        self.assertIn("overridden in 1 of 2 routed delegations", line)
        self.assertIn("too few to say (1 judged, need 5)", line)

    def test_the_override_line_gives_rates_with_five_or_more_judged_on_each_side(self):
        for i in range(5):
            for flag, outcome in ((True, "accepted" if i < 3 else "rejected"), (False, "accepted")):
                workers.append_record({"kind": "run", "id": "r%s%d" % (flag, i), "ts": 1, "worker": "w", "chosen_against_route": flag,
                                       "status": "waiting"})
                workers.append_record({"kind": "attempt", "id": "a%s%d" % (flag, i), "run_id": "r%s%d" % (flag, i), "ts": 1,
                                       "worker": "w", "outcome": outcome, "chosen_against_route": flag})
        line = workers.override_line()
        self.assertIn("Overrides: 60% accepted (5 judged)", line)
        self.assertIn("followed: 100% accepted (5 judged)", line)

    def test_retry_of_keeps_the_worker_with_the_brief_instruction_then_goes_stronger(self):
        self.prompt(route=False)
        self.route()
        self.deleg("alpha-small", "t1")
        first = self.finish("t1")
        hint = self.judge(first, "rejected")
        att1 = hint[0]
        self.assertIn("sisi route --retry-of %s" % att1, hint[1])        # the judge prints that command
        r = self.sisi("route", "--retry-of", att1, env={"SISI_SESSION_ID": self.sid})
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0], "alpha-small")                       # the first retry: the same worker
        self.assertIn("mechanism:", lines[1])
        self.assertIn("improve the brief", r.stdout.lower())
        self.assertIn("sisi delegate check", r.stdout)
        self.assertFalse(self.deleg("alpha-small", "t2")[0])             # the routing decision carries the retry link
        second = self.finish("t2")
        self.assertEqual(second["retry_of"], att1)
        att2 = self.judge(second, "rejected")[0]
        r = self.sisi("route", "--retry-of", att2, env={"SISI_SESSION_ID": self.sid})
        self.assertEqual(r.stdout.splitlines()[0], "beta-large")        # the second rejection: excluded, the next one up
        self.assertIn("alpha-small was rejected twice", r.stdout)

    def test_retry_of_uses_the_benchmark_standing_when_the_record_is_thin(self):
        with open(os.path.join(self.data, "model-strength.json"), "w") as f:
            json.dump({"models": {"alpha-small": {"score": 50, "source": "s", "date": "2026-01-01"},
                                  "beta-large": {"score": 70, "source": "s", "date": "2026-01-01"},
                                  "gamma-mid": {"score": 90, "source": "s", "date": "2026-01-01"}}}, f)
        workers.append_record({"kind": "attempt", "id": "gm", "run_id": None, "ts": 1, "project": "p", "type": "research",
                               "difficulty": 1, "worker": "gamma-mid", "outcome": "accepted", "check": "read"})
        for i, w in enumerate(("alpha-small", "alpha-small")):
            workers.append_record({"kind": "attempt", "id": "rj%d" % i, "run_id": None, "ts": 2 + i, "project": "p", "type": "research",
                                   "difficulty": 1, "worker": w, "outcome": "rejected", "check": "read",
                                   "retry_of": "rj0" if i else None})
        r = self.sisi("route", "--retry-of", "rj1", env={"SISI_SESSION_ID": self.sid})
        self.assertEqual(r.stdout.splitlines()[0], "gamma-mid")
        self.assertIn("stronger", r.stdout)

    def test_retry_of_an_unknown_or_unjudged_run_is_an_error(self):
        r = self.sisi("route", "--retry-of", "nope")
        self.assertEqual(r.returncode, 1)
        self.assertIn("judge the run first", r.stderr)

    def test_an_accepted_result_is_not_a_retry(self):
        workers.append_record({"kind": "attempt", "id": "ok1", "run_id": None, "ts": 1, "type": "research", "difficulty": 1,
                               "worker": "alpha-small", "outcome": "accepted", "check": "read"})
        r = self.sisi("route", "--retry-of", "ok1")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("improve the brief", r.stdout)

    def test_a_superseded_run_is_not_asked_for_by_the_gate(self):
        """Item 10c: a run replaced by a fallback is never listed for judgement."""
        self.prompt(route=False)
        self.route()
        self.deleg("alpha-small", "s1")
        run = workers.merged_runs()[0]
        workers.append_record({"kind": "run-end", "run_id": run["id"], "ts": 5, "ended": 5, "status": "superseded"})
        self.assertEqual(workers.unjudged_runs(), [])
        r = self.sisi("gate", "--tool", "claude-code", stdin=json.dumps(
            {"session_id": self.sid, "cwd": self.proj, "hook_event_name": "Stop"}))
        self.assertEqual(r.stdout.strip(), "")
        self.assertNotIn(run["id"], self.sisi("workers").stdout)


class NewWorkerTests(MeterBase):
    """Item 10d (R-7.2-3, R-13.2-1): a model discovery has not seen before is named once, as unproven."""

    def fake_tool(self, models):
        def fake(driver):
            if driver["name"] == "opencode":
                return {"name": "opencode", "installed": True, "usable": True, "models": list(models), "learned_by_use": False}
            return {"name": driver["name"], "installed": False, "models": [], "usable": False, "learned_by_use": False}
        return fake

    def tick_out(self, sid):
        d = {"session_id": sid, "cwd": self.proj, "hook_event_name": "SessionStart", "source": "startup"}
        return self.sisi("tick", "--tool", "claude-code", stdin=json.dumps(d)).stdout

    def test_a_newly_discovered_model_produces_the_session_start_line_exactly_once(self):
        with open(os.path.join(self.data, "workers.json"), "w") as f:
            json.dump({"checked": 1, "tools": [{"name": "opencode", "installed": True, "usable": True, "models": ["old/m1"]}]}, f)
        with mock.patch.object(workers, "_discover_tool", self.fake_tool(["old/m1", "new/m2", "new/m3", "tier-contributor/m4"])):
            workers.discover(force=True)
        first = self.tick_out("n1")
        line = next(l for l in first.splitlines() if "new worker model" in l)
        self.assertIn("new/m2", line)
        self.assertIn("new/m3", line)
        self.assertNotIn("old/m1", line)
        self.assertNotIn("contributor", line)                           # a tier that trains on prompts is never offered
        self.assertIn("unproven", line)
        self.assertIn("low-stakes", line)
        self.assertIn("one level more carefully", line)
        self.assertNotIn("new worker model", self.tick_out("n2"))        # said once

    def test_up_to_three_are_named(self):
        with open(os.path.join(self.data, "workers.json"), "w") as f:
            json.dump({"checked": 1, "tools": [{"name": "opencode", "installed": True, "usable": True, "models": ["old/m1"]}]}, f)
        with mock.patch.object(workers, "_discover_tool", self.fake_tool(["old/m1"] + ["new/m%d" % i for i in range(2, 7)])):
            workers.discover(force=True)
        line = next(l for l in self.tick_out("n3").splitlines() if "new worker model" in l)
        self.assertIn("(and 2 more)", line)

    def test_the_first_discovery_and_an_unchanged_one_say_nothing(self):
        os.unlink(os.path.join(self.data, "workers.json"))
        with mock.patch.object(workers, "_discover_tool", self.fake_tool(["a/m1"])):
            workers.discover(force=True)
            workers.discover(force=True)
        self.assertNotIn("new worker model", self.tick_out("n4"))

    def test_a_worker_session_is_not_told(self):
        with open(os.path.join(self.data, "workers.json"), "w") as f:
            json.dump({"checked": 1, "tools": [{"name": "opencode", "installed": True, "usable": True, "models": ["old/m1"]}]}, f)
        with mock.patch.object(workers, "_discover_tool", self.fake_tool(["old/m1", "new/m2"])):
            workers.discover(force=True)
        d = {"session_id": "w1", "cwd": self.proj, "hook_event_name": "SessionStart", "source": "startup", "agent_id": "a1"}
        self.assertNotIn("new worker model", self.sisi("tick", "--tool", "claude-code", stdin=json.dumps(d)).stdout)
        self.assertIn("new worker model", self.tick_out("n5"))
