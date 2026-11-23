import json, os, subprocess, unittest
from support import *
from sisi import retro, scope, store

WHEN = "csv, tsv, spreadsheet, tabular data, import, export, parse, delimited file"

def retro_args(**kw):
    f = dict(aim="verified", moment="the export broke in the acme-widgets repo when a field held a newline",
             cause="rows were joined by hand in acme-widgets instead of with a quoting writer",
             change_kind="rule",
             change="Write delimited files with a quoting writer so embedded newlines survive",
             when=WHEN, short="Use a quoting writer for delimited exports.", topic="data files",
             pattern="Build the obvious thing instead of using what the environment already provides")
    f.update(kw)
    out = []
    for k, v in f.items():
        out += ["--" + k.replace("_", "-"), v]
    return out

# (text, kind, expected) expected True = universal passes, False = refused as naming this project
LABELLED = [
    ("Write delimited files with a quoting writer so embedded newlines survive", "rule", True),
    ("Check the README and CHANGELOG agree with the version before publishing", "rule", True),
    ("Update the changelog when behaviour changes and keep the readme example runnable", "rule", True),
    ("Run the whole test suite before saying work is done", "rule", True),
    ("Prefer a readiness probe over a fixed sleep when waiting for servers", "rule", True),
    ("Write the failing test first and watch it fail before fixing code", "rule", True),
    ("Keep functions small enough to test without a display or network", "rule", True),
    ("Never report success when every input record was skipped silently", "rule", True),
    ("Compare totals before and after any data migration with an independent count", "rule", True),
    ("Make error messages name the field that failed and what would be valid", "rule", True),
    ("In the acme-widgets project always quote fields by hand in the exporter", "rule", False),
    ("The acme-widgets exporter must join rows with its own quoting code", "rule", False),
    ("Fix export in widget_export.py by using a quoting writer there", "rule", False),
    ("Change src/widget_export.py to use a quoting writer for every row", "rule", False),
    ("See https://github.com/acme/acme-widgets for how exports should work here", "rule", False),
    ("In acme-widgets, release notes live in the changelog of that repository only", "rule", False),
    ("sisi should refuse lessons that name the project they came from", "tool", True),
    ("sisi must show the backlog separately from loose lesson headings", "tool", True),
    ("Agents should record a retro at the end of every piece of work", "rule", True),
    ("A parser should reject overlong input instead of allocating without bound", "rule", True),
    ("Use the acme-widgets keyboard layout with control on the left in every project", "rule", False),
    ("Keep the widget test fixture frozen at the acme-widgets sample rows", "rule", False),
    ("Always run tests with the licence and security notes updated for releases", "rule", True),
    ("Document every public function with its errors and limits in the readme", "rule", True),
]

class ScopeCase(SisiCase):
    def setUp(self):
        super().setUp()
        self.git_init()
        subprocess.run(["git", "remote", "add", "origin", "https://github.com/acme/acme-widgets.git"], cwd=self.proj, check=True)
        with open(os.path.join(self.proj, "widget_export.py"), "w") as f:
            f.write("x=1\n")
        os.makedirs(os.path.join(self.proj, "src"))
        with open(os.path.join(self.proj, "src", "widget_export.py"), "w") as f:
            f.write("x=1\n")

class ProjectIdTests(ScopeCase):
    def test_remote_id_stable_across_clone_and_rename(self):
        self.assertEqual(scope.project_id(self.proj), scope.normalized_remote("git" + chr(64) + "github.com:acme/acme-widgets.git"))
        other = os.path.join(self.tmp, "renamed")
        subprocess.run(["git", "clone", "-q", self.proj, other], check=True)
        # clone from local path has local remote; set same remote
        subprocess.run(["git", "remote", "set-url", "origin", "git" + chr(64) + "github.com:acme/acme-widgets"], cwd=other, check=True)
        self.assertEqual(scope.project_id(other), scope.project_id(self.proj))

    def test_path_fallback_without_remote(self):
        d = os.path.join(self.tmp, "plainproj"); os.makedirs(d)
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        self.assertEqual(scope.project_id(d), os.path.realpath(d))

