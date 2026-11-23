"""A maker's classes, most capable first: a prior between classes of that maker where nothing better exists, never
above a judged record or a benchmark standing. Invented ids: for this maker each class is a named line.
Requirement ids: R-7.2-1, R-7.2-2, R-7.2-3."""
import json, os, random, unittest
from support import *
from sisi import routing
from test_model_supersession import cand, attempts, pick, NOW
from test_worker_models import ModelCase

ORDER = {"abc": ["fable", "opus", "sonnet", "haiku"]}
COST = {"fable": 9.0, "opus": 6.0, "sonnet": 3.0, "haiku": 1.0}


def fleet(**extra):
    return [cand("prov/abc-%s-5" % c, **dict({"cost": COST[c]}, **extra.get(c, {}))) for c in ("fable", "opus", "sonnet", "haiku")]


def best(cands, difficulty, records=(), **kw):
    opts = {"class_orders": ORDER}
    opts.update(kw.pop("opts", {}))
    return pick(cands, records, difficulty, opts=opts, **kw)


class ClassOrderTests(unittest.TestCase):
    def test_routine_work_goes_to_the_lowest_class_and_hard_work_to_the_upper_ones(self):
        """Nothing judged, no benchmark: the order is the prior and the cheapest capable class wins."""
        cands = fleet()
        self.assertEqual(best(cands, 1)[0], "prov/abc-haiku-5")
        self.assertEqual(best(cands, 2)[0], "prov/abc-sonnet-5")
        who, r = best(cands, 3)
        self.assertEqual(who, "prov/abc-opus-5")
        self.assertEqual(r["assessments"]["prov/abc-opus-5"]["tier"], "class")
        self.assertFalse(r["assessments"]["prov/abc-sonnet-5"]["capable"])

    def test_the_mapping_is_configurable(self):
        cands = fleet()
        self.assertEqual(best(cands, 3, opts={"class_span": {"3": 0}})[0], "prov/abc-fable-5")
        self.assertEqual(best(cands, 3, opts={"class_span": {"3": 100}})[0], "prov/abc-haiku-5")
        self.assertEqual(routing.class_spans({"2": "x", "9": 50, "1": 101})[1], 100.0)

    def test_without_a_recorded_order_a_class_is_no_evidence(self):
        who, r = pick(fleet(), (), 3)
        self.assertEqual(r["basis"], "nothing")
        self.assertFalse(any(a["tier"] == "class" for a in r["assessments"].values()))

    def test_a_judged_record_outranks_the_order(self):
        records = attempts("prov/abc-haiku-5", 12, 12, difficulty=3)
        who, r = best(fleet(), 3, records)
        self.assertEqual(who, "prov/abc-haiku-5")
        self.assertEqual(r["assessments"]["prov/abc-haiku-5"]["tier"], "a")

    def test_a_benchmark_standing_outranks_the_order(self):
        cands = fleet(haiku={"standing": 80.0, "cost": 5.0})
        who, r = best(cands, 2)
        self.assertEqual(who, "prov/abc-haiku-5")     # sonnet is capable by class and cheaper than none, but the standing is preferred
        self.assertEqual(r["assessments"]["prov/abc-haiku-5"]["tier"], "standing")
        self.assertTrue(any("benchmark" in why for w, why in r["passed_over"] if w == "prov/abc-sonnet-5"))

    def test_when_nobody_is_proven_the_strongest_known_means_the_highest_class(self):
        cands = [c for c in fleet() if c["worker"] in ("prov/abc-sonnet-5", "prov/abc-haiku-5")]
        who, r = best(cands, 3)
        self.assertEqual((who, r["basis"]), ("prov/abc-sonnet-5", "strongest"))

    def test_another_makers_models_are_not_placed_by_this_order(self):
        other = cand("prov/xyz-opus-5", cost=0.1, maker="xyz")
        who, r = best(fleet() + [other], 3)
        self.assertEqual(who, "prov/abc-opus-5")
        self.assertNotEqual(r["assessments"]["prov/xyz-opus-5"]["tier"], "class")

    def test_a_class_missing_from_the_order_is_not_placed(self):
        extra = cand("prov/abc-ember-1", cost=0.1)
        who, r = best(fleet() + [extra], 3)
        self.assertNotEqual(r["assessments"]["prov/abc-ember-1"]["tier"], "class")

    def test_the_asking_line_wants_the_order_of_a_maker_with_several_classes(self):
        r = pick(fleet(), (), 3)[1]
        self.assertEqual(r["class_ask"]["order"], [("abc", ["fable", "haiku", "opus", "sonnet"])])
        r = best(fleet(), 3)[1]
        self.assertEqual(r["class_ask"]["order"], [])
        one = pick([cand("prov/abc-opus-5"), cand("prov/abc-opus-6")], (), 3)[1]
        self.assertEqual(one["class_ask"]["order"], [])   # one class only: nothing to order

    def test_property_the_order_never_outranks_a_record_or_a_standing(self):
        rng = random.Random(9)
        for _ in range(300 * ITERS):
            cands = [cand("prov/abc-%s-5" % c, cost=rng.choice([1.0, 2.0, 5.0]),
                          standing=rng.choice([None, None, 40.0, 90.0])) for c in rng.sample(list(COST), rng.randint(2, 4))]
            records = []
            for c in cands:
                for d in (1, 2, 3):
                    if rng.random() < 0.4:
                        n = rng.choice([3, 10, 12])
                        records += attempts(c["worker"], n, rng.randint(0, n), difficulty=d)
            d = rng.choice([2, 3])
            who, r = best(cands, d, records)
            if who is None or r["basis"] != "capable":
                continue
            tiers = {w: a["tier"] for w, a in r["assessments"].items() if a["capable"]}
            if any(t in ("a", "b-higher", "b-all") for t in tiers.values()):
                self.assertIn(tiers[who], ("a", "b-higher", "b-all"))
            elif any(t == "standing" for t in tiers.values()):
                self.assertEqual(tiers[who], "standing")


