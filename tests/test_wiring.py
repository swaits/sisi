import json, os, random, shutil, unittest
from support import *
from sisi import paths, wiring


def snapshot(root):
    snap = {}
    for dp, dns, fns in os.walk(root):
        for n in dns + fns:
            p = os.path.join(dp, n)
            rel = os.path.relpath(p, root)
            if os.path.islink(p):
                snap[rel] = ("l", os.readlink(p))
            elif os.path.isdir(p):
                snap[rel] = ("d",)
            else:
                with open(p, "rb") as f:
                    snap[rel] = ("f", f.read())
    return snap


def remove_hooks(obj):
    """Test oracle: strip our hook groups from a settings object (the product removes them structurally)."""
    changed = False
    hooks = obj.get("hooks")
    if not isinstance(hooks, dict):
        return False
    for ev, sub in (("SessionStart", "tick"), ("UserPromptSubmit", "prompt"), ("Stop", "gate"), ("SubagentStop", "gate"),
                    ("PreToolUse", "watch"), ("PostToolUse", "watch"), ("PostToolUseFailure", "watch")):
        groups = hooks.get(ev)
        if not isinstance(groups, list):
            continue
        keep, ev_changed = [], False
        for g in groups:
            hs = g.get("hooks") if isinstance(g, dict) else None
            if isinstance(hs, list) and any(wiring._is_ours(h, sub) for h in hs):
                changed = ev_changed = True
                rest = [h for h in hs if not wiring._is_ours(h, sub)]
                if rest:
                    g = dict(g, hooks=rest)
                else:
                    continue
            keep.append(g)
        if keep:
            hooks[ev] = keep
        elif ev_changed:
            del hooks[ev]
    if changed and not hooks:
        del obj["hooks"]
    return changed


class WiringBase(SisiCase):
    def setUp(self):
        super().setUp()
        # A fake repo so skills linking can be tested without touching the real canon.
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(self.repo, "canon", "skills", "alpha"))
        os.makedirs(os.path.join(self.repo, "bin"))
        for f in ("canon/core.md", "bin/sisi", "canon/skills/alpha/SKILL.md"):
            open(os.path.join(self.repo, f), "w").write("x\n")
        old = paths.REPO
        paths.REPO = self.repo
        self.addCleanup(setattr, paths, "REPO", old)
        os.makedirs(os.path.join(self.home, ".claude"))

    def path(self, *p):
        return os.path.join(self.home, *p)

    def put(self, rel, data):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def state_snapshot(self):
        return snapshot(self.state)


def rand_json(rng, depth=0):
    r = rng.random()
    if depth > 2 or r < 0.4:
        return rng.choice([None, True, 1, 2.5, 1.0, -7, "s", "unïcode ✓", "", 10**20])
    if r < 0.7:
        return [rand_json(rng, depth + 1) for _ in range(rng.randint(0, 3))]
    return {rng.choice("abcdef") + str(i): rand_json(rng, depth + 1) for i in range(rng.randint(0, 3))}


def rand_hook_group(rng):
    return {"matcher": rng.choice(["*", "Bash", "startup"]), "hooks": [
        {"type": "command", "command": "echo %d" % rng.randint(0, 9), "timeout": rng.randint(1, 30)}
        for _ in range(rng.randint(0, 2))]}


def rand_settings(rng):
    obj = {rng.choice("pqrs") + str(i): rand_json(rng) for i in range(rng.randint(0, 4))}
    r = rng.random()
    if r < 0.7:
        h = {}
        for ev in ("SessionStart", "Stop", "PreToolUse"):
            if rng.random() < 0.5:
                h[ev] = [rand_hook_group(rng) for _ in range(rng.randint(0, 2))]
        obj["hooks"] = h
    elif r < 0.8:
        obj["hooks"] = None if rng.random() < 0.5 else {}
    keys = list(obj.items())
    rng.shuffle(keys)
    obj = dict(keys)
    ind = rng.choice([None, 1, 2, 4, "\t"])
    text = json.dumps(obj, indent=ind, ensure_ascii=rng.random() < 0.5)
    if rng.random() < 0.5:
        text += "\n"
    if rng.random() < 0.2:
        text = "\n  " + text + "  \n\n"
    return text.encode("utf-8")


