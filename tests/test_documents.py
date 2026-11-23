"""Whole-document edits in a learning round: folded lessons become part of the document's own
text, every lesson stays traceable to the exact fragment that carries it, structure is checked
mechanically, and a stale personal copy is listed for re-merge instead of silently kept."""
import json, os, unittest
from support import *
from sisi import cycle, documents, overlay, paths, retro
from test_verifiers import LibCase, vfile, dfile

WHEN = "parser, codec, parse, decode, round trip, fuzzing, tabular data"

RECIPE_BODY = """## Done means
- The parser accepts every valid input in the corpus.
- Invalid input is refused with a clear error.

## Checks
- Round trip: `proptest` (many-inputs), rung 2.

## Common false finishes
- Only the examples in the report were tried.
"""

REWRITE = """---
id: parser-or-codec
title: Parser or codec work
applies_to: parsing work
---

## Done means
- The parser accepts every valid input in the corpus.
- Invalid input is refused with a clear error.
- Seed the corpus from the golden files before fuzzing.
- Try truncated input at every length.

## Checks
- Round trip: `proptest` (many-inputs), rung 2.

## Common false finishes
- Only the examples in the report were tried.
"""


class DocCase(LibCase):
    def setUp(self):
        super().setUp()
        self.put("prove/fuzz.md", vfile("fuzz"))
        self.put("many-inputs/proptest.md", vfile("proptest", "many-inputs", 2))
        self.put("parser-or-codec.md",
                 dfile("parser-or-codec", title="Parser or codec work", applies="parsing work",
                       body="\n" + RECIPE_BODY), self.ddir)
        self.notes = os.path.join(self.data, "notes")

    def mk(self, change, **kw):
        f = dict(aim="verified", change_kind="recipe", target="parser-or-codec",
                 moment="the parser accepted a truncated file in the nightly job",
                 cause="no truncated-input case existed", change=change, when=WHEN,
                 scope="everywhere", short="Seed the corpus from golden files.", topic="parsing")
        f.update(kw)
        con = retro.connect()
        try:
            lid = retro.new_lesson(con, f, self.proj, None)
            con.commit()
            return lid
        finally:
            con.close()

    def cycle_file(self, **parts):
        doc = {"version": 1, "base": cycle.base_version(), "summary": "document round"}
        doc.update(parts)
        p = os.path.join(self.tmp, "cycle.json")
        with open(p, "w") as fh:
            json.dump(doc, fh)
        return p

    def tree_bytes(self):
        out = {}
        for root in (paths.overlay_dir(), paths.notes_dir()):
            for dp, dns, fns in os.walk(root):
                for n in fns:
                    p = os.path.join(dp, n)
                    with open(p, "rb") as fh:
                        out[p] = fh.read()
        return out


class BriefAndCheckTests(DocCase):
    def test_brief_lists_recipe_with_field_notes_in_full(self):
        a = self.mk("Seed the corpus from the golden files before fuzzing parsers")
        b = self.mk("Try truncated input at every length when testing a parser",
                    short="Try truncated input at every length.")
        brief = cycle.brief_text()
        self.assertIn("recipe:parser-or-codec", brief)
        self.assertIn("whole-document", brief.lower())
        self.assertIn("Seed the corpus from the golden files", brief)  # the folded lesson, universal part
        self.assertIn("one instruction per bullet", brief.lower())     # the editorial standard
        self.assertIn(RECIPE_BODY.splitlines()[1], brief)             # the document's current text

    def test_check_refuses_a_file_that_skips_a_listed_document(self):
        self.mk("Seed the corpus from the golden files before fuzzing parsers")
        r = self.sisi("cycle", "check", self.cycle_file())
        self.assertEqual(r.returncode, 1)
        self.assertIn("recipe:parser-or-codec", r.stdout)
        self.assertIn("documents", r.stdout)

    def test_reviewed_entry_satisfies_the_round(self):
        self.mk("Seed the corpus from the golden files before fuzzing parsers")
        p = self.cycle_file(documents=[{"doc": "recipe:parser-or-codec", "action": "reviewed",
                                        "reason": "two short sections, one instruction per bullet, nothing duplicated"}])
        r = self.sisi("cycle", "check", p)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.sisi("cycle", "apply", p).returncode, 0)
        # still shown as a field note until a rewrite integrates it
        self.assertIn("Seed the corpus", retro.notes_for("parser-or-codec"))


