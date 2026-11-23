"""Recency breaks ties: where the arithmetic falls back to a stable order, the more recently released model wins
first (a recorded release date, else the version within one line, else the old tie-break by worker id), and the
rule is in the text agents and people read. Requirement ids: R-7.2-1, R-7.2-2."""
import os, unittest
from support import *
from sisi import routing
from test_model_supersession import cand, pick


class RecencyTieBreakTests(unittest.TestCase):
    def test_a_recorded_release_date_decides_a_tie_between_unrelated_models(self):
        a = cand("prov/aaa-1.0", cost=1.0, fact={"released": "2026-01-10"}, maker="aaa")
        b = cand("prov/bbb-2.0", cost=1.0, fact={"released": "2026-08-01"}, maker="bbb")
        who, r = pick([a, b])
        self.assertEqual(who, "prov/bbb-2.0")
        self.assertIn(("prov/aaa-1.0", "equal on price and load; the choice is the more recently released"), r["passed_over"])

    def test_the_version_inside_one_line_decides_when_nothing_supersedes(self):
        old, new = cand("prov/abc-5.9", cost=1.0), cand("prov/abc-5.10", cost=1.0)
        who, r = pick([old, new], opts={"supersede_guessed": False})
        self.assertEqual(who, "prov/abc-5.10")
        self.assertEqual(pick([new, old], opts={"supersede_guessed": False})[0], "prov/abc-5.10")

    def test_unknown_recency_keeps_the_old_tie_break(self):
        a, b = cand("prov/aaa-1.0", cost=1.0, maker="aaa"), cand("prov/bbb-9.0", cost=1.0, maker="bbb")
        who, r = pick([a, b])
        self.assertEqual(who, "prov/aaa-1.0")
        self.assertIn(("prov/bbb-9.0", "equal on price and load; the choice came first in worker-id order"), r["passed_over"])

    def test_price_and_load_still_come_before_recency(self):
        cheap_old = cand("prov/aaa-1.0", cost=0.5, fact={"released": "2026-01-10"}, maker="aaa")
        dear_new = cand("prov/bbb-2.0", cost=1.0, fact={"released": "2026-08-01"}, maker="bbb")
        self.assertEqual(pick([cheap_old, dear_new])[0], "prov/aaa-1.0")


class TextTests(unittest.TestCase):
    def read(self, *parts):
        with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
            return f.read()

    def test_the_rule_is_in_the_always_loaded_rulebook_the_playbook_and_the_docs(self):
        core = self.read("canon", "core.md")
        rule6 = core[core.index("## 6. Orchestrate"):core.index("## 7.")]
        self.assertIn("most recently released", rule6)
        self.assertIn("never an older version", rule6)
        self.assertIn("class", rule6)
        for path in (("canon", "orchestration.md"), ("docs", "workers.md")):
            text = self.read(*path).lower()
            self.assertIn("most recently released", text, path)
            self.assertIn("different classes", text, path)
            self.assertIn("cheaper", text, path)   # the reason: newer models are better and cheaper

    def test_the_rulebook_is_inside_its_budget(self):
        from sisi import overlay
        lines, chars = overlay.size(self.read("canon", "core.md"))
        self.assertLessEqual(lines, overlay.MAX_LINES)
        self.assertLessEqual(chars, overlay.MAX_CHARS)


class SessionLineTests(SisiCase):
    def test_session_start_asks_for_the_release_date_of_each_worker_that_lacks_one(self):
        from sisi import workers
        line = workers.facts_line()
        self.assertIn("release date", line)
        self.assertIn("--released", line)


if __name__ == "__main__":
    unittest.main()
