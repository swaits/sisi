"""Short lines, topics, the human digest, and the cycle writing them."""
import json, os, sqlite3, unittest
from support import *
from sisi import cycle, paths, retro, store
from test_verifiers import LibCase, vfile, dfile

WHEN = "parser, fuzzing, codec, hostile input, generated input, parsing"


def fields(**kw):
    f = dict(aim="verified", change_kind="rule", target=None,
             moment="the parser server waited 90 seconds in step 4 of the nightly job",
             cause="no readiness probe existed before the browser step",
             change="Prefer a readiness probe over a fixed sleep when waiting for parser servers to answer",
             when=WHEN)
    f.update(kw)
    return f


class ShortCase(LibCase):
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

    def set_lesson(self, lid, **kw):
        con = retro.connect()
        try:
            for k, v in kw.items():
                con.execute("UPDATE lessons SET %s=? WHERE id=?" % k, (v, lid))
            con.commit()
        finally:
            con.close()

    def cycle_doc(self, notes=None, **parts):
        doc = {"version": 1, "base": cycle.base_version(), "summary": "test cycle"}
        if notes is not None:
            notes = list(notes)
            have = {e.get("lesson") for e in notes if isinstance(e, dict) and e.get("action") == "set-scope"}
            for e in list(notes):
                if isinstance(e, dict) and isinstance(e.get("lesson"), int) and e["lesson"] not in have:
                    notes.append({"lesson": e["lesson"], "action": "set-scope", "scope": "core"})
                    have.add(e["lesson"])
            # every active lesson lacking a pattern needs a set-pattern too
            try:
                _con = retro.connect()
                try:
                    _prows = [dict(r) for r in _con.execute(
                        "SELECT id, pattern_id, scope FROM lessons WHERE status IN ('open','applied')")]
                finally:
                    _con.close()
                _have_p = {e.get("lesson") for e in notes if isinstance(e, dict) and e.get("action") == "set-pattern"}
                _exempt = {e.get("lesson") for e in notes if isinstance(e, dict) and e.get("action") in ("retire", "withdraw", "merge")}
                for r in _prows:
                    if not r.get("pattern_id") and r["id"] not in _have_p and r["id"] not in _exempt and r.get("scope") != "project":
                        notes.append({"lesson": r["id"], "action": "set-pattern", "pattern": "Reach for the familiar tool instead of the check that fits the claim"})
            except Exception:
                pass
            doc["notes"] = notes
        doc.update(parts)
        # A cycle file must also answer for every document the brief lists for whole-document
        # review: mark them reviewed here (tests of rewriting itself live in test_documents).
        try:
            from sisi import documents as _docs
            _con = retro.connect()
            try:
                _have = {e.get("doc") for e in doc.get("documents") or [] if isinstance(e, dict)}
                _rev = [{"doc": d["doc"], "action": "reviewed", "reason": "test helper: structure left as it is"}
                        for d in _docs.required_documents(_con) if d["doc"] not in _have]
            finally:
                _con.close()
            if _rev:
                doc["documents"] = list(doc.get("documents") or []) + _rev
        except Exception:
            pass
        p = os.path.join(self.tmp, "cycle.json")
        with open(p, "w") as f:
            json.dump(doc, f)
        return p

    def cycle_path(self, doc):
        p = os.path.join(self.tmp, "cycle-%s.json" % id(doc))
        with open(p, "w") as f:
            json.dump(doc, f)
        return p


