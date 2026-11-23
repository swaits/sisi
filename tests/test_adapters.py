import json, os, random, shutil, unittest
from support import *
from test_wiring import WiringBase, snapshot, rand_json, rand_hook_group
from sisi import adapters, paths, wiring


class AdapterBase(WiringBase):
    def fresh_home(self):
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)
        shutil.rmtree(self.data, ignore_errors=True)
        os.makedirs(os.path.join(self.home, ".claude"))

    def cycle(self):
        """install, install again (idempotent), uninstall (exact). Returns first install's notes."""
        before = snapshot(self.home)
        rc, notes = wiring.install()
        self.assertEqual(rc, 0, notes)
        after = snapshot(self.home)
        rc2, _ = wiring.install()
        self.assertEqual(rc2, 0)
        self.assertEqual(snapshot(self.home), after, "second install changed something")
        wiring.uninstall()
        self.assertEqual(snapshot(self.home), before, "uninstall did not restore the original home")
        return notes

    def rows(self):
        return {r["tool"]: r for r in wiring.doctor()}


class HookToolTests(AdapterBase):
    def test_codex_hooks_trust_note_and_exact_uninstall(self):
        os.makedirs(self.path(".codex"))
        pre = {"description": "mine", "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo keep"}]}],
                                                "Stop": [{"hooks": [{"type": "command", "command": "echo also-keep"}]}]}}
        self.put(".codex/hooks.json", json.dumps(pre, indent=2).encode())
        notes = self.cycle()
        self.assertTrue(any("/hooks" in n and "trust" in n for n in notes))

    def test_codex_hooks_wired_then_doctor(self):
        os.makedirs(self.path(".codex"))
        self.put(".codex/hooks.json", b'{"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo keep"}]}]}}\n')
        wiring.install()
        d = json.load(open(self.path(".codex/hooks.json")))
        self.assertEqual(d["hooks"]["PreToolUse"][0]["hooks"][0]["command"], "echo keep")
        for ev, frag in (("SessionStart", "tick --tool codex"), ("Stop", "gate --tool codex"), ("SubagentStop", "gate --subagent --tool codex")):
            cmds = [h["command"] for g in d["hooks"][ev] for h in g["hooks"]]
            self.assertTrue(any(frag in c for c in cmds), (ev, cmds))
        self.assertEqual(d["hooks"]["SessionStart"][0]["matcher"], "startup|resume")
        r = self.rows()["codex"]
        self.assertEqual((r["status"], r["enforcement"]), ("wired", "blocks"))
        self.assertIn("/hooks", r["action"])
        wiring.uninstall()

    def test_gemini_hooks_and_link(self):
        os.makedirs(self.path(".gemini"))
        self.put(".gemini/settings.json", b'{"theme": "dark", "hooks": {"BeforeTool": [{"matcher": ".*", "hooks": [{"type": "command", "command": "echo k"}]}]}}\n')
        self.cycle()
        wiring.install()
        d = json.load(open(self.path(".gemini/settings.json")))
        self.assertEqual(d["theme"], "dark")
        cmds = {ev: [h["command"] for g in d["hooks"][ev] for h in g["hooks"]] for ev in ("SessionStart", "AfterAgent")}
        self.assertTrue(any("tick --tool gemini" in c for c in cmds["SessionStart"]))
        self.assertTrue(any("gate --tool gemini" in c for c in cmds["AfterAgent"]))
        gate_hook = [h for g in d["hooks"]["AfterAgent"] for h in g["hooks"] if "gate" in h["command"]][0]
        self.assertGreaterEqual(gate_hook["timeout"], 60000)  # Gemini timeouts are milliseconds
        self.assertTrue(os.path.islink(self.path(".gemini/GEMINI.md")))
        self.assertEqual(self.rows()["gemini"]["status"], "wired")
        wiring.uninstall()

    def test_watch_hooks_registered_per_tool(self):
        cases = {"codex": (".codex", ".codex/hooks.json", ("PreToolUse", "PostToolUse"), False),
                 "gemini": (".gemini", ".gemini/settings.json", ("BeforeTool", "AfterTool"), False),
                 "copilot": (".copilot", ".copilot/hooks/sisi.json", ("preToolUse", "postToolUse"), True),
                 "cursor": (".cursor", ".cursor/hooks.json", ("preToolUse", "postToolUse"), True)}
        for name, (d, f, events, flat) in cases.items():
            with self.subTest(tool=name):
                self.fresh_home()
                os.makedirs(self.path(d), exist_ok=True)
                if name == "copilot":
                    os.makedirs(self.path(".copilot", "hooks"), exist_ok=True)
                self.cycle()  # install x2 idempotent, uninstall exact (in cycle), then installs again below
                wiring.install()
                obj = json.load(open(self.path(f)))
                for ev in events:
                    cmds = [e.get("bash") or e.get("command") for e in obj["hooks"][ev]] if flat else \
                        [h["command"] for g in obj["hooks"][ev] for h in g["hooks"]]
                    self.assertTrue(any("watch --tool %s" % name in (c or "") for c in cmds), (name, ev, cmds))
                if name == "codex":
                    for ev in events:
                        self.assertFalse(any(g.get("matcher") for g in obj["hooks"][ev]), "tool hooks cover every tool")
                self.assertEqual(self.rows()[name]["status"], "wired")
                wiring.uninstall()

    def test_gemini_user_file_not_touched(self):
        os.makedirs(self.path(".gemini"))
        self.put(".gemini/GEMINI.md", b"mine\n")
        notes = self.cycle()
        self.assertEqual(open(self.path(".gemini/GEMINI.md"), "rb").read(), b"mine\n")

    def test_copilot_hooks_file_and_link(self):
        os.makedirs(self.path(".copilot", "hooks"))
        self.put(".copilot/hooks/other.json", b'{"version": 1, "hooks": {}}\n')
        self.put(".copilot/hooks/sisi.json", b'{"version": 1, "mine": true, "hooks": {"preToolUse": [{"type": "command", "bash": "echo keep", "timeoutSec": 5}]}}\n')
        self.cycle()
        wiring.install()
        d = json.load(open(self.path(".copilot/hooks/sisi.json")))
        self.assertTrue(d["mine"])
        self.assertEqual(d["hooks"]["preToolUse"][0]["bash"], "echo keep")
        for ev, frag in (("sessionStart", "tick --tool copilot"), ("agentStop", "gate --tool copilot")):
            self.assertTrue(any(frag in e.get("bash", "") for e in d["hooks"][ev]), ev)
        self.assertTrue(os.path.islink(self.path(".copilot/copilot-instructions.md")))
        self.assertEqual(self.rows()["copilot"]["enforcement"], "blocks")
        wiring.uninstall()
        self.assertEqual(open(self.path(".copilot/hooks/other.json"), "rb").read(), b'{"version": 1, "hooks": {}}\n')

    def test_qwen_hooks_and_link(self):
        os.makedirs(self.path(".qwen"))
        self.put(".qwen/settings.json", b'{"ui": {"theme": "x"}}\n')
        self.cycle()
        wiring.install()
        d = json.load(open(self.path(".qwen/settings.json")))
        self.assertEqual(d["ui"], {"theme": "x"})
        self.assertTrue(os.path.islink(self.path(".qwen/QWEN.md")))
        self.assertEqual(self.rows()["qwen"]["status"], "wired")
        wiring.uninstall()

    def test_cursor_hooks_preserve_existing(self):
        os.makedirs(self.path(".cursor"))
        pre = {"version": 1, "hooks": {"sessionStart": [{"command": "bash '/x/herdr.sh' session"}], "afterFileEdit": [{"command": "./fmt.sh"}]}}
        self.put(".cursor/hooks.json", json.dumps(pre, indent=2).encode())
        self.cycle()
        wiring.install()
        d = json.load(open(self.path(".cursor/hooks.json")))
        self.assertEqual(d["hooks"]["afterFileEdit"][0]["command"], "./fmt.sh")
        self.assertIn("herdr", d["hooks"]["sessionStart"][0]["command"])
        self.assertTrue(any("gate --tool cursor" in e["command"] for e in d["hooks"]["stop"]))
        r = self.rows()["cursor"]
        self.assertEqual((r["status"], r["enforcement"], r["rulebook"]), ("wired", "sends a follow-up", False))
        wiring.uninstall()

    def test_pi_extension_and_link(self):
        os.makedirs(self.path(".pi", "agent"))
        self.cycle()
        wiring.install()
        ext = self.path(".pi/agent/extensions/sisi.ts")
        text = open(ext).read()
        for frag in ("session_start", "before_agent_start", "agent_before_settle", "sisi:generated", paths.launcher()):
            self.assertIn(frag, text)
        self.assertTrue(os.path.islink(self.path(".pi/agent/AGENTS.md")))
        self.assertEqual(self.rows()["pi"]["status"], "wired")
        wiring.uninstall()
        self.assertFalse(os.path.lexists(ext))

    def test_pi_user_agents_md_kept(self):
        os.makedirs(self.path(".pi", "agent"))
        self.put(".pi/agent/AGENTS.md", b"my own rules\n")
        self.cycle()
        self.assertEqual(open(self.path(".pi/agent/AGENTS.md"), "rb").read(), b"my own rules\n")

    def test_opencode_plugin_written_and_foreign_plugin_kept(self):
        os.makedirs(self.path(".config", "opencode", "plugins"))
        self.put(".config/opencode/plugins/herdr-agent-state.js", b"// theirs\n")
        self.cycle()
        self.assertEqual(open(self.path(".config/opencode/plugins/herdr-agent-state.js"), "rb").read(), b"// theirs\n")
        wiring.install()
        text = open(self.path(".config/opencode/plugins/sisi.js")).read()
        for frag in ("session.created", "session.idle", "sisi:generated", paths.launcher()):
            self.assertIn(frag, text)
        r = self.rows()["opencode"]
        self.assertEqual((r["status"], r["enforcement"], r["tick"]), ("wired", "unknown", False))
        wiring.uninstall()

    def test_generated_file_conflict_skipped(self):
        os.makedirs(self.path(".config", "opencode", "plugins"))
        self.put(".config/opencode/plugins/sisi.js", b"// my own plugin, not sisi's\n")
        notes = self.cycle()
        self.assertEqual(open(self.path(".config/opencode/plugins/sisi.js"), "rb").read(), b"// my own plugin, not sisi's\n")
        self.assertTrue(any("not touched" in n for n in notes))

    def test_invalid_tool_config_skips_only_that_tool(self):
        os.makedirs(self.path(".gemini"))
        os.makedirs(self.path(".codex"))
        self.put(".gemini/settings.json", b"{ not json")
        rc, notes = wiring.install()
        self.assertEqual(rc, 0, notes)
        self.assertEqual(open(self.path(".gemini/settings.json"), "rb").read(), b"{ not json")
        self.assertTrue(any(n.startswith("gemini: skipped") for n in notes))
        self.assertTrue(os.path.exists(self.path(".codex/hooks.json")))  # other tools still wired
        wiring.uninstall()
        self.assertEqual(open(self.path(".gemini/settings.json"), "rb").read(), b"{ not json")