class ClassesCommandTests(ModelCase):
    def test_a_makers_classes_are_recorded_shown_and_removed(self):
        self.seed([("prov/abc-5.3", 9, 9)])
        r = self.sisi("workers", "classes", "abc", "fable", "opus", "sonnet", "haiku", "--source", "owner, in his words", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        stored = json.load(open(os.path.join(self.data, "worker-models.json")))["classes"]["abc"]
        self.assertEqual((stored["order"], stored["source"]), (["fable", "opus", "sonnet", "haiku"], "owner, in his words"))
        self.assertIn("Classes of abc, most capable first: fable, opus, sonnet, haiku (owner, in his words", self.listing())
        self.assertEqual(self.sisi("workers", "classes", "abc", "--remove", env=self.env()).returncode, 0)
        self.assertNotIn("Classes of abc", self.listing())

    def test_bad_input_is_refused(self):
        for args in (("abc", "opus"), ("abc", "--source", "x"), ("abc", "o pus", "--source", "x"), ("abc", "opus", "opus", "--source", "x")):
            r = self.sisi("workers", "classes", *args, env=self.env())
            self.assertEqual(r.returncode, 1, args)
        self.assertFalse(os.path.exists(os.path.join(self.data, "worker-models.json")))

    def test_route_uses_the_recorded_order_and_asks_for_it_until_then(self):
        models = ("abc-fable-5", "abc-opus-5", "abc-sonnet-5", "abc-haiku-5")
        for m in models:
            self.sisi("workers", "fact", "muse/" + m, "--price", str(COST[m.split("-")[1]]), "--source", "fixture", env=self.env(models))
        first = self.route(3, models=models)
        self.assertIn("record the order", first.stdout)
        self.assertLessEqual(len(first.stdout.splitlines()), 7, first.stdout)
        self.sisi("workers", "classes", "abc", "fable", "opus", "sonnet", "haiku", "--source", "owner", env=self.env(models))
        after = self.route(3, "--explain", models=models)
        self.assertEqual(after.stdout.splitlines()[0], "muse/abc-opus-5", after.stdout)
        self.assertNotIn("record the order", after.stdout)
        self.assertIn("class order", after.stdout)
        self.assertEqual(self.route(1, models=models).stdout.splitlines()[0], "muse/abc-haiku-5")


if __name__ == "__main__":
    unittest.main()
