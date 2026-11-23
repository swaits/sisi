"""The learning loop: lessons take effect at once, are delivered at the moment they match, are measured,
climb the strength ladder, and are consolidated by `sisi cycle`. Nothing here uses a scheduler: due-ness
is a counter checked in tick, the gate, retro, verify and done-for, announced at most once per session
until 20 further checks pass or the counter grows."""
import json, os, random, sqlite3, time, unittest
from support import *
from sisi import cycle, gate, overlay, paths, pdata, retro, store
from test_verifiers import LibCase, vfile, dfile

PARSER_CHANGE = "Prefer a readiness probe over a fixed sleep when waiting for parser servers to answer"
CSV_WHEN = "csv, tsv, spreadsheet, tabular data, import, export, parse, delimited file"
PARSER_WHEN = "parser, server readiness, startup wait, readiness probe, dev server, waiting"


def fields(**kw):
    f = dict(aim="verified", change_kind="rule", target=None,
             moment="the parser server waited 90 seconds in step 4 of the nightly job",
             cause="no readiness probe existed before the browser step",
             change=PARSER_CHANGE)
    f.update(kw)
    return f


class LearningCase(LibCase):
    def setUp(self):
        super().setUp()
        self.put("prove/fuzz.md", vfile("fuzz"))
        self.put("parser-or-codec.md", dfile("parser-or-codec"), self.ddir)
        self.notes = os.path.join(self.data, "notes")

    def mk(self, **kw):
        con = retro.connect()
        try:
            lid = retro.new_lesson(con, fields(**kw), self.proj, None)
            con.commit()
            return lid
        finally:
            con.close()

    def lesson(self, lid):
        con = retro.connect()
        try:
            return dict(con.execute("SELECT * FROM lessons WHERE id=?", (lid,)).fetchone())
        finally:
            con.close()

    def again(self, lid):
        con = retro.connect()
        try:
            retro.add_occurrence(con, lid, "again the parser server waited in step 7", self.proj, None)
            con.commit()
        finally:
            con.close()

    def cycle_doc(self, **parts):
        doc = {"version": 1, "base": cycle.base_version(), "summary": "test cycle"}
        doc.update(parts)
        p = os.path.join(self.tmp, "cycle.json")
        with open(p, "w") as f:
            json.dump(doc, f)
        return p

    def overlay_bytes(self):
        out = {}
        base = paths.overlay_dir()
        for dp, dns, fns in os.walk(base):
            for n in fns:
                p = os.path.join(dp, n)
                with open(p, "rb") as f:
                    out[os.path.relpath(p, base)] = f.read()
        return out


class ImmediateEffectTests(LearningCase):
    def test_field_note_on_first_occurrence_verifier_and_recipe(self):
        a = self.mk(change_kind="verifier", target="fuzz",
                    change="Say in the fuzz notes: seed the corpus from the golden files before fuzzing parsers")
        b = self.mk(change_kind="recipe", target="parser-or-codec",
                    change="Add the readiness probe to the parser-or-codec recipe Checks for server work")
        for lid, target in ((a, "fuzz"), (b, "parser-or-codec")):
            l = self.lesson(lid)
            self.assertEqual((l["status"], l["effect"], l["folded_into"]), ("applied", "field-note", target))
            self.assertIn("lesson %d" % lid, open(os.path.join(self.notes, target + ".md")).read())
        self.again(a)  # a later occurrence never duplicates the bullet
        self.assertEqual(open(os.path.join(self.notes, "fuzz.md")).read().count("seed the corpus"), 1)

    def test_draft_recipe_note_for_a_recipe_that_does_not_exist(self):
        lid = self.mk(change_kind="recipe", target="curated-record-change",
                      change="Add a recipe 'curated-record-change' for editing a sourced record in a curated dataset")
        l = self.lesson(lid)
        self.assertEqual((l["effect"], l["folded_into"]), ("draft-recipe", "draft:curated-record-change"))
        self.assertTrue(os.path.exists(os.path.join(self.notes, "draft-curated-record-change.md")))
        out = self.sisi("done", "for", "editing a sourced record in a curated dataset").stdout
        self.assertIn("Draft recipe curated-record-change", out)
        miss = self.sisi("done", "for", "quantum chromodynamics lattice gauge").stdout
        self.assertNotIn("Draft recipe", miss)

    def test_rule_oracle_brief_become_learned_notes_with_triggers(self):
        for kind in ("rule", "oracle", "brief"):
            lid = self.mk(change_kind=kind, change=PARSER_CHANGE + " (%s)" % kind,
                          moment="moment for %s at step 2 of the upload" % kind)
            l = self.lesson(lid)
            self.assertEqual(l["effect"], "learned-note")
            self.assertIn("pars", l["triggers"])  # stems: parser/parsing/parse all meet at 'pars'
            self.assertTrue(l["applied_at"])

    def test_tool_lessons_backlog_order_and_dev_mode_tick_line(self):
        a = self.mk(change_kind="tool", change="Make the gate count session edits separately per session")
        b = self.mk(change_kind="tool", change="Make sisi verify name the slowest check first")
        c = self.mk(change_kind="tool", change="Cache transcript scans between gate decisions")
        self.again(b); self.again(b); self.again(c); self.again(c)
        out = self.sisi("backlog").stdout.splitlines()
        ids = [int(l.split()[0][1:]) for l in out if l.startswith("#")]
        self.assertEqual(ids, [b, c, a])  # most seen first; the tie goes to the older lesson
        self.assertEqual(self.lesson(b)["effect"], "backlog")
        paths.set_personal_config(("developer", "source"), self.proj, "test")
        tick = self.sisi("tick", stdin=json.dumps({"session_id": "dev1", "cwd": self.proj, "source": "startup"})).stdout
        self.assertIn("top sisi backlog #%d" % b, tick)
        other = os.path.join(self.tmp, "elsewhere"); os.makedirs(other)
        tick2 = self.sisi("tick", stdin=json.dumps({"session_id": "dev2", "cwd": other, "source": "startup"})).stdout
        self.assertNotIn("backlog", tick2)


