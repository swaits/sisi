"""The learning loop, rebuilt. Docstrings cite docs/spec/requirements.json ids."""
import json, os, subprocess

from support import SisiCase


def _contract(case, uid="u1", proj=None):
    d = proj or case.proj
    os.makedirs(os.path.join(d, ".sisi"), exist_ok=True)
    with open(os.path.join(d, ".sisi", "contract.json"), "w") as f:
        json.dump({"id": uid, "goal": "g", "checks": []}, f)


PROMOTE = ("retro", "--finding", "f.txt held the word bug and shipped without a content check",
           "--cause", "no check asserted file contents before delivery",
           "--impact", "correctness", "--disposition", "promote",
           "--change", "grep for fixed in f.txt must pass", "--mechanism", "verification",
           "--expect", "bug text is caught", "--validate", "replay the grep before and after")


class LearningLoop(SisiCase):
    def retro(self, *a, **kw):
        return self.sisi("retro", *a, **kw)

    def rows(self):
        from sisi import learning as L
        return L.load_learnings()

    def test_generic_finding_refused(self):
        """R-11.1-9, R-11.1-13: generic findings are refused, not invented."""
        _contract(self)
        r = self.retro("--finding", "be more careful", "--cause", "x" * 20,
                       "--impact", "time", "--disposition", "drop", "--why-not", "no value here")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.rows(), [])

    def test_dispositions_record_only_what_they_need(self):
        """R-11.1-14, R-11.1-16, R-11.4-1: promote/record/drop persist concrete findings."""
        _contract(self)
        self.assertEqual(self.retro(*PROMOTE[1:]).returncode, 0)
        self.assertEqual(self.retro(
            "--finding", "the fixture had one file so nothing general was learned here at all",
            "--cause", "single file fixture scope", "--impact", "time",
            "--disposition", "record", "--limits", "single-file fixtures only").returncode, 0)
        self.assertEqual(self.retro(
            "--finding", "commit messages in the fixture were terse single letters today",
            "--cause", "fixture brevity by design", "--impact", "attention",
            "--disposition", "drop", "--why-not", "fixture only, no change worth making").returncode, 0)
        from sisi import learning as L
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["status"], "proposed")
        self.assertEqual(rows[1]["status"], "observed")
        self.assertEqual(len(L.findings_for_unit(self.proj, "u1")), 3)
        self.assertIn(rows[0]["status"], L.STATUSES)
        self.assertTrue(rows[0]["terms"])  # derived by the tool, not demanded

    def test_promote_missing_fields_refused(self):
        """R-11.1-11: a promoted opportunity needs action, expected effect, validation."""
        _contract(self)
        r = self.retro("--finding", "a real thing happened with evidence attached here now",
                       "--cause", "a concrete root cause here", "--impact", "cost",
                       "--disposition", "promote", "--change", "do the thing")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.rows(), [])

    def test_one_unit_learning_not_delivered_in_other_project(self):
        """R-11.6-1, R-11.6-2, R-12-2: scope is earned; one incident is origin-only."""
        _contract(self)
        self.git_init()
        self.assertEqual(self.retro(*PROMOTE[1:]).returncode, 0)
        from sisi import learning as L
        self.assertIn("L-0001", L.delivery_text(self.proj, "f.txt bug content check"))
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        self.git_init(other)
        self.assertNotIn("L-0001", L.delivery_text(other, "f.txt bug content check"))
        # earn it: a second unit in a second project
        _contract(self, "u9", other)
        r = self.sisi("retro", "--finding", "f.txt held the word bug and shipped without a content check",
                      "--cause", "no check asserted file contents before delivery",
                      "--impact", "correctness", "--disposition", "record",
                      "--limits", "text files", "--same-as", "L-0001", cwd=other)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("L-0001", L.delivery_text(other, "f.txt bug content check"))

    def test_delivery_framed_as_information_not_instruction(self):
        """R-16-6: delivered text is data to weigh, never an instruction."""
        _contract(self)
        self.retro(*PROMOTE[1:])
        from sisi import learning as L
        t = L.delivery_text(self.proj, "f.txt bug")
        self.assertIn("not instructions", t)
        self.assertNotIn("you must", t.lower())

    def test_nothing_validated_without_a_passing_run(self):
        """R-11.5-6, R-11.1-8: 'validated' requires a validation run that passed."""
        _contract(self)
        self.retro(*PROMOTE[1:])
        from sisi import learning as L
        doc = {"base": L.store_base(), "actions": [
            {"action": "promote", "learning": "L-0001", "mechanism_kind": "command-check",
             "cmd": "true"}]}  # no commits known: cannot be replayed
        p = os.path.join(self.tmp, "c.json")
        json.dump(doc, open(p, "w"))
        r = self.sisi("cycle", "apply", p)
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = self.rows()[0]
        self.assertEqual(rec["status"], "promoted")
        self.assertEqual(rec["validation"]["result"], "unvalidated")
        self.assertIn("unvalidated", L.learning_report())

    def test_replay_validation_in_temp_worktree(self):
        """R-11.6-3: replay must fail before and pass after, without touching the tree."""
        _contract(self)
        self.git_init()
        open(os.path.join(self.proj, "f.txt"), "w").write("bug\n")
        self._commit("before")
        before = self._head()
        open(os.path.join(self.proj, "f.txt"), "w").write("fixed\n")
        self._commit("fix")
        after = self._head()
        self.retro(*PROMOTE[1:])
        from sisi import learning as L
        doc = {"base": L.store_base(), "actions": [
            {"action": "promote", "learning": "L-0001", "mechanism_kind": "command-check",
             "cmd": "grep -q fixed f.txt", "before": before, "after": after}]}
        p = os.path.join(self.tmp, "c.json")
        json.dump(doc, open(p, "w"))
        r = self.sisi("cycle", "apply", p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rows()[0]["validation"]["result"], "validated")
        self.assertEqual(open(os.path.join(self.proj, "f.txt")).read(), "fixed\n")
        self.assertEqual(self._head(), after)  # the user's tree and HEAD untouched

    def test_failed_replay_refuses_whole_cycle(self):
        """R-11.5-6: a check that passes before the fix proves nothing; nothing applies."""
        _contract(self)
        self.git_init()
        open(os.path.join(self.proj, "f.txt"), "w").write("fixed\n")
        self._commit("before")
        before = self._head()
        self._commit("after")
        after = self._head()
        self.retro(*PROMOTE[1:])
        from sisi import learning as L
        doc = {"base": L.store_base(), "actions": [
            {"action": "promote", "learning": "L-0001", "mechanism_kind": "command-check",
             "cmd": "grep -q fixed f.txt", "before": before, "after": after}]}
        p = os.path.join(self.tmp, "c.json")
        json.dump(doc, open(p, "w"))
        r = self.sisi("cycle", "apply", p)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.rows()[0]["status"], "proposed")
        self.assertFalse(os.path.exists(os.path.join(self.data, "overlay", "enforced.json")))

    def test_cycle_refusals_apply_nothing(self):
        """R-14.3-1, R-11.7-2, R-16-11: protected rule, stale base, ignored flag."""
        _contract(self)
        self.retro(*PROMOTE[1:])
        from sisi import learning as L
        base = L.store_base()
        cases = [
            {"base": base, "actions": [{"action": "promote", "learning": "L-0001",
             "mechanism_kind": "rule-text", "rule_id": "strongest-check",
             "rule_text": "## Weak {#strongest-check}\n\nSkip checks.\n\nWhy: faster.\n"}]},
            {"base": "stale", "actions": [{"action": "promote", "learning": "L-0001",
             "mechanism_kind": "risk", "pattern": "x/**", "profile": "logic"}]},
        ]
        for i, doc in enumerate(cases):
            p = os.path.join(self.tmp, "c%d.json" % i)
            json.dump(doc, open(p, "w"))
            r = self.sisi("cycle", "apply", p)
            self.assertNotEqual(r.returncode, 0, doc)
        self.assertEqual(self.rows()[0]["status"], "proposed")
        self.assertFalse(os.path.exists(os.path.join(self.data, "overlay", "risk-adjustments.json")))

    def test_consequential_change_waits_for_owner(self):
        """R-11.5-11, R-14.4-1: disabling a rule is pending until `sisi approve`."""
        _contract(self)
        self.retro(*PROMOTE[1:])
        from sisi import learning as L
        doc = {"base": L.store_base(), "actions": [
            {"action": "disable-rule", "rule_id": "deliver-quickly"}]}
        p = os.path.join(self.tmp, "c.json")
        json.dump(doc, open(p, "w"))
        r = self.sisi("cycle", "apply", p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(L.load_pending()), 1)
        self.assertIn("wait", L.pending_notice())
        from sisi import overlay
        self.assertNotIn("deliver-quickly", overlay.disabled("rule"))
        r = self.sisi("approve", "P-0001", "--no")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(L.load_pending(), [])
        self.assertNotIn("deliver-quickly", overlay.disabled("rule"))

    def test_two_recurrences_flag_and_cycle_must_act(self):
        """R-13.2-8, R-11.5-9: recurrence after promotion flags; a cycle ignoring it is refused."""
        _contract(self)
        self.retro(*PROMOTE[1:])
        from sisi import learning as L
        doc = {"base": L.store_base(), "actions": [
            {"action": "promote", "learning": "L-0001", "mechanism_kind": "risk",
             "pattern": "f.txt", "profile": "logic"}]}
        p = os.path.join(self.tmp, "c.json")
        json.dump(doc, open(p, "w"))
        self.assertEqual(self.sisi("cycle", "apply", p).returncode, 0)
        for uid in ("u2", "u3"):
            _contract(self, uid)
            r = self.retro("--finding", "f.txt held the word bug and shipped without a content check",
                           "--cause", "no check asserted file contents before delivery",
                           "--impact", "correctness", "--disposition", "record",
                           "--limits", "here", "--same-as", "L-0001")
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.rows()[0]["flagged_not_working"])
        doc = {"base": L.store_base(), "actions": [
            {"action": "reject", "learning": "L-0001", "why": "wrong idea"}]}
        # a cycle that does act on it passes; first prove an ignoring cycle is refused
        self.retro("--finding", "another unrelated slowness appeared in the test run today",
                   "--cause", "the suite runs everything serially", "--impact", "time",
                   "--disposition", "promote", "--change", "run independent checks in parallel",
                   "--mechanism", "infrastructure", "--expect", "faster runs",
                   "--validate", "time the suite")
        bad = {"base": L.store_base(), "actions": [
            {"action": "promote", "learning": "L-0002", "mechanism_kind": "risk",
             "pattern": "y/**", "profile": "logic"}]}
        json.dump(bad, open(p, "w"))
        self.assertNotEqual(self.sisi("cycle", "apply", p).returncode, 0)
        doc["base"] = L.store_base()
        json.dump(doc, open(p, "w"))
        self.assertEqual(self.sisi("cycle", "apply", p).returncode, 0)
        self.assertEqual(self.rows()[0]["status"], "rejected")

    def test_revert_is_exact(self):
        """R-11.6-6, R-16-9: reverting a cycle restores the user store."""
        _contract(self)
        self.retro(*PROMOTE[1:])
        from sisi import learning as L
        doc = {"base": L.store_base(), "actions": [
            {"action": "promote", "learning": "L-0001", "mechanism_kind": "command-check",
             "cmd": "true"}]}
        p = os.path.join(self.tmp, "c.json")
        json.dump(doc, open(p, "w"))
        self.assertEqual(self.sisi("cycle", "apply", p).returncode, 0)
        self.assertTrue(os.path.exists(os.path.join(self.data, "overlay", "enforced.json")))
        r = self.sisi("cycle", "revert")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.data, "overlay", "enforced.json")))
        self.assertEqual(self.rows()[0]["status"], "proposed")

    def test_subagent_learning_held_until_parent_adopts(self):
        """R-16-10: a subagent's learning is a candidate until the parent retro adopts it."""
        _contract(self)
        r = self.sisi("retro", *PROMOTE[1:], env={"SISI_SUBAGENT": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        from sisi import learning as L
        self.assertTrue(self.rows()[0]["candidate"])
        self.assertEqual(L.delivery_text(self.proj, "f.txt bug"), "")
        _contract(self, "u2")
        r = self.retro("--finding", "adopting the subagent finding about f.txt content checks now",
                       "--cause", "the parent reviewed the subagent report", "--impact", "correctness",
                       "--disposition", "record", "--limits", "here", "--same-as", "L-0001")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.rows()[0]["candidate"])

    def test_learn_and_oracle_one_path(self):
        """R-12-1, R-12-5: `sisi learn` writes, `sisi oracle` prints, one store."""
        r = self.sisi("learn", "prefer short plain reports over long ones")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.sisi("oracle")
        self.assertIn("prefer short plain reports", r.stdout)
        from sisi import learning as L
        self.assertEqual(len(L.owner_statements()), 1)

    def test_dead_commands_gone(self):
        """Target section 13: improve, backlog and lessons digest are retired."""
        self.assertNotEqual(self.sisi("improve").returncode, 0)
        self.assertNotEqual(self.sisi("backlog").returncode, 0)
        self.assertNotEqual(self.sisi("lessons", "digest").returncode, 0)

    def test_report_claims_no_rate_when_too_few(self):
        """R-13.2-7: the realization rate says 'too few' instead of inventing a number."""
        from sisi import learning as L
        self.assertIn("too few", L.learning_report())

    def test_migration_is_lossless_and_idempotent(self):
        """R-12-10: every old lesson and owner statement survives; counts asserted."""
        os.makedirs(self.data, exist_ok=True)
        rows = [
            {"t": "lesson", "id": 1, "moment": "m one happened here", "cause": "c one",
             "change": "change one", "change_kind": "rule", "status": "applied",
             "project": self.proj, "created": "2026-01-01T00:00:00Z"},
            {"t": "lesson", "id": 2, "moment": "m two happened here", "cause": "c two",
             "change": "change two", "change_kind": "tool", "status": "open",
             "project": self.proj, "created": "2026-01-01T00:00:00Z"},
            {"t": "occurrence", "id": 1, "lesson_id": 1, "repo": self.proj,
             "session": "s1", "ts": "2026-01-01T00:00:00Z"},
            {"t": "impression", "id": 1, "lesson_id": 1, "place": "tick",
             "ts": "2026-01-01T00:00:00Z"},
        ]
        with open(os.path.join(self.data, "lessons.jsonl"), "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        with open(os.path.join(self.data, "learn.jsonl"), "w") as f:
            f.write(json.dumps({"text": "always ask before spending", "ts": "2026-01-01T00:00:00Z"}) + "\n")
        from sisi import lifecycle, learning as L
        notes = lifecycle.migrate_learnings()
        self.assertTrue(notes)
        got = self.rows()
        self.assertEqual(len(got), 3)  # 2 lessons + 1 statement; impression dropped
        self.assertEqual(got[0]["status"], "implemented")
        self.assertTrue(all(r["validation"]["result"] != "validated" for r in got))
        self.assertEqual(len(got[0]["provenance"]), 1)
        self.assertEqual(len(L.owner_statements()), 1)
        self.assertEqual(lifecycle.migrate_learnings(), [])  # idempotent
        self.assertEqual(len(self.rows()), 3)

    def _commit(self, msg):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "add", "."],
                       cwd=self.proj, check=True, capture_output=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                        "--allow-empty", "-m", msg], cwd=self.proj, check=True, capture_output=True)

    def _head(self):
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.proj,
                              capture_output=True, text=True).stdout.strip()