class RulebookOnlyTests(AdapterBase):
    DIRS = {"kiro": (".kiro", ".kiro/steering/AGENTS.md"), "zed": (".config/zed", ".config/zed/AGENTS.md"),
            "goose": (".config/goose", ".config/goose/.goosehints"), "amp": (".config/amp", ".config/amp/AGENTS.md"),
            "grok": (".grok", ".grok/AGENTS.md"), "crush": (".config/crush", ".config/crush/CRUSH.md")}

    def test_each_links_and_uninstalls_exactly(self):
        for name, (d, link) in self.DIRS.items():
            with self.subTest(tool=name):
                self.fresh_home()
                os.makedirs(self.path(d))
                self.cycle()
                wiring.install()
                self.assertTrue(os.path.islink(self.path(link)), link)
                self.assertEqual(os.readlink(self.path(link)), wiring.core())
                r = self.rows()[name]
                self.assertEqual((r["status"], r["enforcement"]), ("wired", "none"))
                wiring.uninstall()

    def test_cline_documents_and_dotcline_variants(self):
        for base, link in (("Documents/Cline", "Documents/Cline/Rules/sisi.md"), (".cline", ".cline/rules/sisi.md")):
            with self.subTest(base=base):
                self.fresh_home()
                os.makedirs(self.path(base))
                self.cycle()
                wiring.install()
                self.assertTrue(os.path.islink(self.path(link)))
                wiring.uninstall()

    def test_windsurf_pointer_and_user_file_guard(self):
        os.makedirs(self.path(".codeium", "windsurf"))
        self.cycle()
        wiring.install()
        text = open(self.path(".codeium/windsurf/memories/global_rules.md")).read()
        self.assertIn(wiring.core(), text)
        self.assertLess(len(text), 6000)
        wiring.uninstall()
        self.assertFalse(os.path.exists(self.path(".codeium/windsurf/memories/global_rules.md")))
        self.fresh_home()
        os.makedirs(self.path(".codeium", "windsurf", "memories"))
        self.put(".codeium/windsurf/memories/global_rules.md", b"my rules\n")
        self.cycle()
        self.assertEqual(open(self.path(".codeium/windsurf/memories/global_rules.md"), "rb").read(), b"my rules\n")

    def test_aider_shapes_round_trip(self):
        cases = [
            b"model: test\n",
            b"",
            b"read:\n  - docs/a.md\nmodel: test\n",
            b"read: [docs/a.md, docs/b.md]\n",
            b"read: []\n",
            b"read: docs/a.md\n",
            b"# comment\nread:\n    - 'quoted name.md'\n",
        ]
        for orig in cases:
            with self.subTest(orig=orig[:24]):
                self.fresh_home()
                self.put(".aider.conf.yml", orig)
                self.cycle()
                wiring.install()
                now = open(self.path(".aider.conf.yml")).read()
                self.assertIn(wiring.core(), now)
                self.assertEqual(self.rows()["aider"]["status"], "wired")
                wiring.uninstall()
                self.assertEqual(open(self.path(".aider.conf.yml"), "rb").read(), orig)

    def test_aider_unrecognised_shape_left_alone(self):
        self.put(".aider.conf.yml", b"read: &anchor docs/a.md\n")
        rc, notes = wiring.install()
        self.assertEqual(rc, 0)
        self.assertEqual(open(self.path(".aider.conf.yml"), "rb").read(), b"read: &anchor docs/a.md\n")
        self.assertTrue(any(n.startswith("aider: skipped") for n in notes))
        wiring.uninstall()


