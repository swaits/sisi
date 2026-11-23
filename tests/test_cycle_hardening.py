"""Hardening of the learning cycle after a real rehearsal. Docstrings cite docs/spec/requirements.json ids.

Each test is an abuse case: the cycle file's author (an agent, untrusted) tries to get something
to run, validate or take effect that nobody approved.
"""
import json, os, subprocess, sys, unittest

from support import SisiCase, terminal
from test_learning_loop import Base, PROMOTE, FINDING, CAUSE, _contract
from sisi import learning as L


class Replay(Base):
    """R-11.5-6, R-11.6-3, R-16-6, R-16-7, R-16-4 (items 1 and 2)."""

    def setUp(self):
        super().setUp()
        self.marker = os.path.join(self.tmp, "marker")
        self.secret_name = "SISI_TEST_SECRET_TOKEN"

    def recorded(self, before, after):
        self.retro(*PROMOTE[1:])
        self.archive_unit(before, after)

    def cmd_action(self, cmd, **kw):
        a = {"action": "promote", "learning": "L-0001", "mechanism_kind": "command-check", "cmd": cmd}
        a.update(kw)
        return a

    def test_check_never_executes_anything_from_the_file(self):
        """R-16-6 (item 1): `sisi cycle check` runs nothing the file contains; `apply` does, in a copy."""
        before, after = self.fixed_repo()
        self.recorded(before, after)
        cmd = "sh -c 'echo ran > %s; grep -q fixed f.txt'" % self.marker
        p = self.cycle_file([self.cmd_action(cmd)])
        r = self.sisi("cycle", "check", p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(self.marker), "check executed a command from the file")
        r = self.sisi("cycle", "apply", p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(self.marker), "apply replays the command (in an exported copy)")

    def test_replay_runs_in_an_exported_copy_without_history_or_the_callers_secrets(self):
        """R-16-4, R-16-6 (items 1, 2): no .git, HOME empty and not the caller's, the secret in the
        caller's environment is not visible, the working directory is not the project, and the copy
        is deleted afterwards."""
        before, after = self.fixed_repo()
        self.recorded(before, after)
        rec = os.path.join(self.tmp, "rec.txt")
        script = ("{ pwd; test -e .git && echo GIT || echo NOGIT; echo \"HOME=$HOME\"; "
                  "echo \"SECRET=${%s:-unset}\"; env | cut -d= -f1 | sort | paste -sd, -; "
                  "ls -A \"$HOME\" | wc -l; } > %s; grep -q fixed f.txt" % (self.secret_name, rec))
        cmd = "sh -c '%s'" % script
        import unittest.mock
        with unittest.mock.patch.dict(os.environ, {self.secret_name: "hunter2-very-secret"}):
            r = self.apply([self.cmd_action(cmd)])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rows()[0]["validation"]["result"], "validated", r.stdout + r.stderr)
        with open(rec) as f:
            out = f.read().splitlines()
        self.assertNotEqual(out[0], self.proj)
        self.assertFalse(os.path.exists(out[0]), "the exported copy was not deleted")
        self.assertEqual(out[1], "NOGIT")
        self.assertNotEqual(out[2], "HOME=" + os.environ.get("HOME", ""))
        self.assertEqual(out[3], "SECRET=unset")
        names = set(out[4].split(",")) - {"PWD", "SHLVL", "_", "OLDPWD"}
        self.assertEqual(names, {"PATH", "HOME", "LANG"}, out[4])
        self.assertEqual(out[5].strip(), "0")
        self.assertNotIn("hunter2", r.stdout + r.stderr + json.dumps(self.rows()))

    def test_a_command_reading_git_history_finds_none(self):
        """R-11.6-3, R-16-7 (item 2): the history trick no longer works. The command names a changed
        path and reads `git log`; with no .git in the copy it cannot pass at the fix, so it is refused."""
        before, after = self.fixed_repo()
        self.recorded(before, after)
        r = self.apply([self.cmd_action("git log -p -- f.txt | grep -q fixed")])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("replay validation failed", r.stderr)
        self.assertFalse(self.exists("overlay/enforced.json"))
        self.assertEqual(self.rows()[0]["status"], "proposed")

    def test_the_fix_commit_subject_trick_is_vacuous_and_refused(self):
        """R-11.6-3 (item 2): `git show HEAD --stat | grep -q <subject>` names no path that differs
        between the two trees: refused as vacuous, with a message that says so."""
        before, after = self.fixed_repo()
        self.recorded(before, after)
        r = self.apply([self.cmd_action('git show HEAD --stat | grep -q "fix"')])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("vacuous", r.stderr)
        self.assertFalse(self.exists("overlay/enforced.json"))
        r = self.sisi("cycle", "check", self.cycle_file([self.cmd_action("echo ok")]))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("vacuous", r.stderr)

    def test_a_learning_without_recorded_commits_cannot_be_validated(self):
        """R-11.6-3 (item 2): no unit record and no commits stored with the finding: the command check
        waits for the owner as unvalidated, whatever commits the file names."""
        before, after = self.fixed_repo()
        self.retro(*PROMOTE[1:])
        self.assertIsNone(L.replay_commits(self.rows()[0]) if not self.rows()[0].get("replay", {}).get("before") else None)
        r = self.apply([self.cmd_action("grep -q fixed f.txt", before=before, after=after)])
        self.assertEqual(r.returncode, 0, r.stderr)
        pend = self.pending()
        self.assertEqual(len(pend), 1)
        self.assertEqual(pend[0]["replay"][0], "unvalidated")
        self.assertIn("no commits are recorded", pend[0]["replay"][1])
        self.assertNotEqual(self.rows()[0]["validation"]["result"], "validated")
        self.assertFalse(self.exists("overlay/enforced.json"))

    def test_the_finding_records_the_unit_start_so_a_retro_can_be_replayed(self):
        """R-11.6-3 (item 2): the commits stored with the finding are the unit's base_head and HEAD."""
        from sisi import trust
        _contract(self)
        self.git_init()
        trust.add(self.proj)
        self.write("f.txt", "bug\n")
        self._commit("before")
        base = self._head()
        cp = os.path.join(self.proj, ".sisi", "contract.json")
        with open(cp) as f:
            c = json.load(f)
        c["base_head"] = base
        with open(cp, "w") as f:
            json.dump(c, f)
        self.write("f.txt", "fixed\n")
        self._commit("fix")
        self.retro(*PROMOTE[1:])
        got = L.replay_commits(self.rows()[0])
        self.assertEqual(got[:2], (base, self._head()))
        r = self.apply([self.cmd_action("grep -q fixed f.txt")])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rows()[0]["validation"]["result"], "validated")


