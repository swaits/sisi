"""The end-of-turn gate: risk-set requirements, bounded send-backs, attribution, pauses, subagents.

Tests cite requirement ids (docs/spec/requirements.json). The property tests run seeded random
sequences of operations against a real git project and check invariants after every stop; scale them
with SISI_TEST_ITERS."""
import io, json, os, random, subprocess, sys, time, unittest
from unittest import mock
from support import *
from sisi import assure, attribution, contract as C, gate, learning, store, unit as U, workers


def _tool_line(name, inp):
    return {"type": "assistant", "timestamp": "2026-01-01T00:00:00.000Z",
            "message": {"role": "assistant", "content": [{"type": "tool_use", "name": name, "input": inp}]}}


def _human_line():
    return {"type": "user", "timestamp": "2026-01-01T00:00:00.000Z",
            "message": {"role": "user", "content": "do the work please"}}


def full(**over):
    """A contract that satisfies every requirement of every profile except independent evidence."""
    c = contract([dict(check("works", "test -f ok.txt"), covers="the feature file is missing")],
                 [dict(check("keeps", "test -f README.md"), covers="the readme is deleted")])
    c.update(id="t", goal="make the feature work",
             requirements=[{"id": "r1", "kind": "explicit", "text": "ok.txt exists when the feature is done", "decision": "now"}],
             risk={"blast_radius": "only the feature file; nothing else reads it", "rollback": "git revert the commit"},
             approach={"chosen": "write the file directly", "why": "the simplest thing that works",
                       "alternatives": ["generate it from a template: more moving parts"]},
             started=store.now(), status="open", pauses=[], deviations=[])
    c.update(over)
    return c


class GateBase(SisiCase):
    sid = "sess-1"

    def setUp(self):
        super().setUp()
        os.environ["SISI_RETRO_REQUIRED"] = "1"  # these tests are about the retro: turn it on
        self.addCleanup(lambda: os.environ.__setitem__("SISI_RETRO_REQUIRED", "0"))
        self.git_init()
        self.put("README.md", "# project\n")
        self.put("ok.txt", "ready\n")
        self.commit_all()
        self.tdir = os.path.join(self.tmp, "transcripts")
        os.makedirs(self.tdir)

    def put(self, rel, text="x\n", mode="w"):
        p = os.path.join(self.proj, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, mode) as f:
            f.write(text)
        return p

    def commit_all(self, msg="c"):
        subprocess.run(["git", "add", "-A"], cwd=self.proj, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg], cwd=self.proj, check=True)

    def session(self, sid=None):
        return Sess(self, sid or self.sid)

    def call(self, cwd=None, sid=None, **extra):
        """Run the gate in process as the hook would, with no transcript (every tree change is this session's)."""
        payload = dict({"session_id": sid or self.sid, "cwd": cwd or self.proj, "hook_event_name": "Stop",
                        "stop_hook_active": False}, **extra)
        return gate.decide(payload)

    def hook(self, payload=None, cwd=None, args=()):
        """Run the real hook command: JSON stdin, stdout, exit code."""
        p = dict({"session_id": self.sid, "cwd": self.proj, "hook_event_name": "Stop"}, **(payload or {}))
        return self.sisi("gate", *args, cwd=cwd, stdin=json.dumps(p))

    def unit_state(self):
        c = C.load(os.path.join(self.proj, C.REL))
        c.setdefault("status", "open")
        return c

    def archives(self):
        d = os.path.join(self.proj, ".sisi", "units")
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def record_finding(self, n=1, cwd=None, sid=None):
        r = self.sisi("retro",
                      "--finding", "`cargo test` run %d took 4 minutes with no fuzz verifier in the project" % n,
                      "--cause", "the recipe never named a fuzz verifier for parsers",
                      "--impact", "time", "--disposition", "promote",
                      "--change", "Add the fuzz verifier to the parser-or-codec recipe Checks, variant %d" % n,
                      "--mechanism", "verification", "--expect", "parser work gets a fuzz check",
                      "--validate", "run the recipe checks on a parser change", cwd=cwd,
                      env={"SISI_SESSION_ID": sid or self.sid})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def lines(self, msg):
        return len(str(msg).splitlines())


class Sess:
    """One agent session in the test project: a Claude-Code-shaped transcript that records its edits,
    the session-start hook, and the stop hook."""

    def __init__(self, case, sid):
        self.case, self.sid = case, sid
        self.tp = os.path.join(case.tdir, sid + ".jsonl")
        with open(self.tp, "w") as f:
            f.write(json.dumps(_human_line()) + "\n")
        case.sisi("tick", stdin=json.dumps({"session_id": sid, "cwd": case.proj, "source": "startup",
                                            "transcript_path": self.tp}))

    def _line(self, name, inp):
        with open(self.tp, "a") as f:
            f.write(json.dumps(_tool_line(name, inp)) + "\n")

    def edit(self, rel, text="x\n"):
        """The agent edits a file with its edit tool."""
        p = self.case.put(rel, text, mode="a")
        self._line("Edit", {"file_path": p})
        return p

    def write(self, rel, text):
        p = self.case.put(rel, text)
        self._line("Write", {"file_path": p})
        return p

    def remove(self, rel):
        os.remove(os.path.join(self.case.proj, rel))
        self._line("Bash", {"command": "rm " + rel})

    def shell(self, command):
        self._line("Bash", {"command": command})

    def contract(self, c):
        """The agent writes the contract file (a claim on the unit)."""
        self.case.write_contract(c)
        self._line("Write", {"file_path": os.path.join(self.case.proj, C.REL)})

    def stop(self):
        """('allow'|'block', message or None) from the real hook entry point."""
        r = self.case.sisi("gate", stdin=json.dumps({"session_id": self.sid, "cwd": self.case.proj,
                                                     "hook_event_name": "Stop", "transcript_path": self.tp}))
        self.case.assertEqual(r.returncode, 0, r.stderr)
        if not r.stdout.strip():
            return "allow", None
        d = json.loads(r.stdout)
        return ("block", d["reason"]) if d.get("decision") == "block" else ("allow", d.get("systemMessage"))


# ======================================================================== requirements by profile