def rand_md(rng):
    parts = []
    for _ in range(rng.randint(0, 6)):
        parts.append(rng.choice(["# Title", "", "some text ünï", "@~/other.md", "  indented", "<!-- c -->", "x\r"]))
    sep = rng.choice(["\n", "\r\n"])
    text = sep.join(parts)
    if parts and rng.random() < 0.6:
        text += sep
    return text.encode("utf-8")


class WiringPropertyTests(WiringBase):
    def run_case(self, rng):
        md = None if rng.random() < 0.2 else rand_md(rng)
        st = None if rng.random() < 0.2 else rand_settings(rng)
        if md is not None:
            self.put(".claude/CLAUDE.md", md)
        if st is not None:
            self.put(".claude/settings.json", st)
        r = rng.random()
        if r < 0.3:
            os.makedirs(self.path(".codex"))
        elif r < 0.5:
            self.put(".codex/AGENTS.md", b"mine\n")
        if rng.random() < 0.5:
            os.makedirs(self.path(".local", "bin"))
        if rng.random() < 0.3:
            os.makedirs(self.path(".agents", "skills"))
        if rng.random() < 0.3:
            os.makedirs(self.path(".config", "opencode"))
        before, state0 = snapshot(self.home), self.state_snapshot()

        rc, _ = wiring.install()
        self.assertEqual(rc, 0)
        after1, st1 = snapshot(self.home), self.state_snapshot()
        wiring.install()
        self.assertEqual(snapshot(self.home), after1, "install not idempotent (home)")
        self.assertEqual(self.state_snapshot(), st1, "install not idempotent (state)")
        # everything else survives install
        if st is not None and st.strip():
            orig = json.loads(st)
            now = json.loads(self.path(".claude/settings.json") and open(self.path(".claude/settings.json"), "rb").read())
            remove_hooks(now)

            def norm(d):  # empty hook lists/objects may legitimately disappear in the structural path
                h = d.get("hooks")
                if isinstance(h, dict):
                    d["hooks"] = {k: v for k, v in h.items() if v != []}
                if d.get("hooks") in (None, {}):
                    d.pop("hooks", None)
                return d
            self.assertEqual(norm(now), norm(orig))
        if md is not None:
            self.assertTrue(open(self.path(".claude/CLAUDE.md"), "rb").read().startswith(md))
        self.assertEqual(wiring.doctor()[0]["status"], "wired")
        wiring.uninstall()
        self.assertEqual(snapshot(self.home), before, "uninstall did not restore the original")

    def test_install_idempotent_and_uninstall_exact(self):
        for seed in [0, 1] + [random.randrange(2**32) for _ in range(ITERS + 1)]:
            rng = random.Random(seed)
            for n in range(10 * ITERS):
                with self.subTest(seed=seed, n=n):
                    shutil.rmtree(self.home, ignore_errors=True)
                    shutil.rmtree(self.state, ignore_errors=True)
                    shutil.rmtree(self.data, ignore_errors=True)
                    os.makedirs(self.path(".claude"))
                    self.run_case(rng)