def _shell_payload(cmd, sid="sess-hook"):
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd},
            "session_id": sid, "cwd": os.getcwd()}


class Approval(Base):
    """R-11.5-11, R-14.3-2, R-16-11, R-16-8 (item 3): an agent cannot approve its own proposals."""

    def park(self):
        _contract(self)
        self.git_init()
        self.retro(*PROMOTE[1:])
        self.apply([{"action": "promote", "learning": "L-0001", "mechanism_kind": "command-check",
                     "cmd": "make deploy --force-everything"}])
        self.assertEqual(len(self.pending()), 1)

    def hook(self, cmd, sid="sess-hook"):
        """Run the before-tool hook on a shell command. Returns the exit code the hook ends with."""
        import contextlib, io
        from sisi import watch
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                watch.before(_shell_payload(cmd, sid))
        except SystemExit as e:
            return e.code
        return 0

    def test_the_before_tool_hook_refuses_every_wrapping_of_approve(self):
        """R-14.3-2 (item 3a): script, sh -c, env, expect, a path to the launcher and python -m sisi."""
        self.park()
        wrapped = [
            'script -qec "sisi approve P-0001 --yes" /dev/null </dev/null',
            "sh -c 'sisi approve P-0001 --yes'",
            "/path/to/bin/sisi approve P-0001 --yes",
            "python3 -m sisi approve P-0001 --yes",
            "env SISI_SESSION_ID=x sisi approve P-0001 --no",
            "expect -c 'spawn sisi approve P-0001 --yes; expect eof'",
            "echo P-0001 | xargs sisi approve --yes",
            "bash -lc \"cd /tmp && sisi   approve P-0001 --yes\"",
            "s\\isi 'app'rove P-0001 --yes",
            "sisi${IFS}approve${IFS}P-0001${IFS}--yes",
            "cd x; sisi approve P-0001 --yes; echo done",
            "a=approve; sisi $a P-0001 --yes",
        ]
        for cmd in wrapped:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.hook(cmd), 2, cmd)
        self.assertEqual(len(self.pending()), 1)
        refused = [r for r in L.load_approvals() if r.get("decision") == "refused"]
        self.assertEqual(len(refused), len(wrapped))
        self.assertTrue(all(r["session"] == "sess-hook" and r["how"] == "hook" for r in refused))
        self.assertEqual(refused[0]["id"], "P-0001")

    def test_the_listing_and_other_commands_are_allowed_through_the_hook(self):
        """R-14.3-2 (item 3a): `sisi approve` with no arguments is the listing; nothing else is touched."""
        for cmd in ("sisi approve", "/path/to/bin/sisi approve", "sisi approve | head -20", "python3 -m sisi approve;",
                    "sisi cycle apply f.json", "sisi cycle check c.json", "echo approve the plan",
                    "git commit -m 'approve the design'", "ls"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.hook(cmd), 0, cmd)
        self.assertEqual(L.load_approvals(), [])

    def test_the_hook_is_one_for_main_threads_and_workers(self):
        """R-16-10 (item 3a): a subagent's shell command goes through the same refusal."""
        payload = _shell_payload("sisi approve P-0001 --yes", "sess-w")
        payload["agent_id"] = "worker-1"
        import contextlib, io
        from sisi import watch
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stderr(io.StringIO()):
            watch.before(payload)
        self.assertEqual(cm.exception.code, 2)

    def test_the_hook_process_exits_2_with_the_reason_and_fails_open_on_error(self):
        """R-16-9 (item 3a): `sisi watch --before` refuses with exit 2 and says whom to ask; an error in
        the check lets the command through."""
        r = self.sisi_proc("watch", "--before", stdin=json.dumps(_shell_payload("sisi approve P-0001 --yes")))
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("owner's alone", r.stderr)
        self.assertIn("give him the command", r.stderr)
        import unittest.mock
        from sisi import watch
        with unittest.mock.patch.object(watch, "_APPROVE", None):
            self.assertEqual(self.hook("sisi approve P-0001 --yes"), 0)

    def test_a_decision_needs_the_word_typed_at_the_terminal(self):
        """R-14.3-2 (item 3b): the full action and a word are printed to the terminal; the word read
        back from it decides. A wrong word, no word, or words on standard input decide nothing."""
        from support import terminal
        self.park()
        t = terminal("wrong")
        with t:
            r = self.sisi("approve", "P-0001", "--yes", env={"SISI_SESSION_ID": "sess-9"})
        self.assertEqual(r.returncode, 2)
        self.assertIn("make deploy --force-everything", t.fake.text)  # the full action, on the terminal
        self.assertIn("Type the word", t.fake.text)
        self.assertEqual(len(self.pending()), 1)
        self.assertFalse(self.exists("overlay/enforced.json"))
        t = terminal(None)
        with t:
            self.assertEqual(self.sisi("approve", "P-0001", "--no").returncode, 2)
        self.assertEqual(len(self.pending()), 1)
        refused = [r for r in L.load_approvals() if r.get("decision") == "refused"]
        self.assertEqual(len(refused), 2)
        self.assertEqual(refused[0]["session"], "sess-9")
        with terminal():
            r = self.sisi("approve", "P-0001", "--yes")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.exists("overlay/enforced.json"))

    def test_no_controlling_terminal_means_refused_and_stdin_cannot_stand_in(self):
        """R-14.3-2 (item 3b): the word is not read from standard input."""
        import unittest.mock
        self.park()
        with unittest.mock.patch("sisi.cycle._open_terminal", return_value=None):
            r = self.sisi("approve", "P-0001", "--yes", stdin="pagaso\nyes\n", env={"SISI_SESSION_ID": "s-1"})
        self.assertEqual(r.returncode, 2)
        self.assertIn("controlling terminal", r.stderr)
        self.assertEqual(len(self.pending()), 1)
        self.assertEqual([x["session"] for x in L.load_approvals()], ["s-1"])
        # a real process in its own session has no controlling terminal at all
        p = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
                                                         "bin", "sisi"), "approve", "P-0001", "--yes"],
                           cwd=self.proj, input="pagaso\n", capture_output=True, text=True, timeout=60,
                           start_new_session=True, env=dict(os.environ))
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertEqual(len(self.pending()), 1)

    @unittest.skipUnless(os.path.exists("/usr/bin/script") or os.path.exists("/bin/script"), "no script(1)")
    def test_script_gives_a_terminal_but_not_the_owners_hands(self):
        """R-14.3-2 (item 3b): the evidence case, `script -qec "sisi approve ..." /dev/null </dev/null`."""
        self.park()
        bin_ = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "bin", "sisi")
        p = subprocess.run(["script", "-qec", "%s %s approve P-0001 --yes" % (sys.executable, bin_), "/dev/null"],
                           cwd=self.proj, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
                           env=dict(os.environ))
        self.assertEqual(len(self.pending()), 1, p.stdout + p.stderr)
        self.assertFalse(self.exists("overlay/enforced.json"))

    def test_a_person_at_a_real_terminal_can_decide(self):
        """R-14.3-2 (item 3b): through a real pseudo-terminal, typing the word approves."""
        try:
            import pty
        except ImportError:
            self.skipTest("no pty")
        self.park()
        bin_ = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "bin", "sisi")
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(self.proj)
            os.execv(sys.executable, [sys.executable, bin_, "approve", "P-0001", "--yes"])
        out = b""
        import re, select, time
        sent, end = False, time.time() + 60
        while time.time() < end:
            ready, _w, _x = select.select([fd], [], [], 1)
            if not ready:
                continue
            try:
                d = os.read(fd, 4096)
            except OSError:
                break
            if not d:
                break
            out += d
            m = re.search(rb"Type the word (\w+) to decide", out)
            if m and not sent:
                os.write(fd, m.group(1) + b"\n")
                sent = True
        _p, status = os.waitpid(pid, 0)
        self.assertTrue(sent, out)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0, out)
        self.assertTrue(self.exists("overlay/enforced.json"))
        self.assertEqual(self.pending(), [])

    def test_security_says_plainly_what_this_stops_and_does_not(self):
        """R-16-1 (item 3): SECURITY.md names the hook, the typed word, and what neither stops."""
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "SECURITY.md")) as f:
            text = f.read()
        low = text.lower()
        for needle in ("typed word", "before-tool hook", "controlling terminal", "does not stop"):
            self.assertIn(needle, low)


