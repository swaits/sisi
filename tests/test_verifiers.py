import json, os, unittest
from support import *
from sisi import verifiers as V

BODY_V = "\n".join("## " + h + "\ntext" for h in V.V_HEADINGS) + "\n"
BODY_D = "\n".join("## " + h + "\ntext" for h in V.D_HEADINGS) + "\n"


def vfile(id, section="prove", rung=1, cost="low", languages="any", kinds="general", detect="true", ran="no",
          title=None, answers="Is it true?", body=BODY_V, extra=""):
    return ("---\nid: %s\ntitle: %s\nanswers: %s\nrung: %s\nsection: %s\nlanguages: %s\nkinds: %s\ncost: %s\n"
            "detect: %s\nran_here: %s\n%s---\n%s" % (id, title or id.title(), answers, rung, section, languages, kinds,
                                                     cost, detect, ran, extra, body))


def dfile(id, title="T", applies="work", body=BODY_D):
    return "---\nid: %s\ntitle: %s\napplies_to: %s\n---\n%s" % (id, title, applies, body)


class LibCase(SisiCase):
    def setUp(self):
        super().setUp()
        self.vdir, self.ddir = os.path.join(self.tmp, "verifiers"), os.path.join(self.tmp, "done")
        os.makedirs(self.vdir)
        os.makedirs(self.ddir)
        os.environ["SISI_VERIFIERS"], os.environ["SISI_DONE"] = self.vdir, self.ddir
        self.addCleanup(os.environ.pop, "SISI_VERIFIERS", None)
        self.addCleanup(os.environ.pop, "SISI_DONE", None)

    def put(self, rel, text, root=None):
        p = os.path.join(root or self.vdir, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)

    def seed(self):
        self.put("prove/lean4.md", vfile("lean4", "prove", 1, "high", "lean, rust", "general, parsing", "false",
                                         title="Lean 4 proofs", answers="Is this property true for every input, not just the ones I tried?"))
        self.put("many-inputs/proptest.md", vfile("proptest", "many-inputs", 2, "low", "rust", "parsing, money", "true",
                                                  title="Rust property testing", answers="Does parsing round trip for random inputs?"))
        self.put("many-inputs/hypothesis.md", vfile("hypothesis", "many-inputs", 2, "low", "python", "parsing", "exit 3",
                                                    title="Python hypothesis", answers="Do random inputs break this function?"))
        self.put("regression/snapshot.md", vfile("snapshot", "regression", 4, "low", "any", "ui", "",
                                                 title="Screenshot comparison", answers="Did the page stop looking the same?"))
        self.put("flat-one.md", vfile("flat-one", "design", 3, "medium", "any", "general", "true", title="Flat file at root",
                                      answers="Is the design sound?"))  # tolerated at root depth

    def ids(self, out):
        return [l.split()[0] for l in out.splitlines() if l.startswith("  ")]


class ParseTests(LibCase):
    def test_header_parsing_and_lists(self):
        self.put("prove/x.md", vfile("x", languages="Lean, Rust", kinds="parsing,money"))
        e = V.load_verifiers()[0]
        self.assertEqual((e["id"], e["rung"], e["section"]), ("x", 1, "prove"))
        self.assertEqual(e["languages"], ["lean", "rust"])
        self.assertEqual(e["kinds"], ["parsing", "money"])
        self.assertIn("Use when", e["body"])
        self.assertEqual(e["problems"], [])

    def test_value_may_contain_colon(self):
        self.put("prove/x.md", vfile("x", answers="Is it true: for all inputs?"))
        self.assertEqual(V.load_verifiers()[0]["answers"], "Is it true: for all inputs?")

    def test_missing_header(self):
        self.put("old.md", "# old file\nno header\n")
        self.assertTrue(V.load_verifiers()[0]["problems"])
        self.assertEqual(V.usable(V.load_verifiers()), [])