class RequirementTests(GateBase):
    """R-5.3-1..11: the gate enforces exactly what the profile's row of canon/risk.json requires."""

    def test_the_table_is_monotone_in_the_profile(self):
        """R-5.3-2: a higher profile never requires less (seeded random contracts)."""
        rng = random.Random(7)
        keys = ["requirements", "risk", "approach", "invariants"]
        for _ in range(40 * ITERS):
            c = full()
            for k in keys:
                if rng.random() < 0.5:
                    c.pop(k, None) if k != "invariants" else c.update(invariants=[])
            if rng.random() < 0.5:
                c["checks"][0].pop("covers")
            lows = [assure.missing(p, c, self.proj) for p in ("isolated", "logic", "integration", "data", "critical", "release")]
            for a, b in zip(lows, lows[1:]):
                self.assertTrue({m[0] for m in a} <= {m[0] for m in b}, (c, a, b))

    def test_trivial_needs_nothing_and_isolated_needs_a_contract_with_a_check(self):
        """R-5.3-4, R-5.3-5."""
        self.assertEqual(assure.missing("trivial", None, self.proj), [])
        miss = assure.missing("isolated", None, self.proj)
        self.assertEqual(len(miss), 1)
        self.assertIn("sisi contract init", miss[0][1])
        self.assertEqual(assure.missing("isolated", contract([check("a", "false")]), self.proj), [])

    def test_logic_needs_covers_on_every_check(self):
        """R-5.3-6."""
        c = contract([check("a", "false"), dict(check("b", "false"), covers="the parser drops a line")])
        miss = assure.missing("logic", c, self.proj)
        self.assertEqual(len(miss), 1)
        self.assertIn("a", miss[0][0])
        self.assertNotIn("(missing on a, b)", miss[0][0])
        self.assertEqual(assure.missing("logic", full(), self.proj), [])

    def test_integration_needs_invariants_requirements_a_risk_note_and_an_approach(self):
        """R-5.3-7: each missing piece is named, with the field that supplies it."""
        c = full(invariants=[], requirements=[], risk={}, approach=None)
        text = " | ".join("%s -> %s" % m for m in assure.missing("integration", c, self.proj))
        for field in ('"invariants"', '"requirements"', '"risk"', '"approach"'):
            self.assertIn(field, text)
        self.assertEqual(assure.missing("integration", full(), self.proj), [])

    def test_data_critical_and_release_need_independent_evidence(self):
        """R-5.3-8, R-5.3-9, R-5.3-10."""
        for p in ("data", "critical", "release"):
            miss = assure.missing(p, full(), self.proj)
            self.assertEqual(len(miss), 1, p)
            self.assertIn("independent", miss[0][0])
        self.assertEqual(assure.missing("integration", full(), self.proj), [])

    def test_the_table_is_data_not_code(self):
        """R-5.3-1: a project that edits the table's row changes what the gate asks, with no code change."""
        from sisi import risk
        row = risk.requirements_for("logic")
        self.assertTrue(row["covers"])
        with mock.patch.object(risk, "requirements_for", return_value=dict(row, covers=False)):
            self.assertEqual(assure.missing("logic", contract([check("a", "false")]), self.proj), [])

    def test_a_declared_profile_raises_freely(self):
        """R-5.3-1."""
        p, info = assure.effective_profile("isolated", full(risk={"profile": "data"}))
        self.assertEqual((p, info["lowered"]), ("data", False))

    def test_floor_wins_over_a_trivial_declaration_without_a_reason(self):
        """R-5.3-1, abuse: declares `trivial` on a migration with no `risk.why`: the floor wins."""
        p, info = assure.effective_profile("data", full(risk={"profile": "trivial"}))
        self.assertEqual((p, info["refused"], info["lowered"]), ("data", True, False))
        for why in ("TODO", "n/a", "none", ""):
            p, info = assure.effective_profile("data", full(risk={"profile": "trivial", "why": why}))
            self.assertEqual(p, "data", why)

    def test_lowering_with_a_reason_is_allowed_recorded_and_visible_in_status(self):
        """R-5.3-1, abuse: with a reason the declaration stands; the record keeps floor, declared and reason."""
        c = full(risk={"profile": "trivial", "why": "the migration only adds a comment to a table"})
        p, info = assure.effective_profile("data", c)
        self.assertEqual((p, info["lowered"]), ("trivial", True))
        self.git_init_unit = None
        self.put("migrations/001_comment.sql", "COMMENT ON TABLE t IS 'x';\n")
        self.write_contract(c)
        c_path = os.path.join(self.proj, C.REL)
        rec = U.build_record(c, self.proj, "delivered", time.time(), rows=[])
        self.assertEqual((rec["risk"]["floor"]["value"], rec["risk"]["declared"], rec["risk"]["lowered"]),
                         ("data", "trivial", True))
        self.assertEqual(rec["risk"]["why"], "the migration only adds a comment to a table")
        out = self.sisi("status").stdout
        self.assertIn("lowered: declared trivial below the floor data: the migration only adds a comment", out)
        self.assertTrue(os.path.exists(c_path))

    def test_placeholder_text_is_not_a_requirement_a_risk_note_or_an_approach(self):
        """R-5.3-7, abuse: present but empty, or placeholder text, counts as missing."""
        for junk in ("TODO", "n/a", "none", "TBD", "", "  ", "-", "ok", "TODO: fill in later"):
            c = full(requirements=[{"id": "r1", "kind": "explicit", "text": junk, "decision": "now"}],
                     risk={"blast_radius": junk, "rollback": junk},
                     approach={"chosen": junk, "why": junk, "alternatives": [junk]})
            text = " | ".join(m[0] for m in assure.missing("integration", c, self.proj))
            for piece in ("requirement list", "risk note", "the approach"):
                self.assertIn(piece, text, "%r: %s" % (junk, piece))
        self.assertTrue(C.is_placeholder("N/A"))
        self.assertFalse(C.is_placeholder("git revert the commit and rerun the migration"))

    def test_an_approach_needs_an_alternative(self):
        """R-5.3-7."""
        c = full(approach={"chosen": "write the file directly", "why": "the simplest thing", "alternatives": []})
        self.assertIn("the approach", " ".join(m[0] for m in assure.missing("integration", c, self.proj)))

    def test_independent_flag_without_by_is_not_evidence(self):
        """R-5.3-9, abuse: `independent: true` with no `by` (or a placeholder `by`)."""
        results = [{"id": "works", "status": "passed"}]
        for by in (None, "", "TODO", "n/a"):
            ck = dict(check("works", "test -f ok.txt"), covers="the file is missing", independent=True)
            if by is not None:
                ck["by"] = by
            c = full(checks=[ck])
            self.assertEqual(assure.independent_evidence(self.proj, c, results), [], by)
        ck = dict(check("works", "test -f ok.txt"), covers="the file is missing", independent=True,
                  by="the reference parser in tools/ref.py")
        c = full(checks=[ck])
        self.assertEqual(len(assure.independent_evidence(self.proj, c, results)), 1)
        self.assertEqual(assure.independent_evidence(self.proj, c, [{"id": "works", "status": "failed"}]), [])
        self.assertEqual(assure.missing("data", c, self.proj, results), [])

    def judged(self, **over):
        row = {"kind": "attempt", "id": "a1", "ts": round(time.time()), "project": os.path.basename(self.proj),
               "type": "review", "difficulty": 2, "worker": "reviewer-model", "outcome": "accepted", "check": "read"}
        row.update(over)
        workers.append_record(row)

    def test_a_judged_review_in_the_window_is_independent_evidence(self):
        """R-5.3-9."""
        c = full(started=store.now())
        self.assertEqual(len(assure.missing("data", c, self.proj)), 1)
        self.judged()
        self.assertEqual(assure.missing("data", c, self.proj), [])

    def test_review_rows_that_do_not_count(self):
        """R-5.3-9, abuse: outside the window, another project, rejected, checked with `none`, not a review."""
        c = full(started=store.now())
        for over in ({"ts": round(time.time()) - 7200}, {"project": "some-other-project"}, {"outcome": "rejected"},
                     {"check": "none"}, {"check": None}, {"type": "impl"}):
            self.judged(**over)
        self.assertEqual(assure.review_evidence(self.proj, c), [])
        self.assertEqual(len(assure.missing("data", c, self.proj)), 1)
        self.judged(check="diffstat")  # stronger than none: counts
        self.assertEqual(len(assure.review_evidence(self.proj, c)), 1)

    def test_a_technique_stronger_than_examples(self):
        """R-5.3-6."""
        self.assertFalse(assure.stronger_technique(contract([check("a", "false", rung=3)])))
        self.assertTrue(assure.stronger_technique(contract([check("a", "false", rung=2)])))
        self.assertTrue(assure.stronger_technique(contract([check("a", "false", rung=4)], [check("i", "false", rung=1)])))


