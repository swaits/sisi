"""Risk profiles (R-5.3-1, R-5.3-2, R-5.3-3..R-5.3-10)."""
import json, os, random, unittest
from support import *

from sisi import risk


class FloorTests(SisiCase):
    def test_docs_only_is_trivial(self):
        """R-5.3-4: documentation/text/styling only is trivial."""
        p, reasons = risk.assess(["README.md", "docs/guide.txt", "web/site.css"])
        self.assertEqual(p, "trivial")
        self.assertTrue(reasons)

    def test_single_module_is_isolated(self):
        """R-5.3-5: one module's behaviour is isolated."""
        p, _ = risk.assess(["src/calc.py"])
        self.assertEqual(p, "isolated")

    def test_logic_kinds(self):
        """R-5.3-6: algorithms, parsing and money are logic."""
        for path in ("src/parser/lexer.py", "src/money/rounding.py", "src/algo/sort.py"):
            with self.subTest(path=path):
                p, _ = risk.assess([path])
                self.assertEqual(p, "logic")

    def test_two_packages_is_integration(self):
        """R-5.3-7, R-5.3-11: several top-level packages is integration."""
        p, reasons = risk.assess(["src/alpha/a.py", "src/beta/b.py"])
        self.assertEqual(p, "integration")
        self.assertTrue(any("package" in r for r in reasons))

    def test_migration_is_data(self):
        """R-5.3-8: schema/persistence/migration is data."""
        p, _ = risk.assess(["db/migrations/0002_add_col.sql"])
        self.assertEqual(p, "data")

    def test_auth_is_critical(self):
        """R-5.3-9: authorization/secrets/concurrency primitives are critical."""
        for path in ("src/auth/login.py", "src/crypto/keys.py", "src/sync/mutex.py"):
            with self.subTest(path=path):
                p, _ = risk.assess([path])
                self.assertEqual(p, "critical")

    def test_diff_keyword_raises_floor(self):
        """R-5.3-1: content keywords count, not only paths."""
        p, _ = risk.assess(["src/util.py"], diff_text="+ encrypt the password at rest")
        self.assertEqual(p, "critical")

    def test_adding_path_never_lowers_floor(self):
        """R-5.3-1: property — the floor is monotone in the change set."""
        rng = random.Random(7)
        pool = ["README.md", "src/a/x.py", "src/b/y.py", "db/migrations/m.sql",
                "src/auth/login.py", "src/parser/p.py", "VERSION", "web/site.css"]
        order = {name: i for i, name in enumerate(risk.PROFILES)}
        for _ in range(80):
            base = rng.sample(pool, rng.randint(0, 4))
            extra = rng.choice(pool)
            before, _ = risk.assess(base)
            after, _ = risk.assess(base + [extra])
            self.assertGreaterEqual(order[after], order[before], (base, extra))

    def test_project_override_and_requirements_table(self):
        """R-5.3-3: a project may override; each profile carries its requirements."""
        p, _ = risk.assess(["src/special/thing.py"],
                           extra_patterns=[{"glob": "**/special/**", "profile": "data",
                                            "reason": "project override: special holds stored data"}])
        self.assertEqual(p, "data")
        req = risk.requirements_for("trivial")
        self.assertFalse(req["contract"])
        self.assertTrue(risk.requirements_for("critical")["independent_evidence"])
        self.assertTrue(risk.requirements_for("release")["contract"])


class RiskCliTests(SisiCase):
    def _repo_with(self, files):
        self.git_init()
        for rel, text in files.items():
            p = os.path.join(self.proj, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(text)

    def test_risk_json_readme_change(self):
        """R-5.3-2: a README edit does not get the full process."""
        self._repo_with({"README.md": "# hi\nchanged\n"})
        r = self.sisi("risk", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["floor"], "trivial")
        self.assertIn("requirements", d)

    def test_risk_json_migration_change(self):
        """R-5.3-8: a migrations change floors at data."""
        self._repo_with({"db/migrations/0001.sql": "ALTER TABLE t ADD c INT;\n"})
        d = json.loads(self.sisi("risk", "--json").stdout)
        self.assertEqual(d["floor"], "data")

    def test_risk_declared_profile_from_contract(self):
        """R-5.3-3: the declared profile in .sisi/contract.json is reported."""
        self._repo_with({"src/a.py": "x = 1\n"})
        os.makedirs(os.path.join(self.proj, ".sisi"), exist_ok=True)
        with open(os.path.join(self.proj, ".sisi", "contract.json"), "w") as f:
            json.dump({"id": "t", "goal": "g", "checks": [], "risk": {"profile": "logic"}}, f)
        d = json.loads(self.sisi("risk", "--json").stdout)
        self.assertEqual(d["declared"], "logic")


if __name__ == "__main__":
    unittest.main()