class WiringTests(WiringBase):
    def test_existing_hooks_preserved_in_place(self):
        orig = {"hooks": {"SessionStart": [{"matcher": "*", "hooks": [{"type": "command", "command": "keep-me"}]}]}, "x": 1}
        self.put(".claude/settings.json", json.dumps(orig, indent=2).encode())
        wiring.install()
        d = json.load(open(self.path(".claude/settings.json")))
        self.assertEqual(d["hooks"]["SessionStart"][0], orig["hooks"]["SessionStart"][0])
        cmds = [h["command"] for g in d["hooks"]["SessionStart"] for h in g["hooks"]]
        self.assertTrue(any(c.endswith("sisi tick --tool claude-code") for c in cmds))
        self.assertTrue(any(h["command"].endswith("gate --tool claude-code") for g in d["hooks"]["Stop"] for h in g["hooks"]))
        self.assertEqual(d["x"], 1)

    def test_import_line_and_marker(self):
        wiring.install()
        text = open(self.path(".claude/CLAUDE.md")).read()
        self.assertIn("<!-- sisi:begin -->", text)
        self.assertIn("@" + paths.generated(), text)  # the generated rulebook, not the product's file
        self.assertNotIn("x\n", text.replace("@", ""))  # canon text is not copied

    def test_symlinks_and_conflicts(self):
        os.makedirs(self.path(".codex"))
        os.makedirs(self.path(".config", "opencode"))
        self.put(".config/opencode/AGENTS.md", b"mine\n")
        rc, notes = wiring.install()
        self.assertTrue(os.path.islink(self.path(".codex/AGENTS.md")))
        self.assertEqual(open(self.path(".config/opencode/AGENTS.md"), "rb").read(), b"mine\n")
        self.assertTrue(any("not touched" in n for n in notes))
        self.assertTrue(os.path.islink(self.path(".agents/skills/alpha")))
        self.assertTrue(os.path.islink(self.path(".local/bin/sisi")))
        st = {r["tool"]: r["status"] for r in wiring.doctor()}
        self.assertEqual((st["codex"], st["opencode"], st["muse"]), ("wired", "not wired", "not wired"))
        wiring.uninstall()
        self.assertEqual(open(self.path(".config/opencode/AGENTS.md"), "rb").read(), b"mine\n")
        self.assertFalse(os.path.lexists(self.path(".codex/AGENTS.md")))

    def test_invalid_settings_left_alone(self):
        self.put(".claude/settings.json", b"{ not json")
        rc, notes = wiring.install()
        self.assertEqual(rc, 1)
        self.assertEqual(open(self.path(".claude/settings.json"), "rb").read(), b"{ not json")

    def test_backups_made_in_personal_data(self):
        self.put(".claude/CLAUDE.md", b"orig")
        self.put(".claude/settings.json", b"{}")
        wiring.install()
        names = os.listdir(os.path.join(self.data, "install", "backups"))
        self.assertEqual(len(names), 2)

    def test_doctor_not_wired_then_wired(self):
        self.assertEqual(wiring.doctor()[0]["status"], "not wired")
        wiring.install()
        r = wiring.doctor()[0]
        self.assertEqual((r["status"], r["blocking_hook"]), ("wired", "yes (Stop)"))

    def test_uninstall_after_user_edit_keeps_edit(self):
        self.put(".claude/settings.json", b'{"a": 1}\n')
        wiring.install()
        p = self.path(".claude/settings.json")
        d = json.load(open(p)); d["b"] = 2
        json.dump(d, open(p, "w"), indent=2)
        wiring.uninstall()
        self.assertEqual(json.load(open(p)), {"a": 1, "b": 2})

    def test_cli_install_uses_overridden_home_only(self):
        r = self.sisi("install")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.islink(self.path(".local/bin/sisi")))
        r = self.sisi("doctor")
        self.assertIn("claude-code", r.stdout)
        self.assertEqual(self.sisi("uninstall").returncode, 0)


class WatchHookTests(WiringBase):
    def test_watch_hooks_registered_for_every_tool_and_removed(self):
        """R-7.1-1: the tool hooks carry no matcher, so the meter sees every tool, not only the shell."""
        before = snapshot(self.home)
        wiring.install()
        d = json.load(open(self.path(".claude/settings.json")))
        for ev in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
            groups = d["hooks"][ev]
            cmds = [h["command"] for g in groups for h in g["hooks"]]
            self.assertTrue(any("watch --tool claude-code" in c for c in cmds), (ev, cmds))
            self.assertFalse(any(g.get("matcher") for g in groups), (ev, groups))
        self.assertEqual(wiring.doctor()[0]["status"], "wired")
        snap = snapshot(self.home)
        wiring.install()
        self.assertEqual(snapshot(self.home), snap)  # idempotent
        wiring.uninstall()
        self.assertEqual(snapshot(self.home), before)  # removed exactly


class SubagentHookTests(WiringBase):
    def test_subagent_stop_registered_idempotent_and_removed(self):
        before = snapshot(self.home)
        wiring.install()
        d = json.load(open(self.path(".claude/settings.json")))
        cmds = [h["command"] for g in d["hooks"]["SubagentStop"] for h in g["hooks"]]
        self.assertEqual(len(cmds), 1)
        self.assertIn("gate --subagent --tool claude-code", cmds[0])
        self.assertEqual(len(d["hooks"]["Stop"]), 1)  # the Stop hook is not duplicated by the subagent one
        snap = snapshot(self.home)
        wiring.install()
        self.assertEqual(snapshot(self.home), snap)
        wiring.uninstall()
        self.assertEqual(snapshot(self.home), before)

    def test_doctor_notices_a_missing_subagent_hook(self):
        wiring.install()
        p = self.path(".claude/settings.json")
        d = json.load(open(p))
        del d["hooks"]["SubagentStop"]
        json.dump(d, open(p, "w"))
        r = wiring.doctor()[0]
        self.assertEqual(r["status"], "not wired")
        self.assertIn("subagent hook", r["detail"])
        self.assertIn("subagent hook", wiring.quick_problem())
        wiring.install()  # repairs it
        self.assertEqual(wiring.doctor()[0]["status"], "wired")


