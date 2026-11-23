"""Reading a model id: maker, line, class, version, and which of two is the more recently released.
Fixtures are invented ids shaped like real ones. Requirement ids: R-7.2-1, R-7.2-2, R-7.2-3."""
import json, os, random, unittest
from support import *
from sisi import modelid

WORDS = json.load(open(os.path.join(REPO, "canon", "model-words.json")))


def p(worker, **kw):
    return modelid.parse(worker, WORDS, **kw)


def r(worker, **kw):
    return modelid.resolve(worker, WORDS, **kw)


class ParseTests(unittest.TestCase):
    def test_version_line_and_class_from_the_name(self):
        """R-7.2-1: the class is read from the id; no tier word means the line's standard model."""
        a = p("prov/abc-5.3")
        self.assertEqual((a["maker"], a["class"], a["version"], a["confident"]), ("abc", "standard", (5, 3), True))
        self.assertEqual(p("prov/abc-5.3-flash")["class"], "flash")

    def test_a_tier_word_before_or_after_the_version_parses_the_same(self):
        after, before = p("prov/abc-5.4-flash"), p("prov/abc-flash-5.4")
        for k in ("maker", "line", "class", "label", "version", "confident"):
            self.assertEqual(after[k], before[k], k)

    def test_versions_compare_numerically(self):
        """5.10 is newer than 5.9, not older (the string order would say so)."""
        self.assertGreater(modelid.compare(r("prov/abc-5.10"), r("prov/abc-5.9")), 0)
        self.assertLess(modelid.compare(r("prov/abc-5.9"), r("prov/abc-5.10")), 0)
        self.assertEqual(modelid.compare(r("prov/abc-5"), r("prov/abc-5.0")), 0)

    def test_a_dated_suffix_compares_as_a_date_and_does_not_disturb_the_version(self):
        dated = p("prov/abc-5-4-20261101")
        self.assertEqual((dated["version"], dated["date"], dated["class"]), ((5, 4), "2026-11-01", "standard"))
        self.assertEqual(p("prov/abc-5.4-2026-11-01")["date"], "2026-11-01")
        self.assertGreater(modelid.compare(r("prov/abc-5-4-20261101"), r("prov/abc-5.3")), 0)
        self.assertEqual(modelid.compare(r("prov/abc-5-4-20261101"), r("prov/abc-5.4")), 0)
        self.assertGreater(modelid.compare(r("prov/abc-5.4-20261101"), r("prov/abc-5.4-20260901")), 0)
        self.assertGreater(modelid.compare(r("prov/abc-20261101"), r("prov/abc-20250301")), 0)
        self.assertEqual(modelid.compare(r("prov/abc-20261101"), r("prov/abc-5.3")), 0)  # not comparable
        self.assertIsNone(p("prov/abc-5.4-20261345")["date"])  # not a date

    def test_two_tier_words_make_one_class_and_letter_prefixed_versions_read(self):
        self.assertEqual(p("prov/abc-flash-lite-5.4")["class"], "flash-lite")
        self.assertEqual(p("prov/xyz-v4.1-pro")["version"], (4, 1))
        self.assertEqual(p("prov/xyz-k2.7-code")["class"], "code")
        self.assertEqual(p("prov/xyz3.8-flash")["version"], (3, 8))

    def test_ignored_words_are_neither_line_nor_class(self):
        self.assertEqual(p("prov/abc-5.4-preview-free")["class"], "standard")
        self.assertEqual(p("prov/abc-5.4-flash-latest")["class"], "flash")

    def test_a_named_line_is_the_class_label(self):
        """Item 7: for a maker whose lines are the classes the line name is the class label."""
        a, b = p("prov/abc-wonder-1.0"), p("prov/abc-wonder-full-1.0")
        self.assertEqual((a["line"], a["label"]), ("wonder", "wonder"))
        self.assertEqual((b["line"], b["class"], b["label"]), ("wonder", "full", "wonder-full"))
        self.assertEqual(p("prov/abc-ember-1.0")["label"], "ember")

    def test_what_cannot_be_read_with_confidence_says_unknown(self):
        """R-7.2-3: no version, or a word after the version that the data does not know: class unknown."""
        for ident in ("prov/xyz-mini", "prov/abc", "prov/abc-6.2-sol", "prov/abc-3-5-sonnet", "prov/5.4"):
            got = p(ident)
            self.assertFalse(got["confident"], ident)
            self.assertEqual(got["class"], "unknown", ident)
            self.assertIsNone(r(ident)["key"], ident)
            self.assertEqual(r(ident)["source"], "unknown", ident)

    def test_tier_words_are_data_not_code(self):
        """Adding a tier word to the data changes the reading; the code names none."""
        self.assertFalse(p("prov/abc-5.4-sol")["confident"])
        got = modelid.parse("prov/abc-5.4-sol", {"tiers": ["sol"], "ignore": []})
        self.assertEqual((got["class"], got["confident"]), ("sol", True))
        text = open(os.path.join(REPO, "sisi", "modelid.py")).read()
        for word in WORDS["tiers"] + WORDS["ignore"]:
            self.assertNotRegex(text.replace("standard", ""), r'"%s"' % word)

    def test_a_recorded_fact_beats_the_reading(self):
        got = r("prov/abc-6.2-sol", fact={"class": "sol", "maker": "abc"})
        self.assertEqual((got["source"], got["class"], got["key"]), ("fact", "sol", ("abc", "", "sol")))
        flipped = r("prov/abc-5.3-flash", fact={"class": "standard"})
        self.assertEqual(flipped["class"], "standard")
        self.assertEqual(r("prov/abc-5.4", fact={"family": "wonder", "class": "full"})["label"], "wonder-full")
        self.assertEqual(r("prov/abc-5.4", fact={"family": "wonder", "class": "wonder-full"})["label"], "wonder-full")
        self.assertEqual(r("prov/abc-5.4")["source"], "guess")

    def test_a_recorded_release_date_beats_version_numbers(self):
        old_but_later = r("prov/abc-5.3", fact={"released": "2026-09-01"})
        new_but_earlier = r("prov/abc-5.4", fact={"released": "2026-03-01"})
        self.assertGreater(modelid.compare(old_but_later, new_but_earlier), 0)
        self.assertGreater(modelid.compare(r("prov/abc-5.4"), r("prov/abc-5.3")), 0)

    def test_a_bare_host_alias_is_the_newest_of_its_class_once_the_class_is_recorded(self):
        alias = r("abc", host_native=True, fact={"class": "standard", "maker": "abc"})
        self.assertTrue(alias["alias"])
        self.assertGreater(modelid.compare(alias, r("prov/abc-9.9")), 0)
        self.assertEqual(alias["key"], r("prov/abc-5.3")["key"])
        unrecorded = r("abc", host_native=True)
        self.assertFalse(unrecorded["alias"])
        self.assertIsNone(unrecorded["key"])

    def test_the_parser_never_raises_and_compare_is_antisymmetric(self):
        rng = random.Random(7)
        pool = ["abc", "xyz", "5", "4", "10", "3.2", "flash", "mini", "pro", "preview", "20261101", "v2", "k3", "x", "", "-", "70b", "sol", "4o", "2026", "11", "01"]
        for _ in range(500 * ITERS):
            ident = "prov/" + "-".join(rng.choice(pool) for _ in range(rng.randint(0, 6)))
            a, b = r(ident), r("prov/" + "-".join(rng.choice(pool) for _ in range(rng.randint(0, 6))))
            self.assertEqual(modelid.compare(a, b), -modelid.compare(b, a), ident)
            if a["source"] == "unknown":
                self.assertIsNone(a["key"])
            modelid.recency_key(a)


if __name__ == "__main__":
    unittest.main()
