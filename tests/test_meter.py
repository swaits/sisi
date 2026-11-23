"""The direct-work meter, the delegation guard and the repeat-failure stop (rule 6, SPEC section 7; R-7.1-1,
R-7.2-2, R-6.3-1, R-6.3-3, R-15-4). Every test is written from the side of an agent trying to keep working
directly; hook input is what Claude Code sends, the output is what the host reads."""
import json, os, subprocess, unittest
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

    def prompt(self, text="fix the parser and explain each module in the project", sid=None):
        return self.sisi("prompt", "--tool", "claude-code", stdin=json.dumps(
            {"session_id": sid or self.sid, "cwd": self.proj, "hook_event_name": "UserPromptSubmit", "prompt": text}))

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
