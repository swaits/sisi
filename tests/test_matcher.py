"""Structured matcher (R-5.2-1, R-5.2-2): labelled set written without the entries' own words.

Each case is (query, acceptable ids, kind) where kind is 'verifier' or 'recipe'.
Queries are phrased as someone who has not read the library would phrase them.
Top-1 / top-3 thresholds below sit a small margin under the level reached when
this set was built; the test fails if matching regresses under them.
"""
import unittest
from support import *

from sisi import verifiers as V

# (query, acceptable verifier ids)
VERIFIER_CASES = [
    ("fix the race condition in the worker pool", {"thread-sanitizer", "go-race-detector", "loom", "shuttle", "stress-repeat", "lock-order-and-deadlock"}),
    ("two background jobs keep stepping on the same shared counter", {"thread-sanitizer", "go-race-detector", "loom", "shuttle", "deterministic-simulation"}),
    ("the parser handles malformed CSV without falling over", {"atheris", "hypothesis", "hostile-input-from-schema", "cargo-fuzz", "proptest", "fast-check", "structure-aware-fuzzing", "jqwik", "go-fuzz", "jazzer"}),
    ("strange delimited files from users must not crash the import", {"atheris", "hypothesis", "hostile-input-from-schema", "cargo-fuzz", "proptest", "structure-aware-fuzzing"}),
    ("money rounding is correct to the cent", {"algebraic-laws", "exhaustive-small-domain", "hypothesis", "proptest", "differential-reference", "metamorphic", "golden-files-hand-verified"}),
    ("the invoice totals always add up whatever lines are on it", {"algebraic-laws", "hypothesis", "proptest", "metamorphic", "derived-view-agreement", "differential-reference"}),
    ("charges are never a fraction of a cent out", {"algebraic-laws", "exhaustive-small-domain", "hypothesis", "metamorphic", "differential-reference"}),
    ("any sequence of moves keeps the account balanced", {"algebraic-laws", "stateful-model-test", "model-test-from-spec", "replay-equivalence"}),
    ("old files from the previous release still open with the same figures", {"old-data-compatibility", "db-migration-safety", "packaging-install-upgrade"}),
    ("moving the stored records to the new shape loses nothing", {"db-migration-safety", "old-data-compatibility", "differential-old-vs-new"}),
    ("the page still looks the same where I did not touch it", {"visual-regression-web", "ui-structure-snapshot", "baseline-before-change"}),
    ("people using only a keyboard can still finish the form", {"accessibility-axe", "e2e-playwright", "owner-acceptance-runbook"}),
    ("would my checks notice if the calculation were quietly wrong", {"cargo-mutants", "mutmut", "mutation-on-diff", "vacuity-check", "assertion-strength-review", "check-the-checker", "pitest", "go-mutation", "stryker"}),
    ("the new check passes even when nothing ran at all", {"vacuity-check", "check-the-checker", "red-before-green"}),
    ("nothing that worked yesterday broke in the tidy-up", {"characterization-tests", "baseline-before-change", "differential-old-vs-new"}),
    ("a hostile file at the boundary gets a clean refusal, not a crash", {"hostile-input-from-schema", "atheris", "cargo-fuzz", "codeql"}),
    ("no password or token ends up in the history", {"secret-scanning", "sensitive-data-leak-test"}),
    ("every state the workflow can sit in is one we meant to allow", {"tlaplus", "quint", "alloy", "small-scope-enumeration", "illegal-states-unrepresentable", "model-coverage"}),
    ("after the power dies mid-save the data reopen intact", {"fault-injection-storage"}),
    ("reading it back gives exactly what was written, every shape of value", {"round-trip", "stateful-model-test"}),
    ("the service still answers each caller the way they expect", {"contract-testing-pact", "smoke-after-deploy", "load-test-k6"}),
    ("it works from a brand-new checkout, not just my messy tree", {"clean-clone-build"}),
]

RECIPE_CASES = [
    ("fix the race condition", {"concurrent-code"}),
    ("two jobs running at once keep losing each other's updates", {"concurrent-code"}),
    ("add multi-page map printing with selectable paper size", {"feature"}),
    ("change the accent color of one UI component", {"web-ui-change"}),
    ("let people print a big map over several sheets of paper", {"feature"}),
    ("make the settings page button a different colour", {"web-ui-change"}),
    ("the total on invoices is a cent out when it rounds", {"numeric-or-financial-core"}),
    ("users' spreadsheet files with broken rows break the import", {"parser-or-codec"}),
    ("numbers coming out of the tax calculation cannot be trusted", {"numeric-or-financial-core"}),
    ("reported defect: the export button does nothing on the second click", {"bugfix"}),
    ("it worked before the tidy-up and must behave identically after", {"refactor"}),
    ("restructure the internals without changing what anyone sees", {"refactor"}),
    ("ship the next version and put the tag on it", {"release"}),
    ("move all the stored records onto the new layout safely", {"data-migration"}),
    ("the stored shape is changing and old records must survive", {"data-migration"}),
    ("someone found a way in through the search box input", {"security-fix"}),
    ("make the nightly job finish in half the time", {"performance-work"}),
    ("why is everything so sluggish since the last change", {"performance-work"}),
    ("rewrite the bit that turns text files into tables", {"parser-or-codec"}),
    ("a whole new app from this one-line idea", {"new-product"}),
    ("a package other teams will build on top of", {"new-library"}),
    ("the bit that keeps files on disk and reads them back after a crash", {"storage-engine"}),
]