class DeliveryTests(LearningCase):
    def setUp(self):
        super().setUp()
        self.lid = self.mk()

    def test_each_moment_appends_matching_lessons_and_records_it(self):
        checks = [
            ("done-for", lambda: self.sisi("done", "for", "parser-or-codec server readiness").stdout),
            ("verifiers-for", lambda: self.sisi("verifiers", "for", "parser server readiness probe").stdout),
            ("verifiers-show", lambda: self.sisi("verifiers", "show", "fuzz").stdout
             if False else self._show()),
        ]
        block = retro.lessons_block("parser server readiness probe", "done-for", session="s-x")
        self.assertIn("#%d" % self.lid, block)
        self.assertLessEqual(len(block), 600)
        out = checks[0][1]()
        self.assertIn("lessons from earlier agents", out)
        con = retro.connect()
        places = [r[0] for r in con.execute("SELECT place FROM impressions WHERE lesson_id=?", (self.lid,))]
        con.close()
        self.assertIn("done-for", places)
        out2 = checks[1][1]()
        self.assertIn("lessons from earlier agents", out2)

    def _show(self):
        lid = self.mk(change_kind="verifier", target="fuzz",
                      change="Seed the fuzz corpus from golden parser files before fuzzing")
        return self.sisi("verifiers", "show", "fuzz").stdout

    def test_verifiers_show_and_contract_init(self):
        out = self._show()
        self.assertIn("lessons from earlier agents", out)
        proj2 = os.path.join(self.tmp, "proj2"); os.makedirs(proj2)
        r = self.sisi("contract", "init", "--goal", "parser server readiness for uploads", cwd=proj2)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("lessons from earlier agents", r.stdout)

    def test_irrelevant_query_surfaces_nothing(self):
        self.assertEqual(retro.lessons_block("quantum chromodynamics lattice gauge theory", "done-for"), "")
        self.assertEqual(retro.match_lessons("zebra xylophone quasar"), [])

    def test_block_is_capped_at_three_and_600_characters(self):
        for i in range(8):
            self.mk(change="Parser server readiness variant %d prefers probes over fixed sleeps always" % i,
                    moment="parser wait number %d at step 3" % i)
        block = retro.lessons_block("parser server readiness probe fixed sleep", "done-for")
        self.assertLessEqual(len(block), 600)
        self.assertLessEqual(len([l for l in block.splitlines() if l.startswith("- #")]), 3)

    def test_tick_shows_highest_strength_first_and_records(self):
        strong = self.mk(change="Zebra marker lesson about caching widgets quietly", moment="widget cache step 1")
        con = retro.connect()
        con.execute("UPDATE lessons SET strength=3 WHERE id=?", (strong,))
        con.commit(); con.close()
        block = retro.tick_block(self.proj, session="tick-s")
        lines = [l for l in block.splitlines() if l.startswith("- ")]
        self.assertTrue(lines[0].startswith("- Zebra marker"), lines)
        con = retro.connect()
        self.assertTrue(con.execute("SELECT 1 FROM impressions WHERE lesson_id=? AND place='tick' AND session='tick-s'",
                                    (strong,)).fetchone())
        con.close()

    def test_gate_send_back_carries_matching_lessons(self):
        self.git_init()
        c = check("parser-readiness", "false")
        c["claim"] = "the parser server answers the readiness probe"
        self.write_contract(contract([c]))
        self.sisi("tick", stdin=json.dumps({"session_id": "g1", "cwd": self.proj, "source": "startup"}))
        with open(os.path.join(self.proj, "work.txt"), "w") as f:
            f.write("x\n")
        a, msg = gate.decide({"session_id": "g1", "cwd": self.proj})
        self.assertEqual(a, "block")
        self.assertIn("lessons from earlier agents", msg)
        self.assertIn("#%d" % self.lid, msg)


class LadderTests(LearningCase):
    def test_promotion_needs_two_showings_then_recurrence(self):
        lid = self.mk()
        self.again(lid)
        self.assertEqual(self.lesson(lid)["strength"], 1)  # never shown: no promotion
        retro.record_shown([lid], "tick", "s")
        self.again(lid)
        self.assertEqual(self.lesson(lid)["strength"], 1)  # shown once: still no
        retro.record_shown([lid], "tick", "s")
        self.again(lid)
        l = self.lesson(lid)
        self.assertEqual((l["strength"], l["needs_cycle"]), (2, 1))
        self.again(lid)  # no fresh showings since the promotion: no second step on stale evidence
        self.assertEqual(self.lesson(lid)["strength"], 2)
        retro.record_shown([lid], "tick", "s")
        self.again(lid)  # only one fresh showing: still no
        self.assertEqual(self.lesson(lid)["strength"], 2)
        retro.record_shown([lid], "tick", "s")
        self.again(lid)  # two fresh showings, another recurrence: strength 3
        self.assertEqual(self.lesson(lid)["strength"], 3)
        self.again(lid)
        self.assertEqual(self.lesson(lid)["status"], "open")  # withdrawal also needs fresh showings
        retro.record_shown([lid], "tick", "s"); retro.record_shown([lid], "tick", "s")
        self.again(lid)  # enforced, shown afresh, still recurring: withdrawn
        self.assertEqual(self.lesson(lid)["status"], "withdrawn")
        self.assertEqual(retro.match_lessons("parser server readiness probe"), [])

    def test_property_ladder_matches_a_simple_reference(self):
        def reference(events):
            s, shown, promoted_at, status = 1, 0, 0, "open"
            for ev in events:
                if status != "open":
                    continue
                if ev == "show":
                    shown += 1
                elif shown - promoted_at >= 2:
                    if s < 3:
                        s += 1
                        promoted_at = shown
                    else:
                        status = "withdrawn"
            return s, status
        for seed in [0, 1, 7] + [random.randrange(2 ** 32) for _ in range(ITERS)]:
            rng = random.Random(seed)
            events = [rng.choice(("show", "recur")) for _ in range(30)]
            lid = self.mk(change="Reference lesson %d about parser readiness probes" % seed,
                          moment="reference wait %d at step 2" % seed)
            for ev in events:
                if ev == "show":
                    retro.record_shown([lid], "tick", "ref")
                else:
                    self.again(lid)
            l = self.lesson(lid)
            got = (l["strength"], "withdrawn" if l["status"] == "withdrawn" else "open")
            self.assertEqual(got, reference(events), "seed %d" % seed)

    def test_folded_lesson_shown_twenty_times_without_recurrence_retires(self):
        lid = self.mk(change_kind="verifier", target="fuzz",
                      change="Seed the fuzz corpus from golden parser files before fuzzing")
        for _ in range(19):
            retro.record_shown([lid], "tick", "s")
        self.assertEqual(self.lesson(lid)["status"], "applied")
        retro.record_shown([lid], "tick", "s")
        self.assertEqual(self.lesson(lid)["status"], "retired")
        lid2 = self.mk(change_kind="verifier", target="fuzz",
                       change="Keep fuzz seeds beside the parser golden files always",
                       moment="fuzz seeds missing at step 5")
        retro.record_shown([lid2], "tick", "s")
        self.again(lid2)  # a recurrence after being shown: retirement must not fire
        for _ in range(20):
            retro.record_shown([lid2], "tick", "s")
        self.assertNotEqual(self.lesson(lid2)["status"], "retired")

    def test_withdrawn_lesson_is_not_relearned_in_the_same_form(self):
        lid = self.mk()
        con = retro.connect()
        con.execute("UPDATE lessons SET status='withdrawn' WHERE id=?", (lid,))
        con.commit(); con.close()
        from test_retro import argv as retro_argv, GOOD
        r = self.sisi("retro", *retro_argv(dict(GOOD, change=PARSER_CHANGE, new=True)))
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("withdrawn", r.stdout)

    def test_measurement_counts_shows_and_recurrences(self):
        lid = self.mk()
        retro.record_shown([lid], "done-for", "sess-9")
        retro.record_shown([lid], "gate", "sess-9")
        self.again(lid)
        con = retro.connect()
        row = con.execute("SELECT * FROM lessons WHERE id=?", (lid,)).fetchone()
        self.assertEqual(retro.shown_count(con, lid), 2)
        self.assertEqual(retro.recurrences_after_shown(con, row), 1)
        sess = con.execute("SELECT DISTINCT session FROM impressions WHERE lesson_id=?", (lid,)).fetchone()[0]
        self.assertEqual(sess, "sess-9")
        con.close()
        out = self.sisi("lessons", "show", str(lid)).stdout
        self.assertIn("listed 2 time(s), read 0, 1 recurrence(s)", out)


