"""Hardening of the learning cycle after a real rehearsal. Docstrings cite docs/spec/requirements.json ids.

Each test is an abuse case: the cycle file's author (an agent, untrusted) tries to get something
to run, validate or take effect that nobody approved.
"""
import json, os, subprocess, sys

from support import SisiCase
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
