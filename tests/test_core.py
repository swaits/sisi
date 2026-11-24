"""The two loops, end to end, through the real command in a temporary home.

Learning: work is done, the retro is forced, its improvement is a rule in the next session, the rules are
organized and the change can be undone. Delegation: the lead is stopped when it should be delegating, and the
models table is researched, read and kept fresh."""
import glob, hashlib, json, os, random, shutil, subprocess, sys, tempfile, time, unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAP = ("--gap", "the export dropped rows with empty names until the person noticed",
       "--cause", "no check compared the row counts before and after")


HEADER = "| worker | how to call it | use for | cost | good at, bad at | notes |\n|---|---|---|---|---|---|\n"
GOAL = ("--goal", "export every row without losing any with empty names", "--check", "row counts match before and after the export",
        "--check", "an empty name still exports as a row", "--next", "the person will want the same for imports: follow-up")
WORKERS = HEADER + (
    "| agy (Gemini) | `agy --print \"<brief>\"` | routine | free | fast | |\n"
    "| zai-coding-plan/glm-5.4 | `opencode run -m zai-coding-plan/glm-5.4 \"<brief>\"` | ordinary | flat | edits | the default |\n"
    "| sonnet (Sonnet 5.5) | host subagent model `sonnet` | hard | per use | everything | |\n")
FIXTURE = HEADER + (
    "| zai-coding-plan/glm-5.4 | `opencode run -m zai-coding-plan/glm-5.4 \"<brief>\"` | ordinary | flat | edits | |\n"
    "| zai-coding-plan/glm-5.3-flash | `opencode run -m zai-coding-plan/glm-5.3-flash \"<brief>\"` | ordinary | flat | cheap edits | |\n"
    "| muse/muse-wonder-1.0 | `muse exec --model muse-wonder-1.0 \"<brief>\"` | ordinary | flat | research | out until 2999-01-01 |\n"
    "| muse/muse-ember-1.0 | `muse exec --model muse-ember-1.0 \"<brief>\"` | ordinary | flat | checks | out until 2000-01-01 |\n"
    "| sonnet (Sonnet 5.5) | host subagent model `sonnet` | ordinary, hard | per use | everything | |\n"
    "| opus (Opus 5.5) | host subagent model `opus` | hard | per use | hardest | |\n")


def tree():
    """A fingerprint of the product tree, so a test that writes into it is caught."""
    out = hashlib.sha1()
    for p in sorted(glob.glob(os.path.join(REPO, "sisi", "*")) + glob.glob(os.path.join(REPO, "canon", "*"))):
        if os.path.isfile(p):
            with open(p, "rb") as f:
                out.update(p.encode() + f.read())
    return out.hexdigest()