# ======================================================================== the flow

class FlowTests(GateBase):
    def test_a_session_that_changed_nothing_passes_silently(self):
        """R-17-3: no change, no check run, no message."""
        self.write_contract(full(checks=[check("bad", "false")]))
        s = self.session()
        self.assertEqual(s.stop(), ("allow", None))
        self.assertEqual(self.results(), [])

    def test_documentation_only_passes_silently_even_with_a_failing_unit_open(self):
        """R-5.3-4, R-17-3."""
        self.write_contract(contract([check("bad", "false")]))
        s = self.session()
        s.edit("README.md", "more words\n")
        self.assertEqual(s.stop(), ("allow", None))

    def test_a_source_change_without_a_contract_is_sent_back_once_with_the_list(self):
        """R-5.3-5, R-17-5."""
        s = self.session()
        s.write("app.py", "def f():\n    return 1\n")
        a, msg = s.stop()
        self.assertEqual(a, "block")
        self.assertIn("a contract for this isolated change", msg)
        self.assertIn("sisi contract init", msg)
        self.assertLessEqual(self.lines(msg), 25)
        self.assertEqual(s.stop()[0], "block")  # still nothing: sent back again (and counted)

    def test_failing_check_sends_back_then_green_offers_the_two_ways_on(self):
        """R-10.3-4, R-10.3-6: failing is sent back with the failure; green offers retro or pause, once."""
        s = self.session()
        s.write("app.py", "x = 1\n")
        s.contract(contract([check("feature", "test -f done.flag")]))
        a, msg = s.stop()
        self.assertEqual(a, "block")
        self.assertIn("feature", msg)
        self.assertIn("Failing checks", msg)
        s.write("done.flag", "ok\n")
        a, msg = s.stop()
        self.assertEqual(a, "block")
        self.assertIn("sisi retro", msg)
        self.assertIn("sisi unit pause", msg)
        self.assertLessEqual(self.lines(msg), 25)
        self.assertEqual(s.stop(), ("allow", None))  # said once: not repeated for the same tree

    def test_pause_is_silent_and_a_new_change_ends_the_wait(self):
        """R-10.3-1: abuse: a pause with no change asks nothing; a change ends it."""
        s = self.session()
        s.write("app.py", "x = 1\n")
        s.contract(contract([check("feature", "test -f ok.txt")]))
        self.assertEqual(s.stop()[0], "block")  # the offer
        self.assertEqual(self.sisi("unit", "pause", "the reviewer").returncode, 0)
        self.assertEqual(s.stop(), ("allow", None))
        self.assertEqual(self.unit_state()["status"], "paused")
        s.edit("app.py", "y = 2\n")
        a, msg = s.stop()
        self.assertEqual(self.unit_state()["status"], "open")  # the wait ended
        self.assertEqual(a, "block")
        self.assertIn("sisi retro", msg)

    def test_a_pause_is_never_a_way_to_hide(self):
        """R-15-13, abuse: init refuses while a unit is open (or paused); status lists both with their age."""
        s = self.session()
        s.write("app.py", "x = 1\n")
        s.contract(contract([check("feature", "test -f ok.txt")]) | {"started": store.now()})
        self.sisi("unit", "pause", "waiting for ever")
        r = self.sisi("contract", "init")
        self.assertEqual(r.returncode, 1)
        self.assertIn("still open", r.stdout)
        out = self.sisi("status").stdout
        self.assertRegex(out, r"paused\s+t\s+age \d+[mhd]\s+waiting for: waiting for ever")
        c = self.unit_state()
        c["status"] = "open"
        C.save(os.path.join(self.proj, C.REL), c)
        self.assertRegex(self.sisi("status").stdout, r"open\s+t\s+age \d+[mhd]")

    def test_a_recorded_retro_closes_and_archives_the_unit(self):
        """R-10.3-5, R-10.3-7."""
        s = self.session()
        s.write("app.py", "x = 1\n")
        s.contract(contract([check("feature", "test -f ok.txt")]))
        self.assertEqual(s.stop()[0], "block")  # offer
        self.record_finding()
        self.assertEqual(s.stop(), ("allow", None))
        self.assertEqual(self.unit_state()["status"], "closed")
        self.assertEqual(self.archives(), ["t.json"])
        self.assertEqual(s.stop(), ("allow", None))

    def test_a_generic_finding_does_not_close_the_unit(self):
        """R-10.3-7, abuse: the learning module refuses it, so the gate has nothing to close on."""
        s = self.session()
        s.write("app.py", "x = 1\n")
        s.contract(contract([check("feature", "test -f ok.txt")]))
        self.assertEqual(s.stop()[0], "block")
        r = self.sisi("retro", "--finding", "it went well", "--cause", "no cause", "--impact", "time",
                      "--disposition", "record", "--limits", "none", env={"SISI_SESSION_ID": self.sid})
        self.assertEqual(learning.findings_for_unit(self.proj, "t"), [], r.stdout)
        s.edit("app.py", "y = 2\n")
        a, msg = s.stop()
        self.assertEqual(a, "block")
        self.assertIn("sisi retro", msg)
        self.assertEqual(self.unit_state()["status"], "open")
        self.assertEqual(self.archives(), [])

    def test_a_retro_recorded_after_a_quiet_stop_still_closes_the_unit(self):
        """R-10.3-7: the offer was ignored once; the retro is recorded later with no edit."""
        s = self.session()
        s.write("app.py", "x = 1\n")
        s.contract(contract([check("feature", "test -f ok.txt")]))
        s.stop()
        self.assertEqual(s.stop(), ("allow", None))  # offered once; not repeated; unit still open
        self.assertEqual(self.unit_state()["status"], "open")
        self.record_finding()
        self.assertEqual(s.stop(), ("allow", None))
        self.assertEqual(self.unit_state()["status"], "closed")

    def test_a_trivial_unit_asks_nothing_unless_it_shows_an_anomaly(self):
        """R-5.3-4: nothing is asked for a trivial change; two send-backs make the retro worth asking."""
        self.write_contract(contract([check("feature", "test -f ok.txt")], ) | {"risk": {"profile": "trivial"}})
        s = self.session()
        s.contract(contract([check("feature", "test -f ok.txt")]) | {"risk": {"profile": "trivial"}})
        s.edit("README.md", "words\n")
        self.assertEqual(s.stop(), ("allow", None))  # quiet
        st = store.load_session(self.sid)
        st["sb_unit"] = 2  # two send-backs earlier in this unit
        store.save_session(self.sid, st)
        s.edit("README.md", "more words\n")
        a, msg = s.stop()
        self.assertEqual(a, "block")
        self.assertIn("sisi retro", msg)
        self.assertIn("sent the agent back 2 times", msg)
        self.assertEqual(s.stop(), ("allow", None))  # asked once

    def test_declaring_trivial_on_a_migration_without_a_reason_does_not_lower_it(self):
        """R-5.3-8, abuse: end to end through the gate."""
        s = self.session()
        s.write("migrations/001_users.sql", "CREATE TABLE users (id integer);\n")
        s.contract(full(risk={"profile": "trivial", "blast_radius": "one table, nothing reads it yet",
                              "rollback": "drop the table"}))
        a, msg = s.stop()
        self.assertEqual(a, "block")
        self.assertIn("declares 'trivial', but the change is 'data'", msg)
        self.assertIn("independent evidence", msg)

    def test_a_migration_with_a_reason_runs_at_the_lowered_profile(self):
        """R-5.3-8, abuse."""
        s = self.session()
        s.write("migrations/001_users.sql", "COMMENT ON TABLE users IS 'people';\n")
        s.contract(full(risk={"profile": "trivial", "why": "a comment on a table changes no data"}))
        self.assertEqual(s.stop(), ("allow", None))  # trivial: nothing asked
        self.assertIn("lowered", self.sisi("status").stdout)

    def test_removing_a_failing_check_does_not_make_the_unit_read_as_delivered(self):
        """R-10.3-3, R-15-6, abuse: the check fails, the agent deletes it, the unit is not plainly delivered."""
        s = self.session()
        s.write("app.py", "x = 1\n")
        s.contract(contract([check("good", "test -f ok.txt"), check("hard", "test -f never.txt")]))
        a, msg = s.stop()
        self.assertEqual(a, "block")
        self.assertIn("hard", msg)
        c = self.unit_state()
        c["checks"] = [x for x in c["checks"] if x["id"] != "hard"]
        s.contract(c)
        self.assertEqual(s.stop()[0], "block")  # the offer
        self.record_finding()
        self.assertEqual(s.stop(), ("allow", None))
        with open(os.path.join(self.proj, ".sisi", "units", "t.json")) as f:
            rec = json.load(f)
        failed = [r for r in rec["verification"] if r["check"] == "hard" and r["status"] == "failed"]
        self.assertTrue(failed)  # the failed result is in the record
        self.assertNotIn("hard", [x["id"] for x in rec["contract"]["checks"]])  # and so is the removal

    def test_green_technique_note_is_given_once_and_never_blocks(self):
        """R-5.3-6: a logic change with no check stronger than examples."""
        s = self.session()
        s.write("parser.py", "def parse(s):\n    return s.split()\n")
        s.contract(full(risk={"profile": "logic", "blast_radius": "the parser only", "rollback": "revert"}))
        a, msg = s.stop()
        self.assertEqual(a, "block")  # the offer, carrying the note
        self.assertIn("sisi verifiers for", msg)
        s.edit("parser.py", "# more\n")
        a, msg = s.stop()
        self.assertNotIn("sisi verifiers for", msg or "")  # once
        rec = U.build_record(self.unit_state(), self.proj, "delivered", time.time(), rows=[])
        self.assertFalse(rec["stronger_technique"])

    def test_waive_lets_a_change_without_a_contract_end_and_is_a_recorded_deviation(self):
        """R-10.3-2: a waiver is a deviation, never a pass."""
        s = self.session()
        s.write("app.py", "x = 1\n")
        self.assertEqual(s.stop()[0], "block")
        self.assertEqual(self.sisi("contract", "waive", "a throwaway script").returncode, 0)
        self.assertEqual(s.stop(), ("allow", None))
        self.assertEqual(store.read("waivers")[0]["reason"], "a throwaway script")

    def test_disabled_allows(self):
        self.write_contract(contract([check("bad", "false")]))
        os.makedirs(self.state, exist_ok=True)
        with open(os.path.join(self.state, "config.json"), "w") as f:
            json.dump({"gate": {"enabled": False}}, f)
        s = self.session()
        s.write("app.py", "x = 1\n")
        self.assertEqual(s.stop(), ("allow", None))

    def test_not_a_git_repo_allows(self):
        d = os.path.join(self.tmp, "plain")
        os.makedirs(d)
        self.assertEqual(self.call(cwd=d), ("allow", None))

    def test_the_contract_is_found_from_a_subdirectory(self):
        self.write_contract(contract([check("bad", "false")]) | {"risk": {"profile": "isolated"}})
        os.makedirs(os.path.join(self.proj, "sub"))
        a, msg = self.call(cwd=os.path.join(self.proj, "sub"))
        self.assertEqual(a, "block")
        self.assertIn("bad", msg)

    def test_a_check_over_the_budget_is_reported_not_passed(self):
        """R-15-5: a check that cannot finish in time is not-run, never passed."""
        with open(os.path.join(self.tmp, "cfg"), "w"):
            pass
        os.makedirs(self.state, exist_ok=True)
        with open(os.path.join(self.state, "config.json"), "w") as f:
            json.dump({"gate": {"budget_s": 0.4}}, f)
        self.write_contract(contract([check("a", "sleep 3", timeout_s=60), check("b", "test -f ok.txt")]) | {"risk": {"profile": "isolated"}})
        a, msg = self.call()
        self.assertEqual(a, "block")
        self.assertEqual({r["check"]: r["status"] for r in self.results()}, {"a": "not-run", "b": "not-run"})