class RetroShortTests(ShortCase):
    def retro_cli(self, **over):
        from test_retro import argv as retro_argv, GOOD
        f = dict(GOOD)
        f.update(over)
        return self.sisi("retro", "--new", *retro_argv(f))

    def test_retro_stores_short_and_topic(self):
        r = self.retro_cli(short="Add fuzzing to the parser recipe checks.", topic="testing")
        self.assertEqual(r.returncode, 0, r.stdout)
        con = retro.connect()
        rows = [tuple(r) for r in con.execute("SELECT short, topic FROM lessons")]
        con.close()
        self.assertEqual(rows[0], ("Add fuzzing to the parser recipe checks.", "testing"))

    def test_retro_without_short_says_next_round_will_write_it(self):
        r = self.retro_cli()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("next learning round will write", r.stdout)

    def test_retro_limits_are_enforced(self):
        long_short = "word " * 40 + "end."
        self.assertEqual(self.retro_cli(short=long_short.strip()).returncode, 2)
        self.assertEqual(self.retro_cli(short="Do the thing...").returncode, 2)
        self.assertEqual(self.retro_cli(short="Do the thing\u2026").returncode, 2)
        self.assertEqual(self.retro_cli(topic="Testing Stuff").returncode, 2)
        self.assertEqual(self.retro_cli(topic="one two three four").returncode, 2)
        self.assertEqual(self.retro_cli(topic="a" * 31).returncode, 2)
        self.assertEqual(self.retro_cli(short="line one\nline two is long enough here.").returncode, 2)
        con = retro.connect()
        try:
            self.assertEqual(con.execute("SELECT count(*) FROM lessons").fetchone()[0], 0)
        finally:
            con.close()


class HeadingTests(ShortCase):
    def test_word_boundary_cut_never_mid_word(self):
        text = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda"
        cut = retro.word_cut(text, 30)
        self.assertTrue(cut.endswith("\u2026"), cut)
        self.assertTrue(text.startswith(cut[:-1]), cut)
        self.assertEqual(text[len(cut[:-1])], " ")
        self.assertLessEqual(len(cut), 30)

    def test_loose_heading_uses_short_when_present(self):
        lid = self.mk(short="Use a readiness probe, not a sleep.", topic="testing")
        row = self.lesson(lid)
        self.assertIn("Use a readiness probe, not a sleep.", retro.loose_heading(row))

    def test_loose_heading_without_short_is_word_cut(self):
        lid = self.mk(change="Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma")
        h = retro.loose_heading(self.lesson(lid))
        self.assertTrue(h.endswith("\u2026"), h)
        body = h.split(": ", 1)[1][:-1]
        self.assertTrue(self.lesson(lid)["change"].startswith(body))

    def test_lessons_list_and_backlog_use_short(self):
        lid = self.mk(short="Use a readiness probe, not a sleep.", topic="testing")
        out = self.sisi("lessons").stdout
        self.assertIn("Use a readiness probe, not a sleep.", out)
        tool = self.mk(change_kind="tool", change="Make sisi cycle print much faster for very large lesson stores",
                       short="Make sisi cycle faster.", topic="sisi itself")
        bout = self.sisi("backlog").stdout
        self.assertIn("Make sisi cycle faster.", bout)