class Core(unittest.TestCase):
    def setUp(self):
        before = tree()
        self.addCleanup(lambda: self.assertEqual(tree(), before, "a test wrote into the product tree"))
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

    def done(self, sid="s1", *extra):
        rc, out, _ = self.sisi("done", *(extra or GOAL), sid=sid)
        self.assertEqual(rc, 0, out)

    def table(self, text):
        self.write(os.path.join(self.data, "models.md"), text) if os.path.isdir(self.data) else (
            os.makedirs(self.data), self.write(os.path.join(self.data, "models.md"), text))

    def state(self, sid="s1"):
        return json.loads(self.read(self.tmp, "state", "core-sessions", sid + ".json"))

    def records(self):
        return [json.loads(l) for l in self.read(self.data, "retro.jsonl").splitlines()]

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
        self.done()
        self.tool("Edit")
        self.assertIn('"block"', self.hook("gate")[1])                   # work was done: the retro is forced
        report = self.sisi("retro", sid="s1")[1]
        self.assertIn("The objective: Maximize the long-term, verified value", report)
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
        self.done()
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
        self.done()
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
        self.done()
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

    # done, the wheel, the numbers

    def test_nothing_starts_before_done_is_recorded(self):
        self.table(WORKERS)
        self.hook("tick")
        self.hook("prompt", prompt="build it")
        rc, _, err = self.tool("Agent", tool_input={"model": "sonnet"})
        self.assertEqual((rc, "nothing starts before done is recorded" in err), (2, True))
        self.assertEqual(self.tool("Edit")[0], 2)
        self.assertEqual(self.tool("Write")[0], 2)
        self.assertEqual(self.tool("Workflow")[0], 2)
        self.assertEqual(self.tool("Read")[0], 0)
        self.assertEqual(self.tool("Bash", tool_input={"command": "sisi done"})[0], 0)
        for bad in (["--goal", "too short", "--check", "a check that can fail", "--next", "follow-up work later"],
                    ["--goal", "export every row without losing any", "--next", "follow-up work later"],
                    ["--pass", "1", "it worked"], ["--bogus"]):
            self.assertEqual(self.sisi("done", *bad, sid="s1")[0], 1, bad)
        rc, out, _ = self.sisi("done", *GOAL, sid="s1")
        self.assertEqual(rc, 0)
        self.assertIn("2. an empty name still exports as a row", out)
        self.assertEqual(self.tool("Edit")[0], 0)
        self.assertEqual(self.tool("Agent", tool_input={"model": "sonnet"})[0], 2)         # no pick yet
        self.assertEqual(self.sisi("pick", "hard", sid="s1")[0], 0)
        self.assertEqual(self.tool("Agent", tool_input={"model": "sonnet"})[0], 0)
        self.assertEqual(self.tool("Workflow")[0], 0)                                      # a workflow is not matched

    def test_the_gate_wants_a_verdict_for_every_check_then_closes_or_forces_the_retro(self):
        self.hook("tick")
        self.hook("prompt", prompt="go")
        self.done()
        self.tool("Edit")
        out = self.hook("gate")[1]
        self.assertIn("these checks have no verdict yet: 1. row counts match before and after export; 2. an empty", out.replace("the export", "export"))
        self.assertIn('"block"', self.hook("gate")[1])
        self.assertEqual(self.hook("gate")[1], "")                                         # at most two blocks, whatever the cause
        self.assertEqual(self.sisi("done", "--pass", "1", "counts equal at 120 rows", sid="s1")[0], 0)
        self.assertEqual(self.sisi("done", "--fail", "2", "the row was dropped", sid="s1")[0], 0)
        self.assertEqual(self.sisi("done", "--pass", "3", "no such check", sid="s1")[0], 1)
        self.hook("prompt", prompt="again")
        self.assertIn("no retro yet", self.hook("gate")[1])                                # changed and failed: the retro
        self.assertEqual(self.sisi("retro", "--no-gap", "the person accepted it first time and every check passed", sid="s1")[0], 1)
        self.assertEqual(self.sisi("retro", *GAP, "--improve", "Compare row counts before and after every export change", sid="s1")[0], 0)
        rec = self.records()[-1]
        self.assertEqual((rec["unit"]["checks_pass"], rec["unit"]["checks_fail"], rec["done"]["checks"][1]["verdict"]), (1, 1, "fail"))
        self.assertIn("without losing any", rec["goal"])
        self.assertNotIn("done", self.state())
        # nothing changed and every check passed: the gate closes the piece of work itself
        self.hook("prompt", prompt="and now")
        self.done("s1", "--goal", "list the empty names in the export", "--check", "each empty name appears once", "--next", "nothing: a one-off report")
        self.assertEqual(self.sisi("done", "--pass", "1", "listed 3 names once each", sid="s1")[0], 0)
        self.assertEqual(self.hook("gate")[1], "")
        self.assertEqual(len(self.records()), 2)
        self.assertEqual(self.records()[-1]["unit"]["checks_pass"], 1)
        self.assertNotIn("gap", self.records()[-1])
        self.assertNotIn("done", self.state())
        self.assertEqual(self.hook("gate")[1], "")
        self.assertEqual(len(self.records()), 2)                                           # closed once

    def test_the_wheel_gives_only_what_is_in_and_follows_table_order(self):
        sys.path.insert(0, REPO)
        from sisi import models
        name = lambda r: r[0].split()[0].lower()
        for _ in range(300):
            self.assertNotIn("muse-wonder", name(models.choose(FIXTURE, "ordinary", rand=random.random)))   # out until 2999
            self.assertNotEqual(name(models.choose(FIXTURE, "ordinary", skip=["zai-coding-plan/glm-5.4"], rand=random.random)), "zai-coding-plan/glm-5.4")
            self.assertNotIn("glm", name(models.choose(FIXTURE, "ordinary", review="zai-coding-plan/glm-5.4", rand=random.random)))
            self.assertIsNone(models.choose(FIXTURE, "hard", review="sonnet", rand=random.random))     # both are claude
        picked = lambda x: name(models.choose(FIXTURE, "ordinary", rand=lambda: x))
        # four candidates (the expired "out until" is back in), weights 4, 3, 2, 1 of 10
        self.assertEqual([picked(x) for x in (0.0, 0.39, 0.4, 0.69, 0.7, 0.89, 0.9, 0.999)],
                         ["zai-coding-plan/glm-5.4"] * 2 + ["zai-coding-plan/glm-5.3-flash"] * 2 + ["muse/muse-ember-1.0"] * 2 + ["sonnet"] * 2)
        self.assertEqual(name(models.choose(FIXTURE, "ordinary", review="zai-coding-plan/glm-5.4", rand=lambda: 0.0)), "muse/muse-ember-1.0")
        self.assertIsNone(models.choose(FIXTURE, "routine", rand=lambda: 0.0))
        self.assertEqual(models.maker("agy", ""), "agy")
        self.assertEqual(models.maker("opencode-go/gpt-6-luna", "`opencode run`"), "gpt")
        self.assertEqual(models.maker("sonnet", "host subagent model `sonnet`"), "claude")

    def test_pick_prints_the_worker_and_remembers_it(self):
        self.table(FIXTURE)
        self.hook("tick")
        rc, out, _ = self.sisi("pick", "hard", "--not", "opus", sid="s1")
        self.assertEqual(rc, 0)
        self.assertIn("sonnet", out)
        self.assertIn("start it with the host's delegation tool", out)
        self.assertEqual(self.state()["picked"], ["sonnet"])
        rc, out, _ = self.sisi("pick", "hard", "--not", "opus", "--not", "sonnet", sid="s1")
        self.assertEqual((rc, "out or excluded" in out), (1, True))
        self.assertEqual(self.sisi("pick", "easy")[0], 1)
        self.assertEqual(self.sisi("pick")[0], 1)

    def test_a_delegation_needs_a_pick_and_one_pick_buys_one_delegation(self):
        self.table(WORKERS)
        self.hook("tick")
        self.hook("prompt", prompt="go")
        self.done()
        self.assertEqual(self.sisi("pick", "hard", sid="s1")[0], 0)
        self.assertEqual(self.tool("Agent", tool_input={"model": "sonnet", "prompt": "use agy"})[0], 0)
        rc, _, err = self.tool("Agent", tool_input={"model": "sonnet"})
        self.assertEqual((rc, "the wheel did not give you" in err), (2, True))             # the pick is spent
        self.assertEqual(self.tool("Agent", tool_input={"prompt": "no model"})[0], 2)
        self.assertEqual(self.sisi("pick", "ordinary", sid="s1")[0], 0)
        self.assertEqual(self.tool("Agent", tool_input={"model": "sonnet"})[0], 2)         # a different worker than picked
        self.assertEqual(self.tool("mcp__t3__delegate_task", tool_input={"target": {"model": "ZAI-coding-plan/GLM-5.4"}})[0], 0)
        self.assertEqual(self.tool("mcp__t3__delegate_task", tool_input={"target": {"model": "zai-coding-plan/glm-5.4"}})[0], 2)
        self.assertEqual(self.tool("Bash", tool_input={"command": "ls"})[0], 0)            # not a worker command
        # no table: nothing about picks is enforced
        os.remove(os.path.join(self.data, "models.md"))
        self.assertEqual(self.tool("Agent", tool_input={"model": "sonnet"})[0], 0)

    def test_a_worker_is_not_started_from_the_shell_unless_the_person_allows_it(self):
        self.table(WORKERS)
        self.hook("tick")
        self.hook("prompt", prompt="go")
        self.done()
        shell = {"command": 'opencode run -m zai-coding-plan/glm-5.4 "x"'}
        rc, out, _ = self.sisi("pick", "ordinary", sid="s1")
        self.assertIn("zai-coding-plan/glm-5.4", out)
        self.assertNotIn("opencode run", out)                                              # no command line by default
        rc, _, err = self.tool("Bash", tool_input=shell)                                   # denied even with a pick
        self.assertEqual((rc, "do not shell out to a worker" in err), (2, True))
        self.assertEqual(self.tool("mcp__t3__delegate_task", tool_input={"target": {"model": "zai-coding-plan/glm-5.4"}})[0], 0)
        self.write(os.path.join(self.data, "config.json"), json.dumps({"core": {"shell_workers": True}}))
        self.assertIn("opencode run -m zai-coding-plan/glm-5.4", self.sisi("pick", "ordinary", sid="s1")[1])
        self.assertEqual(self.tool("Bash", tool_input={"command": 'opencode run -m other/model "x"'})[0], 2)  # needs the pick
        self.assertEqual(self.tool("Bash", tool_input=shell)[0], 0)
        self.assertEqual(self.tool("Bash", tool_input=shell)[0], 2)                        # one pick, one delegation
        s = self.state()
        self.assertEqual((s.get("direct", 0), s["delegations_since"]), (0, 2))             # free on the meter, counted

    def test_a_worker_is_never_asked_for_done_or_a_pick(self):
        self.table(WORKERS)
        self.hook("tick", sid="w")
        self.hook("prompt", sid="w", prompt="You are a worker. Do this task yourself.")
        for name, fields in (("Edit", {}), ("Agent", {}), ("Workflow", {}), ("mcp__t3__delegate_task", {}),
                             ("Bash", {"tool_input": {"command": 'opencode run -m x/y "z"'}})):
            self.assertEqual(self.tool(name, sid="w", **fields)[0], 0, name)
        self.assertEqual(self.hook("gate", sid="w")[1], "")
        self.hook("tick")
        self.hook("prompt", prompt="lead")
        self.assertEqual(self.tool("Edit", agent_id="a1")[0], 0)                           # the host's subagent
        self.assertEqual(self.tool("Agent", agent_id="a1")[0], 0)

    def test_the_retro_shows_the_done_statement_and_the_trend(self):
        self.hook("tick")
        self.done()
        self.sisi("done", "--fail", "1", "the counts differ by two rows", sid="s1")
        log = os.path.join(self.data, "retro.jsonl")
        rec = lambda m, n, f, gap: json.dumps({"ts": "2026-01-01T00:00:00", "project": "p", "unit": {
            "minutes": m, "messages": n, "direct": 1, "delegations": 1, "commits": 0, "checks_pass": 1, "checks_fail": f}, **({"gap": "g"} if gap else {"no-gap": "n"})})
        self.write(log, json.dumps({"ts": "2026-01-01T00:00:00", "gap": "an old record without numbers"}) + "\n" + rec(10, 2, 0, False) + "\n")
        out = self.sisi("retro", sid="s1")[1]
        self.assertIn("export every row without losing any", out)                         # the done statement
        self.assertIn("[fail: the counts differ by two rows]", out)
        self.assertIn("follow-up", out)
        self.assertNotIn("measured", out)                                                 # one numbered record is not a trend
        self.write(log, self.read(log) + "\n".join(rec(m, n, f, g) for m, n, f, g in ((20, 4, 1, True), (30, 6, 0, False), (40, 8, 2, True))) + "\n")
        out = self.sisi("retro", sid="s1")[1]
        self.assertIn("measured", out)
        self.assertRegex(out, r"median 25 min.*median 5 messages.*3 checks failed.*2 with a gap")

    def test_the_new_objective_is_the_one_the_retro_reads(self):
        sys.path.insert(0, REPO)
        from sisi import rules
        self.assertTrue(rules.objective().startswith("Maximize the long-term, verified value of what you deliver"))
        self.assertTrue(rules.objective().endswith("Judge by outcomes, never by activity."))

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
