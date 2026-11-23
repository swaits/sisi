"""Three tiers (core, user, project): round-trips, migration of `everywhere`, the sisi-name
exemption, promote from the clone, export, and exact cycle revert with tiers."""
import json, os, shutil, subprocess, unittest
from support import *
from sisi import paths, retro, scope, store
from unittest import mock

WHEN = "csv, tsv, spreadsheet, tabular data, import, export, parse, delimited file"
PATTERN = "Build the obvious thing instead of using what the environment already provides"


def retro_cli(case, tier, **kw):
    f = dict(aim="verified", moment="the export broke on a quoted field at step 2 of the run",
             cause="rows were joined by hand instead of with a quoting writer",
             change_kind="rule", change="Write delimited files with a quoting writer so fields survive",
             when=WHEN, pattern=PATTERN, short="Use a quoting writer for delimited exports.",
             topic="data files")
    f.update(kw)
    args = ["retro", "--scope", tier]
    for k in ("aim", "moment", "cause", "change_kind", "change", "when", "pattern", "short", "topic"):
        args += ["--" + k.replace("_", "-"), f[k]]
    return case.sisi(*args)


class TierTests(SisiCase):
    def setUp(self):
        super().setUp()
        self.git_init()

    def test_tier_decisions_round_trip(self):
        for tier in ("core", "user"):
            r = retro_cli(self, tier, moment="export %s broke on a quoted field at step 3" % tier,
                          change="Write delimited files with a quoting writer so %s fields survive" % tier)
            if tier == "user":
                self.assertIn(r.returncode, (0, 4), r.stdout)  # 4 = similar lesson kept as sighting
                if r.returncode == 4:
                    r = self.sisi("retro", "--new", "--scope", "user", "--aim", "verified",
                                  "--moment", "export user broke on a quoted field at step 3",
                                  "--cause", "rows were joined by hand instead of with a quoting writer",
                                  "--change-kind", "rule",
                                  "--change", "Write delimited files with a quoting writer so user fields survive",
                                  "--when", WHEN, "--pattern", PATTERN,
                                  "--short", "Use a quoting writer for delimited exports.",
                                  "--topic", "data files")
            self.assertEqual(r.returncode, 0, r.stdout)
        con = retro.connect()
        try:
            tiers = [scope.tier_of(r[0]) for r in con.execute("SELECT scope FROM lessons ORDER BY id")]
        finally:
            con.close()
        self.assertEqual(tiers, ["core", "user"])
        for tier, text in (("core", "sisi should anticipate what is needed from what was already said"),
                           ("user", "always ask questions as options with a recommendation")):
            r = self.sisi("learn", "--scope", tier, text)
            self.assertEqual(r.returncode, 0, r.stdout)
        recs = store.read("learn")
        self.assertEqual([r["scope"] for r in recs], ["core", "user"])
        out = self.sisi("oracle").stdout
        self.assertIn("always ask questions as options", out)
        self.assertIn("sisi should anticipate", out)  # core, until the product carries it

    def test_missing_scope_text_asks_the_two_questions(self):
        r = self.sisi("learn", "always show options")
        self.assertEqual(r.returncode, 2)
        self.assertIn("all projects where sisi may be used", r.stdout)
        self.assertIn("every user who installs sisi", r.stdout)

    def test_statement_naming_sisi_is_accepted_as_core_inside_sisi_repo(self):
        d = os.path.join(self.tmp, "sisi")
        os.makedirs(d)
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        r = self.sisi("learn", "--scope", "core",
                      "sisi should anticipate what I need from what I already said", cwd=d)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(store.read("learn")[0]["scope"], "core")

    def test_everywhere_migrates_to_unscoped_tier_and_still_delivers(self):
        con = retro.connect()
        lid = retro.new_lesson(con, dict(
            aim="verified", change_kind="rule", target=None,
            moment="the export broke on a quoted field at step 2 of the run",
            cause="rows were joined by hand instead of with a quoting writer",
            change="Write delimited files with a quoting writer so fields survive",
            when=WHEN, short="Use a quoting writer.", topic="data files",
            scope="user", pattern=PATTERN), self.proj, None)
        con.execute("UPDATE lessons SET scope='everywhere' WHERE id=?", (lid,))
        con.commit(); con.close()
        con = retro.connect()  # migration on open
        try:
            v = con.execute("SELECT scope FROM lessons WHERE id=?", (lid,)).fetchone()[0]
        finally:
            con.close()
        self.assertEqual(v, "unscoped-tier")
        self.assertIn("Use a quoting writer", retro.tick_block(self.proj))
        brief = self.sisi("cycle", "--now").stdout
        self.assertIn("tier", brief.lower())

    def test_digest_groups_core_user_and_project_counts(self):
        r = retro_cli(self, "core")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.sisi("learn", "--scope", "user", "always ask questions as options with a recommendation")
        out = self.sisi("lessons", "digest").stdout
        self.assertIn("## In sisi itself, for every user", out)
        self.assertIn("## How you want work done", out)
        self.assertIn("waiting to be promoted", out)