class DigestTests(ShortCase):
    def seed_digest(self):
        a = self.mk(short="Use a readiness probe, not a sleep.", topic="testing")
        self.set_lesson(a, folded_into="rule:know-done", effect="learned-note", status="applied")
        b = self.mk(change_kind="verifier", target="fuzz",
                    change="Seed the fuzz corpus from golden parser files before fuzzing anything",
                    moment="fuzz seeds were missing at step 5 of the job",
                    short="Seed the fuzz corpus from golden files.", topic="testing")
        self.set_lesson(b, count=3)
        c = self.mk(change="Ask the person before guessing when the request is unclear about success",
                    moment="a guess about success at step 2 was wrong",
                    short="Ask before guessing what success means.", topic="asking questions")
        d = self.mk(change_kind="tool", change="Make sisi lessons digest group lessons by topic for the owner",
                    moment="the owner asked for a digest at step 1",
                    short="Group the digest by topic.", topic="releases")
        e = self.mk(change="Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau upsilon phi chi psi omega extra words here",
                    moment="a long lesson moment at step 9")
        f = self.mk(short="Retired short line should hide.", topic="testing")
        self.set_lesson(f, status="retired", folded_into="rule:know-done")
        return a, b, c, d, e, f

    def test_digest_grouping_plain_states_and_order(self):
        a, b, c, d, e, f = self.seed_digest()
        out = self.sisi("lessons", "digest").stdout
        lines = out.splitlines()
        self.assertTrue(lines[0].count(".") >= 1 and "lesson" in lines[0], lines[0])
        self.assertIn("5 lessons", lines[0])
        # topics by size: testing (2) before singletons, Not yet summarized last topical heading
        self.assertLess(out.index("## testing"), out.index("## asking questions"))
        self.assertLess(out.index("## asking questions"), out.index("## Not yet summarized"))
        self.assertIn("Use a readiness probe, not a sleep.", out)
        self.assertIn("in the rulebook", out)
        self.assertIn("attached to Fuzz work", out)
        self.assertIn("loose note", out)
        self.assertIn("change to sisi itself, not built yet", out)
        self.assertIn("seen 3 times", out)
        # seen only when > 1: lesson a has count 1, its line must not say seen
        a_line = [l for l in lines if "lesson %d" % a in l][0]
        self.assertNotIn("seen", a_line)
        self.assertNotIn("#%d" % f, out)  # retired left out by default
        self.assertNotIn("Retired short line", out)
        self.assertIn("lesson %d" % e, out)  # every line shows its ID
        last = [l for l in lines if l.strip()][-1]
        self.assertIn("sisi lessons show", last)
        low = out.lower()
        for bad in ("strength", "field-note", "aim:"):
            self.assertNotIn(bad, low)

    def test_digest_all_includes_retired_and_not_yet_is_word_cut(self):
        a, b, c, d, e, f = self.seed_digest()
        out = self.sisi("lessons", "digest", "--all").stdout
        self.assertIn("Retired short line should hide.", out)
        e_line = [l for l in out.splitlines() if "lesson %d" % e in l][0]
        self.assertTrue(e_line.rstrip().endswith(("\u2026", ")")) or "\u2026" in e_line, e_line)

    def test_digest_shows_what_you_said_first(self):
        self.seed_digest()
        self.assertEqual(self.sisi("learn", "--scope", "everywhere", "Always", "show", "the", "options.").returncode, 0)
        out = self.sisi("lessons", "digest").stdout
        self.assertIn("## What you said", out)
        self.assertIn("Always show the options.", out)
        self.assertLess(out.index("## What you said"), out.index("## testing"))


class CycleShortTests(ShortCase):
    def test_brief_lists_lacking_topics_and_limits(self):
        have = self.mk(short="Use a readiness probe, not a sleep.", topic="testing")
        need = self.mk(change="Widget caching lesson about parser readiness probes for servers",
                       moment="widget wait at step 2")
        out = cycle.brief_text()
        self.assertIn("short line", out)
        self.assertIn("#%d" % need, out)
        self.assertIn("testing", out)  # topics already in use
        self.assertIn("140", out)
        self.assertIn("30", out)
        self.assertIn("set-short", out)

    def test_check_refuses_file_omitting_set_short_naming_lesson(self):
        need = self.mk()
        doc = self.cycle_doc(notes=[{"lesson": need, "action": "keep"}])
        r = self.sisi("cycle", "check", doc)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("set-short", r.stdout)
        self.assertIn(str(need), r.stdout)
        good = self.cycle_doc(notes=[{"lesson": need, "action": "keep"},
                                     {"lesson": need, "action": "set-short",
                                      "short": "Use a readiness probe, not a sleep.", "topic": "testing"}])
        r2 = self.sisi("cycle", "check", good)
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)

    def test_set_short_combined_and_limits_in_cycle(self):
        lid = self.mk()
        bad = self.cycle_doc(notes=[{"lesson": lid, "action": "set-short",
                                     "short": "word " * 40, "topic": "testing"}])
        r = self.sisi("cycle", "check", bad)
        self.assertEqual(r.returncode, 1, r.stdout)
        good = self.cycle_doc(notes=[{"lesson": lid, "action": "keep"},
                                     {"lesson": lid, "action": "set-short",
                                      "short": "Use a readiness probe, not a sleep.", "topic": "testing"}])
        self.assertEqual(self.sisi("cycle", "apply", good).returncode, 0)
        l = self.lesson(lid)
        self.assertEqual((l["short"], l["topic"]), ("Use a readiness probe, not a sleep.", "testing"))

    def test_cycle_now_prints_brief_when_not_due(self):
        self.assertEqual(self.sisi("cycle", "due").returncode, 1)
        r = self.sisi("cycle", "--now")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("Base version", r.stdout)


