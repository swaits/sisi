"""Patterns: `sisi retro --pattern`, `sisi retro patterns`, the cycle's set-pattern action,
and patterns-first digest/improve."""
import json, os, unittest
from support import *
from sisi import retro

WHEN = "csv, tsv, spreadsheet, tabular data, import, export, parse, delimited file"
PATTERN = "Build the obvious thing instead of using what the environment already provides"


def retro_args(**kw):
    f = dict(aim="verified", moment="the export broke on a quoted field at step 2 of the run",
             cause="rows were joined by hand instead of with the writer the project already had",
             change_kind="rule", change="Write delimited files with a quoting writer so fields survive",
             when=WHEN, scope="core", pattern=PATTERN,
             short="Use a quoting writer for delimited exports.", topic="data files")
    f.update(kw)
    out = []
    for k in ("aim", "moment", "cause", "change_kind", "change", "when", "scope", "short", "topic", "pattern"):
        if f.get(k) is not None:
            out += ["--" + k.replace("_", "-"), str(f[k])]
    if f.get("pattern_id") is not None:
        out += ["--pattern-id", str(f["pattern_id"])]
    return out


class RetroPatternTests(SisiCase):
    def setUp(self):
        super().setUp()
        self.git_init()

    def test_pattern_is_required_for_a_new_lesson(self):
        r = self.sisi("retro", *retro_args(pattern=None))
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("pattern", (r.stdout + r.stderr).lower())

    def test_pattern_is_stored_and_reused_not_duplicated(self):
        r = self.sisi("retro", *retro_args())
        self.assertEqual(r.returncode, 0, r.stdout)
        r = self.sisi("retro", "--new", *retro_args(
            moment="another export broke on an embedded newline at step 4 of the run",
            change="Write delimited files with a quoting writer so newlines survive"))
        self.assertEqual(r.returncode, 0, r.stdout)
        con = retro.connect()
        try:
            pats = retro.patterns(con)
            self.assertEqual(len(pats), 1, pats)
            self.assertEqual(pats[0]["statement"], PATTERN)
            ids = [row[0] for row in con.execute("SELECT pattern_id FROM lessons ORDER BY id")]
            self.assertEqual(ids, [pats[0]["id"], pats[0]["id"]])
        finally:
            con.close()

    def test_retro_patterns_lists_them_and_pattern_id_selects(self):
        self.assertEqual(self.sisi("retro", *retro_args()).returncode, 0)
        out = self.sisi("retro", "patterns").stdout
        self.assertIn(PATTERN, out)
        r = self.sisi("retro", "--new", *retro_args(
            pattern=None, pattern_id=1,
            moment="a third export broke on a delimiter in a name at step 1 of the run",
            change="Write delimited files with a quoting writer so delimiters survive"))
        self.assertEqual(r.returncode, 0, r.stdout)
        con = retro.connect()
        try:
            self.assertEqual(len(retro.patterns(con)), 1)
        finally:
            con.close()

    def test_pattern_naming_the_project_or_restating_the_change_is_refused(self):
        r = self.sisi("retro", *retro_args(pattern="proj export rows are joined by hand in this repo"))
        self.assertNotEqual(r.returncode, 0, r.stdout)
        r = self.sisi("retro", *retro_args(pattern="Write delimited files with a quoting writer so fields survive"))
        self.assertNotEqual(r.returncode, 0, r.stdout)


class CyclePatternTests(SisiCase):
    def setUp(self):
        super().setUp()
        self.git_init()

    def lesson_without_pattern(self):
        con = retro.connect()
        try:
            lid = retro.new_lesson(con, dict(
                aim="verified", change_kind="rule", target=None,
                moment="the export broke on a quoted field at step 2 of the run",
                cause="rows were joined by hand instead of with a quoting writer",
                change="Write delimited files with a quoting writer so fields survive",
                when=WHEN, short="Use a quoting writer for delimited exports.", topic="data files",
                scope="core"), self.proj, None)
            con.commit()
            return lid
        finally:
            con.close()

    def test_cycle_brief_lists_patterns_and_check_requires_set_pattern(self):
        lid = self.lesson_without_pattern()
        brief = self.sisi("cycle", "--now").stdout
        self.assertIn("pattern", brief.lower())
        from sisi import cycle
        doc = {"version": 1, "base": cycle.base_version(), "summary": "x",
               "notes": [{"lesson": lid, "action": "keep"}]}
        p = os.path.join(self.tmp, "cyc.json")
        with open(p, "w") as f:
            json.dump(doc, f)
        r = self.sisi("cycle", "check", p)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("set-pattern", r.stdout)
        doc["notes"].append({"lesson": lid, "action": "set-pattern", "pattern": PATTERN})
        with open(p, "w") as f:
            json.dump(doc, f)
        r = self.sisi("cycle", "check", p)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.sisi("cycle", "apply", p)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        con = retro.connect()
        try:
            self.assertEqual(retro.patterns(con)[0]["statement"], PATTERN)
        finally:
            con.close()

    def test_pattern_merge_keeps_one(self):
        con = retro.connect()
        try:
            a = retro.get_or_create_pattern(con, PATTERN)
            b = retro.get_or_create_pattern(con, "Rebuild what already exists instead of calling it")
            con.commit()
        finally:
            con.close()
        lid = self.lesson_without_pattern()
        from sisi import cycle
        doc = {"version": 1, "base": cycle.base_version(), "summary": "merge patterns",
               "notes": [{"lesson": lid, "action": "set-pattern", "pattern_id": b}],
               "patterns": [{"pattern": b, "action": "merge", "into": a}]}
        p = os.path.join(self.tmp, "cyc.json")
        with open(p, "w") as f:
            json.dump(doc, f)
        r = self.sisi("cycle", "apply", p)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        con = retro.connect()
        try:
            pats = retro.patterns(con)
            self.assertEqual([x["id"] for x in pats], [a])
            self.assertEqual(con.execute("SELECT pattern_id FROM lessons WHERE id=?", (lid,)).fetchone()[0], a)
        finally:
            con.close()


class PatternsFirstTests(SisiCase):
    def setUp(self):
        super().setUp()
        self.git_init()
        self.assertEqual(self.sisi("retro", *retro_args()).returncode, 0)

    def test_digest_shows_patterns_first(self):
        out = self.sisi("lessons", "digest").stdout
        self.assertIn("## Patterns", out)
        self.assertLess(out.index("## Patterns"), out.index("## In sisi itself"))
        self.assertIn(PATTERN, out)

    def test_improve_shows_patterns(self):
        out = self.sisi("improve").stdout
        self.assertIn(PATTERN, out)


if __name__ == "__main__":
    unittest.main()
