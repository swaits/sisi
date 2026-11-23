import json, os, unittest
from support import *
from sisi import hookio, paths


def payload(tool, proj, sid):
    if tool == "codex":
        return {"session_id": sid, "transcript_path": "/tmp/t.jsonl", "cwd": proj,
                "hook_event_name": "Stop", "turn_id": "t1", "stop_hook_active": False, "last_assistant_message": "done"}
    if tool == "qwen":
        return {"session_id": sid, "transcript_path": "/tmp/t.jsonl", "cwd": proj,
                "hook_event_name": "Stop", "stop_hook_active": False, "last_assistant_message": "done"}
    if tool == "gemini":
        return {"session_id": sid, "transcript_path": "/tmp/t.jsonl", "cwd": proj,
                "hook_event_name": "AfterAgent", "timestamp": "2026-01-01T00:00:00Z",
                "prompt": "do it", "prompt_response": "done", "stop_hook_active": False}
    if tool == "copilot":
        return {"sessionId": sid, "timestamp": 123, "cwd": proj, "transcriptPath": "/tmp/t.jsonl",
                "stopReason": "end_turn", "stop_hook_active": False}
    if tool == "cursor":
        return {"conversation_id": sid, "generation_id": "g1", "model": "m", "hook_event_name": "stop",
                "workspace_roots": [proj], "transcript_path": None, "status": "completed", "loop_count": 0}
    return {"session_id": sid, "cwd": proj}  # pi, opencode: the extension's own payload


ALLOW_OUT = {"codex": "", "qwen": "", "copilot": "", "gemini": "{}\n", "cursor": "{}\n", "pi": "", "opencode": ""}


class NormalizeTests(unittest.TestCase):
    def test_camel_and_cursor_shapes(self):
        n = hookio.normalize("copilot", {"sessionId": "s", "transcriptPath": "/t", "cwd": "/w", "agentId": "a"})
        self.assertEqual(n, {"session_id": "s", "transcript_path": "/t", "cwd": "/w", "agent_id": "a"})
        n = hookio.normalize("cursor", {"conversation_id": "c", "workspace_roots": ["/w"], "transcript_path": None})
        self.assertEqual(n, {"session_id": "c", "cwd": "/w"})

    def test_gate_out_shapes(self):
        self.assertEqual(json.loads(hookio._gate_out("codex", "block", "why", False)[0]), {"decision": "block", "reason": "why"})
        self.assertEqual(json.loads(hookio._gate_out("gemini", "block", "why", False)[0]), {"decision": "deny", "reason": "why"})
        self.assertEqual(json.loads(hookio._gate_out("cursor", "block", "why", False)[0]), {"followup_message": "why"})
        self.assertEqual(hookio._gate_out("pi", "block", "why", False), ("why\n", 2))
        self.assertEqual(hookio._gate_out("opencode", "allow", None, False), (None, 0))

    def test_tick_out_shapes(self):
        self.assertEqual(json.loads(hookio._tick_out("codex", "lessons")),
                         {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "lessons"}})
        self.assertEqual(json.loads(hookio._tick_out("copilot", "lessons")), {"additionalContext": "lessons"})
        self.assertEqual(json.loads(hookio._tick_out("cursor", "lessons")), {"additional_context": "lessons"})
        self.assertEqual(hookio._tick_out("pi", "lessons"), "lessons\n")
        self.assertIsNone(hookio._tick_out("codex", ""))