class ListTests(LibCase):
    def test_grouped_by_section_with_columns(self):
        self.seed()
        out = self.sisi("verifiers").stdout
        self.assertLess(out.index("design"), out.index("prove"))
        self.assertLess(out.index("prove"), out.index("many-inputs"))
        line = next(l for l in out.splitlines() if "lean4" in l)
        for w in ("r1", "high", "lean, rust", "Lean 4 proofs"):
            self.assertIn(w, line)
        self.assertIn("flat-one", out)  # root-depth file tolerated

    def test_filters(self):
        self.seed()
        f = lambda *a: self.ids(self.sisi("verifiers", *a).stdout)
        self.assertEqual(sorted(f("--lang", "rust")), ["flat-one", "lean4", "proptest", "snapshot"])
        self.assertEqual(sorted(f("--lang", "python")), ["flat-one", "hypothesis", "snapshot"])
        self.assertEqual(sorted(f("--kind", "money")), ["proptest"])
        self.assertEqual(sorted(f("--rung", "2")), ["hypothesis", "lean4", "proptest"])  # 2 or stronger
        self.assertEqual(f("--section", "regression"), ["snapshot"])
        self.assertEqual(sorted(f("--installed")), ["flat-one", "proptest", "snapshot"])  # lean4/hypothesis detect fails; empty detect = n/a

    def test_free_text_all_words_case_insensitive(self):
        self.seed()
        self.put("prove/body.md", vfile("body", body=BODY_V + "\nmentions Zebra crossing\n"))
        f = lambda *a: self.ids(self.sisi("verifiers", *a).stdout)
        self.assertEqual(f("ZEBRA"), ["body"])
        self.assertEqual(f("property", "lean"), ["lean4"])
        self.assertEqual(f("property", "python"), [])
        self.assertEqual(f("round", "trip"), ["proptest"])  # matches answers

    def test_json(self):
        self.seed()
        d = json.loads(self.sisi("verifiers", "--json", "--section", "prove").stdout)
        self.assertEqual([x["id"] for x in d], ["lean4"])
        self.assertEqual(d[0]["installed"], "no")
        self.assertEqual(d[0]["rung"], 1)

    def test_bad_flag_value(self):
        self.assertEqual(self.sisi("verifiers", "--rung", "x").returncode, 1)


class ShowAndChooseTests(LibCase):
    def test_show_with_installed_line(self):
        self.seed()
        out = self.sisi("verifiers", "show", "proptest").stdout
        self.assertIn("installed here: yes", out)
        self.assertIn("Use when", out)
        self.assertIn("installed here: no", self.sisi("verifiers", "show", "lean4").stdout)
        self.assertIn("n/a", self.sisi("verifiers", "show", "snapshot").stdout)
        self.assertEqual(self.sisi("verifiers", "show", "nope").returncode, 1)

    def test_show_never_fails_on_broken_or_slow_detect(self):
        self.put("prove/weird.md", vfile("weird", detect="definitely-not-a-command-xyz"))
        self.put("prove/slow.md", vfile("slow", detect="sleep 30"))
        import time
        os.environ["SISI_DETECT_TIMEOUT"] = "0.5"
        self.addCleanup(os.environ.pop, "SISI_DETECT_TIMEOUT", None)
        t = time.time()
        r = self.sisi("verifiers", "show", "weird")
        self.assertEqual(r.returncode, 0)
        self.assertIn("installed here: no", r.stdout)
        self.assertEqual(self.sisi("verifiers", "show", "slow").returncode, 0)
        self.assertLess(time.time() - t, 5)

    def test_for_ranks_by_overlap_rung_and_installed(self):
        self.seed()
        out = self.sisi("verifiers", "for", "random inputs for a parsing function in python").stdout
        ids = [l.split()[1] for l in out.splitlines() if l[:2].strip().rstrip(".").isdigit()]
        self.assertEqual(ids[0], "hypothesis")
        self.assertIn("proptest", ids)
        self.assertNotIn("snapshot", ids)
        self.assertIn("installed:", out)
        self.assertIn("Do random inputs break this function?", out)

    def test_for_stronger_rung_wins_when_relevance_ties(self):
        self.put("prove/strong.md", vfile("strong", rung=1, answers="Does the cache evict correctly?", detect=""))
        self.put("prove/weak.md", vfile("weak", rung=4, answers="Does the cache evict correctly?", detect=""))
        out = self.sisi("verifiers", "for", "cache evict").stdout
        self.assertLess(out.index("strong"), out.index("weak"))

    def test_for_installed_boost(self):
        self.put("prove/here.md", vfile("here", rung=2, answers="Does the queue drain?", detect="true"))
        self.put("prove/gone.md", vfile("gone", rung=2, answers="Does the queue drain?", detect="false"))
        out = self.sisi("verifiers", "for", "queue drain").stdout
        self.assertLess(out.index("here"), out.index("gone"))

    def test_for_top_8_only(self):
        for i in range(12):
            self.put("prove/e%02d.md" % i, vfile("e%02d" % i, answers="Does the widget work?"))
        out = self.sisi("verifiers", "for", "widget").stdout
        self.assertEqual(len([l for l in out.splitlines() if l[:1].isdigit()]), 8)

    def test_for_lang_and_kind_filters(self):
        self.seed()
        out = self.sisi("verifiers", "for", "random inputs parsing", "--lang", "rust").stdout
        self.assertIn("proptest", out)
        self.assertNotIn("hypothesis", out)

    def test_for_no_match_and_empty(self):
        self.seed()
        self.assertIn("no verifier matches", self.sisi("verifiers", "for", "zzzqqq").stdout)
        self.assertEqual(self.sisi("verifiers", "for").returncode, 1)