class RewriteTests(DocCase):
    def _two_lessons(self):
        a = self.mk("Seed the corpus from the golden files before fuzzing parsers")
        b = self.mk("Try truncated input at every length when testing a parser",
                    short="Try truncated input at every length.")
        return a, b

    def test_rewrite_integrates_lessons_and_traces_them(self):
        a, b = self._two_lessons()
        p = self.cycle_file(documents=[{
            "doc": "recipe:parser-or-codec", "action": "rewrite", "text": REWRITE,
            "trace": [{"lesson": a, "fragment": "Seed the corpus from the golden files before fuzzing."},
                      {"lesson": b, "fragment": "Try truncated input at every length."}]}])
        r = self.sisi("cycle", "apply", p)
        self.assertEqual(r.returncode, 0, r.stdout)
        out = self.sisi("done", "parser-or-codec").stdout
        self.assertIn("Seed the corpus from the golden files before fuzzing.", out)
        self.assertNotIn("Field notes from earlier agents", out)  # integrated, not appended
        self.assertEqual(retro.notes_for("parser-or-codec"), "")
        show = self.sisi("lessons", "show", str(a)).stdout
        self.assertIn("recipe:parser-or-codec", show)
        self.assertIn("Seed the corpus from the golden files before fuzzing.", show)
        traced = self.sisi("done", "parser-or-codec", "--trace").stdout
        self.assertIn("#%d" % a, traced)
        self.assertIn("Seed the corpus", traced)

    def test_rewrite_missing_one_fragment_is_refused(self):
        a, b = self._two_lessons()
        p = self.cycle_file(documents=[{
            "doc": "recipe:parser-or-codec", "action": "rewrite", "text": REWRITE,
            "trace": [{"lesson": a, "fragment": "Seed the corpus from the golden files before fuzzing."}]}])
        r = self.sisi("cycle", "check", p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("lesson #%d" % b, r.stdout)

    def test_fragment_must_occur_in_the_new_text(self):
        a, b = self._two_lessons()
        p = self.cycle_file(documents=[{
            "doc": "recipe:parser-or-codec", "action": "rewrite", "text": REWRITE,
            "trace": [{"lesson": a, "fragment": "Seed the corpus from the golden files before fuzzing."},
                      {"lesson": b, "fragment": "This sentence is nowhere in the document."}]}])
        r = self.sisi("cycle", "check", p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("fragment", r.stdout)

    def test_dated_journal_bullet_is_refused(self):
        a, b = self._two_lessons()
        bad = REWRITE + "- 2024-01-02: an old note (aim: verified; seen 1 times; lesson %d)\n" % a
        p = self.cycle_file(documents=[{
            "doc": "recipe:parser-or-codec", "action": "rewrite", "text": bad,
            "trace": [{"lesson": a, "fragment": "Seed the corpus from the golden files before fuzzing."},
                      {"lesson": b, "fragment": "Try truncated input at every length."}]}])
        r = self.sisi("cycle", "check", p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("dated", r.stdout.lower())

    def test_lint_failing_recipe_is_refused(self):
        a, b = self._two_lessons()
        bad = REWRITE.replace("## Checks", "## Things")
        p = self.cycle_file(documents=[{
            "doc": "recipe:parser-or-codec", "action": "rewrite", "text": bad,
            "trace": [{"lesson": a, "fragment": "Seed the corpus from the golden files before fuzzing."},
                      {"lesson": b, "fragment": "Try truncated input at every length."}]}])
        r = self.sisi("cycle", "check", p)
        self.assertEqual(r.returncode, 1)

    def test_revert_restores_documents_and_notes_byte_for_byte(self):
        a, b = self._two_lessons()
        before = self.tree_bytes()
        p = self.cycle_file(documents=[{
            "doc": "recipe:parser-or-codec", "action": "rewrite", "text": REWRITE,
            "trace": [{"lesson": a, "fragment": "Seed the corpus from the golden files before fuzzing."},
                      {"lesson": b, "fragment": "Try truncated input at every length."}]}])
        self.assertEqual(self.sisi("cycle", "apply", p).returncode, 0)
        self.assertNotEqual(self.tree_bytes(), before)
        self.assertEqual(self.sisi("cycle", "revert").returncode, 0)
        self.assertEqual(self.tree_bytes(), before)

    def test_product_change_lists_the_document_for_remerge(self):
        a, b = self._two_lessons()
        p = self.cycle_file(documents=[{
            "doc": "recipe:parser-or-codec", "action": "rewrite", "text": REWRITE,
            "trace": [{"lesson": a, "fragment": "Seed the corpus from the golden files before fuzzing."},
                      {"lesson": b, "fragment": "Try truncated input at every length."}]}])
        self.assertEqual(self.sisi("cycle", "apply", p).returncode, 0)
        self.assertNotIn("needs a re-merge", cycle.brief_text())
        prod = os.path.join(self.ddir, "parser-or-codec.md")
        with open(prod) as fh:
            text = fh.read()
        with open(prod, "w") as fh:
            fh.write(text.replace("Invalid input is refused", "Bad input is refused"))
        brief = cycle.brief_text()
        self.assertIn("Document recipe:parser-or-codec", brief)
        self.assertIn("needs a re-merge", brief)


class RulebookTests(DocCase):
    def test_rule_order_applies_and_numbers_follow_it(self):
        _pre, rules = overlay.effective()
        ids = [r["id"] for r in rules]
        new_order = [ids[1], ids[0]] + ids[2:]
        p = self.cycle_file(rule_order=new_order)
        r = self.sisi("cycle", "apply", p)
        self.assertEqual(r.returncode, 0, r.stdout)
        _pre2, rules2 = overlay.effective()
        self.assertEqual([x["id"] for x in rules2], new_order)
        out = self.sisi("rule", "1").stdout
        self.assertIn("{#%s}" % new_order[0], out)
        self.assertEqual(self.sisi("cycle", "revert").returncode, 0)
        _pre3, rules3 = overlay.effective()
        self.assertEqual([x["id"] for x in rules3], ids)

    def _rulebook_text(self, drop=None, extra=None):
        pre, rules = overlay.effective()
        parts = [pre] if pre.strip() else []
        for r in rules:
            if r["id"] == drop:
                continue
            body = r["body"] + (("\n\n" + extra) if extra and r["id"] == "know-done" else "")
            parts.append("## %s {#%s}\n\n%s" % (r["title"], r["id"], body))
        return "\n\n".join(parts) + "\n"

    def test_rulebook_rewrite_traces_a_rule_lesson(self):
        lid = self.mk("Name the check that decides done before starting the work",
                      change_kind="rule", target=None, short="Name the deciding check first.")
        p = self.cycle_file(notes=[{"lesson": lid, "action": "fold-into-rule", "into": "know-done"}])
        self.assertEqual(self.sisi("cycle", "apply", p).returncode, 0)
        frag = "Name the check that decides done before starting."
        bad = self.cycle_file(documents=[{"doc": "rulebook", "action": "rewrite",
                                          "text": self._rulebook_text(drop="deliver-quickly", extra=frag),
                                          "shortens": "know-done: tightened while integrating",
                                          "trace": [{"lesson": lid, "fragment": frag}]}])
        r = self.sisi("cycle", "check", bad)
        self.assertEqual(r.returncode, 1)
        self.assertIn("deliver-quickly", r.stdout)
        good = self.cycle_file(documents=[{"doc": "rulebook", "action": "rewrite",
                                           "text": self._rulebook_text(extra=frag),
                                           "shortens": "know-done: tightened while integrating",
                                           "trace": [{"lesson": lid, "fragment": frag}]}])
        r = self.sisi("cycle", "apply", good)
        self.assertEqual(r.returncode, 0, r.stdout)
        out = self.sisi("rule", "know-done").stdout
        self.assertIn(frag, out)
        self.assertIn("carried in rulebook", out)
        self.assertIn("lives : in rulebook", self.sisi("lessons", "show", str(lid)).stdout)
        self.assertEqual(self.sisi("cycle", "revert").returncode, 0)
        self.assertNotIn(frag, self.sisi("rule", "know-done").stdout)

    def test_rule_order_must_name_every_rule_once(self):
        _pre, rules = overlay.effective()
        p = self.cycle_file(rule_order=[rules[0]["id"]])
        r = self.sisi("cycle", "check", p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("rule_order", r.stdout)


class StructureTests(unittest.TestCase):
    def test_existing_library_passes_the_structure_checks(self):
        bad = []
        for kind, root in (("recipe", os.path.join(REPO, "done")),
                           ("verifier", os.path.join(REPO, "verifiers"))):
            for dp, dns, fns in os.walk(root):
                for n in sorted(fns):
                    if not n.endswith(".md"):
                        continue
                    p = os.path.join(dp, n)
                    with open(p, encoding="utf-8") as fh:
                        text = fh.read()
                    for prob in documents.structure_problems(kind, text, n[:-3]):
                        bad.append("%s: %s" % (p, prob))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