# ======================================================================== bounded send-backs

class SendBackTests(GateBase):
    def setUp(self):
        super().setUp()
        self.s = self.session()
        self.s.write("migrations/001_users.sql", "CREATE TABLE users (id integer);\n")
        self.s.contract(full())  # everything but the independent evidence a migration needs

    def test_the_migration_send_back_lists_what_is_missing_in_plain_words(self):
        """R-17-5, R-5.3-8: one message, the missing evidence named with the command that supplies it."""
        a, msg = self.s.stop()
        self.assertEqual(a, "block")
        self.assertIn("this data change is not ready to hand over (send-back 1 of 3)", msg)
        self.assertIn("independent evidence", msg)
        self.assertIn("sisi delegate judge", msg)
        self.assertIn('"independent": true', msg)
        self.assertLessEqual(self.lines(msg), 25)

    def test_without_a_contract_the_whole_list_comes_at_once(self):
        """R-17-5: every missing piece in one message, within 25 lines."""
        s = self.session("other")
        self.put("src/db/schema.sql", "CREATE TABLE a (id integer);\n")
        os.remove(os.path.join(self.proj, C.REL))
        s.edit("src/db/schema.sql", "-- more\n")
        a, msg = s.stop()
        self.assertEqual(a, "block")
        for piece in ("a contract", "covers", "invariants", "a requirement list", "a risk note", "the approach",
                      "independent evidence"):
            self.assertIn(piece, msg)
        self.assertLessEqual(self.lines(msg), 25)

    def test_three_send_backs_then_released_as_unverified_and_recorded(self):
        """R-10.3-4, R-15-13, R-17-7."""
        acts = [self.s.stop()[0] for _ in range(3)]
        self.assertEqual(acts, ["block"] * 3)
        a, msg = self.s.stop()
        self.assertEqual(a, "allow")
        self.assertIn("UNVERIFIED", msg)
        self.assertIn("independent evidence", msg)
        self.assertIn("Report the work as unverified", msg)
        row = [r for r in self.results() if r.get("check") == "gate"][-1]
        self.assertEqual(row["status"], "unverified")
        self.assertIn("independent evidence", row["reason"])
        c = self.unit_state()
        self.assertIn("independent evidence", " ".join(c["unverified"]["why"]))
        self.s.stop()
        rec = U.build_record(c, self.proj, U.decide_status(c, [])[0], time.time(), rows=[])
        self.assertEqual(rec["delivery_status"], "unverified")
        self.assertIn("independent", " ".join(rec["released_unverified"]["why"]))
        self.assertIn("released unverified by the gate", self.sisi("status").stdout)

    def test_release_then_a_new_change_counts_afresh(self):
        for _ in range(4):
            self.s.stop()
        self.s.edit("migrations/001_users.sql", "-- touch\n")
        self.assertEqual(self.s.stop()[0], "block")

    def test_a_waiver_is_a_deviation_and_never_green(self):
        """R-10.3-3: waived units close as `deviation`."""
        self.sisi("contract", "waive", "--check", "works", "the reviewer is on leave")
        c = self.unit_state()
        self.assertEqual(U.decide_status(c, [])[0], "deviation")

    def test_independent_evidence_through_the_ledger_ends_the_send_backs(self):
        """R-5.3-9."""
        self.assertEqual(self.s.stop()[0], "block")
        workers.append_record({"kind": "attempt", "id": "r1", "ts": round(time.time()), "project": os.path.basename(self.proj),
                               "type": "review", "difficulty": 2, "worker": "reviewer-model",
                               "outcome": "accepted", "check": "read"})
        a, msg = self.s.stop()
        self.assertEqual(a, "block")
        self.assertIn("sisi retro", msg)  # now only the offer remains
        self.assertNotIn("independent evidence", msg)

    def test_independent_evidence_through_a_named_passing_check(self):
        """R-5.3-9."""
        c = self.unit_state()
        c["checks"][0].update(independent=True, by="the reference migration tool")
        self.s.contract(c)
        a, msg = self.s.stop()
        self.assertIn("sisi retro", msg)

    def test_independent_without_by_still_sends_back(self):
        """R-5.3-9, abuse through the gate."""
        c = self.unit_state()
        c["checks"][0].update(independent=True)
        self.s.contract(c)
        a, msg = self.s.stop()
        self.assertEqual(a, "block")
        self.assertIn("independent evidence", msg)