class DetectionAndDoctorTests(AdapterBase):
    ALL_DIRS = [".codex", ".gemini", ".copilot", ".qwen", ".pi/agent", ".cursor", ".config/opencode",
                ".codeium/windsurf", "Documents/Cline", ".kiro", ".config/zed", ".config/goose",
                ".config/amp", ".grok", ".config/crush", ".config/muse", ".gemini/antigravity", ".t3"]

    def test_absent_tools_skipped_and_no_rows(self):
        rc, notes = wiring.install()
        self.assertEqual(rc, 0)
        for name in ("codex", "gemini", "copilot", "qwen", "pi", "cursor", "opencode", "windsurf", "cline",
                     "kiro", "zed", "goose", "amp", "grok", "crush", "aider", "muse"):
            self.assertTrue(any(n.startswith(name + ":") and "skipped" in n for n in notes), name)
        rows = self.rows()
        for name in ("gemini", "copilot", "qwen", "pi", "cursor", "windsurf", "antigravity"):
            self.assertNotIn(name, rows)
        self.assertEqual(rows["muse"]["status"], "not wired")
        self.assertIn("foreign", rows["muse"]["detail"])
        self.assertIn("t3-code", rows)
        self.assertIn("orca", rows)
        wiring.uninstall()

    def test_every_row_when_every_folder_exists(self):
        for d in self.ALL_DIRS:
            os.makedirs(self.path(d), exist_ok=True)
        self.put(".aider.conf.yml", b"model: test\n")
        wiring.install()
        rows = self.rows()
        for name in ("claude-code", "codex", "gemini", "copilot", "qwen", "pi", "cursor", "opencode", "windsurf",
                     "cline", "kiro", "zed", "goose", "amp", "grok", "crush", "aider", "muse", "antigravity",
                     "t3-code", "orca", "skills", "cli", "product", "personal", "rulebook"):
            self.assertIn(name, rows)
        for name in ("codex", "gemini", "copilot", "qwen", "pi"):
            self.assertEqual((rows[name]["status"], rows[name]["enforcement"]), ("wired", "blocks"), name)
        self.assertEqual(rows["cursor"]["enforcement"], "sends a follow-up")
        self.assertEqual(rows["opencode"]["enforcement"], "unknown")
        self.assertEqual(rows["muse"]["rulebook"], True)
        self.assertIn("claude-code", rows["t3-code"]["detail"])
        wiring.uninstall()

    def test_plan_changes_nothing(self):
        for d in self.ALL_DIRS:
            os.makedirs(self.path(d), exist_ok=True)
        self.put(".aider.conf.yml", b"model: test\n")
        before = snapshot(self.home)
        plans = {a.name: a.plan() for a in adapters.ADAPTERS if a.detect()}
        self.assertEqual(snapshot(self.home), before)
        self.assertTrue(plans["codex"])
        self.assertTrue(plans["pi"])