class CycleDueTests(LearningCase):
    def make_due(self, n=5):
        return [self.mk(change="Due lesson %d about parser readiness probes" % i,
                        moment="due wait %d at step 2" % i) for i in range(n)]

    def test_due_by_count_pending_and_notes_size(self):
        self.assertEqual(self.sisi("cycle", "due").returncode, 1)
        self.make_due(2)
        con = retro.connect()
        con.execute("UPDATE lessons SET needs_cycle=1 WHERE id=(SELECT min(id) FROM lessons)")
        con.commit(); con.close()
        r = self.sisi("cycle", "due")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("waiting for consolidation", r.stdout)

    def test_due_by_five_lessons_and_by_notes_size(self):
        self.make_due(5)
        r = self.sisi("cycle", "due")
        self.assertEqual(r.returncode, 0)
        self.assertIn("5 lessons recorded since the last cycle", r.stdout)
        con = retro.connect()
        con.execute("UPDATE lessons SET created='2000-01-01T00:00:00Z'")
        retro.set_meta(con, "last_cycle_ts", "2999-01-01T00:00:00Z")
        con.execute("UPDATE lessons SET change=change || ? ", (" padding" * 300,))
        con.commit(); con.close()
        st = cycle.due_state()
        self.assertTrue(any("note" in x for x in st["reasons"]), st)

    def test_no_nag_for_twenty_checks_then_again_and_counter_growth(self):
        self.make_due()
        first = cycle.due_notice(session="nag")
        self.assertIn("learning cycle is due", first)
        for _ in range(20):
            self.assertEqual(cycle.due_notice(session="nag"), "")
        self.assertIn("learning cycle is due", cycle.due_notice(session="nag"))
        self.assertEqual(cycle.due_notice(session="nag"), "")
        self.mk(change="One more parser readiness lesson arrives", moment="one more wait at step 9")
        self.assertIn("learning cycle is due", cycle.due_notice(session="nag"))  # the counter grew

    def test_due_line_in_retro_verify_done_for_gate_and_tick(self):
        self.make_due(4)
        from test_retro import argv as retro_argv, GOOD
        r = self.sisi("retro", *retro_argv(dict(GOOD, change="Add the readiness probe to every server recipe Checks list",
                                                moment="`sisi done` run 12 showed no readiness probe for servers", new=True)),
                      env={"SISI_SESSION_ID": "due-retro"})
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("learning cycle is due", r.stdout)
        tick = self.sisi("tick", stdin=json.dumps({"session_id": "due-tick", "cwd": self.proj, "source": "startup"})).stdout
        self.assertIn("learning cycle is due", tick)
        self.assertIn("learning cycle is due",
                      self.sisi("done", "for", "parser-or-codec", env={"SISI_SESSION_ID": "due-done"}).stdout)
        self.git_init()
        self.write_contract(contract([check("ok", "true")]))
        v = self.sisi("verify", env={"SISI_SESSION_ID": "due-verify"})
        self.assertEqual(v.returncode, 0, v.stdout)
        self.assertIn("learning cycle is due", v.stdout)
        v2 = self.sisi("verify", env={"SISI_SESSION_ID": "due-verify"})
        self.assertNotIn("learning cycle is due", v2.stdout)  # same session: no nagging
        with open(os.path.join(self.proj, "work.txt"), "w") as f:
            f.write("x\n")
        a, msg = gate.decide({"session_id": "due-gate", "cwd": self.proj})
        self.assertEqual(a, "allow")
        self.assertIn("learning cycle is due", msg or "")


RULE_BODY = ("Before non-trivial work, write a contract at `.sisi/contract.json` in the project "
             "(`sisi contract init` creates the skeleton) listing the checks that decide success.\n\n"
             "Why: a request says what is wanted, rarely how success is measured.")


