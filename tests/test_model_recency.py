"""Recency breaks ties: where the arithmetic falls back to a stable order, the more recently released model wins
first (a newer version of the same model, never across makers or classes), and the
rule is in the text agents and people read. Requirement ids: R-7.2-1, R-7.2-2."""
import os, unittest
from support import *
from sisi import routing
from test_model_supersession import cand, pick


class RecencyTieBreakTests(unittest.TestCase):
    def test_a_newer_release_never_beats_a_different_model_just_for_being_newer(self):
        """The owner: newer means a newer version of the SAME model, not the newest release across models."""
        a = cand("prov/aaa-1.0", cost=1.0, rel="2026-01-10", maker="aaa")
        b = cand("prov/bbb-2.0", cost=1.0, rel="2026-08-01", maker="bbb")
        who, r = pick([a, b])
        self.assertEqual(who, "prov/aaa-1.0")   # the old tie-break (worker id), whatever the release dates
        self.assertEqual(pick([b, a])[0], "prov/aaa-1.0")
        flash = cand("prov/abc-flash", cls="flash", cost=1.0, rel="2026-01-10")
        std = cand("prov/abc-std", cls="standard", cost=1.0, rel="2026-08-01")
        self.assertEqual(pick([flash, std])[0], "prov/abc-flash")
        self.assertEqual(routing.recency_order([a, b, flash, std]), {w: 0 for w in ("prov/aaa-1.0", "prov/bbb-2.0", "prov/abc-flash", "prov/abc-std")})

    def test_within_one_model_the_newer_version_goes_first(self):
        old, new = cand("prov/abc-old", rel="2026-01-10"), cand("prov/abc-new", rel="2026-08-01")
        self.assertEqual(routing.recency_order([old, new]), {"prov/abc-new": 0, "prov/abc-old": 1})

    def test_price_and_load_still_come_before_the_tie_break(self):
        cheap = cand("prov/aaa-1.0", cost=0.5, maker="aaa")
        dear = cand("prov/bbb-2.0", cost=1.0, maker="bbb", rel="2026-08-01")
        self.assertEqual(pick([cheap, dear])[0], "prov/aaa-1.0")


class TextTests(unittest.TestCase):
    def read(self, *parts):
        with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
            return f.read()

    def test_the_rule_is_in_the_always_loaded_rulebook_the_playbook_and_the_docs(self):
        core = self.read("canon", "core.md")
        rule6 = core[core.index("## 6. Orchestrate"):core.index("## 7.")]
        self.assertIn("newest version of a given model", rule6)
        self.assertIn("never an older version", rule6)
        self.assertIn("different model or class", rule6)
        for path in (("canon", "orchestration.md"), ("docs", "workers.md")):
            text = self.read(*path).lower()
            self.assertIn("newest version of a given model", text.replace("\n", " ").replace("  ", " "), path)
            self.assertIn("different model or class", text.replace("\n", " ").replace("  ", " "), path)
            self.assertIn("cheaper", text, path)   # the reason: newer models are better and cheaper

    def test_the_rulebook_is_inside_its_budget(self):
        from sisi import overlay
        lines, chars = overlay.size(self.read("canon", "core.md"))
        self.assertLessEqual(lines, overlay.MAX_LINES)
        self.assertLessEqual(chars, overlay.MAX_CHARS)


class SessionLineTests(SisiCase):
    def test_session_start_names_unclassified_workers_in_the_one_facts_line(self):
        from sisi import workers
        line = workers.facts_line(unclassified=2)
        self.assertEqual(len(line.splitlines()), 1)
        self.assertIn("2 routable workers have no recorded maker, class and release date", line)
        self.assertIn("sisi workers classify", line)
        self.assertNotIn("classify", workers.facts_line(unclassified=0))


if __name__ == "__main__":
    unittest.main()