class LabelledUniversalTests(ScopeCase):
    def test_labelled_set(self):
        hits = false_refusals = 0
        for text, kind, want_pass in LABELLED:
            reason = scope.universal_refusal([text], self.proj, kind=kind)
            got_pass = reason is None
            if got_pass and want_pass:
                hits += 1
            if not got_pass and want_pass:
                false_refusals += 1
            self.assertEqual(got_pass, want_pass, "%r kind=%s reason=%s" % (text, kind, reason))
        self.assertGreaterEqual(len(LABELLED), 20)

    def test_universal_change_with_project_moment_passes(self):
        # amendment: moment/cause may name the project; only delivered parts are checked
        for text in LABELLED[:4]:
            self.assertIsNone(scope.universal_refusal([text], self.proj, kind="rule"))
        r = self.sisi("retro", *retro_args(scope="everywhere"))
        self.assertEqual(r.returncode, 0, r.stdout)

class RetroScopeTests(ScopeCase):
    def test_missing_scope_refused_with_explanation(self):
        r = self.sisi("retro", *retro_args())
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("core", r.stdout); self.assertIn("user", r.stdout); self.assertIn("project", r.stdout)
        self.assertIn("general terms", r.stdout)

    def test_everywhere_naming_project_refused(self):
        r = self.sisi("retro", *retro_args(scope="everywhere",
                                           change="In acme-widgets always use a quoting writer in the exporter for rows"))
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("rewrite", r.stdout.lower())

    def test_project_scope_goes_to_handover_not_global(self):
        r = self.sisi("retro", *retro_args(scope="project",
                                           change="Use a quoting writer for delimited exports in this project",
                                           short="Use a quoting writer here."))
        self.assertEqual(r.returncode, 0, r.stdout)
        con = retro.connect()
        self.assertEqual(con.execute("SELECT count(*) FROM lessons").fetchone()[0], 0); con.close()
        from sisi import handover
        items = handover.for_project(scope.project_id(self.proj))
        self.assertEqual(len(items), 1)
        self.assertIn("acme-widgets", items[0]["moment"])
        part1, part2 = retro.delivery("csv spreadsheet export delimited file")
        self.assertFalse(part1 or part2)
        self.assertIn("belong to this project", retro.tick_block(self.proj))
        other = os.path.join(self.tmp, "otherproj"); os.makedirs(other)
        self.assertNotIn("belong to this project", retro.tick_block(other))
        out = self.sisi("handover").stdout
        self.assertIn("Use a quoting writer for delimited exports in this project", out)
        hid = items[0]["hid"]
        bad = self.sisi("handover", "done", hid, "--where", "NOTES.md")
        self.assertEqual(bad.returncode, 1, bad.stdout)
        with open(os.path.join(self.proj, "NOTES.md"), "w") as f:
            f.write("# design notes\n\nUse a quoting writer for delimited exports in this project.\n")
        ok = self.sisi("handover", "done", hid, "--where", "NOTES.md")
        self.assertEqual(ok.returncode, 0, ok.stdout)
        self.assertEqual(handover.load_pile(), [])
        self.assertIn("NOTES.md", open(handover.filed_path()).read())

    def test_learn_missing_scope_and_project_learn(self):
        r = self.sisi("learn", "always show options")
        self.assertEqual(r.returncode, 2, (r.stdout, r.stderr))
        r = self.sisi("learn", "--scope", "project", "use the left control key here")
        self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))
        self.assertEqual(store.read("quarantine"), [])
        from sisi import handover
        items = handover.for_project(scope.project_id(self.proj))
        self.assertEqual(items[-1]["text"], "use the left control key here")
        r = self.sisi("learn", "--scope", "everywhere", "in acme-widgets always show options")
        self.assertEqual(r.returncode, 2, (r.stdout, r.stderr))

    def test_lessons_show_split(self):
        r = self.sisi("retro", *retro_args(scope="everywhere"))
        self.assertEqual(r.returncode, 0, r.stdout)
        out = self.sisi("lessons", "show", "1").stdout
        self.assertIn("Where this came from (historical example)", out)
        self.assertLess(out.index("Write delimited files"), out.index("Where this came from"))
        self.assertIn("acme-widgets", out.split("Where this came from (historical example)", 1)[1])

    def test_digest_universal_first_then_project(self):
        self.sisi("retro", *retro_args(scope="everywhere"))
        self.sisi("retro", "--new", *retro_args(scope="project",
                                                 change="Use a quoting writer for delimited exports in this project",
                                                 short="Use a quoting writer here.", moment="another export broke at step 2 in this repo today"))
        out = self.sisi("lessons", "digest").stdout
        self.assertIn("Use a quoting writer for delimited exports.", out)
        self.assertNotIn("Use a quoting writer here.", out)
        self.assertIn("waiting to be filed", out)
        self.assertIn("acme-widgets", out)