class CycleApplyTests(LearningCase):
    def test_brief_has_base_lessons_rulebook_and_format(self):
        lid = self.mk()
        con = retro.connect()
        con.execute("UPDATE lessons SET strength=3 WHERE id=?", (lid,))
        con.commit(); con.close()
        out = self.sisi("cycle").stdout
        self.assertIn("Base version (copy into your file): " + cycle.base_version(), out)
        self.assertIn("#%-4d" % lid, out)
        self.assertIn("NEEDS A CHECK", out)
        self.assertIn("budget %d" % overlay.MAX_LINES, out)
        self.assertIn("Current rulebook", out)
        self.assertIn("sisi cycle apply FILE", out)
        self.assertIn("contract-requirement", out)

    def test_apply_merges_folds_replaces_and_enforces(self):
        a = self.mk(change="Parser readiness probes beat fixed sleeps for servers", moment="wait a at step 1")
        b = self.mk(change="Fixed sleeps waste minutes when parser servers start slowly", moment="wait b at step 2")
        c = self.mk(change_kind="recipe", target="parser-or-codec",
                    change="Parser recipes need a fuzz check for hostile inputs", moment="hostile input at step 3")
        pre, base = overlay.base_rules()
        title = next(r["title"] for r in base if r["id"] == "know-done")
        doc = self.cycle_doc(
            rules=[{"id": "know-done", "title": title, "body": RULE_BODY, "action": "replace"}],
            notes=[{"lesson": a, "action": "fold-into-rule", "into": "know-done"},
                   {"lesson": b, "action": "merge", "merged_into": a}],
            enforced=[{"lesson": c, "type": "contract-requirement", "when": "parser",
                       "require_kind": "parsing", "max_rung": 2}])
        r = self.sisi("cycle", "apply", doc)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.exists(paths.overlay_dir("rules", "know-done.md")))
        self.assertIn("success is measured", open(paths.generated()).read())
        la, lb, lc = self.lesson(a), self.lesson(b), self.lesson(c)
        self.assertEqual((la["folded_into"], la["strength"]), ("rule:know-done", 2))
        self.assertEqual(lb["status"], "superseded")
        self.assertEqual((lc["strength"], bool(lc["check_json"])), (3, True))
        self.assertEqual(len(cycle.load_enforced()), 1)
        self.assertIn("cycle-0001", self.sisi("cycle", "status").stdout)
        log = pdata.git("log", "--format=%s", "-1").stdout
        self.assertIn("cycle cycle-0001", log)

    def test_apply_refuses_saying_exactly_why(self):
        lid = self.mk()
        cases = [
            ({"notes": [{"lesson": 9999, "action": "keep"}]}, "no lesson with id 9999"),
            ({"rules": [{"id": "know-done", "title": "X", "body": "no reason here", "action": "replace"}]}, "must keep its Why"),
            ({"enforced": [{"lesson": lid, "type": "command", "cmd": "definitely-not-here-xyz --fast",
                            "expect": {"exit": 0}}]}, "does not exist on this machine"),
            ({"rules": [{"id": "know-done", "title": "X", "body": "Use `sisi frobnicate` first.\n\nWhy: testing",
                         "action": "replace"}]}, "not a command"),
        ]
        for parts, why in cases:
            with self.subTest(why):
                before = self.overlay_bytes()
                r = self.sisi("cycle", "apply", self.cycle_doc(**parts))
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn(why, r.stdout)
                self.assertEqual(self.overlay_bytes(), before)
        doc = {"version": 1, "base": "stale", "summary": "x", "notes": [{"lesson": lid, "action": "keep"}]}
        p = os.path.join(self.tmp, "stale.json")
        with open(p, "w") as f:
            json.dump(doc, f)
        r = self.sisi("cycle", "apply", p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("stale base", r.stdout)

    def test_rulebook_may_grow_only_by_replacement(self):
        r = self.sisi("cycle", "apply", self.cycle_doc(disable_rules=["know-done"]))
        self.assertEqual(r.returncode, 0, r.stdout)
        doc = self.cycle_doc(rules=[{"id": "brand-new-rule", "title": "Brand new",
                                     "body": "Do the brand new thing carefully.\n\nWhy: it helps.", "action": "add"}])
        r = self.sisi("cycle", "apply", doc)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("would grow", r.stdout)

    def test_two_sessions_second_apply_refuses_cleanly(self):
        a = self.mk(change="Session one lesson about parser readiness", moment="s1 wait at step 1")
        b = self.mk(change="Session two lesson about widget caching", moment="s2 wait at step 2")
        base = cycle.base_version()  # both sessions read the same brief
        doc1 = {"version": 1, "base": base, "summary": "one", "notes": [{"lesson": a, "action": "keep"}]}
        doc2 = {"version": 1, "base": base, "summary": "two", "notes": [{"lesson": b, "action": "keep"}]}
        paths_ = []
        for i, d in enumerate((doc1, doc2)):
            p = os.path.join(self.tmp, "two-%d.json" % i)
            with open(p, "w") as f:
                json.dump(d, f)
            paths_.append(p)
        self.assertEqual(self.sisi("cycle", "apply", str(paths_[0])).returncode, 0)
        r = self.sisi("cycle", "apply", str(paths_[1]))
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("stale base", r.stdout)
        self.assertEqual(len(cycle.cycle_records()), 1)

    def test_revert_undoes_exactly_and_only_the_newest(self):
        a = self.mk()
        before = self.overlay_bytes()
        doc = self.cycle_doc(notes=[{"lesson": a, "action": "retire"}],
                             enforced=[{"lesson": a, "type": "command", "cmd": "true", "expect": {"exit": 0}}])
        self.assertEqual(self.sisi("cycle", "apply", doc).returncode, 0)
        self.assertNotEqual(self.overlay_bytes(), before)
        self.assertEqual(self.lesson(a)["strength"], 3)
        r = self.sisi("cycle", "revert", "cycle-9999")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not the newest", r.stdout)
        r = self.sisi("cycle", "revert")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.overlay_bytes(), before)
        l = self.lesson(a)
        self.assertEqual((l["status"], l["strength"], l["check_json"]), ("open", 1, None))
        self.assertEqual(cycle.load_enforced(), [])

    def test_property_apply_then_revert_leaves_overlay_byte_identical(self):
        pre, base = overlay.base_rules()
        title = next(r["title"] for r in base if r["id"] == "know-done")
        ids = [self.mk(change="Property lesson %d about parser readiness" % i,
                       moment="property wait %d at step 2" % i) for i in range(4)]
        for seed in [0, 3] + [random.randrange(2 ** 32) for _ in range(ITERS)]:
            rng = random.Random(seed)
            before = self.overlay_bytes()
            notes = [{"lesson": i, "action": rng.choice(("keep", "retire"))} for i in rng.sample(ids, rng.randint(1, 3))]
            body = RULE_BODY + " (variant %d)" % seed
            doc = self.cycle_doc(
                rules=[{"id": "know-done", "title": title, "body": body, "action": "replace"}],
                notes=notes,
                enforced=[{"lesson": rng.choice(ids), "type": "contract-requirement", "when": "parser",
                           "require_kind": "parsing", "max_rung": 2}])
            r = self.sisi("cycle", "apply", doc)
            self.assertEqual(r.returncode, 0, "seed %d: %s" % (seed, r.stdout + r.stderr))
            r = self.sisi("cycle", "revert")
            self.assertEqual(r.returncode, 0, "seed %d: %s" % (seed, r.stdout))
            self.assertEqual(self.overlay_bytes(), before, "seed %d" % seed)

    def test_status_flags_a_cycle_that_made_deliveries_worse(self):
        lid = self.mk()
        rows = [{"end": "2020-01-01T00:00:00Z", "seconds": 60, "send_backs": 0} for _ in range(3)]
        for r in rows:
            store.append("deliveries", r)
        doc = self.cycle_doc(notes=[{"lesson": lid, "action": "keep"}])
        self.assertEqual(self.sisi("cycle", "apply", doc).returncode, 0)
        rec = cycle.cycle_records()[-1]
        self.assertFalse(cycle.flagged(rec))  # nothing measured since yet
        for _ in range(10):
            store.append("deliveries", {"end": "2999-01-01T00:00:00Z", "seconds": 900, "send_backs": 4})
        self.assertTrue(cycle.flagged(rec))
        self.assertIn("WORSE", self.sisi("cycle", "status").stdout)
        self.assertIn("FIRST:", cycle.brief_text())

    def test_cycle_can_set_when_terms_on_an_old_lesson(self):
        lid = self.mk()
        self.assertIsNone(self.lesson(lid)["when_terms"])
        brief = cycle.brief_text()
        self.assertIn("Lessons with no when-terms yet", brief)
        self.assertIn("#%d" % lid, brief)
        bad = self.sisi("cycle", "apply", self.cycle_doc(
            notes=[{"lesson": lid, "action": "keep", "when": "parser, servers"}]))
        self.assertEqual(bad.returncode, 1, bad.stdout)
        self.assertIn("when needs at least 5 terms", bad.stdout)
        good = self.sisi("cycle", "apply", self.cycle_doc(
            notes=[{"lesson": lid, "action": "keep", "when": PARSER_WHEN}]))
        self.assertEqual(good.returncode, 0, good.stdout)
        self.assertIn("readiness probe", self.lesson(lid)["when_terms"])
        self.assertNotIn("MISSING", cycle.brief_text().split("#%-4d" % lid)[1].splitlines()[2])


