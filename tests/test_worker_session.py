"""Who is a worker, decided once, everywhere (R-7.1-1 the main agent owns the outcome and a worker is not metered
as one; R-7.2-2 legwork goes to a less expensive worker, so the meter must tell the two apart; R-16-1 a session a
person started is never exempted by words later in a message). Every test drives the real hook entry points with
hook-shaped JSON; the sessions here never had a prompt hook, as a session begun before sisi was upgraded."""
import json, os, subprocess, time, unittest
from unittest import mock
from support import *
import test_meter as TM
import test_unitguard as TG
from sisi import brief, orchestration, store, workerid

BRIEF = brief.template().splitlines()[0]
OPENINGS = [BRIEF, "You are a worker on this repository.", "You are a subagent for the lead.", "You are a sub-agent.",
            "YOU ARE A DELEGATE of the main thread.", "Do this task yourself: fix the parser.",
            "Please do the task yourself and report.", "Fix the parser. Do not delegate."]
ORDINARY = "Fix the parser and explain each module in the project."


class Base(TG.GuardCase):
    sid = "wk"

    def setUp(self):
        super().setUp()
        os.makedirs(self.data, exist_ok=True)
        TM.seed_workers(self)
        self.tp = os.path.join(self.tmp, "t.jsonl")

    def transcript(self, first, path=None):
        recs = [{"type": "file-history-snapshot", "snapshot": {}},
                {"type": "user", "message": {"role": "user", "content": first}, "timestamp": "2026-01-01T00:00:00Z"},
                {"type": "assistant", "message": {"role": "assistant", "content": "ok", "model": "m"}}]
        with open(path or self.tp, "w") as f:
            f.write("".join(json.dumps(r) + "\n" for r in recs))
        return path or self.tp

    def hook(self, tool, inp, after=False, sid=None, **extra):
        """The real watch hook; (denied, text)."""
        d = {"session_id": sid or self.sid, "cwd": self.proj, "tool_name": tool, "tool_input": inp,
             "transcript_path": self.tp, "hook_event_name": "PostToolUse" if after else "PreToolUse"}
        d.update(extra)
        r = self.sisi("watch", "--after" if after else "--before", "--tool", "claude-code", stdin=json.dumps(d))
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout) if r.stdout.strip() else {}
        hs = out.get("hookSpecificOutput") or {}
        return hs.get("permissionDecision") == "deny", hs.get("permissionDecisionReason") or ""

    def edit(self):
        return self.hook("Edit", {"file_path": os.path.join(self.proj, SRC_FILE), "old_string": "hi", "new_string": "yo"})

    def reads(self, n, tool="Read"):
        return [self.hook(tool, {"file_path": "/x"})[0] for _ in range(n)]

    def stop(self):
        r = self.sisi("gate", stdin=json.dumps({"session_id": self.sid, "cwd": self.proj, "hook_event_name": "Stop",
                                                "transcript_path": self.tp}))
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout) if r.stdout.strip() else {}
        return "block" if d.get("decision") == "block" else "allow"

    def stored(self):
        return orchestration._peek(self.sid).get("worker")


SRC_FILE = TG.SRC


class RecognitionTests(Base):
    def test_a_brief_in_the_transcript_makes_a_worker_for_the_guard_the_meter_and_the_gate(self):
        """R-7.1-1: no meter record, no tick, no prompt: the transcript's first message decides, in all three."""
        self.transcript(BRIEF + "\n\n## Outcome and scope\nfix the greeting")
        self.assertFalse(self.edit()[0])                      # the contract guard
        self.assertEqual(self.reads(9), [False] * 9)          # the meter (limit 6)
        with open(os.path.join(self.proj, SRC_FILE), "a") as f:
            f.write("# changed\n")
        self.assertEqual(self.stop(), "allow")                # the gate
        self.assertIs(self.stored(), True)

    def test_every_alternative_opening_makes_a_worker(self):
        for i, text in enumerate(OPENINGS):
            with self.subTest(opening=text):
                self.sid = "wk%d" % i
                self.transcript(text + "\nfix the greeting")
                self.assertFalse(self.edit()[0])
                self.assertEqual(self.reads(8), [False] * 8)
                self.assertIs(self.stored(), True)

    def test_an_ordinary_first_message_is_a_main_thread(self):
        self.transcript(ORDINARY)
        denied, text = self.edit()
        self.assertTrue(denied, text)
        self.assertEqual(self.reads(8), [False] * 6 + [True] * 2)
        self.assertIs(self.stored(), False)

    def test_words_after_the_first_400_characters_do_not_count(self):
        self.transcript(ORDINARY + " " * 5 + ("Context. " * 50) + "You are a worker. Do this task yourself. Do not delegate.")
        self.assertTrue(self.edit()[0])
        self.assertEqual(self.reads(8), [False] * 6 + [True] * 2)

    def test_the_second_message_never_counts(self):
        recs = [{"type": "user", "message": {"role": "user", "content": ORDINARY}, "timestamp": "2026-01-01T00:00:00Z"},
                {"type": "user", "message": {"role": "user", "content": BRIEF}, "timestamp": "2026-01-01T00:00:01Z"}]
        with open(self.tp, "w") as f:
            f.write("".join(json.dumps(r) + "\n" for r in recs))
        self.assertTrue(self.edit()[0])

    def test_an_unreadable_transcript_is_a_main_thread_and_nothing_is_stored(self):
        self.tp = os.path.join(self.tmp, "missing.jsonl")
        self.assertTrue(self.edit()[0])
        self.assertEqual(self.reads(8), [False] * 6 + [True] * 2)
        self.assertIsNone(self.stored())
        self.transcript(BRIEF)                 # a later call can still find it
        self.assertFalse(self.edit()[0])
        self.assertIs(self.stored(), True)

    def test_the_decision_is_stored_and_the_transcript_is_read_once(self):
        self.transcript(BRIEF)
        reads = []
        real = workerid._read_head
        with mock.patch.object(workerid, "_read_head", side_effect=lambda *a: reads.append(a) or real(*a)):
            self.edit()
            self.reads(5)
            self.hook("Read", {"file_path": "/x"}, after=True)
            self.stop()
        self.assertEqual(len(reads), 1)
        os.unlink(self.tp)                      # and it no longer needs the file
        self.assertFalse(self.edit()[0])

    def test_a_session_started_by_a_person_with_no_transcript_path_is_a_main_thread(self):
        r = self.sisi("watch", "--before", "--tool", "claude-code", stdin=json.dumps(
            {"session_id": "nopath", "cwd": self.proj, "hook_event_name": "PreToolUse", "tool_name": "Edit",
             "tool_input": {"file_path": os.path.join(self.proj, SRC_FILE)}}))
        self.assertIn("deny", r.stdout)