class WiringSafetyTests(WiringBase):
    def test_symlinked_settings_and_claude_md_written_through(self):
        real = os.path.join(self.tmp, "dotfiles")
        os.makedirs(real)
        for name, data in (("settings.json", b'{\n  "a": 1\n}\n'), ("CLAUDE.md", b"mine")):
            with open(os.path.join(real, name), "wb") as f:
                f.write(data)
            os.symlink(os.path.join(real, name), self.path(".claude", name))
        wiring.install()
        for name in ("settings.json", "CLAUDE.md"):
            self.assertTrue(os.path.islink(self.path(".claude", name)), name + " link was replaced")
        self.assertIn(b"sisi:begin", open(os.path.join(real, "CLAUDE.md"), "rb").read())
        self.assertIn(b"sisi", open(os.path.join(real, "settings.json"), "rb").read())
        wiring.uninstall()
        for name in ("settings.json", "CLAUDE.md"):
            self.assertTrue(os.path.islink(self.path(".claude", name)))
        self.assertEqual(open(os.path.join(real, "CLAUDE.md"), "rb").read(), b"mine")
        self.assertEqual(open(os.path.join(real, "settings.json"), "rb").read(), b'{\n  "a": 1\n}\n')

    def test_dangling_symlink_refused_and_nothing_changed(self):
        os.symlink(os.path.join(self.tmp, "nowhere"), self.path(".claude", "settings.json"))
        before = snapshot(self.home)
        rc, notes = wiring.install()
        self.assertEqual(rc, 1)
        self.assertEqual(snapshot(self.home), before)

    def test_invalid_settings_changes_nothing_at_all(self):
        os.makedirs(self.path(".codex"))
        self.put(".claude/settings.json", b"{ not json")
        self.put(".claude/CLAUDE.md", b"keep\n")
        before, st = snapshot(self.home), self.state_snapshot()
        r = self.sisi("install")
        self.assertEqual(r.returncode, 1)
        self.assertIn("nothing was changed", r.stdout)
        self.assertEqual(snapshot(self.home), before)  # no CLAUDE.md edit, no codex link, no ~/.local/bin
        self.assertEqual(self.state_snapshot(), st)  # no manifest or backups

    def test_unwritable_target_changes_nothing(self):
        self.put(".claude/settings.json", b"{}\n")
        os.chmod(self.path(".claude/settings.json"), 0o444)
        os.chmod(self.path(".claude"), 0o555)
        self.addCleanup(os.chmod, self.path(".claude"), 0o755)
        if os.access(self.path(".claude/settings.json"), os.W_OK):
            self.skipTest("running as a user that ignores permissions")
        before = snapshot(self.home)
        rc, _ = wiring.install()
        self.assertEqual(rc, 1)
        self.assertEqual(snapshot(self.home), before)

    def test_hook_command_path_with_spaces(self):
        repo = os.path.join(self.tmp, "my repo", "sisi")
        shutil.copytree(REPO, repo, ignore=shutil.ignore_patterns(".git", "__pycache__", "tests"))
        paths.REPO = repo
        wiring.install()
        d = json.load(open(self.path(".claude/settings.json")))
        cmd = d["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertIn("'", cmd)  # quoted
        snap = snapshot(self.home)
        wiring.install()  # still recognised as ours: no duplicate entries
        self.assertEqual(snapshot(self.home), snap)
        self.assertEqual(wiring.doctor()[0]["status"], "wired")
        # the command string really runs under a shell
        import subprocess
        r = subprocess.run(cmd, shell=True, input=json.dumps({"session_id": "s", "cwd": self.proj}),
                           capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        wiring.uninstall()
        self.assertFalse(os.path.exists(self.path(".claude/settings.json")))  # it did not exist before install


if __name__ == "__main__":
    unittest.main()
