import contextlib, io, json, os, random, shutil, stat, subprocess, sys, unittest
from unittest import mock
from support import *
from test_wiring import WiringBase, snapshot
from sisi import adapters, paths, wiring


class SafetyBase(WiringBase):
    def fresh_home(self):
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)
        shutil.rmtree(self.data, ignore_errors=True)
        os.makedirs(os.path.join(self.home, ".claude"))

    def rows(self):
        return {r["tool"]: r for r in wiring.doctor()}

    def skip_if_perms_ignored(self, p):
        if os.access(p, os.W_OK):
            self.skipTest("running as a user that ignores permissions")


class DanglingAndUnreadableTests(SafetyBase):
    def test_dangling_symlink_config_refused_and_preserved(self):
        os.makedirs(self.path(".gemini"))
        os.makedirs(os.path.join(self.tmp, "elsewhere"))
        target = os.path.join(self.tmp, "elsewhere", "settings.json")
        os.symlink(target, self.path(".gemini/settings.json"))
        before = snapshot(self.home)
        rc, notes = wiring.install()
        self.assertEqual(rc, 0, notes)
        self.assertTrue(os.path.islink(self.path(".gemini/settings.json")))
        self.assertEqual(os.readlink(self.path(".gemini/settings.json")), target)
        self.assertFalse(os.path.exists(target), "install wrote through a dangling symlink")
        self.assertTrue(any("dangling" in n for n in notes), notes)
        wiring.uninstall()
        self.assertTrue(os.path.islink(self.path(".gemini/settings.json")), "uninstall deleted the symlink")
        self.assertEqual(snapshot(self.home), before)

    def test_dangling_symlink_generated_refused_and_preserved(self):
        os.makedirs(self.path(".config", "opencode", "plugins"))
        os.makedirs(os.path.join(self.tmp, "elsewhere"))
        target = os.path.join(self.tmp, "elsewhere", "sisi.js")
        os.symlink(target, self.path(".config/opencode/plugins/sisi.js"))
        rc, notes = wiring.install()
        self.assertEqual(rc, 0, notes)
        self.assertTrue(os.path.islink(self.path(".config/opencode/plugins/sisi.js")))
        self.assertFalse(os.path.exists(target), "install wrote through a dangling symlink")
        wiring.uninstall()
        self.assertTrue(os.path.islink(self.path(".config/opencode/plugins/sisi.js")), "uninstall deleted the symlink")

    def test_directory_at_config_path_is_not_missing(self):
        os.makedirs(self.path(".gemini", "settings.json"))
        rc, notes = wiring.install()
        self.assertEqual(rc, 0, notes)
        self.assertTrue(os.path.isdir(self.path(".gemini/settings.json")))
        self.assertTrue(any("gemini" in n and ("director" in n or "cannot be read" in n or "not writable" in n) for n in notes), notes)
        wiring.uninstall()

    def test_live_symlinked_config_written_through_and_restored(self):
        real = os.path.join(self.tmp, "dotfiles")
        os.makedirs(real)
        with open(os.path.join(real, "gemini-settings.json"), "wb") as f:
            f.write(b'{"theme": "dark"}\n')
        os.makedirs(self.path(".gemini"))
        os.symlink(os.path.join(real, "gemini-settings.json"), self.path(".gemini/settings.json"))
        wiring.install()
        self.assertTrue(os.path.islink(self.path(".gemini/settings.json")))
        self.assertIn(b"sisi", open(os.path.join(real, "gemini-settings.json"), "rb").read())
        wiring.uninstall()
        self.assertTrue(os.path.islink(self.path(".gemini/settings.json")))
        self.assertEqual(open(os.path.join(real, "gemini-settings.json"), "rb").read(), b'{"theme": "dark"}\n')


class BackupPermissionTests(SafetyBase):
    def test_backup_permissions_match_secret_source(self):
        self.put(".claude/settings.json", b'{"apiKey": "secret"}\n')
        os.chmod(self.path(".claude/settings.json"), 0o600)
        os.makedirs(self.path(".gemini"))
        self.put(".gemini/settings.json", b'{"apiKey": "secret2"}\n')
        os.chmod(self.path(".gemini/settings.json"), 0o600)
        wiring.install()
        bdir = os.path.join(self.data, "install", "backups")
        self.assertEqual(stat.S_IMODE(os.stat(bdir).st_mode), 0o700)
        self.assertTrue(os.listdir(bdir))
        for n in os.listdir(bdir):
            mode = stat.S_IMODE(os.stat(os.path.join(bdir, n)).st_mode)
            self.assertEqual(mode & 0o077, 0, (n, oct(mode)))
            self.assertEqual(mode, 0o600, (n, oct(mode)))
        wiring.uninstall()


