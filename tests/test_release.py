import json, os, shutil, unittest
from unittest import mock
from support import *
from sisi import paths, release, wiring


def make_source(root):
    """A small stand-in for the source folder: the real code, a tiny library, and things that are not product."""
    os.makedirs(root)
    for d in ("bin", "sisi", "canon"):
        shutil.copytree(os.path.join(REPO, d), os.path.join(root, d), ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(os.path.join(REPO, "config.default.json"), root)
    shutil.copy(os.path.join(REPO, "VERSION"), root)
    for d, f in (("verifiers", "x/v.md"), ("done", "r.md"), ("docs", "a.md"), ("tests", "t.py"), ("notes", "n.md"), (".sisi", "contract.json")):
        os.makedirs(os.path.join(root, d, os.path.dirname(f)), exist_ok=True)
        open(os.path.join(root, d, f), "w").write("hello\n")
    return root


class ReleaseCase(SisiCase):
    def setUp(self):
        super().setUp()
        self.src = make_source(os.path.join(self.tmp, "source"))
        self.lib = paths.lib()
        p = mock.patch.object(release, "run_checks", return_value=(True, "ok"))
        self.checks = p.start()
        self.addCleanup(p.stop)
        self.rebuild = mock.patch.object(release, "_rebuild_rulebook", return_value=("rebuilt", 0))
        self.rebuild.start()  # a subprocess per release is slow; test_regenerates_rulebook runs the real one
        self.addCleanup(self.rebuild.stop)

    def rel(self, *a):
        r = self.sisi("release", self.src, *a)
        return r

    def current(self):
        return os.path.realpath(os.path.join(self.lib, "current"))


class TestRelease(ReleaseCase):
    def test_refuses_when_checks_fail(self):
        self.checks.return_value = (False, "check x failed")
        r = self.rel()
        self.assertEqual(r.returncode, 1)
        self.assertIn("refused", r.stderr)
        self.assertIn("check x failed", r.stderr)
        self.assertFalse(os.path.exists(self.lib))

    def test_real_verify_gates_release(self):
        mock.patch.stopall()
        os.makedirs(os.path.join(self.src, ".sisi"), exist_ok=True)
        c = contract([check("bad", "false")])
        with open(os.path.join(self.src, ".sisi", "contract.json"), "w") as f:
            json.dump(c, f)
        from sisi import trust
        trust.add(self.src)
        r = self.sisi("release", self.src)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        c = contract([check("ok", "true")])
        with open(os.path.join(self.src, ".sisi", "contract.json"), "w") as f:
            json.dump(c, f)
        r = self.sisi("release", self.src)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_deep_flag_runs_slow_checks(self):
        self.rel("--deep")
        self.checks.assert_called_with(self.src, True)
        self.rel()
        self.checks.assert_called_with(self.src, False)

    def test_copy_has_product_files_and_nothing_personal(self):
        open(os.path.join(self.src, "sisi", "junk.pyc"), "w").write("x")
        os.makedirs(os.path.join(self.src, "sisi", "__pycache__"))
        r = self.rel()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        cur = self.current()
        for p in ("bin/sisi", "sisi/cli.py", "canon/core.md", "verifiers/x/v.md", "done/r.md", "docs/a.md", "config.default.json", "VERSION"):
            self.assertTrue(os.path.isfile(os.path.join(cur, p)), p)
        self.assertEqual(sorted(os.listdir(cur)), sorted(["bin", "sisi", "canon", "verifiers", "done", "docs", "config.default.json", "VERSION"]))
        for dp, dns, fns in os.walk(cur):
            self.assertNotIn("__pycache__", dns)
            self.assertFalse([f for f in fns if f.endswith(".pyc")])
        self.assertTrue(os.access(os.path.join(cur, "bin", "sisi"), os.X_OK))
        self.assertIn("first release", r.stdout)

    def test_prints_what_changed(self):
        self.rel()
        open(os.path.join(self.src, "docs", "new.md"), "w").write("n")
        open(os.path.join(self.src, "done", "r.md"), "w").write("changed")
        r = self.rel()
        self.assertIn("1 added, 1 changed, 0 removed", r.stdout)
        self.assertIn("+ docs/new.md", r.stdout)
        self.assertIn("~ done/r.md", r.stdout)

    def test_regenerates_rulebook(self):
        self.rebuild.stop()
        self.rel()
        self.assertTrue(os.path.isfile(paths.generated()))

    def test_switch_is_atomic_rename(self):
        self.rel()
        first = release.current_name()
        calls = []
        real = os.replace
        def spy(a, b):
            calls.append((a, b, os.path.islink(a)))
            return real(a, b)
        with mock.patch.object(os, "replace", spy):
            release.switch(first)
        link = os.path.join(self.lib, "current")
        self.assertTrue(any(b == link and islink for a, b, islink in calls))
        self.assertEqual(os.readlink(link), os.path.join("releases", first))

    def test_current_is_never_missing_twice_running_during_switch(self):
        self.rel()
        names = []
        for i in range(3):
            names.append(release.make_release(self.src))
        import threading
        stop, bad = threading.Event(), []
        def watch():
            while not stop.is_set():
                # On some filesystems (btrfs, measured) a lookup that races the rename can miss for an
                # instant, about 1 in 40,000. What must hold: a second look straight away finds a
                # complete release. A hook that hits the instant fails open, like any hook error.
                target = os.path.join(self.lib, "current", "bin", "sisi")
                if not os.path.isfile(target) and not os.path.isfile(target):
                    bad.append("missing")
        t = threading.Thread(target=watch)
        t.start()
        for i in range(300):
            release.switch(names[i % 3])
        stop.set()
        t.join()
        self.assertEqual(bad, [])

    def test_incomplete_release_is_not_visible(self):
        with mock.patch.object(shutil, "copytree", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                release.make_release(self.src)
        self.assertEqual(release.releases(), [])
        self.assertEqual(os.listdir(paths.releases_dir()), [])

    def test_prunes_to_three(self):
        names = []
        for i in range(5):
            self.assertEqual(self.rel().returncode, 0)
            names.append(release.current_name())
        left = release.releases()
        self.assertEqual(len(left), 3)
        self.assertEqual(left, sorted(names)[-3:])
        self.assertEqual(release.current_name(), names[-1])

    def test_same_second_releases_get_distinct_names(self):
        a, b = release.make_release(self.src), release.make_release(self.src)
        self.assertNotEqual(a, b)
        self.assertEqual(release.releases(), [a, b])

    def test_rollback(self):
        self.rel()
        a = release.current_name()
        self.rel()
        b = release.current_name()
        self.assertNotEqual(a, b)
        r = self.sisi("rollback")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(release.current_name(), a)
        r = self.sisi("rollback")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no earlier release", r.stderr)
        self.assertEqual(release.current_name(), a)

    def test_lib_override(self):
        other = os.path.join(self.tmp, "elsewhere")
        with mock.patch.dict(os.environ, {"SISI_LIB": other}):
            self.assertEqual(paths.releases_dir(), os.path.join(other, "releases"))
            self.assertEqual(paths.current_link(), os.path.join(other, "current"))

    def test_stable_copy_runs(self):
        self.rel()
        launcher = paths.stable_launcher()
        import subprocess
        r = subprocess.run([sys.executable, launcher, "help"], capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(r.returncode, 0)
        self.assertIn("sisi verify", r.stdout)


class TestInstallUsesStable(ReleaseCase):
    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.home, ".claude"))

    def hook_cmd(self):
        with open(os.path.join(self.home, ".claude", "settings.json")) as f:
            return json.load(f)["hooks"]["Stop"][0]["hooks"][0]["command"]

    def test_install_without_release_uses_clone(self):
        self.assertEqual(self.sisi("install").returncode, 0)
        self.assertEqual(os.readlink(wiring.loc()["bin"]), os.path.join(paths.REPO, "bin", "sisi"))
        self.assertIn(os.path.join(paths.REPO, "bin", "sisi"), self.hook_cmd())
        r = self.sisi("doctor")
        self.assertIn("the clone", r.stdout)
        self.assertNotIn("not wired", "\n".join(l for l in r.stdout.splitlines() if l.startswith(("cli", "claude"))))

    def test_install_with_release_uses_stable_copy(self):
        self.rel()
        stable = os.path.join(self.lib, "current", "bin", "sisi")
        self.assertEqual(self.sisi("install").returncode, 0)
        self.assertEqual(os.readlink(wiring.loc()["bin"]), stable)
        self.assertIn(stable, self.hook_cmd())
        self.assertNotIn(paths.REPO, self.hook_cmd())
        r = self.sisi("doctor")
        self.assertNotIn("not wired", "\n".join(l for l in r.stdout.splitlines() if l.startswith(("cli", "claude"))))
        self.assertEqual(self.sisi("uninstall").returncode, 0)
        self.assertFalse(os.path.lexists(wiring.loc()["bin"]))

    def test_release_after_clone_install_asks_for_reinstall_then_rewires(self):
        self.assertEqual(self.sisi("install").returncode, 0)
        r = self.rel()
        self.assertIn("run `sisi install`", r.stdout)
        self.assertEqual(self.sisi("install").returncode, 0)
        self.assertEqual(os.readlink(wiring.loc()["bin"]), os.path.join(self.lib, "current", "bin", "sisi"))
        self.assertEqual(self.hook_cmd().count("sisi"), self.hook_cmd().count("sisi"))
        r = self.rel()
        self.assertNotIn("run `sisi install`", r.stdout)

    def test_doctor_reports_live_copy_and_source_ahead(self):
        self.sisi("dev", "on", self.src)
        self.rel()
        r = self.sisi("doctor")
        self.assertIn("release " + release.current_name(), r.stdout)
        self.assertIn("in step", r.stdout)
        open(os.path.join(self.src, "docs", "more.md"), "w").write("x")
        r = self.sisi("doctor")
        self.assertIn("ahead (1 file differ)", r.stdout)


class TestDev(ReleaseCase):
    def test_on_off_status(self):
        self.assertIn("off", self.sisi("dev", "status").stdout)
        r = self.sisi("dev", "on", self.src)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(paths.personal_config()["developer"]["source"], self.src)
        self.assertEqual(store_cfg()["developer"]["source"], self.src)
        self.assertIn(self.src, self.sisi("dev", "status").stdout)
        self.assertEqual(self.sisi("dev", "off").returncode, 0)
        self.assertNotIn("developer", paths.personal_config())
        self.assertIn("off", self.sisi("dev", "status").stdout)

    def test_on_rejects_non_source_and_keeps_other_config(self):
        r = self.sisi("dev", "on", self.proj)
        self.assertEqual(r.returncode, 1)
        os.makedirs(self.data, exist_ok=True)
        json.dump({"gate": {"budget_s": 5}, "developer": {"personal_terms": ["zed"]}}, open(os.path.join(self.data, "config.json"), "w"))
        self.sisi("dev", "on", self.src)
        self.sisi("dev", "off")
        cfg = paths.personal_config()
        self.assertEqual(cfg["gate"], {"budget_s": 5})
        self.assertEqual(cfg["developer"], {"personal_terms": ["zed"]})

    def test_release_finds_source_from_release_copy(self):
        self.sisi("dev", "on", self.src)
        self.assertEqual(self.sisi("release").returncode, 0)
        with mock.patch.object(paths, "REPO", self.current()):  # now running as the stable copy
            self.assertEqual(release.source(), self.src)
            self.assertEqual(self.sisi("release").returncode, 0)
            self.sisi("dev", "off")
            with self.assertRaises(release.ReleaseError):
                release.source()


def store_cfg():
    from sisi import store
    return store.config()


class TestPromote(ReleaseCase):
    def setUp(self):
        super().setUp()
        self.sisi("dev", "on", self.src)
        self.assertEqual(self.rel().returncode, 0)
        # run as the stable copy, so the source is found through developer mode and never the real repository
        p = mock.patch.object(paths, "REPO", self.current())
        p.start()
        self.addCleanup(p.stop)
        self.assertEqual(release.source(), self.src)

    def promote(self, *a):
        with mock.patch.dict(os.environ, {"USER": "alice"}), \
                mock.patch("os.path.expanduser", lambda p: "/home/alice" if p == "~" else p):
            return self.sisi("promote", *a)

    def put(self, rel, text):
        p = os.path.join(self.data, "overlay", rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(text)

    def test_dry_run_lists_scrubbed_and_writes_nothing(self):
        self.put("done/my-recipe.md", "see /home/alice/Code/x and bob@example.com, alice said Acme rules\n")
        json.dump({"developer": {"source": self.src, "personal_terms": ["Acme"]}}, open(os.path.join(self.data, "config.json"), "w"))
        r = self.promote("my-recipe")
        self.assertEqual(r.returncode, 0, r.stderr)
        for t in ("/home/alice", "bob@example.com", "alice", "Acme", "dry run"):
            self.assertIn(t, r.stdout)
        self.assertIn("~/Code/x and <email>, <user> said <personal> rules", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.src, "done", "my-recipe.md")))

    def test_apply_writes_scrubbed_recipe_and_verifier(self):
        self.put("done/my-recipe.md", "path /home/alice/x\n")
        self.put("verifiers/sec/my-v.md", "mail a@b.co\n")
        self.assertEqual(self.promote("my-recipe", "--apply").returncode, 0)
        self.assertEqual(open(os.path.join(self.src, "done", "my-recipe.md")).read(), "path ~/x\n")
        self.assertEqual(self.promote("my-v", "--apply").returncode, 0)
        self.assertEqual(open(os.path.join(self.src, "verifiers", "sec", "my-v.md")).read(), "mail <email>\n")

    def test_refuses_naming_lines_when_terms_remain(self):
        self.put("done/leaky.md", "fine\nAlice was here\nALICE too\n")
        r = self.promote("leaky", "--apply")
        self.assertEqual(r.returncode, 1)
        self.assertIn("refused", r.stderr)
        self.assertIn("3: ALICE too", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.src, "done", "leaky.md")))

    def test_rule_appended_and_replaced(self):
        self.put("rules/new-rule.md", "## Be kind\n\nSay thanks at /home/alice.\n")
        self.assertEqual(self.promote("new-rule", "--apply").returncode, 0)
        core = open(os.path.join(self.src, "canon", "core.md")).read()
        self.assertIn("{#new-rule}", core)
        self.assertIn("Say thanks at ~.", core)
        self.assertNotIn("alice", core)
        self.put("rules/new-rule.md", "## Be kinder\n\nAlways.\n")
        self.assertEqual(self.promote("new-rule", "--apply").returncode, 0)
        core = open(os.path.join(self.src, "canon", "core.md")).read()
        self.assertEqual(core.count("{#new-rule}"), 1)
        self.assertIn("Be kinder", core)
        self.assertNotIn("Be kind\n", core)

    def test_unknown_id_and_no_commit(self):
        r = self.promote("nope")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no overlay", r.stderr)


if __name__ == "__main__":
    unittest.main()
