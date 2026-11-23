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