class ReadOnlyPreflightTests(SafetyBase):
    def test_readonly_adapter_config_skips_whole_tool_untouched(self):
        os.makedirs(self.path(".gemini"))
        self.put(".gemini/settings.json", b'{"theme": "dark"}\n')
        os.chmod(self.path(".gemini/settings.json"), 0o444)
        self.addCleanup(os.chmod, self.path(".gemini/settings.json"), 0o644)
        self.skip_if_perms_ignored(self.path(".gemini/settings.json"))
        rc, notes = wiring.install()
        self.assertEqual(rc, 0, notes)
        self.assertEqual(open(self.path(".gemini/settings.json"), "rb").read(), b'{"theme": "dark"}\n')
        self.assertFalse(os.path.lexists(self.path(".gemini/GEMINI.md")), "half-wired: link created though hooks were refused")
        self.assertTrue(any("gemini" in n and "skipped" in n for n in notes), notes)
        os.chmod(self.path(".gemini/settings.json"), 0o644)
        wiring.uninstall()

    def test_readonly_codex_hooks_no_link_either(self):
        os.makedirs(self.path(".codex"))
        self.put(".codex/hooks.json", b'{"hooks": {}}\n')
        os.chmod(self.path(".codex/hooks.json"), 0o444)
        self.addCleanup(os.chmod, self.path(".codex/hooks.json"), 0o644)
        self.skip_if_perms_ignored(self.path(".codex/hooks.json"))
        rc, notes = wiring.install()
        self.assertEqual(rc, 0, notes)
        self.assertEqual(open(self.path(".codex/hooks.json"), "rb").read(), b'{"hooks": {}}\n')
        self.assertFalse(os.path.lexists(self.path(".codex/AGENTS.md")), "half-wired: rulebook linked though hooks were refused")
        os.chmod(self.path(".codex/hooks.json"), 0o644)
        wiring.uninstall()


class DuplicateHookTests(SafetyBase):
    def _count_nested(self, path, *events):
        d = json.load(open(path))
        out = {}
        for ev in events:
            out[ev] = sum(1 for g in d.get("hooks", {}).get(ev, []) for h in g.get("hooks", []) if "sisi" in h.get("command", ""))
        return out

    def test_duplicate_hooks_deduped_in_all_add_functions(self):
        # structural add functions directly (Claude nested, adapter nested, adapter flat)
        cmds = wiring.hook_cmds()
        dup = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": cmds["Stop"][0], "timeout": 5}]},
                                   {"hooks": [{"type": "command", "command": cmds["Stop"][0], "timeout": 5},
                                              {"type": "command", "command": "echo user"}]}]}}
        wiring.add_hooks(dup)
        n = sum(1 for g in dup["hooks"]["Stop"] for h in g["hooks"] if h.get("command") == cmds["Stop"][0])
        self.assertEqual(n, 1, dup)
        self.assertTrue(any(h.get("command") == "echo user" for g in dup["hooks"]["Stop"] for h in g["hooks"]))
        a = adapters.BY_NAME["codex"]
        spec = a.spec()
        dup2 = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": spec["Stop"]["cmd"], "timeout": 1}]},
                                   {"hooks": [{"type": "command", "command": spec["Stop"]["cmd"], "timeout": 1}]}]}}
        adapters.add_nested(dup2, spec)
        n2 = sum(1 for g in dup2["hooks"]["Stop"] for h in g["hooks"] if h.get("command") == spec["Stop"]["cmd"])
        self.assertEqual(n2, 1, dup2)
        c = adapters.BY_NAME["cursor"]
        cspec = c.spec()
        dup3 = {"version": 1, "hooks": {"stop": [{"command": cspec["stop"]["cmd"]}, {"command": cspec["stop"]["cmd"]}, {"command": "./mine.sh"}]}}
        adapters.add_flat(dup3, cspec, c._entry)
        self.assertEqual(sum(1 for e in dup3["hooks"]["stop"] if e.get("command") == cspec["stop"]["cmd"]), 1, dup3)
        self.assertTrue(any(e.get("command") == "./mine.sh" for e in dup3["hooks"]["stop"]))

    def test_duplicate_hooks_deduped_on_install(self):
        os.makedirs(self.path(".codex"))
        wiring.install()
        d = json.load(open(self.path(".codex/hooks.json")))
        d["hooks"]["Stop"] = d["hooks"]["Stop"] + d["hooks"]["Stop"]  # register the gate twice
        json.dump(d, open(self.path(".codex/hooks.json"), "w"), indent=2)
        wiring.install()
        self.assertEqual(self._count_nested(self.path(".codex/hooks.json"), "Stop")["Stop"], 1)
        wiring.uninstall()