def _tool_args(n):
    return ("retro", "--new", "--finding", "the stub number %d crashed sisi cycle on input case %d" % (n, n),
            "--cause", "no test covered stub %d" % n, "--impact", "correctness", "--disposition", "promote",
            "--change", "make sisi cycle handle stub %d" % n, "--mechanism", "tool",
            "--expect", "stub %d no longer crashes" % n, "--validate", "run stub %d" % n)


class Due(Base):
    """R-11.5-4, R-11.5-7, R-14.4-1 (items 4 and 9): "due" counts only learnings a cycle can act on."""

    def test_a_tool_learning_is_backlog_never_proposed_and_never_due(self):
        """Item 4: recording a tool learning gives it the status `backlog`; five of them make no cycle due;
        they appear in the learning report and the contribution export, never in a brief."""
        from sisi import cycle, release
        _contract(self)
        for n in range(6):
            self.assertEqual(self.sisi(*_tool_args(n)).returncode, 0)
        self.assertEqual({r["status"] for r in self.rows()}, {"backlog"})
        self.assertEqual(cycle.proposed(), [])
        self.assertNotIn("cycle is due", cycle.due_notice())
        self.assertNotIn("L-0001", self.sisi("cycle").stdout)
        self.assertIn("tool backlog (6 change(s)", L.learning_report())
        self.assertIn("backlog 6", L.learning_report())
        self.assertEqual(len(release.core_items()[0]), 6)
        # five learnings a cycle can act on make it due
        for n in range(5):
            self.another(n)
        self.assertIn("cycle is due (5 proposed", cycle.due_notice())

    def test_a_learning_waiting_for_the_owner_is_not_proposed_and_the_cycle_is_not_due_again(self):
        """Item 4: after a cycle parks everything, session start does not say a cycle is due."""
        from sisi import cycle
        _contract(self)
        self.git_init()
        ids = [self.another(n) for n in range(5)]
        self.assertIn("cycle is due", cycle.due_notice())
        self.assertEqual(self.apply([{"action": "promote", "learning": i, "mechanism_kind": "command-check",
                                      "cmd": "make check-%s" % i} for i in ids]).returncode, 0)
        self.assertEqual({r["status"] for r in self.rows()}, {"pending-approval"})
        self.assertEqual(cycle.proposed(), [])
        out = cycle.due_notice()
        self.assertNotIn("cycle is due", out)
        self.assertIn("wait for the owner", out)
        self.assertNotIn("L-0001", self.sisi("cycle").stdout)  # not in a brief either
        # the owner declines one: it is rejected, not proposed again
        with terminal():
            self.assertEqual(self.sisi("approve", "P-0001", "--no").returncode, 0)
        self.assertEqual(self.rows()[0]["status"], "rejected")
        self.assertEqual(cycle.proposed(), [])

    def test_the_config_switch_that_silenced_the_notice_is_gone(self):
        """Item 4: learning.cycle_notice was a stopgap for the bug; the code for it is deleted."""
        from sisi import cycle
        _contract(self)
        for n in range(5):
            self.another(n)
        self.set_config({"learning": {"cycle_notice": False}})
        self.assertIn("cycle is due", cycle.due_notice())
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "sisi", "cycle.py")) as f:
            self.assertNotIn("cycle_notice", f.read())

    def test_migration_puts_an_old_tool_lesson_in_the_backlog(self):
        """Item 4: the old store's open tool lesson becomes `backlog`, an open check lesson `proposed`."""
        from sisi import lifecycle
        from test_learning_loop import Migration
        Migration.seed(self)
        lifecycle.migrate_learnings()
        by = {r["legacy_id"]: r["status"] for r in self.rows() if r.get("legacy_id")}
        self.assertEqual((by[2], by[3]), ("backlog", "proposed"))