class EnforcedTests(LearningCase):
    def apply_enforced(self, entry):
        lid = entry["lesson"]
        doc = self.cycle_doc(enforced=[entry])
        r = self.sisi("cycle", "apply", doc)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return lid

    def test_contract_requirement_is_checked_like_a_floor(self):
        lid = self.mk()
        self.apply_enforced({"lesson": lid, "type": "contract-requirement", "when": "parser",
                             "require_kind": "parsing", "max_rung": 2})
        weak = contract([check("p1", "true", rung=3, kind="general")])
        weak["checks"][0]["claim"] = "the parser accepts the sample files"
        self.write_contract(weak)
        r = self.sisi("verify")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("enforced lesson #%d" % lid, r.stdout)
        strong = contract([check("p1", "true", rung=2, kind="parsing")])
        strong["checks"][0]["claim"] = "the parser accepts the sample files"
        self.write_contract(strong)
        self.assertEqual(self.sisi("verify").returncode, 0)

    def test_command_check_runs_only_for_trusted_projects(self):
        lid = self.mk()
        self.apply_enforced({"lesson": lid, "type": "command", "cmd": "false", "expect": {"exit": 0}})
        c = contract([check("ok", "true")])
        self.write_contract(c, trusted=True)
        res = cycle.enforced_results(c, self.proj)
        self.assertEqual([x["status"] for x in res], ["failed"])
        from sisi import trust
        trust.remove(self.proj)
        self.assertEqual(cycle.enforced_results(c, self.proj), [])  # never run untrusted
        trust.add(self.proj)
        self.assertEqual(self.sisi("verify").returncode, 1)


class ImproveAndMigrationTests(LearningCase):
    def test_improve_says_too_little_data_then_answers(self):
        out = self.sisi("improve").stdout
        self.assertIn("Is it getting better?", out)
        self.assertIn("Too little data", out)
        lid = self.mk()
        self.again(lid)
        for _ in range(6):
            store.append("deliveries", {"end": store.now(), "seconds": 120, "send_backs": 1})
        out = self.sisi("improve").stdout
        self.assertIn("1 taking effect", out)
        self.assertIn("0 folded into a recipe, entry or rule, 1 still loose notes", out)
        self.assertIn("showings:", out)
        self.assertIn("rulebook:", out)
        self.assertIn("Not measured:", out)
        self.assertIn("learning            :", self.sisi("status").stdout)

    def test_old_database_migrates_without_loss(self):
        # a second, old-shaped database on the side, opened through retro.connect by swapping files
        old = os.path.join(self.tmp, "old.db")
        con = sqlite3.connect(old)
        con.executescript("""
        CREATE TABLE lessons(id INTEGER PRIMARY KEY, created TEXT, aim TEXT, change_kind TEXT, target TEXT,
          moment TEXT, cause TEXT, change TEXT, status TEXT DEFAULT 'open', count INTEGER DEFAULT 1, last_seen TEXT);
        CREATE TABLE occurrences(id INTEGER PRIMARY KEY, lesson_id INTEGER, ts TEXT, session TEXT, tool TEXT,
          cwd TEXT, repo TEXT, moment TEXT, fp TEXT);
        """)
        con.execute("INSERT INTO lessons VALUES (1,'2020-01-01T00:00:00Z','speed','verifier','fuzz','m','c',"
                    "'Seed the fuzz corpus from golden parser files','open',2,'2020-01-02T00:00:00Z')")
        con.execute("INSERT INTO occurrences VALUES (1,1,'2020-01-01T00:00:00Z','s','t','/tmp','/tmp','m','f')")
        con.commit(); con.close()
        import shutil
        os.makedirs(os.path.dirname(retro.db_path()), exist_ok=True)
        shutil.copy(old, retro.db_path())
        con = retro.connect()  # migration happens on open
        row = dict(con.execute("SELECT * FROM lessons WHERE id=1").fetchone())
        occ = con.execute("SELECT count(*) FROM occurrences").fetchone()[0]
        retro.ensure_effects(con)
        con.close()
        self.assertEqual((row["change"], occ), ("Seed the fuzz corpus from golden parser files", 1))
        self.assertEqual(row["strength"], 1)
        self.assertIn("fuzz", row["triggers"])
        self.assertTrue(os.path.exists(os.path.join(self.notes, "fuzz.md")))  # effect folds in too
        self.assertEqual(self.lesson(1)["status"], "applied")

    def test_old_lessons_jsonl_imports(self):
        p = os.path.join(self.tmp, "old.jsonl")
        with open(p, "w") as f:
            f.write(json.dumps({"t": "lesson", "id": 7, "created": "2020-01-01T00:00:00Z", "aim": "speed",
                                "change_kind": "rule", "target": None, "moment": "m", "cause": "c",
                                "change": PARSER_CHANGE, "status": "open", "count": 1,
                                "last_seen": "2020-01-01T00:00:00Z"}) + "\n")
        r = self.sisi("lessons", "import", p)
        self.assertEqual(r.returncode, 0, r.stdout)
        l = self.lesson(7)
        self.assertEqual(l["change"], PARSER_CHANGE)
        con = retro.connect()
        retro._backfill(con)
        con.close()
        self.assertIn("pars", self.lesson(7)["triggers"])