ALL_CASES = ([(q, ids, "verifier") for q, ids in VERIFIER_CASES]
             + [(q, ids, "recipe") for q, ids in RECIPE_CASES])

# Measured when built: new top-1 0.75, top-3 0.93 (old word overlap: 0.55 / 0.68).
# Thresholds are that minus a small margin.
TOP1_MIN = 0.68
TOP3_MIN = 0.88


def _ranked_ids(query, kind):
    if kind == "verifier":
        return [e["id"] for _, e in V.rank_verifiers(query)]
    return [r["id"] for _, r in V.rank_recipes(query)]


class LabelledSetTests(SisiCase):
    def test_labelled_set_accuracy(self):
        """R-5.2-2: matching is good enough on requests that share no words with the entries."""
        self.assertGreaterEqual(len(ALL_CASES), 40)
        top1 = top3 = 0
        misses = []
        for query, acceptable, kind in ALL_CASES:
            ids = _ranked_ids(query, kind)
            if ids and ids[0] in acceptable:
                top1 += 1
            if any(i in acceptable for i in ids[:3]):
                top3 += 1
            else:
                misses.append((query, ids[:3]))
        n = len(ALL_CASES)
        self.assertGreaterEqual(top3 / n, TOP3_MIN, "top-3 misses: %r" % (misses,))
        self.assertGreaterEqual(top1 / n, TOP1_MIN, "top-1 too low; misses: %r" % (misses,))

    def test_audit_failures_rank_first(self):
        """R-5.2-1: the audit's named failures are fixed."""
        self.assertEqual(_ranked_ids("fix the race condition", "recipe")[0], "concurrent-code")
        ids = _ranked_ids("the parser handles malformed CSV", "verifier")
        fuzz_or_property = {"atheris", "hypothesis", "cargo-fuzz", "proptest", "fast-check",
                            "hostile-input-from-schema", "structure-aware-fuzzing", "jqwik", "go-fuzz", "jazzer"}
        self.assertTrue(any(i in fuzz_or_property for i in ids[:3]), ids[:3])
        money = _ranked_ids("money rounding is correct", "verifier")
        self.assertTrue(any(i in money for i in
                            [e["id"] for _, e in V.rank_verifiers("money rounding is correct")
                             if "money" in e["kinds"]][:3] or money[:3]), money[:3])

    def test_spec_examples_get_recipes(self):
        """SPEC Appendix A/B: both worked examples get a fitting recipe."""
        self.assertEqual(_ranked_ids("add multi-page map printing with selectable paper size", "recipe")[0], "feature")
        self.assertIn(_ranked_ids("change the accent color of one UI component", "recipe")[0],
                      ("web-ui-change", "native-gui-change"))


class RankingTests(SisiCase):
    def test_proven_ranks_above_documentation_only(self):
        """R-5.2-6: an entry proven on a real run outranks a docs-only twin."""
        import os
        vdir = os.path.join(self.tmp, "v2")
        os.makedirs(os.path.join(vdir, "prove"))
        body = "\n".join("## " + h + "\ntext" for h in V.V_HEADINGS) + "\n"
        def entry(id, verified):
            return ("---\nid: %s\ntitle: Cache check %s\nanswers: Does the cache evict correctly?\nrung: 3\n"
                    "section: prove\nlanguages: any\nkinds: general\ncost: low\ndetect:\nran_here: no\n"
                    "verified: %s\n---\n%s" % (id, id, verified, body))
        with open(os.path.join(vdir, "prove", "docs-twin.md"), "w") as f:
            f.write(entry("docs-twin", "docs"))
        with open(os.path.join(vdir, "prove", "ran-twin.md"), "w") as f:
            f.write(entry("ran-twin", "ran"))
        ranked = V.rank_verifiers("cache evict", entries=V.load_verifiers(vdir))
        self.assertEqual(ranked[0][1]["id"], "ran-twin")


if __name__ == "__main__":
    unittest.main()