# ======================================================================== other sessions, subagents

class AttributionTests(GateBase):
    """R-9-1, R-15-9: two sessions, one folder: the gate judges only this session's own edits."""

    def test_another_sessions_uncommitted_edits_never_send_this_session_back(self):
        """Abuse: B breaks the tree and edits a migration; A made no edit of its own."""
        a, b = self.session("sess-a"), self.session("sess-b")
        b.write("migrations/002_orders.sql", "CREATE TABLE orders (id integer);\n")
        b.contract(contract([check("c", "false")]))
        self.assertEqual(a.stop(), ("allow", None))
        self.assertEqual(self.results(), [])  # nothing was even run for A
        a.edit("README.md", "my own words\n")  # A's own change is documentation
        self.assertEqual(a.stop(), ("allow", None))

    def test_this_sessions_own_source_change_is_judged_on_its_own_paths(self):
        a, b = self.session("sess-a"), self.session("sess-b")
        b.write("migrations/002_orders.sql", "CREATE TABLE orders (id integer);\n")
        a.write("app.py", "x = 1\n")
        action, msg = a.stop()
        self.assertEqual(action, "block")
        self.assertIn("isolated change", msg)  # not 'data': B's migration is not A's work
        self.assertNotIn("migrations", msg)

    def test_shell_edits_count_and_read_only_shell_does_not(self):
        a = self.session("sess-a")
        a.shell("ls -la; git status --short; cat README.md")
        self.put("app.py", "someone else wrote this\n")
        self.assertEqual(a.stop(), ("allow", None))
        a.shell("echo hi > out.py")
        self.put("out.py", "hi\n")
        self.assertEqual(a.stop()[0], "block")  # a command that may write: the change is this session's

    def test_a_missing_or_corrupt_transcript_is_strict(self):
        """R-15-5: when the gate cannot tell, the change is the session's."""
        self.put("app.py", "x = 1\n")
        for name, body in (("missing.jsonl", None), ("corrupt.jsonl", "not json at all\n{{{\n")):
            tp = os.path.join(self.tdir, name)
            if body:
                with open(tp, "w") as f:
                    f.write(body)
            a, msg = gate.decide({"session_id": "s-" + name, "cwd": self.proj, "transcript_path": tp})
            self.assertEqual(a, "block", name)

    def test_only_the_new_tail_of_the_transcript_is_read(self):
        s = self.session("sess-tail")
        self.assertEqual(s.stop(), ("allow", None))
        size = os.path.getsize(s.tp)
        self.assertEqual(store.load_session("sess-tail")["attr_offset"], size)
        with open(s.tp, "a") as f:
            f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "x" * 5000}}) + "\n")
        s.write("app.py", "x = 1\n")
        self.assertEqual(s.stop()[0], "block")
        self.assertEqual(store.load_session("sess-tail")["attr_gen"], 1)  # counted once, not rescanned

    def test_native_subagent_edits_are_the_parents_edits(self):
        """R-9-1: the parent answers for what its subagents wrote."""
        a = self.session("sess-a")
        subdir = os.path.join(self.tdir, "sess-a", "subagents")
        os.makedirs(subdir)
        with open(os.path.join(subdir, "agent-x1.jsonl"), "w") as f:
            f.write(json.dumps(_human_line()) + "\n")
            f.write(json.dumps(_tool_line("Edit", {"file_path": os.path.join(self.proj, "app.py")})) + "\n")
        self.put("app.py", "x = 1\n")
        self.assertEqual(a.stop()[0], "block")

    def test_shell_classifier(self):
        for cmd in ("sed -i 's/a/b/' f.txt", "echo x > out.txt", "git apply p.diff", "python3 scripts/build.py",
                    "sisi contract init", "python3 tests/run_parallel.py"):
            self.assertTrue(attribution.shell_may_write(cmd), cmd)
        for cmd in ("ls -la; git status; cat f.txt", "sisi verify", "grep -rn foo sisi/", "git commit -qm x",
                    "gh run list", "sisi retro --aim speed --moment m"):
            self.assertFalse(attribution.shell_may_write(cmd), cmd)
        self.assertIsNone(attribution.shell_may_write("echo 'unterminated"))
        self.assertIs(gate._shell_may_write, attribution.shell_may_write)  # watch.py reaches it here

    def test_snapshot_ignores_commits_and_gitignored_files(self):
        from sisi import gitutil
        s0 = gitutil.snapshot(self.proj)
        self.put("README.md", "changed\n", mode="a")
        self.assertIn("README.md", gitutil.snapshot_diff(s0, gitutil.snapshot(self.proj)))
        self.commit_all()
        s1 = gitutil.snapshot(self.proj)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "e"],
                       cwd=self.proj, check=True)
        self.assertEqual(gitutil.snapshot_diff(s1, gitutil.snapshot(self.proj)), [])
        self.put(".gitignore", "ignored.txt\n")
        s2 = gitutil.snapshot(self.proj)
        self.put("ignored.txt", "")
        self.assertNotIn("ignored.txt", gitutil.snapshot_diff(s2, gitutil.snapshot(self.proj)))