class Repair(Base):
    """R-11.6-6, R-16-9 (items 4 and 9): a store migrated by earlier code is repaired once by `sisi update`."""

    def old_store(self):
        """Rows as earlier code wrote them: a tool learning `proposed`, one with a decision waiting,
        and one whose origin is a deleted linked worktree."""
        _contract(self)
        self.git_init()
        self.sisi(*_tool_args(1))
        for n in range(2):
            self.another(n)
        self.apply([{"action": "promote", "learning": "L-0003", "mechanism_kind": "command-check", "cmd": "make a"}])
        rows = self.rows()
        by = {r["id"]: r for r in rows}
        by["L-0001"]["status"] = "proposed"
        by["L-0003"]["status"] = "proposed"
        dead = os.path.join(self.home, ".t3", "worktrees", "proj", "t3-gone")
        by["L-0002"]["origin_project"] = dead
        by["L-0002"]["provenance"][0]["project"] = dead
        L.save_learnings(rows, "old code", touched=rows, via="test")
        return dead

    def test_update_repairs_statuses_and_project_keys_once(self):
        from sisi import lifecycle
        main = os.path.join(self.home, "Code", "proj")
        os.makedirs(main)
        self.git_init(main)
        dead = self.old_store()
        # an enforced mechanism written for the dead path follows the learning
        os.makedirs(os.path.join(self.data, "overlay"), exist_ok=True)
        with open(os.path.join(self.data, "overlay", "enforced.json"), "w") as f:
            json.dump({"checks": [{"type": "contract-requirement", "when": "data", "require_kind": "parsing",
                                   "learning": "L-0002", "scope": "project", "project": dead}]}, f)
        notes = lifecycle.repair_learnings()
        self.assertTrue(notes and "1 tool learning(s) moved to the backlog" in notes[0], notes)
        by = {r["id"]: r for r in self.rows()}
        self.assertEqual(by["L-0001"]["status"], "backlog")
        self.assertEqual(by["L-0003"]["status"], "pending-approval")
        self.assertEqual(by["L-0002"]["origin_project"], os.path.realpath(main))
        self.assertEqual(by["L-0002"]["provenance"][0]["project"], os.path.realpath(main))
        self.assertEqual(self.read_json("overlay/enforced.json")["checks"][0]["project"], os.path.realpath(main))
        self.assertTrue(all(L.is_registered(r) for r in self.rows()))  # still delivered: the repair is sisi's own
        self.assertEqual(lifecycle.repair_learnings(), [])  # idempotent: nothing to do the second time
        # `sisi update` runs it (the migrate step is where an installation brings its data up to date)
        self.assertIn("repair_learnings()", open(lifecycle.__file__).read().split("def run():")[1].split("def migrate_learnings")[0])

    def test_a_hand_edited_row_is_not_laundered_by_the_repair(self):
        from sisi import lifecycle
        self.old_store()
        with open(L.learnings_path()) as f:
            text = f.read()
        with open(L.learnings_path(), "w") as f:
            f.write(text.replace('"title": "make sisi cycle handle stub 1"', '"title": "hand edited"', 1))
        lifecycle.repair_learnings()
        self.assertFalse(L.is_registered(L.get(self.rows(), "L-0001")))