class StaleReadingTests(ScopeCase):
    def test_reading_lessons_does_not_stale_cycle(self):
        # folded lesson shown 20x via lessons show retires; cycle check must still pass
        con = retro.connect()
        lid = retro.new_lesson(con, dict(aim="verified", change_kind="verifier", target=None,
                                         moment="fuzz seeds missing at step 5 of the nightly run",
                                         cause="the corpus was not seeded from golden files",
                                         change="Seed the fuzz corpus from golden parser files before fuzzing",
                                         when=WHEN, short="Seed fuzz corpus from golden files.", topic="testing"), self.proj, None)
        con.execute("UPDATE lessons SET folded_into='fuzz', status='applied', effect='field-note' WHERE id=?", (lid,))
        con.commit(); con.close()
        from sisi import cycle
        base = cycle.base_version()
        for _ in range(20):
            out = self.sisi("lessons", "show", str(lid))
            self.assertEqual(out.returncode, 0, out.stdout)
        con = retro.connect()
        st = dict(con.execute("SELECT * FROM lessons WHERE id=?", (lid,)).fetchone()); con.close()
        self.assertEqual(st["status"], "applied")  # retirement deferred while the round is open
        doc = {"version": 1, "base": base, "summary": "keep",
               "notes": [{"lesson": lid, "action": "set-short", "short": "Seed fuzz corpus from golden files.", "topic": "testing"},
                         {"lesson": lid, "action": "set-pattern", "pattern": "Reach for the familiar tool instead of the check that fits the claim"},
                         {"lesson": lid, "action": "set-scope", "scope": "core"}]}
        p = os.path.join(self.tmp, "cyc.json")
        with open(p, "w") as f: json.dump(doc, f)
        r = self.sisi("cycle", "check", p)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

class DueAndBacklogTests(ScopeCase):
    def test_tool_lessons_do_not_make_cycle_due_by_headings(self):
        con = retro.connect()
        for i in range(10):
            retro.new_lesson(con, dict(aim="speed", change_kind="tool", target=None,
                                       moment="tool wait %d at step 2 of the run" % i, cause="no cache existed for that step",
                                       change="Make sisi cache transcript scans between gate decisions number %d and reuse them always" % i,
                                       when=WHEN, short="Cache transcript scans.", topic="sisi itself"), self.proj, None)
        con.commit(); con.close()
        from sisi import cycle
        st = cycle.due_state()
        self.assertFalse(any("loose lesson headings" in r for r in st["reasons"]), st["reasons"])
        out = self.sisi("backlog").stdout
        self.assertIn("cap", out.lower())

    def test_applied_tool_lesson_not_not_built_in_digest(self):
        con = retro.connect()
        lid = retro.new_lesson(con, dict(aim="speed", change_kind="tool", target=None,
                                         moment="tool wait at step 2 of the run today", cause="no cache existed for that step",
                                         change="Make sisi cache transcript scans between gate decisions and reuse them",
                                         when=WHEN, short="Cache transcript scans.", topic="sisi itself"), self.proj, None)
        con.commit(); con.close()
        self.assertEqual(self.sisi("lessons", "set", str(lid), "--status", "applied").returncode, 0)
        out = self.sisi("lessons", "digest").stdout
        self.assertNotIn("not built yet", out)
        self.assertIn("built", out)
        self.assertNotIn("#%d" % lid, self.sisi("backlog").stdout)