class WatchTests(GateBase):
    """R-9-1: measured shell attribution: a command's real effect on the tree, not its text."""

    def setUp(self):
        super().setUp()
        self.put("noop.py", "print('nothing written')\n")
        self.put("gen.py", "open('generated.py', 'w').write('x = 1\\n')\n")
        self.commit_all()

    def watch(self, s, command, during=None, after=True):
        s.shell(command)
        base = {"session_id": s.sid, "cwd": self.proj, "transcript_path": s.tp,
                "tool_name": "Bash", "tool_input": {"command": command}}
        r = self.sisi_proc("watch", stdin=json.dumps(dict(base, hook_event_name="PreToolUse")))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        if during:
            during()
        if after:
            r = self.sisi_proc("watch", stdin=json.dumps(dict(base, hook_event_name="PostToolUse")))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def run_in_proj(self, *argv):
        return subprocess.run(argv, cwd=self.proj, check=True, capture_output=True, text=True)

    def test_an_orchestrator_that_only_runs_commands_never_edits(self):
        a = self.session("orch")
        self.assertEqual(a.stop(), ("allow", None))
        for cmd, during in (("python3 noop.py", lambda: self.run_in_proj(sys.executable, "noop.py")),
                            ("git commit -qm x", lambda: self.run_in_proj("git", "commit", "-q", "--allow-empty", "-m", "x")),
                            ("gh run list", None)):
            self.watch(a, cmd, during=during)
        self.assertFalse(store.load_session("orch").get("attr_since_pass"))
        self.put("app.py", "another session wrote this\n")
        self.assertEqual(a.stop(), ("allow", None))

    def test_a_command_that_writes_a_project_file_is_an_edit_of_that_path(self):
        a = self.session("gen")
        self.watch(a, "python3 gen.py", during=lambda: self.run_in_proj(sys.executable, "gen.py"))
        self.assertIn("generated.py", store.load_session("gen").get("attr_since_pass", []))
        self.put("app.py", "another session wrote this\n")
        action, msg = a.stop()
        self.assertEqual(action, "block")
        self.assertIn("isolated change", msg)

    def test_a_command_that_writes_only_outside_the_project_is_not_an_edit(self):
        a = self.session("out")
        outside = os.path.join(self.tmp, "outside.txt")
        self.put("gen_out.py", "open(%r, 'w').write('elsewhere\\n')\n" % outside)
        self.commit_all()
        self.watch(a, "python3 gen_out.py", during=lambda: self.run_in_proj(sys.executable, "gen_out.py"))
        self.assertTrue(os.path.exists(outside))
        self.assertFalse(store.load_session("out").get("attr_since_pass"))
        self.assertEqual(a.stop(), ("allow", None))

    def test_a_missing_after_record_is_strict(self):
        a = self.session("kill")
        self.watch(a, "python3 gen.py", after=False)  # killed: no PostToolUse ever arrives
        self.put("app.py", "x = 1\n")
        self.assertEqual(a.stop()[0], "block")

    def commit_notice(self, command):
        return self.sisi_proc("watch", "--before", stdin=json.dumps(
            {"session_id": "w", "cwd": self.proj, "hook_event_name": "PreToolUse", "tool_name": "Bash",
             "tool_input": {"command": command}})).stdout

    def test_commit_time_notice_when_the_checks_have_not_passed_on_this_tree(self):
        """R-5.6-1: said at `git commit`, once per commit, never a block."""
        self.write_contract(contract([check("feature", "test -f ok.txt")]))
        out = self.commit_notice("git commit -am wip")
        d = json.loads(out)
        self.assertIn("sisi verify", d["systemMessage"])
        self.assertEqual(d["hookSpecificOutput"]["additionalContext"], d["systemMessage"])
        self.assertIn("sisi verify", json.loads(self.commit_notice("cd x && git merge main"))["systemMessage"])
        self.assertEqual(self.commit_notice("git status"), "")
        self.assertEqual(self.sisi("verify").returncode, 0)
        self.assertEqual(self.commit_notice("git commit -am wip"), "")  # passed on this very tree
        self.put("app.py", "x = 1\n")
        self.assertIn("sisi verify", self.commit_notice("git commit -am wip"))  # the tree moved on
        os.remove(os.path.join(self.proj, C.REL))
        self.assertEqual(self.commit_notice("git commit -am wip"), "")  # no unit: nothing to say