# ---- measured matching: a labelled corpus -----------------------------------
# (lesson change, a later request as a different agent would phrase the same work)
SHOULD_MATCH = [
    ("For any CSV importer, run a property test that round-trips generated rows containing quotes, commas and newlines before saying it works",
     "write a CSV importer for customer records"),
    ("On btrfs, os.replace of a symlink is not atomic for readers: a lookup can see ENOENT mid-switch, so retry a missing current link briefly",
     "atomically switch a symlink to the new release folder"),
    ("Any test that runs a command which reads stdin must pass stdin explicitly (input or DEVNULL), because an inherited open pipe makes it hang",
     "my test hangs when the subprocess reads from a pipe"),
    ("Verify webhook HMAC signatures over the raw request body before parsing JSON, because reserialized JSON never matches",
     "add a webhook endpoint that checks the signature"),
    ("A daily 02:30 local job must decide what happens in the DST spring-forward gap, when that wall-clock time never occurs",
     "schedule a daily job at 2:30 local time"),
    ("Cursor pagination needs a stable tie-breaker on id after the timestamp, or rows sharing a timestamp are skipped between pages",
     "paginate a feed without skipping items that share a timestamp"),
    ("JWT tokens need a small clock-skew leeway on expiry, because client and server clocks differ by seconds",
     "auth tokens rejected as expired due to clock differences"),
    ("Money must be integer cents end to end; float prices round differently per platform and totals drift by a cent",
     "price totals are off by a cent sometimes"),
    ("Websocket reconnects need exponential backoff with jitter, or a dropped server gets a thundering herd of retries",
     "live socket connection drops and reconnects in a loop"),
    ("Phone photos carry EXIF orientation; decode must apply it or portrait uploads render sideways",
     "uploaded photos appear sideways"),
    ("Normalize filenames to NFC on read and write; macOS returns NFD, so accented names miss lookups byte-wise",
     "file with an accented name is not found on disk"),
    ("Reject tar entries whose names escape the destination with .. or absolute paths before extracting anything",
     "extract a tar archive from an upload"),
    ("Respect DNS TTL values and never cache address records in the process beyond them",
     "DNS cache keeps serving old records after a change"),
    ("Add a required column with expand-contract: nullable first, backfill in batches, then set NOT NULL in a later deploy",
     "add a required column to a huge table without downtime"),
    ("Copy dependency manifests and install before copying source, so the Docker layer cache survives code edits",
     "docker build is slow because the dependency layer rebuilds after source edits"),
    ("OAuth redirect URIs match exactly, including a trailing slash; register the byte-exact callback",
     "OAuth callback fails with redirect mismatch"),
    ("Resample microphone input from 48 kHz to the model's 16 kHz explicitly; playing it raw pitches a voice recording down",
     "recorded voice plays back pitched down"),
    ("Store GPS coordinates at full double precision; rounding to 4 decimal places moves a pin by metres",
     "map pins drift by a few metres"),
    ("Encode non-ASCII mail subjects as MIME encoded-words, or accented subjects arrive garbled",
     "email subject lines with accents arrive garbled"),
    ("Escape ampersands in sitemap URLs; a raw ampersand makes the XML unparsable",
     "sitemap XML rejected for invalid characters in URLs"),
    ("Plural choice must use CLDR plural categories per locale; one/other breaks Russian and Polish",
     "Russian translations show the wrong plural form"),
    ("Embed and subset fonts in generated PDFs, or printing on a machine without the font substitutes another typeface",
     "PDF prints in the wrong typeface on another machine"),
    ("A Redis lock must carry a random token and release by compare-and-delete, or an expired lock lets a second worker run the job",
     "a second worker entered while the lock was still held"),
    ("Parallel branches belong in git worktrees; two agents in one checkout share an index and stomp each other's staging",
     "work on two branches at once in separate folders of one repo"),
    ("A failed charge may be retried safely only with an idempotency key per checkout attempt, stored with the first response",
     "retry a failed charge without billing the customer twice"),
]
# Later requests that must surface nothing: common words only, or a single distinctive word with no support.
SHOULD_NOT_MATCH = [
    "run the test file and check the output", "add a check for empty input",
    "the tests take a long time to run", "read the input file line by line",
    "run all the checks before finishing", "test it with a small example first",
    "check the output matches the example", "write the results to a file",
    "add a test for this change", "run it again and check the output",
    "check the first line of the output file", "write a small test for the change",
    "run the whole test suite again", "the output file is empty after the run",
    "add the missing import and run it", "check the return value is not empty",
    "write the output to a new file each time", "test the change with the example input",
    "the first run is slower than the second", "add a line to the output for each input",
    "write tests first, then the code", "open the CSV in a spreadsheet to look at it",
    "restart the websocket service", "the tar file is huge", "renew the OAuth secret",
    "rename a variable in the logger",
]


def _reached(block, lid):
    import re
    return bool(re.search(r"#%d \(" % lid, block))


class MatchingCorpusTests(LearningCase):
    def test_measured_part_one_precision_and_overall_reach(self):
        # New behaviour: part one ("likely to apply", in full) must never fire on a should-not
        # request; overall reach counts the right lesson in part one OR listed in part two within
        # its budget, where the asking agent reads the headings and decides.
        ids = []
        for i, (change, _) in enumerate(SHOULD_MATCH):
            ids.append(self.mk(change=change, moment="incident %d at step 3" % i,
                               cause="overlooked at step 2"))
        hits, misses = 0, []
        for lid, (_, query) in zip(ids, SHOULD_MATCH):
            if _reached(retro.delivery_block(query, "corpus"), lid):
                hits += 1
            else:
                misses.append((lid, query))
        wrong = [q for q in SHOULD_NOT_MATCH if retro.delivery(q)[0]]
        print("matching corpus: reach (part one or listed) %d/%d, part-one wrong %d/%d"
              % (hits, len(SHOULD_MATCH), len(wrong), len(SHOULD_NOT_MATCH)))
        self.assertGreaterEqual(hits / len(SHOULD_MATCH), 0.90, "misses: %r" % (misses,))
        self.assertEqual(wrong, [], "part one must stay empty for should-not requests")

    def test_csv_lesson_reaches_the_next_agent_three_ways(self):
        r = self.sisi("retro", "--new", "--aim", "verified",
                      "--moment", "The CSV importer test passed but 'python3 import.py big.csv' crashed on a quoted comma in row 4011",
                      "--cause", "the importer was only tested with three hand-written rows",
                      "--change-kind", "rule", "--when", CSV_WHEN,
                      "--change", "For any CSV importer, run a property test that round-trips generated rows containing quotes, commas and newlines before saying it works")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("lesson #", r.stdout)
        lid = int(r.stdout.split("lesson #")[1].split(",")[0])
        for q in ("write a CSV importer for customer records", "CSV importer with quotes and commas",
                  "import customer rows from a csv file"):
            with self.subTest(q):
                out = self.sisi("done", "for", q).stdout
                self.assertIn("#%d" % lid, out)
                self.assertIn("CSV importer", out)

    def test_recipe_title_words_alone_never_create_a_match(self):
        # Regression: 'rename a variable in the logger' matched a gate lesson only through the words
        # 'docs-change Changing' that `done for` added from the chosen recipe (chang escaped COMMON).
        lid = self.mk(change="Make the gate attribute tree changes to sessions and stop counting a "
                             "send-back when another live session is changing the same files",
                      moment="gate send-backs in step 4 while files changed underneath")
        self.assertEqual(retro.match_lessons("rename a variable in the logger"), [])
        self.assertEqual(retro.match_lessons("rename a variable in the logger",
                                              extra="docs-change Changing documentation"), [])
        self.assertIn(retro._stem("changing"), retro.COMMON)
        self.assertTrue(retro.match_lessons("gate send-backs when sessions change files",
                                             extra="docs-change Changing documentation"))

    def test_part_two_headings_are_listed_not_read(self):
        lid = self.mk(change="Seed the fuzz corpus from golden parser files before fuzzing",
                      moment="fuzz seeds missing at step 5",
                      when="fuzzing, parser, hostile input, generated input, corpus seeds, property testing")
        out = self.sisi("done", "for", "fuzzing").stdout  # one shared when word: a heading, not part one
        self.assertIn("other lessons from earlier agents; open any that apply", out)
        self.assertNotIn("likely to apply", out)
        self.assertIn("#%d" % lid, out)
        con = retro.connect()
        self.assertEqual((retro.listed_count(con, lid), retro.read_count(con, lid)), (1, 0))
        self.assertEqual(con.execute("SELECT place FROM impressions WHERE lesson_id=?", (lid,)).fetchone()[0],
                         "done-for-listed")
        con.close()
        self.sisi("lessons", "show", str(lid))  # opening one in full is the reading
        con = retro.connect()
        self.assertEqual((retro.listed_count(con, lid), retro.read_count(con, lid)), (1, 1))
        con.close()

    def test_semicolon_prose_is_not_hidden_and_generic_fix_is_no_bridge(self):
        # Two real-corpus failures: '; fixed-position...' read as a shell separator and silently hid
        # the lesson; and the generic verb 'fix' offered an unrelated lesson as possibly related.
        self.assertIsNotNone(retro.display_line("check it before shipping; fixed-position footers hide buttons", self.proj))
        self.assertIsNone(retro.display_line("do the thing; rm -rf build", self.proj))
        lid = self.mk(change="Check every page at a 375px phone width before shipping; fixed-position footers hide primary buttons",
                      moment="the button was below the fold in step 2 on a phone",
                      when="responsive, mobile, phone screen, small screen, layout, signup form")
        out = self.sisi("done", "for", "make the signup form responsive on mobile").stdout
        self.assertIn("#%d" % lid, out)
        part1, _ = retro.delivery("fix the flaky thing")
        self.assertEqual(part1, [])  # a generic verb in the anecdote never makes a part-one match

    def test_done_id_also_shows_matched_lessons(self):
        lid = self.mk(change_kind="recipe", target="parser-or-codec",
                      change="Parser recipes need a fuzz check over hostile generated inputs",
                      moment="hostile parser input at step 3",
                      when="parser, fuzzing, codec, hostile input, generated input")
        out = self.sisi("done", "parser-or-codec").stdout
        self.assertIn("likely to apply", out)  # one when hit + target is the entry being printed
        self.assertIn("#%d" % lid, out)

    def test_unconfirmed_duplicate_sighting_is_recorded(self):
        first = self.sisi("retro", "--new", "--aim", "verified",
                          "--moment", "the parser server waited 90 seconds in step 4 of the nightly job",
                          "--cause", "no readiness probe existed before the browser step",
                          "--change-kind", "rule", "--when", PARSER_WHEN, "--change", PARSER_CHANGE)
        self.assertEqual(first.returncode, 0, first.stdout)
        lid = int(first.stdout.split("lesson #")[1].split(",")[0])
        dup = self.sisi("retro", "--aim", "verified",
                        "--moment", "again the parser server waited 90 seconds in step 9 of the nightly job",
                        "--cause", "still no readiness probe before the browser step at all",
                        "--change-kind", "rule", "--when", PARSER_WHEN,
                        "--change", "Prefer a readiness probe over a fixed sleep when waiting for parser servers")
        self.assertEqual(dup.returncode, 4, dup.stdout)
        self.assertIn("sighting was kept", dup.stdout)
        con = retro.connect()
        self.assertEqual(retro.sightings_count(con, lid), 1)
        con.close()
        self.assertIn("1 unconfirmed sighting(s)", self.sisi("lessons", "show", str(lid)).stdout)
        as_new = self.sisi("retro", "--new", "--aim", "verified",
                           "--moment", "again the parser server waited 90 seconds in step 9 of the nightly job",
                           "--cause", "still no readiness probe before the browser step at all",
                           "--change-kind", "rule", "--when", PARSER_WHEN,
                           "--change", "Prefer a readiness probe over a fixed sleep when waiting for parser servers")
        self.assertEqual(as_new.returncode, 0, as_new.stdout)  # kept apart, but the sighting is not lost
        con = retro.connect()
        self.assertEqual(retro.sightings_count(con, lid), 1)
        con.close()