def rand_hooks_obj(rng, flat):
    obj = {rng.choice("pqrs") + str(i): rand_json(rng) for i in range(rng.randint(0, 3))}
    if rng.random() < 0.75:
        h = {}
        events = ("sessionStart", "stop", "agentStop") if flat else ("SessionStart", "Stop", "PreToolUse", "AfterAgent")
        for ev in events:
            if rng.random() < 0.5:
                if flat:
                    h[ev] = [{"command": "echo %d" % rng.randint(0, 9)} if rng.random() < 0.5
                             else {"type": "command", "bash": "echo %d" % rng.randint(0, 9), "timeoutSec": 5}
                             for _ in range(rng.randint(0, 2))]
                else:
                    h[ev] = [rand_hook_group(rng) for _ in range(rng.randint(0, 2))]
        obj["hooks"] = h
    if flat and rng.random() < 0.5:
        obj["version"] = 1
    ind = rng.choice([None, 2, 4])
    text = json.dumps(obj, indent=ind, ensure_ascii=rng.random() < 0.5)
    if rng.random() < 0.5:
        text += "\n"
    return text.encode("utf-8")


class MergePropertyTests(AdapterBase):
    TARGETS = {"codex": (".codex", ".codex/hooks.json", False), "gemini": (".gemini", ".gemini/settings.json", False),
               "qwen": (".qwen", ".qwen/settings.json", False), "cursor": (".cursor", ".cursor/hooks.json", True),
               "copilot": (".copilot", ".copilot/hooks/sisi.json", True)}

    def test_random_preexisting_configs(self):
        for name, (d, f, flat) in self.TARGETS.items():
            for seed in (11, 12, 13):
                rng = random.Random(seed * 1000 + len(name))
                for n in range(6 * ITERS):
                    with self.subTest(tool=name, seed=seed, n=n):
                        self.fresh_home()
                        os.makedirs(self.path(d), exist_ok=True)
                        if rng.random() < 0.8:
                            self.put(f, rand_hooks_obj(rng, flat))
                        self.cycle()


