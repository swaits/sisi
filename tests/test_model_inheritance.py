"""A new version of a model starts from its predecessor's judged record: inherited evidence ranks below the model's
own record and above a benchmark, counts as judged proof, stops once the model has a thick record of its own, and a
predecessor's bad record does not block it. Invented ids. Requirement ids: R-7.2-1, R-7.2-3."""
import random, unittest
from support import *
from sisi import routing
from test_model_supersession import cand, attempts, pick, NOW


def assessed(cands, records, worker, difficulty=2, kind="impl", **kw):
    r = routing.choose(cands, list(records), {}, kind, difficulty, now=NOW, **kw)
    return r["assessments"].get(worker), r


class InheritanceTests(unittest.TestCase):
    def test_a_new_version_inherits_the_record_of_its_predecessor_and_says_so(self):
        old, new = cand("prov/abc-5.3", cost=1.0), cand("prov/abc-5.4", cost=2.0)
        records = attempts("prov/abc-5.3", 12, 11, difficulty=2)
        a, r = assessed([old, new], records, "prov/abc-5.4")
        self.assertEqual((a["tier"], a["capable"], a["inherited_from"]), ("a", True, "prov/abc-5.3"))
        self.assertEqual(r["choice"]["worker"], "prov/abc-5.4")
        line = routing.evidence_line(a, "impl", 2, r["choice"], r["basis"])
        self.assertIn("the record of its predecessor prov/abc-5.3", line)
        self.assertIn("11 of 12", line)

    def test_it_walks_back_one_predecessor_at_a_time(self):
        cands = [cand("prov/abc-5.2", cost=1.0), cand("prov/abc-5.3", cost=1.0), cand("prov/abc-5.4", cost=1.0)]
        records = attempts("prov/abc-5.2", 12, 12, difficulty=2) + attempts("prov/abc-5.3", 3, 3, difficulty=2)
        a, _ = assessed(cands, records, "prov/abc-5.4")
        self.assertEqual(a["inherited_from"], "prov/abc-5.2")   # 5.3 has only a thin record
        records += attempts("prov/abc-5.3", 9, 9, difficulty=2, start=50)
        a, _ = assessed(cands, records, "prov/abc-5.4")
        self.assertEqual(a["inherited_from"], "prov/abc-5.3")   # now the closest thick one

    def test_a_predecessors_bad_record_does_not_block_the_newer_model(self):
        cands = [cand("prov/abc-5.3", cost=1.0), cand("prov/abc-5.4", cost=1.0, standing=70.0)]
        records = attempts("prov/abc-5.3", 12, 2, difficulty=2)
        a, _ = assessed(cands, records, "prov/abc-5.4")
        self.assertFalse(a["bad"])
        self.assertEqual(a["tier"], "standing")   # it starts from its benchmark, not from the old verdict
        bare = assessed([cands[0], cand("prov/abc-5.4", cost=1.0)], records, "prov/abc-5.4")[0]
        self.assertFalse(bare["bad"])
        self.assertFalse(bare["capable"])

    def test_the_models_own_thick_record_replaces_the_inherited_one(self):
        cands = [cand("prov/abc-5.3", cost=1.0), cand("prov/abc-5.4", cost=1.0)]
        records = attempts("prov/abc-5.3", 12, 12, difficulty=2) + attempts("prov/abc-5.4", 9, 1, difficulty=2)
        a, _ = assessed(cands, records, "prov/abc-5.4")
        self.assertTrue(a["bad"])
        self.assertIsNone(a.get("inherited_from"))
        records = attempts("prov/abc-5.3", 12, 2, difficulty=2) + attempts("prov/abc-5.4", 9, 9, difficulty=2)
        a, _ = assessed(cands, records, "prov/abc-5.4")
        self.assertEqual((a["tier"], a.get("inherited_from")), ("a", None))

    def test_a_thin_record_that_already_contradicts_is_not_papered_over(self):
        cands = [cand("prov/abc-5.3", cost=1.0), cand("prov/abc-5.4", cost=1.0)]
        records = attempts("prov/abc-5.3", 12, 12, difficulty=2) + attempts("prov/abc-5.4", 3, 0, difficulty=2)
        a, _ = assessed(cands, records, "prov/abc-5.4")
        self.assertIsNone(a.get("inherited_from"))
        self.assertFalse(a["capable"])

    def test_nothing_is_inherited_across_classes_or_makers(self):
        flash, new = cand("prov/abc-5.3-flash", cost=1.0), cand("prov/abc-5.4", cost=1.0)
        records = attempts("prov/abc-5.3-flash", 12, 12, difficulty=2)
        self.assertFalse(assessed([flash, new], records, "prov/abc-5.4")[0]["capable"])
        other = cand("prov/xyz-5.4", cost=1.0, maker="xyz")
        self.assertFalse(assessed([cand("prov/abc-5.3"), other], attempts("prov/abc-5.3", 12, 12, difficulty=2), "prov/xyz-5.4")[0]["capable"])

    def test_nothing_is_inherited_by_an_unreadable_class(self):
        cands = [cand("prov/abc-6.2-sol"), cand("prov/abc-6.3-sol")]
        records = attempts("prov/abc-6.2-sol", 12, 12, difficulty=2)
        self.assertFalse(assessed(cands, records, "prov/abc-6.3-sol")[0]["capable"])

    def test_inherited_evidence_counts_as_a_judged_record_before_a_benchmark(self):
        """Difficulty 2 and 3: proof comes before benchmark, and an inherited record is proof."""
        new = cand("prov/abc-5.4", cost=5.0)
        rival = cand("prov/xyz-2.0", cost=0.1, maker="xyz", standing=90.0)
        records = attempts("prov/abc-5.3", 12, 12, difficulty=3)
        who, r = pick([cand("prov/abc-5.3", cost=5.0), new, rival], records, 3)
        self.assertEqual(who, "prov/abc-5.4")
        self.assertTrue(r["judged_first"])

    def test_inherited_ranks_below_the_models_own_record_in_strength(self):
        own = routing.assess({"w": {"uses": 0, "by_cell": {("impl", 2): {"n": 10, "good": 10}}}}, "w", "impl", 2)
        inherited = routing.assess({"w": {"uses": 0, "by_cell": {("impl", 2): {"n": 10, "good": 10, "from": "old"}}}}, "w", "impl", 2)
        bench = routing.assess({"w": {"uses": 0, "by_cell": {}}}, "w", "impl", 2, standing=80.0, best_standing=80.0)
        self.assertGreater(routing.strength(own), routing.strength(inherited))
        self.assertGreater(routing.strength(inherited), routing.strength(bench))
        self.assertEqual(inherited["inherited_from"], "old")

    def test_a_model_with_no_data_of_its_own_is_routable_through_its_predecessor(self):
        from sisi import workers
        old, new, lone = cand("prov/abc-5.3"), cand("prov/abc-5.4"), cand("prov/xyz-9.9", maker="xyz")
        for c in (old, new, lone):
            c["price_source"] = None
        old["price_source"] = "fixture"
        keep, cold, excluded = workers.routable_candidates([old, new, lone], [])
        self.assertEqual(sorted(c["worker"] for c in keep), ["prov/abc-5.3", "prov/abc-5.4"])
        self.assertEqual(excluded, 1)

    def test_property_inherited_evidence_never_outranks_a_thick_record_of_the_models_own(self):
        rng = random.Random(41)
        seen = 0
        for _ in range(300 * ITERS):
            versions = rng.sample(["5.1", "5.2", "5.3", "5.4", "5.10"], rng.randint(2, 4))
            cands = [cand("prov/abc-%s" % v, cost=rng.choice([None, 1.0, 2.0])) for v in versions]
            records = []
            for c in cands:
                for d in (1, 2, 3):
                    if rng.random() < 0.6:
                        n = rng.choice([2, 8, 12])
                        records += attempts(c["worker"], n, rng.randint(0, n), difficulty=d, start=d * 100)
            stats = routing.candidate_stats(cands, records)
            eff = routing.inherit_stats(cands, stats)
            for c in cands:
                for ck, cell in stats[c["worker"]]["by_cell"].items():
                    if cell["n"] >= routing.MIN_ATTEMPTS:
                        self.assertEqual(eff[c["worker"]]["by_cell"][ck], cell)
                        seen += 1
                for ck, cell in eff[c["worker"]]["by_cell"].items():
                    if cell.get("from"):
                        own = stats[c["worker"]]["by_cell"].get(ck, {"n": 0})
                        self.assertLess(own["n"], routing.MIN_ATTEMPTS)
                        self.assertGreaterEqual(cell["n"], routing.MIN_ATTEMPTS)
                        self.assertGreaterEqual(cell["good"] / cell["n"], routing.MIN_ACCEPTED_RATE)  # a bad record is never inherited
        self.assertGreater(seen, 100)


if __name__ == "__main__":
    unittest.main()