# A harder set: each request shares NO content word with its lesson's moment, cause or change text.
# Only the recording agent's when-terms bridge the two wordings, as another agent would write them.
# (change, when, later request)
HARD_MATCH = [
    ("For any CSV importer, run a property test that round-trips generated rows containing quotes, commas and newlines before saying it works",
     CSV_WHEN, "parse a spreadsheet export of orders into the database"),
    ("Check every page at a 375px phone width with a screenshot before shipping; fixed-position footers hide primary buttons",
     "responsive, mobile, phone screen, small screen, layout, viewport, signup form, login page",
     "make the signup form responsive on mobile"),
    ("Expand-contract only: nullable first, backfill in batches, switch reads, only then drop the old shape",
     "migration, schema change, add column, users table, backfill, move data, alter table",
     "add a column to the users table and move the data over"),
    ("Photographs carry orientation metadata; decode must apply it or portraits render rotated",
     "sideways photos, image rotation, uploaded pictures, EXIF, photo orientation",
     "uploaded pictures appear sideways"),
    ("Verify HMAC signatures over the raw request body before parsing JSON, because reserialized JSON never matches",
     "webhook, payment callback, provider notifications, signed callbacks, callback authentication",
     "payment provider callbacks must be authenticated"),
    ("On btrfs, os.replace of a link is not atomic for readers: a lookup can see ENOENT midway, so retry a missing one briefly",
     "symlink, release switch, atomic deploy, current pointer, live version",
     "point the live release symlink at the new build"),
    ("Pass standard input explicitly or use DEVNULL; inherited descriptors can block",
     "stdin, pipe, subprocess hang, blocked process, standard input, inherited pipe",
     "subprocess hangs reading from a pipe"),
    ("A 02:30 daily trigger must define behaviour for the spring-forward gap, when that local time never occurs",
     "DST, daylight saving, schedule, nightly job, clock change, timezone",
     "schedule a nightly job that survives clock changes"),
    ("Cursor order needs a stable tie-breaker on id after the timestamp, or rows sharing a timestamp are skipped between responses",
     "pagination, feed scrolling, cursor pages, endless list, missing items",
     "scrolling the feed misses items"),
    ("Amounts must be integer cents end to end; floats round differently per platform",
     "money, prices, totals, penny, rounding, billing amounts, checkout total",
     "checkout total differs by a penny"),
    ("Expiry checks need a small leeway in seconds, because two machines' clocks differ",
     "JWT, tokens, logged out, session expiry, auth, token expired",
     "users randomly logged out with token expired errors"),
    ("Reject entries whose names escape the destination with dot-dot or absolute paths before extracting anything",
     "archive extraction, zip slip, unpack upload, tar, path traversal, extracting archives",
     "safely unpack a zip from a customer"),
    ("Respect TTL values; a process-level resolver cache must expire entries on time",
     "DNS, old server, address change, resolver, hostname lookup, stale address",
     "app keeps calling the old server address after the move"),
    ("Copy dependency manifests and install before copying source, so the layer cache survives code edits",
     "docker, container build, image layers, slow builds, caching, dockerfile",
     "container image builds take ten minutes after every tweak"),
    ("Redirect URIs match exactly, including a trailing slash; register the byte-exact callback",
     "OAuth, login, Google sign-in, callback mismatch, redirect, sign in",
     "login with Google fails after consent"),
    ("Resample microphone input from 48 kHz to the model's 16 kHz explicitly; playing it raw pitches speech lower",
     "audio, voice notes, pitch, sample rate, microphone, resampling",
     "voice notes sound like a slowed-down robot"),
    ("Store coordinates at full double precision; rounding to 4 decimal places moves a pin by metres",
     "GPS, map markers, coordinates, location accuracy, pins",
     "map markers land on the wrong street"),
    ("Encode non-ASCII mail subjects as encoded-words, or accented subjects arrive garbled",
     "MIME, email subject, umlauts, garbled headers, header encoding, non-ASCII mail",
     "German umlauts in email headers break"),
    ("Plural choice must use CLDR categories per locale; one/other is not enough for many languages",
     "i18n, plural forms, Polish, Russian, translations, word forms, localization",
     "Polish users see incorrect word forms for counts"),
    ("A Redis lock must carry a random token and release by compare-and-delete, or expiry lets another holder in",
     "distributed lock, cron overlap, duplicate runs, Redis lock, mutex, scheduled job",
     "the same scheduled job executed on two machines at once"),
    ("A missing config file must print one plain line naming the path it wanted and exit 2, never a traceback",
     "cli, command line, terminal tool, script, arguments, flags, config file, error message, exit code, usage",
     "add a --verbose option to the backup script"),
]
HARD_NOT_MATCH = [
    "write a haiku about autumn", "fix flaky websocket reconnect", "rename a variable in the logger",
    "translate the README into French", "tidy up CSS variable names",
    "show each task's deadline on the weekly planner", "optimise the image thumbnail resizer",
    "run the test file and check the output", "add a check for empty input",
    "read the input file line by line", "run all the checks before finishing",
    "export the quarterly report", "mobile app crashes on startup",
    "schedule a team lunch next week", "polish the landing page design",
    "check the return value is not empty", "write the output to a new file each time",
    "test the change with the example input", "add a line to the output for each input",
    "write tests first, then the code", "restart the websocket service",
    "check the first line of the output file", "run it again and check the output",
    "add the missing import and run it",
]
HARD_MOMENT, HARD_CAUSE = "spotted at step 3", "overlooked at step 2"