class PromptHookTests(AdapterBase):
    def test_prompt_hooks_registered_and_removed_per_tool(self):
        cases = {"codex": (".codex", ".codex/hooks.json", "UserPromptSubmit", False),
                 "gemini": (".gemini", ".gemini/settings.json", "BeforeAgent", False),
                 "copilot": (".copilot", ".copilot/hooks/sisi.json", "userPromptSubmitted", True)}
        for name, (d, f, ev, flat) in cases.items():
            with self.subTest(tool=name):
                self.fresh_home()
                os.makedirs(self.path(d), exist_ok=True)
                if name == "copilot":
                    os.makedirs(self.path(".copilot", "hooks"), exist_ok=True)
                self.cycle()  # install x2 idempotent, uninstall exact, prompt hook included
                wiring.install()
                obj = json.load(open(self.path(f)))
                cmds = [e.get("bash") or e.get("command") for e in obj["hooks"][ev]] if flat else \
                    [h["command"] for g in obj["hooks"][ev] for h in g["hooks"]]
                self.assertTrue(any("prompt --tool %s" % name in (c or "") for c in cmds), (name, ev, cmds))
                self.assertEqual(self.rows()[name]["status"], "wired")
                wiring.uninstall()

    def test_pi_extension_carries_prompt_call(self):
        self.assertIn(b'"prompt", "--tool", "pi"', adapters._pi_extension())

    def test_no_prompt_hook_where_injection_is_unconfirmed(self):
        for a in adapters.ADAPTERS:
            spec = a.spec() if hasattr(a, "spec") else {}
            if a.name in ("qwen", "cursor"):
                self.assertFalse(any(s.get("sub") == "prompt" for s in spec.values()), a.name)


class GeneratedScriptTests(AdapterBase):
    def test_opencode_plugin_parses_as_javascript(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        import subprocess
        p = os.path.join(self.tmp, "sisi-check.mjs")
        with open(p, "wb") as fh:
            fh.write(adapters._opencode_plugin())
        r = subprocess.run([node, "--check", p], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
