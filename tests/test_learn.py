import json, os, random, subprocess, sys, time, unittest

from support import SisiCase, REPO

from sisi import escapes, groundtruth, harvest, learn_cli, scoreboard, store, taskset

T0 = harvest.epoch("2026-11-01T10:00:00.000Z")


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


def rec(typ, t, sid="S1", cwd="/nowhere", sidechain=False, agent=None, **kw):
    d = {"parentUuid": None, "isSidechain": sidechain, "type": typ, "timestamp": iso(t), "cwd": cwd, "sessionId": sid,
         "entrypoint": "cli", "userType": "external", "gitBranch": "main"}
    if agent:
        d["agentId"] = agent
    d.update(kw)
    return json.dumps(d, separators=(",", ":"))


def user(t, text, **kw):
    return rec("user", t, message={"role": "user", "content": text}, **kw)


def asst(t, text=None, tool=None, cmd=None, model="claude-sonnet-5-5", **kw):
    blocks = []
    if text is not None:
        blocks.append({"type": "text", "text": text})
    if tool:
        blocks.append({"type": "tool_use", "id": "tu1", "name": tool, "input": {"command": cmd} if cmd else {}})
    return rec("assistant", t, message={"role": "assistant", "model": model, "content": blocks}, **kw)


def tool_result(t, **kw):
    return rec("user", t, message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu1", "content": "ok"}]},
               toolUseResult={"stdout": "ok"}, **kw)