class SubagentTests(GateBase):
    """R-17-7: a subagent's last message is its report to its parent."""

    def payload(self, **extra):
        return dict({"session_id": "parent", "cwd": self.proj, "hook_event_name": "SubagentStop", "agent_id": "ag-1"}, **extra)

    def test_a_subagent_stop_is_never_blocked_and_asks_for_nothing(self):
        """Abuse: a subagent that edited source, with a failing contract and no retro."""
        self.write_contract(contract([check("bad", "false")]))
        tp = os.path.join(self.tmp, "agent-ag-1.jsonl")
        with open(tp, "w") as f:
            f.write(json.dumps(_tool_line("Write", {"file_path": os.path.join(self.proj, "app.py")})) + "\n")
        self.put("app.py", "x = 1\n")
        pl = self.payload(agent_transcript_path=tp)
        self.assertEqual(gate.decide_subagent(pl), ("allow", None))
        self.assertEqual(gate.decide(pl), ("allow", None))  # even by the main entry
        r = self.sisi("gate", "--subagent", stdin=json.dumps(pl))
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        r = self.sisi("gate", stdin=json.dumps(pl))
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertEqual(self.results(), [])

    def test_what_the_subagent_observed_reaches_the_parents_gate(self):
        """A subagent that wrote makes the parent's next stop a stop after an edit."""
        tp = os.path.join(self.tmp, "agent-ag-1.jsonl")
        with open(tp, "w") as f:
            f.write(json.dumps(_tool_line("Write", {"file_path": os.path.join(self.proj, "app.py")})) + "\n")
        parent = self.session("parent")
        self.put("app.py", "x = 1\n")
        gate.decide_subagent(self.payload(agent_transcript_path=tp))
        row = store.read("subagents")[0]
        self.assertEqual((row["session"], row["edited"]), ("parent", True))
        a, msg = parent.stop()
        self.assertEqual(a, "block")
        self.assertIn("isolated change", msg)

    def test_a_session_marked_as_a_subagent_is_never_sent_back(self):
        self.put("app.py", "x = 1\n")
        st = store.load_session("child") or {}
        st["subagent"] = True
        store.save_session("child", st)
        self.assertEqual(self.call(sid="child"), ("allow", None))


# ======================================================================== fail open, trust

class GateFailOpenTests(GateBase):
    def test_internal_error_allows_and_logs(self):
        self.write_contract(contract([check("bad", "false")]))
        with mock.patch.object(gate, "decide", side_effect=RuntimeError("kaboom")), \
                mock.patch.object(sys, "stdin", io.StringIO("{}")), mock.patch.object(sys, "stdout", io.StringIO()) as out:
            self.assertEqual(gate.main(), 0)
            self.assertEqual(out.getvalue(), "")
        with open(os.path.join(self.state, "errors.log")) as f:
            self.assertIn("kaboom", f.read())

    def test_unwritable_state_allows(self):
        self.write_contract(contract([check("bad", "false")]))
        os.makedirs(self.state, exist_ok=True)
        open(os.path.join(self.state, "sessions"), "w").close()  # session records can no longer be written
        r = self.hook()
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_garbage_stdin_allows(self):
        self.assertEqual(self.sisi("gate", stdin="not json").stdout, "")
        self.assertEqual(self.sisi("gate", stdin="").stdout, "")

    def test_corrupt_session_and_config_files(self):
        os.makedirs(os.path.join(self.state, "sessions"))
        with open(os.path.join(self.state, "sessions", "sess-1.json"), "w") as f:
            f.write("{{{")
        with open(os.path.join(self.state, "config.json"), "w") as f:
            f.write("nope")
        self.write_contract(contract([check("bad", "false")]))
        self.assertEqual(self.hook().returncode, 0)

    def test_an_unreadable_contract_is_reported_not_crashed_on(self):
        os.makedirs(os.path.join(self.proj, ".sisi"))
        with open(os.path.join(self.proj, C.REL), "w") as f:
            f.write("{not json")
        from sisi import trust
        trust.add(self.proj)
        self.put("app.py", "x = 1\n")
        a, msg = self.call()
        self.assertEqual(a, "block")
        self.assertIn("cannot read contract", msg)


