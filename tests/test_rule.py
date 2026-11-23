"""`sisi rule`: every rule points at its own detail, and the enforcement column comes from code facts."""
import json, os, unittest
from support import *
from sisi import overlay, retro


class RuleTableTests(SisiCase):
    def test_table_lists_every_rule_with_enforcement(self):
        r = self.sisi("rule")
        self.assertEqual(r.returncode, 0, r.stderr)
        _, rules = overlay.base_rules()
        for rule in rules:
            self.assertIn(rule["id"], r.stdout)
            self.assertIn(rule["title"], r.stdout)
        self.assertIn("measured only", r.stdout)  # a rule is honestly reported as only measured, not enforced

    def test_every_base_rule_has_an_enforcement_entry(self):
        from sisi import rulecmd
        _, rules = overlay.base_rules()
        for rule in rules:
            self.assertIn(rule["id"], rulecmd.ENFORCEMENT, rule["id"])
            self.assertTrue(rulecmd.enforcement_for(rule["id"]).strip())

    def test_enforcement_wording_names_real_mechanisms(self):
        from sisi import rulecmd
        self.assertIn("end-of-turn", rulecmd.enforcement_for("define-done"))
        self.assertIn("retro", rulecmd.enforcement_for("close-with-retro").lower())
        ask = rulecmd.enforcement_for("own-the-outcome").lower()
        self.assertTrue("dialog" in ask or "asking" in ask, ask)


class RuleDetailTests(SisiCase):
    def test_rule_by_number_and_by_id(self):
        by_num = self.sisi("rule", "1")
        by_id = self.sisi("rule", "own-the-outcome")
        self.assertEqual(by_num.returncode, 0, by_num.stderr)
        self.assertEqual(by_id.returncode, 0, by_id.stderr)
        for out in (by_num.stdout, by_id.stdout):
            self.assertIn("Own the outcome", out)
            self.assertIn("Why:", out)
            self.assertIn("AskUserQuestion", out)
            self.assertIn("base", out.lower())

    def test_unknown_rule_fails(self):
        self.assertEqual(self.sisi("rule", "no-such-rule").returncode, 1)
        self.assertEqual(self.sisi("rule", "99").returncode, 1)

    def test_overlay_replacement_is_named_as_overlay(self):
        d = os.path.join(self.data, "overlay", "rules")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "deliver-fast.md"), "w") as f:
            f.write("## Deliver quickly\n\nReplacement body written by the owner.\n\nWhy: a test.\n")
        r = self.sisi("rule", "deliver-fast")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Replacement body", r.stdout)
        self.assertIn("overlay", r.stdout.lower())


class RetiredRuleIdTests(SisiCase):
    """R-14.3-1, R-11.5-11, R-12-1: personal rule changes keyed by a retired rule id were written
    against the old wording. They are never applied to the new rule; they stay in the store."""

    def put(self, rel, text):
        p = os.path.join(self.data, "overlay", rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)

    def fixture(self):
        self.sisi("tick")  # creates the personal store
        self.put("rules/deliver-quickly.md", "## Deliver quickly\n\nOld replacement text.\n\nWhy: mine.\n")
        self.put("rules/disabled.txt", "strongest-check\n")
        self.put("rules/my-own-rule.md", "## Mine\n\nAn addition that replaces nothing.\n\nWhy: mine.\n")

    def test_map_covers_every_old_rule_and_points_at_a_real_rule(self):
        ids = {r["id"] for r in overlay.base_rules()[1]}
        ret = overlay.retired_ids()
        self.assertEqual(len(ret), 9)
        for old, new in ret.items():
            self.assertNotIn(old, ids)
            self.assertTrue(new is None or new in ids, (old, new))

    def test_old_id_replacement_and_disabling_are_stale_additions_are_kept(self):
        self.fixture()
        _, rules = overlay.effective()
        by = {r["id"]: r for r in rules}
        self.assertNotIn("Old replacement text.", overlay.render())
        self.assertEqual(by["deliver-fast"]["origin"], "base")  # the new rule is untouched
        self.assertEqual(by["verify-enough"]["origin"], "base")  # not disabled through the map
        self.assertEqual(by["my-own-rule"]["origin"], "added")
        self.assertEqual([(i, h) for i, h, _ in overlay.stale_entries()],
                         [("deliver-quickly", "replacement"), ("strongest-check", "disabling")])
        out = self.sisi("overlay", "list").stdout
        self.assertIn("stale", out)

    def test_stale_entries_are_reported_once_and_nothing_is_deleted(self):
        self.fixture()
        first = overlay.scan_retests()
        self.assertEqual(sorted(r["id"] for r in first), ["deliver-quickly", "strongest-check"])
        self.assertTrue(all(r["action"].startswith("stale") for r in first))
        self.assertEqual(overlay.scan_retests(), [])  # reported once
        self.assertTrue(os.path.exists(os.path.join(self.data, "overlay", "rules", "deliver-quickly.md")))
        self.assertIn("strongest-check", overlay.disabled("rule"))
        self.assertIn("deliver-quickly", overlay.overlay_rules(include_stale=True))

    def test_a_new_rule_cannot_be_added_under_a_retired_id(self):
        r = self.sisi("overlay", "add-rule", "--id", "know-done", "-", stdin="## X\n\nBody.\n\nWhy: y.\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("retired", r.stderr)


class MoreLineTests(SisiCase):
    def test_generated_rulebook_points_each_rule_at_its_detail(self):
        text = overlay.render()
        _, rules = overlay.effective()
        for n, rule in enumerate(rules, 1):
            self.assertIn("More: `sisi rule %d`" % n, text, rule["id"])
        lines, chars = overlay.size(text)
        self.assertLessEqual(lines, overlay.MAX_LINES)
        self.assertLessEqual(chars, overlay.MAX_CHARS)

    def test_help_names_rule_and_prompt(self):
        out = self.sisi("help").stdout
        self.assertIn("sisi rule", out)
        self.assertIn("sisi prompt", out)


if __name__ == "__main__":
    unittest.main()