class GateTranslationTests(SisiCase):
    def run_gate(self, tool, sid, raw=None):
        return self.sisi("gate", "--tool", tool, stdin=raw if raw is not None else json.dumps(payload(tool, self.proj, sid)))

    def test_allow_and_block_per_tool(self):
        self.write_contract(contract([check("ok", "true")]))
        for tool in hookio.TOOLS:
            with self.subTest(tool=tool, case="allow"):
                r = self.run_gate(tool, "allow-" + tool)
                self.assertEqual((r.returncode, r.stdout), (0, ALLOW_OUT[tool]))
        self.write_contract(contract([check("bad", "echo boom-output >&2; exit 1")]))
        for tool in hookio.TOOLS:
            with self.subTest(tool=tool, case="block"):
                r = self.run_gate(tool, "block-" + tool)
                if tool in ("pi", "opencode"):
                    self.assertEqual(r.returncode, 2)
                    self.assertIn("boom-output", r.stdout)
                    continue
                self.assertEqual(r.returncode, 0)
                d = json.loads(r.stdout)
                if tool == "gemini":
                    self.assertEqual(d["decision"], "deny")
                    self.assertIn("boom-output", d["reason"])
                elif tool == "cursor":
                    self.assertIn("boom-output", d["followup_message"])
                else:
                    self.assertEqual(d["decision"], "block")
                    self.assertIn("boom-output", d["reason"])

    def test_copilot_snake_case_variant(self):
        self.write_contract(contract([check("bad", "false")]))
        p = {"hook_event_name": "Stop", "session_id": "snake-1", "timestamp": "2026-01-01T00:00:00Z",
             "cwd": self.proj, "transcript_path": "/tmp/t", "stop_reason": "end_turn", "stop_hook_active": False}
        r = self.sisi("gate", "--tool", "copilot", stdin=json.dumps(p))
        self.assertEqual(json.loads(r.stdout)["decision"], "block")

    def test_cursor_aborted_turn_is_not_gated(self):
        self.write_contract(contract([check("bad", "false")]))
        p = payload("cursor", self.proj, "cur-abort")
        p["status"] = "aborted"
        r = self.sisi("gate", "--tool", "cursor", stdin=json.dumps(p))
        self.assertEqual((r.returncode, r.stdout), (0, "{}\n"))

    def test_garbage_fails_open_per_tool(self):
        self.write_contract(contract([check("bad", "false")]))
        for tool in hookio.TOOLS:
            for raw in ("not json{{{", "[1, 2]", "42"):
                with self.subTest(tool=tool, raw=raw):
                    r = self.run_gate(tool, "garbage-" + tool, raw=raw)
                    self.assertEqual((r.returncode, r.stdout), (0, ALLOW_OUT[tool]))

    def test_unknown_tool_keeps_claude_shape(self):
        self.write_contract(contract([check("bad", "false")]))
        p = {"session_id": "u1", "cwd": self.proj, "hook_event_name": "Stop"}
        r = self.sisi("gate", "--tool", "no-such-tool", stdin=json.dumps(p))
        self.assertEqual(json.loads(r.stdout)["decision"], "block")


class TickTranslationTests(SisiCase):
    def make_tick_speak(self):
        """A dangling rulebook reference makes tick print one problem line, deterministically."""
        d = os.path.join(self.home, ".codex")
        os.makedirs(d, exist_ok=True)
        link = os.path.join(d, "AGENTS.md")
        if os.path.lexists(link):
            os.unlink(link)
        os.symlink(paths.generated(), link)  # generated rulebook does not exist in this fresh home

    def test_tick_shapes_with_text(self):
        self.make_tick_speak()
        starts = {
            "codex": {"session_id": "t1", "cwd": self.proj, "hook_event_name": "SessionStart", "source": "startup"},
            "gemini": {"session_id": "t2", "cwd": self.proj, "hook_event_name": "SessionStart", "source": "startup"},
            "copilot": {"sessionId": "t3", "cwd": self.proj, "source": "startup"},
            "cursor": {"session_id": "t4", "is_background_agent": False, "composer_mode": "agent"},
            "pi": {"session_id": "t5", "cwd": self.proj},
        }
        for tool, p in starts.items():
            with self.subTest(tool=tool):
                r = self.sisi("tick", "--tool", tool, stdin=json.dumps(p))
                self.assertEqual(r.returncode, 0)
                if tool == "pi":
                    self.assertIn("generated rulebook is missing", r.stdout)
                    continue
                d = json.loads(r.stdout)
                if tool == "copilot":
                    text = d["additionalContext"]
                elif tool == "cursor":
                    text = d["additional_context"]
                else:
                    self.assertEqual(d["hookSpecificOutput"]["hookEventName"], "SessionStart")
                    text = d["hookSpecificOutput"]["additionalContext"]
                self.assertIn("generated rulebook is missing", text)

    def test_tick_garbage_fails_open(self):
        for tool in hookio.TOOLS:
            with self.subTest(tool=tool):
                r = self.sisi("tick", "--tool", tool, stdin="not json{{{")
                self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