class GeneratedHeaderTests(SafetyBase):
    def test_marker_string_in_user_file_not_overwritten(self):
        os.makedirs(self.path(".config", "opencode", "plugins"))
        mine = b"// my own plugin\n// mentions sisi:generated in passing\nexport default {};\n"
        self.put(".config/opencode/plugins/sisi.js", mine)
        rc, notes = wiring.install()
        self.assertEqual(rc, 0, notes)
        self.assertEqual(open(self.path(".config/opencode/plugins/sisi.js"), "rb").read(), mine)
        r = self.rows()["opencode"]
        self.assertEqual(r["status"], "not wired")
        wiring.uninstall()
        self.assertEqual(open(self.path(".config/opencode/plugins/sisi.js"), "rb").read(), mine)

    def test_marker_string_in_windsurf_file_not_overwritten(self):
        os.makedirs(self.path(".codeium", "windsurf", "memories"))
        mine = b"# my rules\n<!-- sisi:generated is a string I read about -->\n- be nice\n"
        self.put(".codeium/windsurf/memories/global_rules.md", mine)
        wiring.install()
        self.assertEqual(open(self.path(".codeium/windsurf/memories/global_rules.md"), "rb").read(), mine)
        wiring.uninstall()
        self.assertEqual(open(self.path(".codeium/windsurf/memories/global_rules.md"), "rb").read(), mine)


class AiderQuoteTests(SafetyBase):
    def test_aider_flow_quoted_comma_survives_edit_and_uninstall(self):
        self.put(".aider.conf.yml", b'read: ["a,b.md", docs/c.md]\nmodel: test\n')
        wiring.install()
        p = self.path(".aider.conf.yml")
        now = open(p).read()
        self.assertIn('"a,b.md"', now)
        self.assertIn(wiring.core(), now)
        edited = now.replace("docs/c.md]", "docs/c.md, docs/d.md]").replace("docs/c.md,", "docs/c.md,")
        if "docs/d.md" not in edited:
            edited = now.replace("]", ", docs/d.md]")
        open(p, "w").write(edited)
        wiring.uninstall()
        out = open(p).read()
        self.assertIn('"a,b.md"', out, out)
        self.assertIn("docs/c.md", out)
        self.assertIn("docs/d.md", out)
        self.assertNotIn(wiring.core(), out)
        span = adapters._aider_read_span(out.split("\n"))
        self.assertEqual(span[2], ["a,b.md", "docs/c.md", "docs/d.md"])

    def test_aider_uncertain_flow_skipped(self):
        orig = b"read: [[nested], docs/c.md]\n"
        self.put(".aider.conf.yml", orig)
        rc, notes = wiring.install()
        self.assertEqual(rc, 0, notes)
        self.assertEqual(open(self.path(".aider.conf.yml"), "rb").read(), orig)
        self.assertTrue(any(n.startswith("aider: skipped") for n in notes), notes)
        wiring.uninstall()


class ByteExactTests(SafetyBase):
    ORIG = b'{"theme": "caf\\u00e9", "limit": 1e3, "x": 1, "x": 2, "hooks": {"BeforeTool": [{"hooks": [{"type": "command", "command": "echo k"}]}]}}\n'

    def test_uninstall_after_user_edit_preserves_spellings(self):
        os.makedirs(self.path(".gemini"))
        self.put(".gemini/settings.json", self.ORIG)
        wiring.install()
        p = self.path(".gemini/settings.json")
        now = open(p, "rb").read()
        self.assertIn(b"1e3", now)
        self.assertIn(b"caf\\u00e9", now)
        edited = now.replace(b'"limit": 1e3', b'"limit": 2e3, "mine": true')
        open(p, "wb").write(edited)
        wiring.uninstall()
        out = open(p, "rb").read()
        self.assertIn(b"2e3", out, out)
        self.assertIn(b"caf\\u00e9", out, out)
        self.assertIn(b'"mine": true', out, out)
        self.assertEqual(out.count(b'"x":'), 2, out)
        self.assertNotIn(b"sisi", out, out)

    def test_second_round_changed_original_restored(self):
        os.makedirs(self.path(".gemini"))
        self.put(".gemini/settings.json", b'{"theme": "one", "limit": 1e3}\n')
        wiring.install(); wiring.uninstall()
        self.assertEqual(open(self.path(".gemini/settings.json"), "rb").read(), b'{"theme": "one", "limit": 1e3}\n')
        self.put(".gemini/settings.json", b'{"theme": "two", "limit": 2.50, "extra": [1, 2]}\n')
        wiring.install(); wiring.uninstall()
        self.assertEqual(open(self.path(".gemini/settings.json"), "rb").read(), b'{"theme": "two", "limit": 2.50, "extra": [1, 2]}\n')

    def test_uninstall_edited_generated_left_alone(self):
        os.makedirs(self.path(".pi", "agent"))
        wiring.install()
        p = self.path(".pi/agent/extensions/sisi.ts")
        with open(p, "a") as f:
            f.write("// my own tweak\n")
        edited = open(p, "rb").read()
        wiring.uninstall()
        self.assertTrue(os.path.exists(p))
        self.assertEqual(open(p, "rb").read(), edited)


