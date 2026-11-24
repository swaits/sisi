"""The two loops, end to end, through the real command in a temporary home.

Learning: work is done, the retro is forced, its improvement is a rule in the next session, the rules are
organized and the change can be undone. Delegation: the lead is stopped when it should be delegating, and the
models table is researched, read and kept fresh."""
import glob, hashlib, json, os, shutil, subprocess, sys, tempfile, time, unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAP = ("--gap", "the export dropped rows with empty names until the person noticed",
       "--cause", "no check compared the row counts before and after")


class Core(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sisi-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.data = os.path.join(self.tmp, "data")
        self.env = dict(os.environ, HOME=self.tmp, SISI_DATA=self.data, SISI_STATE=os.path.join(self.tmp, "state"),
                        SISI_LIB=os.path.join(self.tmp, "lib"), CLAUDE_CONFIG_DIR=os.path.join(self.tmp, "claude"))
        for name in ("SISI_SESSION_ID", "CLAUDE_ENV_FILE"):
            self.env.pop(name, None)
        self.proj = self.project("alpha")

    def project(self, name):
        path = os.path.join(self.tmp, name)
        os.makedirs(path)
        for args in (["init", "-q"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "start"]):
            subprocess.run(["git"] + args, cwd=path, check=True, capture_output=True)
        return path

    def sisi(self, *args, cwd=None, sid=None, stdin=""):
        env = dict(self.env, SISI_SESSION_ID=sid) if sid else self.env
        r = subprocess.run([sys.executable, os.path.join(REPO, "bin", "sisi")] + list(args), cwd=cwd or self.proj,
                           env=env, input=stdin, capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr

    def hook(self, name, sid="s1", cwd=None, **fields):
        return self.sisi(name, stdin=json.dumps(dict(fields, session_id=sid, cwd=cwd or self.proj)))

    def tool(self, name, sid="s1", **fields):
        return self.hook("watch", sid=sid, hook_event_name="PreToolUse", tool_name=name, **fields)

    def read(self, *parts):
        with open(os.path.join(*parts), encoding="utf-8") as f:
            return f.read()

    def write(self, path, text):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    # the learning loop

    def test_a_retro_is_forced_and_its_improvement_becomes_a_rule(self):
        self.hook("tick")
        self.hook("prompt", prompt="add the export")
        self.assertEqual(self.hook("gate")[1], "")                       # nothing changed: nothing is asked
        self.tool("Edit")
        self.assertIn('"block"', self.hook("gate")[1])                   # work was done: the retro is forced
        report = self.sisi("retro", sid="s1")[1]
        self.assertIn("The objective: In this order: stay inside the lines", report)
        self.assertIn("you made 1 tool call(s) yourself", report)
        rc, out, _ = self.sisi("retro", *GAP, "--improve", "Compare row counts before and after every export change", sid="s1")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.hook("gate")[1], "")                       # held: the turn may end
        self.assertIn("Compare row counts", self.hook("tick", sid="s2")[1])                         # next session here
        self.assertNotIn("Compare row counts", self.hook("tick", sid="s3", cwd=self.project("beta"))[1])  # not elsewhere
        self.sisi("retro", *GAP, "--improve", "Ask one question with options, never three open ones", "--scope", "user", sid="s1")
        book = self.read(self.data, "generated", "core.md")
        self.assertIn("## 8. Close with a retro", book)
        self.assertIn("## Learned here", book)
        self.assertIn("Ask one question with options", book)             # for all projects: in the rulebook itself
        self.assertEqual(len(self.read(self.data, "retro.jsonl").splitlines()), 2)

    def test_a_retro_needs_real_sentences_and_no_gap_needs_its_evidence(self):
        self.hook("tick")
        self.tool("Write")
        for args in (["--gap", "bad"], ["--no-gap", "fine"], GAP + ("--improve", "be careful"), ["--later", "x"],
                     GAP + ("--improve", "Compare the row counts every time", "--scope", "everyone")):
            self.assertEqual(self.sisi("retro", *args, sid="s1")[0], 1, args)
        self.assertIn('"block"', self.hook("gate")[1])
        self.assertEqual(self.sisi("retro", "--no-gap", "the person accepted it first time and every check passed", sid="s1")[0], 0)
        self.assertEqual(self.hook("gate")[1], "")

    def test_later_lets_unfinished_work_pause_until_it_changes_again(self):
        self.hook("tick")
        self.hook("prompt", prompt="start")
        self.tool("Write")
        self.assertEqual(self.sisi("retro", "--later", "the person's answer about the format", sid="s1")[0], 0)
        self.assertEqual(self.hook("gate")[1], "")
        self.write(os.path.join(self.proj, "new.txt"), "a worker or a shell command changed the tree")
        self.hook("prompt", prompt="go on")
        self.assertIn('"block"', self.hook("gate")[1])
        self.assertIn('"block"', self.hook("gate")[1])
        self.assertEqual(self.hook("gate")[1], "")                       # never stuck: the third stop goes through

    def test_a_secret_never_reaches_a_rule(self):
        self.hook("tick")
        self.sisi("retro", "--gap", "the deploy failed because the key was pasted wrong", "--cause", "the key was typed by hand each time",
                  "--improve", "Read the deploy key from the keyring, never paste api_key=sk-abcdefghijklmnopqrstuvwx into a command", sid="s1")
        stored = "".join(self.read(p) for p in glob.glob(os.path.join(self.data, "**", "*.*"), recursive=True))
        self.assertIn("Read the deploy key from the keyring", stored)
        self.assertIn("<redacted>", stored)
        self.assertNotIn("sk-abcdefghijklmnop", stored)

    def test_rules_are_organized_by_a_worker_and_the_change_can_be_undone(self):
        for i in range(9):
            self.assertEqual(self.sisi("learn", "--project", "Always run the map tests number %d before a commit" % i)[0], 0)
        self.assertIn("need organizing", self.hook("tick")[1])
        brief = self.sisi("rules", "organize")[1]
        self.assertIn("map tests number 8", brief)
        self.assertIn("at most 30 lines", brief)
        path = glob.glob(os.path.join(self.data, "rules", "projects", "*.md"))[0]
        before = self.read(path)
        answer = os.path.join(self.tmp, "answer.md")
        for bad in ("no sections at all", "## user\n## project\n" + "- one more rule\n" * 31, "## user\n## project\n"):
            self.assertEqual(self.sisi("rules", "organize", "--record", self.write(answer, bad))[0], 1, bad[:20])
            self.assertEqual(self.read(path), before)
        self.write(answer, "## user\n- Work from the checklist the person gave [owner 2026-01-01]\n"
                           "## project\n- Run the map tests before a commit [owner 2026-01-01]\n")
        self.assertEqual(self.sisi("rules", "organize", "--record", answer)[0], 0)
        self.assertEqual(self.read(path), "- Run the map tests before a commit [owner 2026-01-01]\n")
        self.assertIn("Work from the checklist", self.read(self.data, "generated", "core.md"))
        self.assertNotIn("need organizing", self.hook("tick", sid="s2")[1])
        self.assertIn("Run the map tests", self.sisi("rules")[1])
        self.assertEqual(self.sisi("rules", "revert")[0], 0)
        self.assertEqual(self.read(path), before)
        self.assertNotIn("Work from the checklist", self.read(self.data, "generated", "core.md"))

    # delegation

    def test_the_lead_is_stopped_when_it_should_be_delegating(self):
        self.hook("tick")
        self.hook("prompt", prompt="build it")
        for _ in range(8):
            self.assertEqual(self.tool("Read")[0], 0)
        rc, _, err = self.tool("Bash", tool_input={"command": "grep -r x ."})
        self.assertEqual(rc, 2)
        self.assertIn("Delegate the rest", err)
        self.assertEqual(self.tool("Agent")[0], 0)                                           # delegating is never refused
        self.assertEqual(self.tool("mcp__host__delegate_task")[0], 0)
        self.assertEqual(self.tool("Bash", tool_input={"command": "sisi models"})[0], 0)    # nor is sisi itself
        self.assertEqual(self.tool("Bash", tool_input={"command": "sisi models; rm -rf x"})[0], 2)
        self.assertEqual(self.tool("AskUserQuestion")[0], 0)
        self.assertEqual(self.sisi("direct", "merging", sid="s1")[0], 1)                    # a reason, not a word
        self.assertEqual(self.sisi("direct", "merging the worker's branch is one command", sid="s1")[0], 0)
        self.assertEqual(self.tool("Bash", tool_input={"command": "git merge w"})[0], 0)
        report = self.sisi("retro", sid="s1")[1]
        self.assertIn("merging the worker's branch", report)                                # the reason is in the retro
        self.assertIn("9 tool call(s) yourself and 2 delegation(s)", report)
        self.hook("prompt", prompt="next")
        self.assertEqual(self.tool("Read")[0], 0)                                           # a new turn counts afresh

    def test_workers_and_subagents_are_left_alone(self):
        self.hook("tick", sid="w")
        self.hook("prompt", sid="w", prompt="Context the host adds.\n\nYou are a worker. Do this task yourself; do not delegate it further.")
        for _ in range(20):
            self.assertEqual(self.tool("Edit", sid="w")[0], 0)
        self.assertEqual(self.hook("gate", sid="w")[1], "")
        self.hook("tick")
        self.hook("prompt", prompt="lead work")
        for _ in range(20):
            self.assertEqual(self.tool("Read", agent_id="a1")[0], 0)                         # the host's own subagent
        self.assertEqual(self.sisi("gate", "--subagent", stdin=json.dumps({"session_id": "s1", "cwd": self.proj}))[1], "")

    def test_the_models_table_is_researched_recorded_and_goes_stale(self):
        self.assertIn("no models table yet", self.hook("tick")[1])
        self.sisi("learn", "Only the cheapest models on the shared plan")
        brief = self.sisi("models", "research")[1]
        self.assertIn("Fallback order:", brief)
        self.assertIn("Only the cheapest models on the shared plan", brief)                 # the person's words bind the researcher
        answer = os.path.join(self.tmp, "table.md")
        self.assertEqual(self.sisi("models", "research", "--record", self.write(answer, "a few words of prose"))[0], 1)
        self.write(answer, "| worker | how to call it | use for | cost | good at, bad at | notes |\n|---|---|---|---|---|---|\n"
                           "| small | host subagent `small` | routine | flat | fast; weak at design | |\n"
                           "Fallback order: routine: small, then the lead.\n")
        self.assertEqual(self.sisi("models", "research", "--record", answer)[0], 0)
        self.assertIn("| small |", self.sisi("models")[1])
        self.assertNotIn("models table", self.hook("tick", sid="s2")[1])
        self.assertEqual(self.sisi("judge", "small", "good", "fixed the bug in one pass")[0], 0)
        self.assertIn("fixed the bug in one pass", self.sisi("models")[1])
        self.assertIn("fixed the bug in one pass", self.sisi("models", "research")[1])      # and informs the next research
        old = time.time() - 9 * 86400
        os.utime(os.path.join(self.data, "models.md"), (old, old))
        self.assertIn("9 days old", self.hook("tick", sid="s3")[1])

    # setting up

    def test_install_adds_the_hooks_once_and_keeps_the_rest(self):
        folder = self.env["CLAUDE_CONFIG_DIR"]
        os.makedirs(folder)
        spath = self.write(os.path.join(folder, "settings.json"),
                           json.dumps({"model": "x", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other"}]}]}}))
        self.assertEqual(self.sisi("install")[0], 0)
        first = self.read(spath)
        self.assertEqual(self.sisi("install")[0], 0)
        self.assertEqual(self.read(spath), first)
        settings = json.loads(first)
        self.assertEqual(settings["model"], "x")
        self.assertEqual(len(settings["hooks"]["Stop"]), 2)
        self.assertEqual(sorted(settings["hooks"]), ["PreToolUse", "SessionStart", "Stop", "UserPromptSubmit"])
        self.assertEqual(self.read(folder, "CLAUDE.md").count("generated/core.md"), 1)
        self.assertNotIn("MISSING", self.sisi("doctor")[1])
        self.write(spath, "{broken")
        self.assertEqual(self.sisi("install")[0], 1)
        self.assertEqual(self.read(spath), "{broken")

    def test_rollback_goes_to_the_release_before(self):
        lib = self.env["SISI_LIB"]
        for name in ("20260101T000000Z", "20260102T000000Z"):
            os.makedirs(os.path.join(lib, "releases", name, "bin"))
            os.chmod(self.write(os.path.join(lib, "releases", name, "bin", "sisi"), "#!/bin/sh\nexit 0\n"), 0o755)
        os.symlink(os.path.join(lib, "releases", "20260102T000000Z"), os.path.join(lib, "current"))
        self.assertEqual(self.sisi("rollback")[0], 0)
        self.assertTrue(os.path.realpath(os.path.join(lib, "current")).endswith("20260101T000000Z"))
        self.assertEqual(self.sisi("rollback")[0], 1)

    def test_a_hook_never_breaks_the_session(self):
        for name in ("tick", "prompt", "watch", "gate"):
            self.assertEqual(self.sisi(name, stdin="not json")[0], 0, name)
            self.assertEqual(self.sisi(name, stdin=json.dumps({"session_id": "s1", "cwd": "/no/such/place"}))[0], 0, name)

    # the standing constraints

    def test_the_spec_is_unchanged(self):
        for line in self.read(REPO, "docs", "spec", "SHA256SUMS").splitlines():
            digest, rel = line.split()
            with open(os.path.join(REPO, rel), "rb") as f:
                self.assertEqual(hashlib.sha256(f.read()).hexdigest(), digest, rel)

    def test_the_product_stays_small(self):
        code = sum(len(self.read(p).splitlines()) for p in glob.glob(os.path.join(REPO, "sisi", "*.py")))
        self.assertLess(code, 1200, "sisi is two loops. If it needs more than this, find the simpler shape.")
        rulebook = self.read(REPO, "canon", "core.md")
        self.assertLess(len(rulebook.splitlines()), 100)
        self.assertLess(len(rulebook), 7000)


if __name__ == "__main__":
    unittest.main()