class BulletTests(ShortCase):
    def test_field_note_bullet_uses_short_at_creation(self):
        lid = self.mk(change_kind="verifier", target="fuzz",
                      change="Seed the fuzz corpus from golden parser files before fuzzing anything",
                      moment="fuzz seeds were missing at step 5",
                      short="Seed the fuzz corpus from golden files.", topic="testing")
        text = open(os.path.join(self.notes, "fuzz.md")).read()
        self.assertIn("Seed the fuzz corpus from golden files.", text)
        self.assertIn("seen 1 times; lesson %d; full text: sisi lessons show %d" % (lid, lid), text)

    def test_bullet_rewrite_and_exact_revert(self):
        lid = self.mk(change_kind="verifier", target="fuzz",
                      change="Seed the fuzz corpus from golden parser files before fuzzing anything",
                      moment="fuzz seeds were missing at step 5")
        p = os.path.join(self.notes, "fuzz.md")
        before = open(p, "rb").read()
        self.assertIn(b"Seed the fuzz corpus from golden parser files", before)
        doc = self.cycle_doc(notes=[{"lesson": lid, "action": "set-short",
                                     "short": "Seed the fuzz corpus from golden files.", "topic": "testing"}])
        r = self.sisi("cycle", "apply", doc)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        after = open(p, "rb").read()
        self.assertNotEqual(after, before)
        self.assertIn(b"Seed the fuzz corpus from golden files.", after)
        self.assertIn(("full text: sisi lessons show %d" % lid).encode(), after)
        self.assertNotIn(b"Seed the fuzz corpus from golden parser files before fuzzing", after)
        r = self.sisi("cycle", "revert")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(open(p, "rb").read(), before)  # exact bytes restored
        l = self.lesson(lid)
        self.assertIsNone(l["short"])
        self.assertIsNone(l["topic"])

    def test_explicit_note_bullet_is_not_rewritten(self):
        lid = self.mk(change="Parser recipes need a readiness probe before any server work begins",
                      moment="server wait at step 3")
        doc = self.cycle_doc(notes=[
            {"lesson": lid, "action": "fold-into-entry", "into": "parser-or-codec",
             "note": "Explicit split note about readiness probes"},
            {"lesson": lid, "action": "set-short",
             "short": "Use a readiness probe, not a sleep.", "topic": "testing"}])
        self.assertEqual(self.sisi("cycle", "apply", doc).returncode, 0)
        text = open(os.path.join(self.notes, "parser-or-codec.md")).read()
        self.assertIn("Explicit split note about readiness probes", text)
        # a later set-short in a new cycle also leaves the explicit bullet alone
        self.set_lesson(lid, short=None, topic=None)
        # restore base: the previous cycle changed the lesson, so clear via a fresh cycle file
        doc2 = {"version": 1, "base": cycle.base_version(), "summary": "second",
                "notes": [{"lesson": lid, "action": "set-short",
                           "short": "Prefer probes over sleeps.", "topic": "testing"}],
                "documents": [{"doc": "recipe:parser-or-codec", "action": "reviewed",
                               "reason": "this round only rewrites the short line"}]}
        p2 = self.cycle_path(doc2)
        r = self.sisi("cycle", "apply", p2)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text2 = open(os.path.join(self.notes, "parser-or-codec.md")).read()
        self.assertIn("Explicit split note about readiness probes", text2)
        self.assertNotIn("Prefer probes over sleeps.", text2)


class MigrationTests(ShortCase):
    def test_old_store_without_fields_still_loads(self):
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
        con.commit(); con.close()
        import shutil
        os.makedirs(os.path.dirname(retro.db_path()), exist_ok=True)
        shutil.copy(old, retro.db_path())
        con = retro.connect()
        try:
            row = dict(con.execute("SELECT * FROM lessons WHERE id=1").fetchone())
            cols = [r[1] for r in con.execute("PRAGMA table_info(lessons)")]
        finally:
            con.close()
        self.assertIn("short", cols)
        self.assertIn("topic", cols)
        self.assertEqual(row["change"], "Seed the fuzz corpus from golden parser files")
        self.assertIsNone(row["short"])
        out = self.sisi("lessons", "digest").stdout
        self.assertIn("Seed the fuzz corpus", out)


if __name__ == "__main__":
    unittest.main()