def git(cwd, *args, date=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = iso(date)
    p = subprocess.run(["git"] + list(args), cwd=cwd, env=env, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


class Fixture(SisiCase):
    def projdir(self, name="-home-t-Code-r"):
        d = os.path.join(self.home, ".claude", "projects", name)
        os.makedirs(d, exist_ok=True)
        return d

    def write(self, path, lines, mode="w"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, mode, encoding="utf-8") as f:
            for ln in lines:
                f.write(ln + "\n")

    def session(self, sid, lines, proj="-home-t-Code-r"):
        p = os.path.join(self.projdir(proj), sid + ".jsonl")
        self.write(p, lines)
        return p

    def harvest(self):
        con = harvest.connect()
        st = harvest.run(home=self.home, workers=1, con=con)
        return con, st

    def repo(self, name="r"):
        d = os.path.join(self.home, "Code", name)
        os.makedirs(d)
        git(d, "init", "-q", "-b", "main")
        return d

    def commit(self, d, fname, t, content="x"):
        with open(os.path.join(d, fname), "a") as f:
            f.write(content + "\n")
        git(d, "add", "-A")
        git(d, "commit", "-q", "-m", "c " + fname, date=t)
        return git(d, "rev-parse", "HEAD")


class TestTypedText(unittest.TestCase):
    def test_rule(self):
        tt = harvest.typed_text
        h = {"type": "user", "message": {"content": "please fix the build"}}
        self.assertEqual(tt(h)[0], "please fix the build")
        self.assertIsNone(tt({"type": "user", "isMeta": True, "message": {"content": "hi"}})[0])
        self.assertIsNone(tt({"type": "user", "toolUseResult": {}, "message": {"content": "hi"}})[0])
        self.assertIsNone(tt({"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}})[0])
        self.assertIsNone(tt({"type": "user", "origin": {"kind": "task-notification"}, "message": {"content": "x"}})[0])
        self.assertIsNone(tt({"type": "user", "origin": {"kind": "peer"}, "message": {"content": "x"}})[0])
        self.assertEqual(tt({"type": "user", "origin": {"kind": "human"}, "message": {"content": "yo"}})[0], "yo")
        for wrapped in ("<system-reminder>x</system-reminder>", "<local-command-stdout>x</local-command-stdout>",
                        "<task-notification>x</task-notification>", "This session is being continued from a previous conversation",
                        "<local-command-caveat>Caveat: x</local-command-caveat>"):
            self.assertIsNone(tt({"type": "user", "message": {"content": wrapped}})[0], wrapped)
        self.assertIsNone(tt({"type": "user", "isCompactSummary": True, "message": {"content": "summary"}})[0])
        self.assertEqual(tt({"type": "user", "message": {"content": "[Request interrupted by user for tool use]"}}), (None, 0, True))
        self.assertIsNone(tt({"type": "user", "message": {"content": "<command-name>/clear</command-name><command-args></command-args>"}})[0])
        self.assertEqual(tt({"type": "user", "message": {"content": "<command-name>/x</command-name><command-args>do it</command-args>"}})[0], "do it")
        txt, pasted, _ = tt({"type": "user", "message": {"content": "look <pasted_content id=\"1\">" + "z" * 50 + "</pasted_content> now"}})
        self.assertEqual(txt, "look  now")
        self.assertGreater(pasted, 50)
        txt, _, _ = tt({"type": "user", "message": {"content": [{"type": "text", "text": "[Image #1] see this"}, {"type": "image"}]}})
        self.assertEqual(txt, "see this")
        self.assertEqual(tt({"type": "user", "message": {"content": [{"type": "text", "text": "[Image #1]"}, {"type": "image"}]}})[0], "")

    def test_queued_command(self):
        a = {"type": "queued_command", "commandMode": "prompt", "prompt": "do more", "origin": {"kind": "human"}}
        self.assertEqual(harvest.typed_text(a, queued_prompt=a["prompt"])[0], "do more")
        b = dict(a, origin={"kind": "task-notification"})
        self.assertIsNone(harvest.typed_text(b, queued_prompt="x")[0])


class TestHeuristics(unittest.TestCase):
    def test_machine(self):
        self.assertTrue(harvest.machine_reason("You are a worker: do this", None, "cli")[0])
        self.assertTrue(harvest.machine_reason("Act as the design sub-agent for this task.", None, "t3-code")[0])
        self.assertTrue(harvest.machine_reason("x" * 4000, None, "cli")[0])
        self.assertTrue(harvest.machine_reason(None)[0])
        self.assertTrue(harvest.machine_reason("Generate a title that will help the user", None, "sdk-cli")[0])
        self.assertFalse(harvest.machine_reason("Tell me how you work with subagents", None, "cli")[0])
        self.assertFalse(harvest.machine_reason("fix the login bug in app.py please", None, "cli")[0])

    def test_correction(self):
        self.assertTrue(harvest.is_correction("No, that's not what I asked"))
        self.assertTrue(harvest.is_correction("it still doesn't work"))
        self.assertFalse(harvest.is_correction("great, now add tests"))
        self.assertFalse(harvest.is_correction("no" + " blah" * 600))


class TestHarvest(Fixture):
    def test_main_vs_subagent_and_counts(self):
        proj = self.projdir()
        main = [user(T0, "fix the parser bug", cwd="/x"),
                asst(T0 + 5, "Which file?"),
                user(T0 + 60, "parser.py"),
                asst(T0 + 70, tool="Bash", cmd="git commit -am x"),
                tool_result(T0 + 71),
                asst(T0 + 80, tool="Bash", cmd="sisi verify"),
                asst(T0 + 90, tool="AskUserQuestion"),
                asst(T0 + 100, "All tests pass. Done."),
                user(T0 + 200, "no, that's wrong, it still fails"),
                rec("user", T0 + 205, message={"role": "user", "content": "[Request interrupted by user]"}),
                asst(T0 + 300, "Fixed it.")]
        self.write(os.path.join(proj, "S1.jsonl"), main)
        sub = os.path.join(proj, "S1", "subagents", "agent-abc.jsonl")
        self.write(sub, [user(T0 + 10, "You are a worker: do X", sid="S1", sidechain=True, agent="abc"),
                         asst(T0 + 20, "done", sid="S1", sidechain=True, agent="abc", model="claude-haiku-5-5")])
        with open(sub[:-6] + ".meta.json", "w") as f:
            json.dump({"agentType": "x", "model": "haiku"}, f)
        wf = os.path.join(proj, "S1", "subagents", "workflows", "wf_1234abcd-xx", "agent-zzz.jsonl")
        self.write(wf, [user(T0 + 12, "brief two", sid="S1", sidechain=True, agent="zzz")])
        self.write(os.path.join(proj, "S1", "subagents", "workflows", "wf_1234abcd-xx", "journal.jsonl"), ['{"a":1}'])
        con, st = self.harvest()
        self.assertEqual(st["seen"], 3)
        m = con.execute("SELECT * FROM sessions WHERE kind='main'").fetchone()
        self.assertEqual(m["id"], "S1")
        self.assertEqual(m["user_turns"], 3)
        self.assertEqual(m["n_corrections"], 1)
        self.assertEqual(m["n_premature_done"], 1)  # correction right after a completion claim
        self.assertEqual(m["n_interrupts"], 1)
        self.assertEqual(m["n_ask"], 1)
        self.assertEqual(m["n_question_turns"], 1)
        self.assertEqual((m["ran_commit"], m["used_verify"], m["used_contract"]), (1, 1, 0))
        self.assertEqual(m["last_claims_done"], 1)
        self.assertEqual(json.loads(m["tools"])["Bash"], 2)
        self.assertEqual(m["machine"], 0)
        subs = {r["agent_id"]: r for r in con.execute("SELECT * FROM sessions WHERE kind='subagent'")}
        self.assertEqual(set(subs), {"abc", "zzz"})
        self.assertEqual(subs["abc"]["parent_id"], "S1")
        self.assertEqual(subs["abc"]["user_turns"], 0)
        self.assertEqual(json.loads(subs["abc"]["meta"])["model"], "haiku")
        self.assertTrue(subs["abc"]["first_message"].startswith("You are a worker"))
        msgs = [r["text"] for r in con.execute("SELECT text FROM user_msgs WHERE session_id='S1' ORDER BY idx")]
        self.assertEqual(msgs, ["fix the parser bug", "parser.py", "no, that's wrong, it still fails"])
        self.assertEqual(con.execute("SELECT correction FROM user_msgs WHERE idx=2").fetchone()[0], 1)

    def test_incremental(self):
        p = self.session("S1", [user(T0, "do a thing please", cwd="/x"), asst(T0 + 5, "ok")])
        con, st = self.harvest()
        self.assertEqual((st["parsed"], st["skipped"]), (1, 0))
        con.close()
        con, st = self.harvest()
        self.assertEqual((st["parsed"], st["skipped"]), (0, 1))
        self.write(p, [user(T0 + 100, "and another thing")], mode="a")
        con.close()
        con, st = self.harvest()
        self.assertEqual((st["parsed"], st["skipped"]), (1, 0))
        self.assertEqual(con.execute("SELECT user_turns FROM sessions").fetchone()[0], 2)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM user_msgs").fetchone()[0], 2)

    def test_malformed_lines_never_raise(self):
        p = os.path.join(self.projdir(), "S1.jsonl")
        with open(p, "wb") as f:
            f.write(b"not json at all\n")
            f.write(b'{"parentUuid":null,"type":"user","message":{"content":\n')  # truncated
            f.write(b'{"parentUuid":null,"type":"user","message":null,"timestamp":12}\n')
            f.write(b'{"parentUuid":null,"type":"assistant","message":{"content":[1,"x",null]},"timestamp":"garbage"}\n')
            f.write(b'\xff\xfe\x00bad bytes\n')
            f.write(b'{"parentUuid":null,"type":"attachment","attachment":{"type":"queued_command","prompt":7}}\n')
            f.write((user(T0, "a real request here", cwd="/x") + "\n").encode())
        con, st = self.harvest()
        self.assertEqual(st["errors"], 0)
        self.assertEqual(con.execute("SELECT user_turns FROM sessions").fetchone()[0], 1)

    def test_queued_message_counts_once(self):
        att = rec("attachment", T0 + 50, attachment={"type": "queued_command", "prompt": "also do this", "commandMode": "prompt",
                                                      "origin": {"kind": "human"}, "timestamp": iso(T0 + 50)})
        note = rec("attachment", T0 + 60, attachment={"type": "queued_command", "prompt": "<task-notification>x", "commandMode": "task-notification",
                                                       "origin": {"kind": "task-notification"}})
        self.session("S1", [user(T0, "start the work", cwd="/x"), asst(T0 + 10, tool="Read"), att, note, user(T0 + 51, "also do this")])
        con, _ = self.harvest()
        self.assertEqual(con.execute("SELECT user_turns FROM sessions").fetchone()[0], 2)


class TestGroundTruth(Fixture):
    def test_start_commit_ignores_foreign_refs(self):
        d = self.repo()
        c1 = self.commit(d, "a", T0 - 7200)
        c2 = self.commit(d, "b", T0 - 3600)
        # a checkpoint commit made after c2 and before the session, reachable only from refs/t3/...
        git(d, "checkout", "-q", "--detach")
        c3 = self.commit(d, "ckpt", T0 - 600)
        git(d, "update-ref", "refs/t3/x/checkpoints/1", c3)
        git(d, "checkout", "-q", "main")
        git(d, "reset", "-q", "--hard", c2)
        git(d, "update-ref", "-d", "refs/heads/detached") if False else None
        self.assertEqual(groundtruth.estimate_start(d, T0), c2)
        self.assertEqual(groundtruth.estimate_start(d, T0 - 5000), c1)
        self.assertIsNone(groundtruth.estimate_start(d, T0 - 99999))
        # a remote-tracking ref counts
        git(d, "update-ref", "refs/remotes/origin/main", c3)
        self.assertEqual(groundtruth.estimate_start(d, T0), c3)

    def test_ground_truth_end_to_end(self):
        d = self.repo()
        with open(os.path.join(d, "justfile"), "w") as f:
            f.write("check:\n\techo ok\n")
        git(d, "add", "-A")
        git(d, "commit", "-q", "-m", "init", date=T0 - 1000)
        start = git(d, "rev-parse", "HEAD")
        after = self.commit(d, "new.py", T0 + 600)
        late = self.commit(d, "late.py", T0 + 12000)  # beyond window + 2h
        self.session("S1", [user(T0, "add the feature to new.py", cwd=d), asst(T0 + 10, tool="Edit"), asst(T0 + 3000, "ok")], proj="-p1")
        con, _ = self.harvest()
        groundtruth.run(con, home=self.home, workers=1)
        g = con.execute("SELECT * FROM groundtruth WHERE session_id='S1'").fetchone()
        self.assertEqual((g["start_commit"], g["start_kind"]), (start, "estimated"))
        self.assertEqual([c["sha"] for c in json.loads(g["commits"])], [after])
        self.assertEqual(g["test_cmd"], "just check")
        self.assertEqual(g["repo_root"], os.path.realpath(d))
        # sisi's own record makes it exact
        store.save_session("S1", {"session_id": "S1", "head": start})
        con.execute("DELETE FROM groundtruth")
        groundtruth.run(con, home=self.home, workers=1)
        g = con.execute("SELECT * FROM groundtruth WHERE session_id='S1'").fetchone()
        self.assertEqual(g["start_kind"], "exact")

    def test_missing_t3_worktree_recovered(self):
        d = self.repo("proj")
        self.commit(d, "a", T0 - 100)
        gone = os.path.join(self.home, ".t3", "worktrees", "proj", "t3-abc")
        root, how, _ = groundtruth.resolve_repo(gone, self.home)
        self.assertEqual((root, how), (os.path.realpath(d), "t3-worktree-recovery"))
        self.assertEqual(groundtruth.resolve_repo(os.path.join(self.home, ".t3", "worktrees", "nothere", "x"), self.home)[0], None)
        self.assertEqual(groundtruth.resolve_repo(self.proj, self.home)[1], "not-a-git-repo")

    def test_linked_worktree_resolves_to_main_repo(self):
        d = self.repo()
        self.commit(d, "a", T0 - 100)
        wt = os.path.join(self.tmp, "wt")
        git(d, "worktree", "add", "-q", "-b", "t3/x", wt)
        self.assertEqual(groundtruth.resolve_repo(wt, self.home)[0], os.path.realpath(d))

    def test_test_command_detection(self):
        d = self.repo()
        for name, content, want in (("Cargo.toml", "[package]\n", "cargo test"),):
            with open(os.path.join(d, name), "w") as f:
                f.write(content)
        git(d, "add", "-A")
        git(d, "commit", "-q", "-m", "i", date=T0)
        self.assertEqual(groundtruth.test_command(d, git(d, "rev-parse", "HEAD"))[0], "cargo test")
        e = self.repo("e")
        with open(os.path.join(e, "package.json"), "w") as f:
            json.dump({"scripts": {"test": "jest"}}, f)
        self.assertEqual(groundtruth.test_command(e, None)[0], "npm test")
        with open(os.path.join(e, "package.json"), "w") as f:
            json.dump({"scripts": {"test": "echo \"Error: no test specified\" && exit 1"}}, f)
        self.assertIsNone(groundtruth.test_command(e, None)[0])

    def test_overlap_detection(self):
        d = self.repo()
        self.commit(d, "a", T0 - 100)
        self.session("A", [user(T0, "task one here", cwd=d), asst(T0 + 10, tool="Edit"), asst(T0 + 1000, "x")], proj="-p")
        self.session("B", [user(T0 + 500, "task two here", cwd=d), asst(T0 + 600, tool="Read"), asst(T0 + 700, "x")], proj="-p")
        self.session("C", [user(T0 + 50000, "task three here", cwd=d), asst(T0 + 50010, "x")], proj="-p")
        con, _ = self.harvest()
        groundtruth.run(con, home=self.home, workers=1)
        g = {r["session_id"]: r for r in con.execute("SELECT * FROM groundtruth")}
        self.assertEqual((g["A"]["overlap_any"], g["A"]["overlap_writers"]), (1, 0))  # B only read
        self.assertEqual((g["B"]["overlap_any"], g["B"]["overlap_writers"]), (1, 1))  # A wrote
        self.assertEqual(g["C"]["overlap_any"], 0)


class TestTaskset(Fixture):
    def test_split_is_stable_and_roughly_70_30(self):
        ids = ["h-%08x" % random.Random(i).getrandbits(32) for i in range(2000)]
        first = {i: taskset.split_of(i) for i in ids}
        dev = sum(1 for v in first.values() if v == "dev") / len(ids)
        self.assertTrue(0.65 < dev < 0.75, dev)
        for i in ids:
            self.assertEqual(taskset.split_of(i), first[i])

    def test_adding_tasks_never_moves_existing(self):
        con = harvest.connect()
        now = time.time()
        existing = {}
        rng = random.Random(7)
        for round_ in range(5):
            for _ in range(40):
                tid = "t%d" % rng.getrandbits(40)
                taskset._upsert(con, existing, now, id=tid, kind="human", session_id=tid, grade="B", reasons="[]")
                existing[tid] = con.execute("SELECT split FROM tasks WHERE id=?", (tid,)).fetchone()[0]
            snap = {r["id"]: r["split"] for r in con.execute("SELECT id,split FROM tasks")}
            for tid, sp in snap.items():  # re-upserting with another grade keeps the split
                taskset._upsert(con, existing, now, id=tid, kind="human", session_id=tid, grade="C", reasons="[]")
            after = {r["id"]: r["split"] for r in con.execute("SELECT id,split FROM tasks")}
            self.assertEqual(snap, after)
            self.assertTrue(all(sp == taskset.split_of(t) for t, sp in after.items()))

    def row(self, **kw):
        base = dict(start_kind="estimated", test_cmd="just test", overlap_any=0, overlap_writers=0, n_commits=2,
                    first_message="please implement the feature in detail", ran_commit=1, tools="{}")
        base.update(kw)
        return base

    def test_grades(self):
        g = lambda **kw: taskset.grade_human(self.row(**kw), self.row(**kw))[0]
        self.assertEqual(g(), "A")                                                   # no sibling, test command
        self.assertEqual(g(start_kind="exact", test_cmd=None), "A")                  # exact start
        self.assertEqual(g(start_kind="exact", test_cmd=None, overlap_any=1, overlap_writers=1), "C")
        self.assertEqual(g(overlap_any=1, overlap_writers=1), "B")                   # estimated, siblings wrote, has tests
        self.assertEqual(g(test_cmd=None, overlap_any=1, overlap_writers=0), "B")
        self.assertEqual(g(test_cmd=None), "B")                                      # no sibling but no tests: not A
        self.assertEqual(g(n_commits=80), "C")
        self.assertEqual(g(first_message="continue"), "C")
        self.assertEqual(g(ran_commit=0), "C")
        self.assertEqual(g(ran_commit=0, tools='{"Edit": 3}'), "A")

    def test_build_end_to_end_with_duplicates(self):
        d = self.repo()
        with open(os.path.join(d, "justfile"), "w") as f:
            f.write("test:\n\ttrue\n")
        git(d, "add", "-A")
        git(d, "commit", "-q", "-m", "i", date=T0 - 500)
        self.commit(d, "n.py", T0 + 400)
        msg = "please implement the new feature in n.py"
        self.session("S1", [user(T0, msg, cwd=d), asst(T0 + 10, tool="Edit"), asst(T0 + 500, "ok")], proj="-p")
        self.session("S2", [user(T0 + 90000, msg, cwd=d), asst(T0 + 90010, tool="Edit"), asst(T0 + 90500, "ok")], proj="-p")
        self.session("M1", [user(T0 + 300000, "You are a worker. Do the thing.", cwd=d)], proj="-p")
        con, _ = self.harvest()
        groundtruth.run(con, home=self.home, workers=1)
        r = taskset.build(con, home=self.home)
        self.assertEqual(r["human"], 1)  # only S1 has following commits; M1 is machine-written
        t = taskset.list_tasks(con, kind="human")[0]
        self.assertEqual((t["id"], t["grade"], t["test_cmd"]), ("h-S1", "A", "just test"))
        split = t["split"]
        taskset.build(con, home=self.home)
        self.assertEqual(taskset.list_tasks(con, kind="human")[0]["split"], split)
        self.assertEqual(taskset.get_task(con, "h-S")["id"], "h-S1")

    def test_ledger_matching(self):
        sub = lambda i, t0, t1: {"id": i, "t0": t0, "t1": t1, "names": {"r"}, "classes": {"sonnet"}}
        led = lambda i, ts, w="sonnet", m=None, p="r": {"id": i, "ts": ts, "worker": w, "project": p, "outcome": "accepted", "minutes": m}
        out = taskset.match_ledger([sub("a", T0, T0 + 600)], [led("L1", T0 + 700, m=10)])
        self.assertEqual((out["a"][1], out["a"][0]["id"]), ("high", "L1"))
        out = taskset.match_ledger([sub("a", T0, T0 + 600)], [led("L1", T0 + 700, m=90)])
        self.assertEqual(out["a"][1], "medium")
        out = taskset.match_ledger([sub("a", T0, T0 + 600), sub("b", T0 + 100, T0 + 650)], [led("L1", T0 + 700)])
        self.assertEqual((out["a"][1], out["a"][0]), ("low", None))
        self.assertEqual(out["b"][1], "low")
        out = taskset.match_ledger([sub("a", T0, T0 + 600)], [led("L1", T0 + 700, w="opencode-go/x")])
        self.assertEqual(out["a"][1], "none")
        out = taskset.match_ledger([sub("a", T0, T0 + 600)], [led("L1", T0 + 700, p="other")])
        self.assertEqual(out["a"][1], "none")
        out = taskset.match_ledger([sub("a", T0, T0 + 600)], [led("L1", T0 + 9000)])
        self.assertEqual(out["a"][1], "none")


class TestEscapesChecksScoreboard(Fixture):
    def results(self, project, t, ok=True, session=None):
        return [{"ts": iso(t)[:19] + "Z", "contract": "c", "project": project, "check": "unit", "status": "passed" if ok else "failed",
                 "run": "r%d" % t, "session": session}]

    def test_escapes(self):
        d = self.repo()
        self.commit(d, "a", T0 - 100)
        self.session("S1", [user(T0, "implement the thing in a", cwd=d), asst(T0 + 100, "All tests pass. Done."),
                            user(T0 + 200, "no, that's wrong, it still fails"), asst(T0 + 300, "sorry")], proj="-p")
        con, _ = self.harvest()
        groundtruth.run(con, home=self.home, workers=1)
        res = self.results(d, T0 + 120)  # attributed by time and project, no session field
        out = escapes.find(con, res)
        kinds = [e["kind"] for e in out]
        self.assertIn("contract-then-correction", kinds)
        self.assertIn("premature-done", kinds)
        # a failed run is not "verified"
        self.assertEqual([e for e in escapes.find(con, self.results(d, T0 + 120, ok=False)) if e["kind"].startswith("contract")], [])
        # a correction BEFORE the pass is not an escape
        self.assertEqual([e for e in escapes.find(con, self.results(d, T0 + 250)) if e["kind"].startswith("contract")], [])

    def test_fix_session_escape(self):
        d = self.repo()
        self.commit(d, "a.py", T0 - 100)
        self.commit(d, "a.py", T0 + 100)
        self.session("S1", [user(T0, "implement the thing in a.py", cwd=d), asst(T0 + 50, tool="Edit"), asst(T0 + 150, "ok")], proj="-p")
        c2 = self.commit(d, "a.py", T0 + 86400 * 2, "fix")
        self.session("S2", [user(T0 + 86400 * 2 - 100, "the thing in a.py is broken, please fix it", cwd=d), asst(T0 + 86400 * 2 - 50, tool="Edit"),
                            asst(T0 + 86400 * 2 + 60, "ok")], proj="-p")
        con, _ = self.harvest()
        groundtruth.run(con, home=self.home, workers=1)
        out = escapes.find(con, self.results(d, T0 + 120, session="S1"))
        fix = [e for e in out if e["kind"] == "contract-then-fix-session"]
        self.assertEqual(len(fix), 1)
        self.assertEqual(fix[0]["evidence"]["later_session"], "S2")

    def test_check_stats(self):
        rs = [{"check": "a", "status": "passed", "verifier": "v1"} for _ in range(12)]
        rs += [{"check": "b", "status": "failed"}, {"check": "b", "status": "timeout"}, {"check": "gate", "status": "unverified"}]
        rs += [{"check": "c", "status": "passed", "verifier": "v2"}, "junk"]
        st = scoreboard.check_stats(rs)
        by = {s["id"]: s for s in st["checks"]}
        self.assertTrue(by["a"]["never_seen_failing"])
        self.assertEqual((by["b"]["runs"], by["b"]["failures"], by["b"]["timeouts"]), (2, 1, 1))
        self.assertFalse(by["b"]["never_seen_failing"])
        self.assertFalse(by["c"]["never_seen_failing"])  # too few runs
        self.assertNotIn("gate", by)
        self.assertEqual({s["id"]: s["runs"] for s in st["verifiers"]}, {"v1": 12, "v2": 1})

    def test_scoreboard_weeks(self):
        w1 = harvest.epoch("2026-11-02T10:00:00.000Z")  # Monday of ISO week 45
        w2 = w1 + 7 * 86400
        self.session("S1", [user(w1, "do the first task here", cwd="/x"), asst(w1 + 5, "Done. All tests pass."),
                            user(w1 + 60, "no, that's wrong"), asst(w1 + 70, tool="Bash", cmd="sisi contract check")], proj="-p")
        self.session("S2", [user(w2, "do the second task here", cwd="/x"), asst(w2 + 5, "ok?")], proj="-p")
        self.session("M", [user(w2, "You are a worker. Do X.", cwd="/x")], proj="-p")
        con, _ = self.harvest()
        sb = scoreboard.scoreboard(con)
        self.assertEqual(list(sb["weeks"]), ["2026-W45", "2026-W46"])
        a = sb["weeks"]["2026-W45"]
        self.assertEqual((a["sessions"], a["turns_per_session"], a["corrections_per_100"], a["contract_share"], a["premature_done_share"]),
                         (1, 2.0, 50.0, 1.0, 1.0))
        self.assertEqual(sb["weeks"]["2026-W46"]["sessions"], 1)  # machine-written session excluded
        self.assertEqual(sb["weeks"]["2026-W46"]["questions_per_100"], 100.0)


class TestCli(Fixture):
    def run_cli(self, *args):
        env = dict(os.environ, PYTHONPATH=REPO)
        return subprocess.run([sys.executable, "-m", "sisi.learn_cli"] + list(args), capture_output=True, text=True, env=env, cwd=self.proj, timeout=120)

    def test_commands_run(self):
        d = self.repo()
        self.commit(d, "a", T0 - 100)
        self.session("S1", [user(T0, "implement the thing here please", cwd=d), asst(T0 + 100, "ok")], proj="-p")
        p = self.run_cli("harvest", "--json", "--workers", "1")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["transcripts"]["parsed"], 1)
        self.assertEqual(json.loads(self.run_cli("harvest", "--json").stdout)["transcripts"]["parsed"], 0)
        self.assertEqual(self.run_cli("tasks", "build").returncode, 0)
        self.assertEqual(self.run_cli("tasks", "list", "--json").returncode, 0)
        self.assertEqual(self.run_cli("tasks", "show", "nope").returncode, 1)
        self.assertEqual(self.run_cli("escapes", "--json").returncode, 0)
        self.assertEqual(self.run_cli("checks").returncode, 0)
        sb = json.loads(self.run_cli("scoreboard", "--json").stdout)
        self.assertEqual(sb["weeks"]["2026-W44"]["sessions"], 1)

    def test_register_attaches_commands(self):
        import argparse
        ap = argparse.ArgumentParser()
        learn_cli.register(ap.add_subparsers(dest="cmd"))
        for argv in (["harvest"], ["tasks", "build"], ["tasks", "list", "--grade", "A"], ["tasks", "show", "x"], ["escapes"], ["checks"], ["scoreboard", "--json"]):
            self.assertTrue(callable(ap.parse_args(argv).func))


if __name__ == "__main__":
    unittest.main()