class PromoteTierTests(SisiCase):
    def setUp(self):
        super().setUp()
        self.git_init()
        self.src = os.path.join(self.tmp, "src")
        for d in ("bin", "sisi", "canon"):
            os.makedirs(os.path.join(self.src, d))
        open(os.path.join(self.src, "bin", "sisi"), "w").write("#!/bin/sh\n")
        open(os.path.join(self.src, "sisi", "cli.py"), "w").write("# cli\n")
        shutil.copy(os.path.join(REPO, "canon", "core.md"), os.path.join(self.src, "canon", "core.md"))
        os.makedirs(os.path.join(self.data), exist_ok=True)
        _p = mock.patch.object(paths, "REPO", self.src)  # run from the clone
        _p.start()
        self.addCleanup(_p.stop)

    def core_lesson_folded_to_rule(self):
        r = retro_cli(self, "core")
        self.assertEqual(r.returncode, 0, r.stdout)
        d = os.path.join(self.data, "overlay", "rules")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "quoting-writer.md"), "w") as f:
            f.write("## Write delimited files with a quoting writer\n\n"
                    "Write delimited files with a quoting writer so embedded delimiters and "
                    "newlines survive.\n\nWhy: hand-joined rows break on real data.\n")
        con = retro.connect()
        try:
            con.execute("UPDATE lessons SET folded_into='rule:quoting-writer' WHERE id=1")
            con.commit()
        finally:
            con.close()

    def test_promote_lists_core_items(self):
        self.assertEqual(retro_cli(self, "core").returncode, 0)
        out = self.sisi("promote").stdout
        self.assertIn("lesson:1", out)

    def test_promote_from_clone_edits_product_and_drops_personal_copy(self):
        self.core_lesson_folded_to_rule()
        overlay_file = os.path.join(self.data, "overlay", "rules", "quoting-writer.md")
        self.assertTrue(os.path.exists(overlay_file))
        r = self.sisi("promote", "lesson:1")  # dry run: product untouched
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("quoting-writer", open(os.path.join(self.src, "canon", "core.md")).read())
        r = self.sisi("promote", "lesson:1", "--apply")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        core = open(os.path.join(self.src, "canon", "core.md")).read()
        self.assertIn("quoting writer so embedded delimiters", core)
        self.assertFalse(os.path.exists(overlay_file))  # dropped only after the product has it
        con = retro.connect()
        try:
            self.assertTrue(con.execute("SELECT promoted FROM lessons WHERE id=1").fetchone()[0])
        finally:
            con.close()
        self.assertNotIn("lesson:1", self.sisi("promote").stdout)

    def test_export_contains_no_history_or_names(self):
        self.assertEqual(retro_cli(self, "core").returncode, 0)
        self.sisi("learn", "--scope", "core", "sisi should use what the host already provides")
        p = os.path.join(self.tmp, "contrib.md")
        r = self.sisi("promote", "--export", p)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = open(p).read()
        self.assertIn("Write delimited files with a quoting writer", text)
        self.assertIn("sisi should use what the host already provides", text)
        self.assertNotIn("the export broke on a quoted field", text)  # the moment (history)
        self.assertNotIn("rows were joined by hand", text)            # the cause (history)
        self.assertNotIn(self.tmp, text)

    def test_cycle_set_scope_to_core_and_exact_revert(self):
        con = retro.connect()
        lid = retro.new_lesson(con, dict(
            aim="verified", change_kind="rule", target=None,
            moment="the export broke on a quoted field at step 2 of the run",
            cause="rows were joined by hand instead of with a quoting writer",
            change="Write delimited files with a quoting writer so fields survive",
            when=WHEN, short="Use a quoting writer.", topic="data files",
            pattern=PATTERN), self.proj, None)
        con.commit(); con.close()
        from sisi import cycle
        doc = {"version": 1, "base": cycle.base_version(), "summary": "tier it",
               "notes": [{"lesson": lid, "action": "set-scope", "scope": "core"}]}
        p = os.path.join(self.tmp, "cyc.json")
        with open(p, "w") as f:
            json.dump(doc, f)
        r = self.sisi("cycle", "apply", p)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        con = retro.connect()
        try:
            self.assertEqual(con.execute("SELECT scope FROM lessons WHERE id=?", (lid,)).fetchone()[0], "core")
        finally:
            con.close()
        r = self.sisi("cycle", "revert")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        con = retro.connect()
        try:
            self.assertEqual(con.execute("SELECT scope FROM lessons WHERE id=?", (lid,)).fetchone()[0],
                             "unscoped-tier")
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