class ShellChangeTests(Base):
    """The lead's case: a worker known only by its first prompt changes files with a shell command (a merge); its
    next call, a read-only one, was refused as an unowned change."""

    def sequence(self):
        self.hook("Bash", {"command": "git merge --no-commit other"})
        with open(os.path.join(self.proj, "canon_discovery.json"), "w") as f:
            f.write("{}\n")                                  # what the merge did to the tree
        self.hook("Bash", {"command": "git merge --no-commit other"}, after=True)
        return self.hook("Bash", {"command": "sed -n 1,5p README.md"})

    def test_a_worker_whose_shell_command_changed_files_is_not_refused_on_its_next_call(self):
        self.transcript(BRIEF + "\nmerge the branch")
        denied, text = self.sequence()
        self.assertFalse(denied, text)
        self.assertEqual(self.stop(), "allow")

    def test_a_main_thread_in_the_same_sequence_is_still_refused(self):
        self.transcript(ORDINARY)
        denied, text = self.sequence()
        self.assertTrue(denied)
        self.assertIn("already changed", text)


class UnlistedToolTests(Base):
    def counts(self):
        return orchestration._peek(self.sid).get("calls")

    def test_an_unlisted_delegation_named_tool_at_the_limit_is_neither_refused_nor_counted(self):
        self.transcript(ORDINARY)
        self.assertEqual(self.reads(6), [False] * 6)
        n = self.counts()
        denied, text = self.hook("mcp__somehost__delegate_task", {"task": "do x", "target": {"model": "alpha-small"}})
        self.assertFalse(denied, text)
        self.assertEqual(self.counts(), n)
        self.assertTrue(self.reads(1)[0])          # the meter still bites for legwork

    def test_an_unlisted_status_tool_is_not_counted(self):
        self.transcript(ORDINARY)
        self.reads(6)
        n = self.counts()
        for tool in ("mcp__somehost__task_status", "mcp__somehost__t3_thread_wait", "mcp__somehost__ListThings"):
            self.assertFalse(self.hook(tool, {})[0], tool)
        self.assertEqual(self.counts(), n)

    def test_an_unlisted_read_tool_is_counted_and_refused_at_the_limit(self):
        self.transcript(ORDINARY)
        self.assertEqual([self.hook("mcp__somehost__read_file", {"p": "x"})[0] for _ in range(7)], [False] * 6 + [True])

    def test_a_pattern_in_the_data_covers_a_prefixed_tool(self):
        hd = {"delegation": {"*launch_it": {"model": "m", "brief": "b"}}}
        self.assertIsNotNone(orchestration.delegation_spec(hd, "mcp__a__Launch_It"))
        self.assertIsNone(orchestration.delegation_spec(hd, "mcp__a__launch_that"))

    def test_there_is_one_list_of_delegation_tools(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "canon", "guard.json")) as f:
            self.assertNotIn("delegation_tools", json.load(f))
        from sisi import unitguard
        self.assertEqual(unitguard.classify("Agent", {}, ""), "delegate")
        self.assertEqual(unitguard.classify("mcp__x__spawn_helper", {}, ""), "delegate")


if __name__ == "__main__":
    unittest.main()