class DoctorTests(LibCase):
    def test_doctor_summarises_per_section(self):
        self.seed()
        out = self.sisi("verifiers", "doctor").stdout
        self.assertIn("many-inputs: 1 of 2 installed", out)
        self.assertIn("prove: 0 of 1 installed", out)
        self.assertNotIn("snapshot", out)  # no detect command
        self.assertIn("total: 2 of 4", out)

    def test_doctor_runs_concurrently_under_cap(self):
        import time
        for i in range(8):
            self.put("prove/s%d.md" % i, vfile("s%d" % i, detect="sleep 0.7"))
        t = time.time()
        out = self.sisi("verifiers", "doctor").stdout
        self.assertLess(time.time() - t, 3.5)  # 8 x 0.7 s would be 5.6 s if serial
        self.assertIn("8 of 8", out)


class DoneTests(LibCase):
    def seed_done(self):
        self.put("bugfix.md", dfile("bugfix", "Fixing a bug", "a defect in existing behaviour, fix, regression"), self.ddir)
        self.put("new-library.md", dfile("new-library", "Writing a new library", "a reusable package with a public API"), self.ddir)
        self.put("web-ui.md", dfile("web-ui", "Changing a web UI", "pages, layout, screenshots"), self.ddir)

    def test_list_show_for(self):
        self.seed_done()
        out = self.sisi("done").stdout
        for i in ("bugfix", "new-library", "web-ui"):
            self.assertIn(i, out)
        self.assertIn("Done means", self.sisi("done", "bugfix").stdout)
        self.assertEqual(self.sisi("done", "nope").returncode, 1)
        out = self.sisi("done", "for", "fix a regression bug in the parser").stdout
        self.assertTrue(out.startswith("Best match: bugfix"))
        out = self.sisi("done", "for", "change the page layout").stdout
        self.assertTrue(out.startswith("Best match: web-ui"))
        self.assertIn("no recipe matches", self.sisi("done", "for", "zzzqqq").stdout)


