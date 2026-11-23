"""The critique gives a verdict for every module and every command that existed when sisi was
assessed against SPEC.md (R-19-2, R-19-3: inventory the current system and map each component
to the specification). The inventory is frozen in docs/reconciliation/inventory-base.json."""
import json, os, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "docs", "reconciliation", "inventory-base.json")
CRITIQUE = os.path.join(ROOT, "docs", "reconciliation", "critique.md")
PLAN = os.path.join(ROOT, "docs", "plan.md")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class CritiqueIsComplete(unittest.TestCase):
    def setUp(self):
        self.base = json.loads(read(BASE))
        self.critique = read(CRITIQUE)

    def test_every_module_has_a_verdict(self):
        missing = [m for m in self.base["modules"] if "`%s`" % m not in self.critique]
        self.assertEqual(missing, [], "modules with no verdict in the critique")

    def test_every_command_has_a_verdict(self):
        missing = [c for c in self.base["commands"] if "`%s`" % c not in self.critique]
        self.assertEqual(missing, [], "commands with no verdict in the critique")

    def test_inventory_is_not_empty(self):
        self.assertGreaterEqual(len(self.base["modules"]), 40)
        self.assertGreaterEqual(len(self.base["commands"]), 40)


class PlanCoversTheSpecStages(unittest.TestCase):
    def test_plan_names_every_reconciliation_step(self):
        """R-19-1: the project is reconciled in stages; the plan has each of them."""
        plan = read(PLAN)
        for word in ("baseline", "work-unit record", "Learning loop", "Evaluation harness",
                     "Cutover", "Exceptions"):
            self.assertIn(word, plan)


if __name__ == "__main__":
    unittest.main()