class OldGeneratedTests(SafetyBase):
    OLD_PI = (b"// sisi:generated by `sisi install` -- runs `sisi tick` at session start and `sisi gate` before the session settles. Remove with `sisi uninstall`.\n"
              b"import { execFile } from \"node:child_process\";\nconst OLD = true;\n")

    def test_old_pi_extension_updated_by_install_and_dry_run(self):
        os.makedirs(self.path(".pi", "agent", "extensions"))
        p = self.path(".pi/agent/extensions/sisi.ts")
        self.put(".pi/agent/extensions/sisi.ts", self.OLD_PI)
        r = self.sisi("install", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("is not ours", r.stdout)
        self.assertEqual(open(p, "rb").read(), self.OLD_PI)  # dry run changes nothing
        rc, notes = wiring.install()
        self.assertEqual(rc, 0, notes)
        self.assertNotEqual(open(p, "rb").read(), self.OLD_PI)
        self.assertIn(b"sisi:generated", open(p, "rb").read().split(b"\n", 1)[0])
        wiring.uninstall()
        self.assertFalse(os.path.exists(p))

    def test_old_marker_only_in_body_still_refused(self):
        os.makedirs(self.path(".pi", "agent", "extensions"))
        mine = b"// my extension\nexport const X = 'sisi:generated';\n"
        self.put(".pi/agent/extensions/sisi.ts", mine)
        rc, notes = wiring.install()
        self.assertEqual(rc, 0, notes)
        self.assertEqual(open(self.path(".pi/agent/extensions/sisi.ts"), "rb").read(), mine)
        wiring.uninstall()


class FailOpenCommandTests(SafetyBase):
    def test_hook_command_fails_open_without_launcher(self):
        repo = os.path.join(self.tmp, "repo-copy")
        shutil.copytree(REPO, repo, ignore=shutil.ignore_patterns(".git", "__pycache__", "tests", ".agent-work"))
        old_repo = paths.REPO
        paths.REPO = repo
        self.addCleanup(setattr, paths, "REPO", old_repo)
        os.makedirs(self.path(".codex"), exist_ok=True)
        wiring.install()
        d = json.load(open(self.path(".claude/settings.json")))
        cmd = d["hooks"]["Stop"][0]["hooks"][0]["command"]
        payload = json.dumps({"session_id": "s", "cwd": self.proj})
        r = subprocess.run(cmd, shell=True, input=payload, capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))
        os.rename(os.path.join(repo, "bin", "sisi"), os.path.join(repo, "bin", "sisi-gone"))
        r2 = subprocess.run(cmd, shell=True, input=payload, capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual((r2.returncode, r2.stdout), (0, ""), (r2.stdout, r2.stderr))


class DoctorAccuracyTests(SafetyBase):
    def test_doctor_stale_generated_not_wired(self):
        os.makedirs(self.path(".pi", "agent"))
        wiring.install()
        p = self.path(".pi/agent/extensions/sisi.ts")
        self.assertEqual(self.rows()["pi"]["status"], "wired")
        with open(p, "a") as f:
            f.write("// drift\n")
        r = self.rows()["pi"]
        self.assertEqual(r["status"], "not wired", r)
        wiring.uninstall()

    def test_doctor_agents_override_shadows_codex_and_pi(self):
        os.makedirs(self.path(".codex"))
        os.makedirs(self.path(".pi", "agent"))
        wiring.install()
        self.assertEqual(self.rows()["codex"]["status"], "wired")
        self.put(".codex/AGENTS.override.md", b"override wins\n")
        self.put(".pi/agent/AGENTS.override.md", b"override wins\n")
        rows = self.rows()
        for tool in ("codex", "pi"):
            self.assertEqual(rows[tool]["status"], "not wired", rows[tool])
            self.assertFalse(rows[tool]["rulebook"])
            self.assertIn("override", rows[tool]["detail"].lower())
        wiring.uninstall()

    def test_env_overrides_honoured(self):
        # Fresh process semantics, in-process: clear the cache effects by checking adapter resolution
        # and a real install into the override dirs (all inside the fake home).
        for d in ("oc-custom", "codex-home", "copilot-home", "grok-home", "pi-agent"):
            os.makedirs(os.path.join(self.home, d))
        env = {"OPENCODE_CONFIG_DIR": os.path.join(self.home, "oc-custom"),
               "CODEX_HOME": os.path.join(self.home, "codex-home"),
               "COPILOT_HOME": os.path.join(self.home, "copilot-home"),
               "GROK_HOME": os.path.join(self.home, "grok-home"),
               "PI_CODING_AGENT_DIR": os.path.join(self.home, "pi-agent")}
        with mock.patch.dict(os.environ, env):
            rc, notes = wiring.install()
            self.assertEqual(rc, 0, notes)
            self.assertTrue(os.path.islink(os.path.join(self.home, "codex-home", "AGENTS.md")))
            self.assertTrue(os.path.exists(os.path.join(self.home, "codex-home", "hooks.json")))
            self.assertTrue(os.path.islink(os.path.join(self.home, "oc-custom", "AGENTS.md")))
            self.assertTrue(os.path.exists(os.path.join(self.home, "copilot-home", "hooks", "sisi.json")))
            self.assertTrue(os.path.islink(os.path.join(self.home, "grok-home", "AGENTS.md")))
            self.assertTrue(os.path.exists(os.path.join(self.home, "pi-agent", "extensions", "sisi.ts")))
            wiring.uninstall()

    def test_xdg_config_home_honoured_for_opencode_and_crush(self):
        xdg = os.path.join(self.home, "xdg")
        os.makedirs(os.path.join(xdg, "opencode"))
        os.makedirs(os.path.join(xdg, "crush"))
        env = {"HOME": self.home, "XDG_CONFIG_HOME": xdg}
        with mock.patch.dict(os.environ, env):
            os.environ.pop("SISI_HOME", None)
            self.assertEqual(wiring.loc()["opencode_dir"], os.path.join(xdg, "opencode"))
            self.assertEqual(adapters.BY_NAME["crush"]._detect_dir, os.path.join(xdg, "crush"))


class DocsAndDryRunTests(SafetyBase):
    def test_docs_evidence_markers_and_no_claude_only_claim(self):
        readme = open(os.path.join(REPO, "README.md"), encoding="utf-8").read()
        self.assertNotIn("blocks in Claude Code only", readme)
        harnesses = open(os.path.join(REPO, "docs", "harnesses.md"), encoding="utf-8").read()
        for sec in ("## Amp", "## Goose", "## Cline"):
            body = harnesses.split(sec, 1)[1].split("\n## ", 1)[0]
            self.assertTrue("onfirmed" in body or "not verified" in body or "nconfirmed" in body, (sec, body))

    def test_install_dry_run_changes_nothing(self):
        for d in (".codex", ".gemini", ".cursor", ".config/opencode", ".pi/agent"):
            os.makedirs(self.path(d), exist_ok=True)
        self.put(".gemini/settings.json", b'{"theme": "dark"}\n')
        before = (snapshot(self.home), snapshot(self.data) if os.path.isdir(self.data) else {},
                  snapshot(self.state) if os.path.isdir(self.state) else {})
        r = self.sisi("install", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dry-run", r.stdout.lower())
        self.assertIn("@@", r.stdout)
        self.assertIn("settings.json", r.stdout)
        after = (snapshot(self.home), snapshot(self.data) if os.path.isdir(self.data) else {},
                 snapshot(self.state) if os.path.isdir(self.state) else {})
        self.assertEqual(after, before)
        r2 = self.sisi("install")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        wiring.uninstall()


class WidenedPropertyTests(SafetyBase):
    """Every config-merging tool against hostile pre-existing configs. The documented guarantee:
    unedited files restore byte for byte; edited files keep the user's edits and every other byte;
    files sisi cannot edit with certainty are never rewritten."""
    TOOLS = {
        "codex": (".codex", ".codex/hooks.json", ".codex/AGENTS.md"),
        "gemini": (".gemini", ".gemini/settings.json", ".gemini/GEMINI.md"),
        "qwen": (".qwen", ".qwen/settings.json", ".qwen/QWEN.md"),
        "cursor": (".cursor", ".cursor/hooks.json", None),
        "copilot": (".copilot", ".copilot/hooks/sisi.json", ".copilot/copilot-instructions.md"),
    }
    SPELLINGS = b'{"theme": "caf\\u00e9", "limit": 1e3, "ratio": 2.50, "x": 1, "x": 2}\n'
    JSONC = b'{\n  // a comment\n  "theme": "dark",\n}\n'

    def run_case(self, tool, kind):
        d, f, link = self.TOOLS[tool]
        self.fresh_home()
        os.makedirs(self.path(d), exist_ok=True)
        p = self.path(f)
        elsewhere = os.path.join(self.tmp, "elsewhere-" + tool)
        os.makedirs(elsewhere, exist_ok=True)
        if kind == "spellings":
            self.put(f, self.SPELLINGS)
        elif kind == "jsonc":
            self.put(f, self.JSONC)
        elif kind == "live-symlink":
            real = os.path.join(elsewhere, "real.json")
            open(real, "wb").write(self.SPELLINGS)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            os.symlink(real, p)
        elif kind == "dangling":
            os.makedirs(os.path.dirname(p), exist_ok=True)
            os.symlink(os.path.join(elsewhere, "missing.json"), p)
        elif kind == "readonly":
            self.put(f, self.SPELLINGS)
            os.chmod(p, 0o444)
            self.skip_if_perms_ignored(p)
        before = snapshot(self.home)
        try:
            rc, notes = wiring.install()
            self.assertEqual(rc, 0, (tool, kind, notes))
            after1 = snapshot(self.home)
            wiring.install()
            self.assertEqual(snapshot(self.home), after1, (tool, kind, "install twice != install once"))
            if kind in ("jsonc", "readonly"):
                self.assertEqual(open(p, "rb").read(), self.JSONC if kind == "jsonc" else self.SPELLINGS)
            if kind == "dangling":
                self.assertTrue(wiring._dangling(p))
                self.assertFalse(os.path.exists(os.path.join(elsewhere, "missing.json")))
            if kind in ("jsonc", "dangling", "readonly") and link:
                self.assertFalse(os.path.lexists(self.path(link)), (tool, kind, "half-wired link"))
            wiring.uninstall()
            if kind == "readonly":
                os.chmod(p, 0o644)
            self.assertEqual(snapshot(self.home), before, (tool, kind, "uninstall not exact"))
        finally:
            if kind == "readonly" and os.path.exists(p) and not os.path.islink(p):
                try:
                    os.chmod(p, 0o644)
                except OSError:
                    pass

    def test_nasty_configs_per_tool(self):
        for tool in self.TOOLS:
            for kind in ("absent", "spellings", "jsonc", "live-symlink", "dangling", "readonly"):
                with self.subTest(tool=tool, kind=kind):
                    self.run_case(tool, kind)

    def test_edit_between_install_and_uninstall_per_tool(self):
        for tool, (d, f, _link) in self.TOOLS.items():
            with self.subTest(tool=tool):
                self.fresh_home()
                os.makedirs(self.path(d), exist_ok=True)
                self.put(f, self.SPELLINGS)
                p = self.path(f)
                wiring.install()
                now = open(p, "rb").read()
                self.assertIn(b"1e3", now)
                edited = now.replace(b"1e3", b"2e3").replace(b"{", b'{"mine": true, ', 1)
                open(p, "wb").write(edited)
                wiring.uninstall()
                out = open(p, "rb").read()
                self.assertIn(b"2e3", out, (tool, out))
                self.assertIn(b'"mine": true', out, (tool, out))
                self.assertIn(b"caf\\u00e9", out, (tool, out))
                self.assertNotIn(b"--tool", out, (tool, out))

    def test_duplicates_then_reinstall_per_tool(self):
        for tool, (d, f, _link) in self.TOOLS.items():
            with self.subTest(tool=tool):
                self.fresh_home()
                os.makedirs(self.path(d), exist_ok=True)
                wiring.install()
                p = self.path(f)
                obj = json.load(open(p))
                for ev in list(obj.get("hooks", {})):
                    obj["hooks"][ev] = obj["hooks"][ev] + obj["hooks"][ev]
                json.dump(obj, open(p, "w"), indent=2)
                wiring.install()
                raw = open(p, "rb").read()
                # exactly one registration per event in the tool's spec (tick, prompt where wired,
                # gate, subagent gate, watch before/after), however many duplicates were planted
                adapter = next(a for a in adapters.ADAPTERS if a.name == tool)
                self.assertLessEqual(raw.count(b"--tool " + tool.encode()), len(adapter.spec()), (tool, raw))
                d2 = json.load(open(p))
                for ev, entries in d2.get("hooks", {}).items():
                    flat = [e.get("bash") or e.get("command") for e in entries if isinstance(e, dict)]
                    nested = [h.get("command") for g in entries if isinstance(g, dict) for h in g.get("hooks", [])]
                    cmds = [c for c in flat + nested if c and "sisi" in c]
                    self.assertEqual(len(cmds), len(set(cmds)), (tool, ev, cmds))
                wiring.uninstall()

    def test_marker_string_files_for_generated_tools(self):
        cases = [
            (".config/opencode/plugins", ".config/opencode/plugins/sisi.js",
             b"// mine\nconst x = 'sisi:generated';\n"),
            (".pi/agent/extensions", ".pi/agent/extensions/sisi.ts",
             b"// mine\nexport const MARKER = 'sisi:generated';\n"),
        ]
        for d, f, mine in cases:
            with self.subTest(file=f):
                self.fresh_home()
                os.makedirs(self.path(".config", "opencode"), exist_ok=True)
                os.makedirs(self.path(d), exist_ok=True)
                self.put(f, mine)
                before = snapshot(self.home)
                wiring.install(); wiring.install()
                self.assertEqual(open(self.path(f), "rb").read(), mine)
                wiring.uninstall()
                self.assertEqual(open(self.path(f), "rb").read(), mine)
                self.assertEqual(snapshot(self.home), before)

    def test_seeded_random_valid_configs(self):
        from test_adapters import rand_hooks_obj
        flat_tools = {"cursor", "copilot"}
        for tool, (d, f, _link) in self.TOOLS.items():
            rng = random.Random(4242 + len(tool))
            for n in range(3 * ITERS):
                with self.subTest(tool=tool, n=n):
                    self.fresh_home()
                    os.makedirs(self.path(d), exist_ok=True)
                    if rng.random() < 0.85:
                        self.put(f, rand_hooks_obj(rng, tool in flat_tools))
                    before = snapshot(self.home)
                    rc, notes = wiring.install()
                    self.assertEqual(rc, 0, notes)
                    after1 = snapshot(self.home)
                    wiring.install()
                    self.assertEqual(snapshot(self.home), after1, (tool, n))
                    wiring.uninstall()
                    self.assertEqual(snapshot(self.home), before, (tool, n))


if __name__ == "__main__":
    unittest.main()


real_cmds = wiring.hook_cmds  # the registration as this version makes it, kept before any test patches it


class AllToolsHookMigrationTests(SafetyBase):
    """Item 7: an installed shell-only configuration becomes all-tool hooks, span-preserving, and uninstall restores
    the original bytes (R-7.1-1 / R-6.3-1: the meter must see every tool)."""

    ORIGINAL = (b'{\n    "theme": "dark",   \n    "hooks": {\n        "PreToolUse": [\n'
                b'            {"matcher": "Edit", "hooks": [{"type": "command", "command": "echo mine"}]}\n        ]\n    },\n'
                b'    "model": "x"\n}\n')

    def settings(self):
        return self.path(".claude/settings.json")

    def install_old_style(self):
        """What the previous release wrote: shell-only matchers on the tool hooks and no failure hook."""
        old = {"PreToolUse": "Bash", "PostToolUse": "Bash"}
        with mock.patch.object(wiring, "HOOK_MATCHERS", old), \
                mock.patch.object(wiring, "hook_cmds", lambda: {k: v for k, v in real_cmds().items() if k != "PostToolUseFailure"}):
            rc, notes = wiring.install()
        self.assertEqual(rc, 0, notes)

    def groups(self, ev):
        return json.load(open(self.settings()))["hooks"][ev]

    def test_shell_only_install_is_migrated_and_uninstall_restores_the_original_bytes(self):
        self.put(".claude/settings.json", self.ORIGINAL)
        self.install_old_style()
        self.assertTrue(any(g.get("matcher") == "Bash" for g in self.groups("PreToolUse")))
        self.assertNotIn("PostToolUseFailure", json.load(open(self.settings()))["hooks"])
        self.assertIn("watch-failure hook", wiring.doctor_claude())            # doctor says what is missing
        rc, notes = wiring.install()                                          # `sisi install` again, with this version
        self.assertEqual(rc, 0, notes)
        for ev in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
            mine = [g for g in self.groups(ev) if any("watch --tool" in h["command"] for h in g["hooks"])]
            self.assertEqual(len(mine), 1, ev)
            self.assertFalse(mine[0].get("matcher"), (ev, mine))                 # every tool: no matcher
        user = [g for g in self.groups("PreToolUse") if g.get("matcher") == "Edit"]
        self.assertEqual(user, [{"matcher": "Edit", "hooks": [{"type": "command", "command": "echo mine"}]}])
        self.assertEqual(wiring.doctor_claude(), "")
        before = open(self.settings(), "rb").read()
        wiring.install()
        self.assertEqual(open(self.settings(), "rb").read(), before)            # idempotent
        wiring.uninstall()
        self.assertEqual(open(self.settings(), "rb").read(), self.ORIGINAL)     # the original bytes, spelling and all

    def test_a_group_shared_with_a_users_own_hook_is_split_not_widened(self):
        """Our entry sharing a Bash-matcher group with a user's hook must not widen the user's hook to every tool."""
        cmd = real_cmds()["PreToolUse"][0]
        shared = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": "echo mine"}, {"type": "command", "command": cmd, "timeout": 60}]}]}}
        self.put(".claude/settings.json", json.dumps(shared, indent=2).encode() + b"\n")
        wiring.install()
        groups = self.groups("PreToolUse")
        user = [g for g in groups if any(h["command"] == "echo mine" for h in g["hooks"])]
        self.assertEqual(len(user), 1)
        self.assertEqual(user[0]["matcher"], "Bash")
        self.assertEqual(len(user[0]["hooks"]), 1)
        ours = [g for g in groups if any("watch --tool" in h["command"] for h in g["hooks"])]
        self.assertEqual(len(ours), 1)
        self.assertFalse(ours[0].get("matcher"))

    def test_sisi_update_brings_an_existing_installation_to_all_tool_hooks(self):
        self.put(".claude/settings.json", self.ORIGINAL)
        self.install_old_style()
        from sisi import lifecycle
        with contextlib.redirect_stdout(io.StringIO()):
            lifecycle._rewire_existing()
        self.assertFalse(any(g.get("matcher") == "Bash" for g in self.groups("PreToolUse")))
        self.assertIn("PostToolUseFailure", json.load(open(self.settings()))["hooks"])
        wiring.uninstall()
        self.assertEqual(open(self.settings(), "rb").read(), self.ORIGINAL)

    def test_update_without_an_installation_changes_nothing(self):
        self.put(".claude/settings.json", self.ORIGINAL)
        from sisi import lifecycle
        with contextlib.redirect_stdout(io.StringIO()):
            lifecycle._rewire_existing()
        self.assertEqual(open(self.settings(), "rb").read(), self.ORIGINAL)

    def test_codex_shell_only_hooks_are_widened_too(self):
        os.makedirs(self.path(".codex"))
        old = {"PreToolUse": {"cmd": "x"}}
        spec = adapters.BY_NAME["codex"].spec()
        spec_old = {k: dict(v, matcher="Bash") if k in ("PreToolUse", "PostToolUse") else v for k, v in spec.items()}
        with mock.patch.object(adapters.Codex, "spec", lambda self: spec_old):
            wiring.install()
        self.assertTrue(any(g.get("matcher") == "Bash" for g in json.load(open(self.path(".codex/hooks.json")))["hooks"]["PreToolUse"]))
        wiring.install()
        self.assertFalse(any(g.get("matcher") for g in json.load(open(self.path(".codex/hooks.json")))["hooks"]["PreToolUse"]))
        wiring.uninstall()
        self.assertFalse(os.path.exists(self.path(".codex/hooks.json")))

    def test_doctor_says_what_the_meter_can_do_per_tool(self):
        from sisi import orchestration
        shutil.copy(os.path.join(REPO, "canon", "orchestration-tools.json"), os.path.join(self.repo, "canon"))
        orchestration._HOSTS.clear()
        self.addCleanup(orchestration._HOSTS.clear)
        os.makedirs(self.path(".codex"))
        os.makedirs(self.path(".qwen"))
        wiring.install()
        rows = {r["tool"]: r for r in wiring.doctor()}
        self.assertIn("can refuse", rows["claude-code"]["meter"])
        self.assertIn("observed live", rows["claude-code"]["meter"])
        self.assertIn("exit status 2", rows["codex"]["meter"])
        self.assertIn("not run live", rows["codex"]["meter"])
        self.assertIn("cannot run", rows["qwen"]["meter"])
        out = self.sisi("doctor").stdout
        self.assertIn("orchestration meter: cannot run", out)