class HarderMatchingTests(LearningCase):
    def test_measured_recall_when_only_when_terms_bridge_the_words(self):
        ids = []
        for change, when, query in HARD_MATCH:
            content = (retro._stems(change) | retro._stems(HARD_MOMENT) | retro._stems(HARD_CAUSE)) - retro.COMMON
            asked = retro._stems(query) - retro.COMMON
            self.assertFalse(content & asked, "pair shares content words %r: %r" % (content & asked, query))
            self.assertTrue(retro._stems(when) & asked, "pair shares no when word either: %r" % query)
            ids.append(self.mk(change=change, moment=HARD_MOMENT, cause=HARD_CAUSE, when=when))
        hits, part1_hits, misses = 0, 0, []
        for lid, (_, _, query) in zip(ids, HARD_MATCH):
            p1, _ = retro.delivery(query)
            if lid in [d["row"]["id"] for d in p1]:
                part1_hits += 1
            if _reached(retro.delivery_block(query, "corpus"), lid):
                hits += 1
            else:
                misses.append((lid, query))
        wrong = [q for q in HARD_NOT_MATCH if retro.delivery(q)[0]]
        print("harder matching (when-terms only): reach %d/%d (part one %d), part-one wrong %d/%d"
              % (hits, len(HARD_MATCH), part1_hits, len(wrong), len(HARD_NOT_MATCH)))
        self.assertEqual(hits, len(HARD_MATCH), "misses: %r" % (misses,))
        self.assertEqual(wrong, [], "part one must stay empty for should-not requests")


class ImproveFromUseTests(LearningCase):
    def test_sisi_improves_from_use_end_to_end(self):
        """The purpose itself: a lesson from session A reaches session B doing the same kind of work,
        its showing is recorded, and recurrence after fresh showings strengthens it until a cycle is due."""
        a = self.sisi("retro", "--new", "--aim", "verified",
                      "--moment", "The CSV importer test passed but 'python3 import.py big.csv' crashed on a quoted comma in row 4011",
                      "--cause", "the importer was only tested with three hand-written rows",
                      "--change-kind", "rule", "--when", CSV_WHEN,
                      "--change", "For any CSV importer, run a property test that round-trips generated rows containing quotes, commas and newlines before saying it works",
                      env={"SISI_SESSION_ID": "session-A"})
        self.assertEqual(a.returncode, 0, a.stdout)
        lid = int(a.stdout.split("lesson #")[1].split(",")[0])
        b_env = {"SISI_SESSION_ID": "session-B"}
        for out in (self.sisi("done", "for", "write a CSV importer for customer records", env=b_env).stdout,
                    self.sisi("verifiers", "for", "csv parsing must survive quotes and commas", env=b_env).stdout):
            self.assertIn("#%d" % lid, out)
        proj2 = os.path.join(self.tmp, "csvproj"); os.makedirs(proj2)
        init = self.sisi("contract", "init", "--goal", "import customer rows from a csv file", cwd=proj2, env=b_env)
        self.assertIn("#%d" % lid, init.stdout)
        unrelated = self.sisi("done", "for", "style a settings page with a sidebar", env=b_env).stdout
        self.assertEqual(retro.delivery("style a settings page with a sidebar")[0], [])  # never in part one
        self.assertNotIn("likely to apply", unrelated)  # at most an unconfirmed heading in part two
        con = retro.connect()
        places = sorted(r[0] for r in con.execute(
            "SELECT DISTINCT place FROM impressions WHERE lesson_id=? AND session='session-B'", (lid,)))
        con.close()
        # verifiers-for matched in part one (csv + parse in the when-terms); the other two listed it
        self.assertEqual(places, ["contract-init-listed", "done-for-listed", "verifiers-for"])
        same = self.sisi("retro", "--same-as", str(lid),
                         "--moment", "again a quoted comma in row 88 broke 'python3 import.py small.csv'",
                         env=b_env)
        self.assertEqual(same.returncode, 0, same.stdout)
        self.assertEqual(self.lesson(lid)["strength"], 2)  # three showings, then the same mistake
        due = self.sisi("cycle", "due")
        self.assertEqual(due.returncode, 0, due.stdout)
        self.assertIn("waiting for consolidation", due.stdout)
        # a second round of showings, then another recurrence: up another step on fresh evidence
        self.sisi("done", "for", "CSV importer with quotes and commas", env=b_env)
        self.sisi("verifiers", "for", "csv parsing must survive quotes and commas", env=b_env)
        same2 = self.sisi("retro", "--same-as", str(lid),
                          "--moment", "a newline inside a quoted field broke 'python3 import.py rows.csv' at row 12",
                          env=b_env)
        self.assertEqual(same2.returncode, 0, same2.stdout)
        self.assertEqual(self.lesson(lid)["strength"], 3)


if __name__ == "__main__":
    unittest.main()