class GateTrustTests(GateBase):
    """A contract that arrived with a clone is never executed without approval."""

    def setUp(self):
        super().setUp()
        self.marker = os.path.join(self.tmp, "ran")
        self.write_contract(contract([check("evil", "touch %s; false" % self.marker)]) | {"risk": {"profile": "isolated"}},
                            trusted=False)

    def test_gate_allows_with_one_notice_and_runs_nothing(self):
        r = self.hook()
        msg = json.loads(r.stdout)["systemMessage"]
        self.assertIn("untrusted", msg)
        self.assertIn("sisi contract trust", msg)
        self.assertEqual(self.hook().stdout, "")  # notice only once per session
        self.assertFalse(os.path.exists(self.marker))

    def test_verify_refuses_with_distinct_exit(self):
        r = self.sisi("verify")
        self.assertEqual(r.returncode, 3)
        self.assertFalse(os.path.exists(self.marker))

    def test_trust_then_untrust(self):
        self.assertEqual(self.sisi("contract", "trust").returncode, 0)
        self.assertEqual(json.loads(self.hook().stdout)["decision"], "block")
        self.assertTrue(os.path.exists(self.marker))
        os.remove(self.marker)
        self.sisi("contract", "untrust")
        self.assertEqual(self.sisi("verify").returncode, 3)
        self.assertFalse(os.path.exists(self.marker))


# ======================================================================== seeded sequences

class GateSequenceTests(GateBase):
    """Seeded random sequences of operations against a real project; the invariants are checked after
    every stop. A failing seed is printed with the operations that led to it."""

    OPS = ["edit_src", "edit_src", "edit_doc", "break", "fix", "stop", "stop", "retro", "pause", "other_edits", "other_breaks"]

    def run_sequence(self, seed, steps=14):
        rng = random.Random(seed)
        proj_note = "seed %d" % seed
        a = self.session("seq-a-%d" % seed)
        b = self.session("seq-b-%d" % seed)
        a.write("app.py", "x = 0\n")
        a.contract(contract([check("feature", "test -f ok.txt")]))
        log, last_action, consecutive_blocks, paused, n_retro = [], None, 0, False, 0
        for step in range(steps):
            op = rng.choice(self.OPS)
            log.append(op)
            if op == "edit_src":
                a.edit("app.py", "x = %d\n" % step)
                paused = False
            elif op == "edit_doc":
                a.edit("README.md", "line %d\n" % step)
                paused = False
            elif op == "break" and os.path.exists(os.path.join(self.proj, "ok.txt")):
                a.remove("ok.txt")
                paused = False
            elif op == "fix":
                a.write("ok.txt", "ready\n")
                paused = False
            elif op == "retro":
                n_retro += 1
                self.record_finding(n_retro, sid=a.sid)
            elif op == "pause" and self.unit_state().get("status") == "open":
                self.sisi("unit", "pause", "waiting for the reviewer %d" % step)
                paused = True
            elif op == "other_edits":
                b.edit("other.py", "y = %d\n" % step)
            elif op == "other_breaks":
                b.write("migrations/%03d.sql" % step, "CREATE TABLE t%d (id integer);\n" % step)
            if op != "stop":
                continue
            action, msg = a.stop()
            where = "%s ops=%s" % (proj_note, log)
            self.assertLessEqual(self.lines(msg), 25, where)
            ok_now = os.path.exists(os.path.join(self.proj, "ok.txt"))
            c = self.unit_state()
            if action == "block":
                consecutive_blocks += 1
                self.assertLessEqual(consecutive_blocks, 3 + 4, where)  # bounded: offers are not counted
            else:
                consecutive_blocks = 0
                if msg and "UNVERIFIED" in msg:
                    last_action = "released"
            # invariant: a unit is archived only after a retro was recorded for it
            if c.get("status") == "closed":
                self.assertTrue(learning.findings_for_unit(self.proj, "t"), where)
                self.assertEqual(self.archives(), ["t.json"], where)
                return
            # invariant: no silent pass with a failing check and a source change pending,
            # unless the unit is paused with no change since, or the gate released it as unverified
            if action == "allow" and msg is None and not ok_now and c.get("status") == "open" \
                    and not c.get("unverified"):
                st = store.load_session(a.sid)
                self.assertFalse(st.get("dirty"), where)  # then nothing of this session's was pending
            # invariant: a stop right after a silent allow, with nothing in between, is silent again
            if action == "allow" and msg is None:
                self.assertEqual(a.stop(), ("allow", None), where)

    def test_seeded_sequences(self):
        seeds = [0, 1, 2, random.randrange(2 ** 32)] + [random.randrange(2 ** 32) for _ in range(ITERS - 1)]
        for seed in seeds:
            with self.subTest(seed=seed):
                self.setUp_again()
                self.run_sequence(seed)

    def setUp_again(self):
        """A clean project and state for the next seed."""
        import shutil
        shutil.rmtree(self.proj, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)
        shutil.rmtree(self.data, ignore_errors=True)
        os.makedirs(self.proj)
        self.git_init()
        self.put("README.md", "# project\n")
        self.put("ok.txt", "ready\n")
        self.commit_all()

    def test_another_sessions_work_never_touches_this_sessions_stops(self):
        """R-15-9: for any sequence of B's edits and breakages, A (which does nothing) is never sent back."""
        for seed in range(3 * ITERS):
            with self.subTest(seed=seed):
                self.setUp_again()
                rng = random.Random(seed)
                a, b = self.session("a%d" % seed), self.session("b%d" % seed)
                self.assertEqual(a.stop(), ("allow", None))
                for step in range(8):
                    op = rng.choice(["src", "doc", "migration", "break", "contract", "secret"])
                    if op == "src":
                        b.edit("b%d.py" % step, "y = 1\n")
                    elif op == "doc":
                        b.edit("README.md", "b %d\n" % step)
                    elif op == "migration":
                        b.write("migrations/%03d.sql" % step, "CREATE TABLE x (id integer);\n")
                    elif op == "break" and os.path.exists(os.path.join(self.proj, "ok.txt")):
                        b.remove("ok.txt")
                    elif op == "contract" and not os.path.exists(os.path.join(self.proj, C.REL)):
                        b.contract(contract([check("c", "false")]))
                    elif op == "secret":
                        b.write("config/secrets.env", "PASSWORD=hunter2\n")
                    self.assertEqual(a.stop(), ("allow", None), "seed %d step %d %s" % (seed, step, op))


if __name__ == "__main__":
    unittest.main()