class LintTests(LibCase):
    def lint(self):
        r = self.sisi("verifiers", "lint")
        return r.returncode, r.stdout

    def test_clean(self):
        self.seed()
        self.put("bugfix.md", dfile("bugfix"), self.ddir)
        rc, out = self.lint()
        self.assertEqual(rc, 0, out)
        self.assertIn("lint ok", out)

    def test_each_problem_is_reported(self):
        cases = {
            "missing key": ("prove/a.md", vfile("a").replace("answers: Is it true?\n", ""), "missing or empty 'answers'"),
            "bad rung": ("prove/a.md", vfile("a", rung=7), "rung must be"),
            "rung word": ("prove/a.md", vfile("a", rung="strong"), "rung must be"),
            "unknown section": ("zzz/a.md", vfile("a", section="zzz"), "unknown section"),
            "bad cost": ("prove/a.md", vfile("a", cost="huge"), "cost must be"),
            "id != stem": ("prove/a.md", vfile("b"), "must equal the file name"),
            "no header": ("prove/a.md", "# nothing\n", "no header block"),
            "bad kind": ("prove/a.md", vfile("a", kinds="vibes"), "unknown kind"),
            "bad ran_here": ("prove/a.md", vfile("a", ran="maybe"), "ran_here"),
            "wrong dir": ("design/a.md", vfile("a", section="prove"), "does not match its directory"),
            "heading": ("prove/a.md", vfile("a", body=BODY_V.replace("## Run\ntext\n", "")), "'Run'"),
            "heading needs to be a heading": ("prove/a.md", vfile("a", body=BODY_V.replace("## Set up", "Set up")), "'Set up'"),
        }
        for name, (rel, text, expect) in cases.items():
            with self.subTest(name):
                for d in (self.vdir, self.ddir):
                    for f in os.listdir(d):
                        import shutil
                        p = os.path.join(d, f)
                        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
                self.put(rel, text)
                rc, out = self.lint()
                self.assertEqual(rc, 1)
                self.assertIn(expect, out)

    def test_duplicate_ids_and_recipes(self):
        self.put("prove/a.md", vfile("a"))
        self.put("design/a.md", vfile("a", section="design"))
        rc, out = self.lint()
        self.assertIn("duplicate id", out)
        self.put("bad.md", dfile("bad").replace("## Checks\ntext\n", ""), self.ddir)
        self.put("other.md", dfile("else"), self.ddir)
        rc, out = self.lint()
        self.assertIn("'Checks'", out)
        self.assertIn("must equal the file name", out)

    def test_empty_detect_allowed_missing_detect_key_not(self):
        self.put("prove/a.md", vfile("a", detect=""))
        self.assertEqual(self.lint()[0], 0)
        self.put("prove/b.md", vfile("b").replace("detect: true\n", ""))
        self.assertIn("'detect'", self.lint()[1])


class LintCrossCheckTests(LibCase):
    def recipe(self, checks_text):
        body = "## Done means\nx\n\n## Checks\n%s\n## Common false finishes\nx\n" % checks_text
        self.put("r.md", dfile("r", body=body), self.ddir)

    def test_unknown_cited_id_fails_with_file_and_id(self):
        self.seed()
        self.recipe("- Fast: `proptest`, `lean4` (prove), rung 2; run `cargo test --release` or `pytest -q`.\n- `no-such-check`\n")
        r = self.sisi("verifiers", "lint")
        self.assertEqual(r.returncode, 1)
        self.assertIn("r.md", r.stdout)
        self.assertIn("'no-such-check'", r.stdout)
        self.assertNotIn("'proptest'", r.stdout)
        self.assertNotIn("cargo", r.stdout)  # commands are not citations
        self.assertNotIn("pytest", r.stdout)

    def test_valid_citations_and_other_sections_ignored(self):
        self.seed()
        body = "## Done means\nsee `not-checked-here`\n\n## Checks\n- `lean4`\n\n## Common false finishes\n`also-ignored`\n"
        self.put("r.md", dfile("r", body=body), self.ddir)
        self.assertEqual(self.sisi("verifiers", "lint").returncode, 0)

    def test_warnings_do_not_fail(self):
        self.put("prove/short.md", vfile("short", extra="verified: memory\n"))
        self.put("prove/long.md", vfile("long", body=BODY_V + "line\n" * 90))
        r = self.sisi("verifiers", "lint")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("lines (aim for 30-80)", r.stdout)
        self.assertIn("short.md: 30" if False else "verified: memory", r.stdout)
        self.assertIn("warning(s)", r.stdout)


class CoreMdTests(SisiCase):
    def test_help_lists_new_commands(self):
        out = self.sisi("help").stdout + self.sisi("help", "verifiers").stdout + self.sisi("help", "done").stdout
        for w in ("verifiers show", "verifiers for", "verifiers doctor | lint", "sisi done", "done for"):
            self.assertIn(w, out)


if __name__ == "__main__":
    unittest.main()