class Origin(Base):
    """R-11.6-2, R-16-5 (item 9): an origin project is the main repository, never a worktree's path."""

    def test_a_linked_worktree_records_the_main_repository(self):
        main = os.path.join(self.tmp, "main")
        os.makedirs(main)
        self.git_init(main)
        wt = os.path.join(self.tmp, "wt-linked")
        subprocess.run(["git", "worktree", "add", "-q", "-b", "side", wt], cwd=main, check=True, capture_output=True)
        self.assertEqual(L.project_key(wt), os.path.realpath(main))
        # even when the helper that finds the main repository fails, the key is not the worktree's path
        import unittest.mock
        with unittest.mock.patch("sisi.groundtruth.main_repo_of", side_effect=RuntimeError("boom")):
            self.assertEqual(L.project_key(wt), os.path.realpath(main))
        _contract(self, "uw", wt)
        r = self.retro(*PROMOTE[1:], cwd=wt)
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = self.rows()[0]
        self.assertEqual(rec["origin_project"], os.path.realpath(main))
        self.assertEqual(rec["provenance"][0]["project"], os.path.realpath(main))

    def test_a_deleted_worktree_path_resolves_to_its_main_repository(self):
        main = os.path.join(self.home, "Code", "proj")
        os.makedirs(main)
        self.git_init(main)
        dead = os.path.join(self.home, ".t3", "worktrees", "proj", "t3-abc123")
        self.assertEqual(L.normalize_project(dead), os.path.realpath(main))

    def test_a_mechanism_whose_project_is_gone_waits_for_the_owner(self):
        """Item 9: nothing can show it works in a project that no longer exists on disk."""
        self.git_init()
        _contract(self)
        self.retro(*PROMOTE[1:])
        rows = self.rows()
        gone = os.path.join(self.tmp, "deleted-project")
        rows[0]["origin_project"] = gone
        L.save_learnings(rows, "test", touched=rows, via="test")
        r = self.apply([{"action": "promote", "learning": "L-0001", "mechanism_kind": "risk",
                         "pattern": "f.txt", "profile": "critical"}])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.pending()), 1)
        self.assertIn("no longer exists", self.pending()[0]["reasons"][0])
        self.assertFalse(self.exists("overlay/risk-adjustments.json"))

    def test_a_requirement_whose_when_no_code_evaluates_is_refused(self):
        """Item 9: free text in `when` can never trigger; a risk profile or a path glob can."""
        from sisi import cycle
        self.git_init()
        _contract(self)
        self.retro(*PROMOTE[1:])
        req = {"action": "promote", "learning": "L-0001", "mechanism_kind": "contract-requirement",
               "require_kind": "parsing"}
        for when in ("csv import", "when the user mentions money", "data and stuff"):
            r = self.apply([dict(req, when=when)])
            self.assertEqual(r.returncode, 2, when)
            self.assertIn("not something the code evaluates", r.stderr)
        r = self.apply([dict(req, when="data", require_kind="property")])
        self.assertIn("require_kind", r.stderr)
        # evaluated: a profile (that or a higher one) and a path glob
        c = {"goal": "g", "risk": {"profile": "critical"}, "checks": []}
        self.assertFalse(cycle._requirement_met(c, dict(req, when="data"), self.proj))
        self.assertTrue(cycle._requirement_met(dict(c, risk={"profile": "logic"}), dict(req, when="data"), self.proj))
        self.assertTrue(cycle._requirement_met(dict(c, checks=[{"kind": "parsing", "rung": 3}]), dict(req, when="data"), self.proj))
        os.makedirs(os.path.join(self.proj, "src", "auth"))
        self.write("src/auth/login.py", "x = 1\n")
        self.assertFalse(cycle._requirement_met(c, dict(req, when="src/auth/**"), self.proj))
        self.assertTrue(cycle._requirement_met(c, dict(req, when="src/billing/**"), self.proj))
        self.assertEqual(self.apply([dict(req, when="src/auth/**")]).returncode, 0)