class CycleScopeTests(ScopeCase):
    def test_cycle_refuses_folding_project_lesson_into_entry(self):
        con = retro.connect()
        lid = retro.new_lesson(con, dict(aim="verified", change_kind="rule", target=None,
                                         moment="export broke at step 2 in this repo", cause="rows joined by hand here",
                                         change="Use a quoting writer for delimited exports in this project",
                                         when=WHEN, short="Use a quoting writer here.", topic="data files"), self.proj, None)
        con.execute("UPDATE lessons SET scope='project', project=? WHERE id=?", (scope.project_id(self.proj), lid))
        con.commit(); con.close()
        from sisi import cycle
        doc = {"version": 1, "base": cycle.base_version(), "summary": "x",
               "notes": [{"lesson": lid, "action": "fold-into-rule", "into": "know-done"},
                         {"lesson": lid, "action": "set-short", "short": "Use a quoting writer here.", "topic": "data files"}]}
        p = os.path.join(self.tmp, "cyc2.json")
        with open(p, "w") as f: json.dump(doc, f)
        r = self.sisi("cycle", "check", p)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("project", r.stdout)

class CleanupRevertTests(ScopeCase):
    def test_set_scope_project_moves_and_revert_restores(self):
        con = retro.connect()
        lid = retro.new_lesson(con, dict(aim="verified", change_kind="rule", target=None,
                                         moment="export broke at step 2 in acme-widgets today", cause="rows joined by hand here",
                                         change="Use a quoting writer for delimited exports in this project",
                                         when=WHEN, short="Use a quoting writer here.", topic="data files"), self.proj, None)
        con.commit(); con.close()
        store.append("quarantine", store.stamp({"text": "use the left control key here"}))
        from sisi import cycle
        base = cycle.base_version()
        brief = self.sisi("cycle", "--now").stdout
        self.assertIn("Scope cleanup", brief)
        self.assertIn(self.proj, brief)
        doc = {"version": 1, "base": base, "summary": "cleanup",
               "notes": [{"lesson": lid, "action": "set-scope", "scope": "project",
                          "project": scope.project_id(self.proj)}],
               "learn": [{"text": "use the left control key here", "action": "set-scope",
                          "scope": "project", "project": scope.project_id(self.proj)}]}
        p = os.path.join(self.tmp, "cleanup.json")
        with open(p, "w") as f: json.dump(doc, f)
        r = self.sisi("cycle", "apply", p)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("characters ->", r.stdout)
        con = retro.connect()
        self.assertEqual(con.execute("SELECT count(*) FROM lessons").fetchone()[0], 0); con.close()
        self.assertEqual(store.read("quarantine"), [])
        from sisi import handover
        self.assertEqual(len(handover.load_pile()), 2)
        self.assertNotIn("Use a quoting writer here", self.sisi("lessons", "digest").stdout)
        r = self.sisi("cycle", "revert")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        con = retro.connect()
        self.assertEqual(con.execute("SELECT count(*) FROM lessons").fetchone()[0], 1); con.close()
        self.assertEqual(len(store.read("quarantine")), 1)
        self.assertEqual(handover.load_pile(), [])


if __name__ == "__main__":
    unittest.main()