class Duplicates(Base):
    """R-11.5-11, R-16-8 (item 5): no second decision about something already waiting."""

    def test_a_learning_that_already_waits_cannot_be_promoted_again(self):
        self.git_init()
        _contract(self)
        self.retro(*PROMOTE[1:])
        act = {"action": "promote", "learning": "L-0001", "mechanism_kind": "command-check", "cmd": "make deploy"}
        self.assertEqual(self.apply([act]).returncode, 0)
        r = self.apply([dict(act, cmd="make deploy2")], base=L.store_base())
        self.assertEqual(r.returncode, 2)
        self.assertIn("already waits for the owner (P-0001)", r.stderr)
        self.assertEqual(len(self.pending()), 1)

    def test_a_second_replacement_of_the_same_rule_is_refused_while_the_first_waits(self):
        _contract(self)
        a, b = "L-0001", None
        self.another(0)
        b = self.another(1)
        text = "## Deliver {#deliver-fast}\n\nShip it.\n\nWhy: speed.\n"
        rep = lambda lid: {"action": "promote", "learning": lid, "mechanism_kind": "rule-replace",
                           "rule_id": "deliver-fast", "rule_text": text,
                           "shortens": "nothing: the rule is already short"}
        self.assertEqual(self.apply([rep(a)]).returncode, 0)
        r = self.apply([rep(b)], base=L.store_base())
        self.assertEqual(r.returncode, 2)
        self.assertIn("rule deliver-fast already has a change waiting (P-0001)", r.stderr)
        # two in one file: the second is refused too, and so is disabling a rule with a change waiting
        c, d = self.another(2), self.another(3)
        rep2 = lambda lid: dict(rep(lid), rule_id="orchestrate", rule_text="## O {#orchestrate}\n\nDelegate.\n\nWhy: cost.\n")
        r = self.apply([rep2(c), rep2(d)], base=L.store_base())
        self.assertIn("in this file", r.stderr)
        r = self.apply([{"action": "disable-rule", "rule_id": "deliver-fast"}], base=L.store_base())
        self.assertIn("already has a change", r.stderr)
        self.assertEqual(len(self.pending()), 1)
