"""The newest usable version of a maker's class always wins over its older versions (hard rule), however good the
older record or cheap its plan. Identity and recency come from recorded facts. Pure routing tests over invented ids.
Requirement ids: R-7.2-1, R-7.2-2, R-7.2-3."""
import random, unittest
from support import *
from sisi import routing

NOW = 1000000.0
R1, R2, R3, R4 = "2026-03-01", "2026-06-01", "2026-09-01", "2026-11-01"


def cand(worker, cls="standard", rel=None, maker="abc", plan="per-use", cost=1.0, host_native=False, standing=None,
         known=True, **kw):
    """A candidate whose maker, class and release date were recorded (known=False: nothing recorded)."""
    model = worker.rsplit("/", 1)[-1]
    fact = {"class": cls, "maker": maker, "released": rel} if known else {}
    c = {"worker": worker, "tool": worker.split("/")[0] if "/" in worker else None, "model": model, "maker": maker,
         "plan": plan, "cost": cost, "allowance_pct_left": None, "usable": True, "standing": standing,
         "aliases": [worker, model], "lineage": routing.lineage_from_fact(fact, host_native=host_native)}
    c.update(kw)
    return c


def attempts(worker, n, good, kind="impl", difficulty=1, start=0):
    return [{"kind": "attempt", "id": "%s-%d-%d" % (worker, difficulty, start + i), "type": kind, "difficulty": difficulty,
             "worker": worker, "outcome": "accepted" if i < good else "rejected", "check": "tests", "ts": NOW - 10}
            for i in range(n)]


def pick(cands, records=(), difficulty=1, availability=None, **kw):
    r = routing.choose(cands, list(records), availability or {}, "impl", difficulty, now=NOW, **kw)
    return (r["choice"] or {}).get("worker"), r


class IdentityTests(unittest.TestCase):
    def test_no_recorded_class_and_maker_means_no_identity(self):
        for fact in (None, {}, {"class": "flash"}, {"maker": "abc"}, {"released": "2026-01-01"}):
            got = routing.lineage_from_fact(fact)
            self.assertIsNone(got["key"], fact)
            self.assertEqual(got["source"], "unknown")

    def test_a_recorded_maker_and_class_are_the_identity_whatever_the_name(self):
        a = routing.lineage_from_fact({"class": "Flash", "maker": "ABC", "released": "2026-03-01"})
        self.assertEqual((a["key"], a["source"], a["released"]), (("abc", "flash"), "fact", "2026-03-01"))
        self.assertNotEqual(routing.lineage_from_fact({"class": "standard", "maker": "abc"})["key"], a["key"])

    def test_the_more_recent_release_date_is_newer_and_dates_compare_as_dates(self):
        old = routing.lineage_from_fact({"class": "x", "maker": "m", "released": "2026-09-30"})
        new = routing.lineage_from_fact({"class": "x", "maker": "m", "released": "2026-10-02"})
        self.assertGreater(routing.compare_release(new, old), 0)
        self.assertLess(routing.compare_release(old, new), 0)
        self.assertEqual(routing.compare_release(old, old), 0)
        self.assertEqual(routing.compare_release(old, routing.lineage_from_fact({"class": "x", "maker": "m"})), 0)  # unknowable
        self.assertGreater(routing.days("2026-10-02"), routing.days("2026-09-30"))
        self.assertEqual(routing.days("soon"), 0)

    def test_a_bare_host_alias_without_a_release_date_is_the_newest_of_its_class(self):
        alias = routing.lineage_from_fact({"class": "x", "maker": "m"}, host_native=True)
        dated = routing.lineage_from_fact({"class": "x", "maker": "m", "released": "2030-01-01"})
        self.assertTrue(alias["alias"])
        self.assertGreater(routing.compare_release(alias, dated), 0)
        self.assertFalse(routing.lineage_from_fact({"class": "x", "maker": "m"})["alias"])
        self.assertFalse(routing.lineage_from_fact({}, host_native=True)["alias"])   # no class recorded: no comparison
        self.assertFalse(routing.lineage_from_fact({"class": "x", "maker": "m", "released": "2026-01-01"}, host_native=True)["alias"])

    def test_unknown_answers_and_partial_dates(self):
        self.assertIsNone(routing.lineage_from_fact({"class": "unknown", "maker": "abc"})["key"])
        self.assertIsNone(routing.lineage_from_fact({"class": "x", "maker": "unknown"})["key"])
        self.assertIsNone(routing.lineage_from_fact({"class": "x", "maker": "abc", "released": "unknown"})["released"])
        a = routing.lineage_from_fact({"class": "x", "maker": "m", "released": "2026-09"})
        b = routing.lineage_from_fact({"class": "x", "maker": "m", "released": "2026-10-15"})
        self.assertGreater(routing.compare_release(b, a), 0)
        self.assertGreater(routing.days("2026-10"), routing.days("2026-09-30"))

    def test_no_code_reads_a_model_name(self):
        import os, re as _re
        self.assertFalse(os.path.exists(os.path.join(REPO, "sisi", "modelid.py")))
        self.assertFalse(os.path.exists(os.path.join(REPO, "canon", "model-words.json")))
        text = open(os.path.join(REPO, "sisi", "routing.py")).read()
        self.assertEqual(_re.findall(r"modelid|tier word|parse_model", text), [])


class SupersessionTests(unittest.TestCase):
    def test_the_newer_version_wins_over_an_older_one_with_a_better_record_and_a_cheaper_plan(self):
        """The owner's rule: no evidence exception, no price exception."""
        old = cand("prov/abc-old", rel=R1, plan="flat", cost=0.0)
        new = cand("prov/abc-new", rel=R2, plan="per-use", cost=9.0)
        records = attempts("prov/abc-old", 30, 30, difficulty=1)
        who, r = pick([old, new], records)
        self.assertEqual(who, "prov/abc-new")
        self.assertIn(("prov/abc-old", "superseded by prov/abc-new (a newer version of the same class)"), r["passed_over"])

    def test_the_release_date_decides_not_the_name(self):
        """A name that looks newer but was released earlier is the older model."""
        a = cand("prov/abc-9.9", rel=R1)
        b = cand("prov/abc-1.0", rel=R3)
        self.assertEqual(pick([a, b])[0], "prov/abc-1.0")

    def test_different_classes_never_supersede_each_other(self):
        flash, std = cand("prov/abc-a", cls="flash", rel=R1, cost=0.1), cand("prov/abc-b", rel=R2, cost=5.0)
        who, r = pick([flash, std])
        self.assertEqual(who, "prov/abc-a")  # the cheaper class still competes
        self.assertFalse([w for w, why in r["passed_over"] if why.startswith("superseded")])

    def test_two_named_lines_of_one_maker_are_different_classes(self):
        a, b = cand("prov/abc-w", cls="wonder", rel=R1, cost=1.0), cand("prov/abc-e", cls="ember", rel=R2, cost=2.0)
        who, r = pick([a, b])
        self.assertEqual(who, "prov/abc-w")
        self.assertFalse([w for w, why in r["passed_over"] if why.startswith("superseded")])

    def test_different_makers_never_supersede_each_other(self):
        a, b = cand("prov/abc-a", rel=R1, cost=1.0), cand("prov/xyz-b", rel=R3, cost=2.0, maker="xyz")
        self.assertEqual(pick([a, b])[0], "prov/abc-a")

    def test_a_model_with_nothing_recorded_is_never_compared(self):
        a, b = cand("prov/abc-a", known=False, cost=1.0), cand("prov/abc-b", rel=R3, cost=2.0)
        who, r = pick([a, b])
        self.assertEqual(who, "prov/abc-a")
        self.assertFalse([w for w, why in r["passed_over"] if why.startswith("superseded")])
        no_date = cand("prov/abc-c", cost=1.0)    # class recorded, no date: not comparable with a dated one
        self.assertFalse([w for w, why in pick([no_date, cand("prov/abc-d", rel=R3)])[1]["passed_over"] if why.startswith("superseded")])

    def test_the_newer_one_unusable_lets_the_older_compete_again(self):
        old, new = cand("prov/abc-old", rel=R1, cost=1.0), cand("prov/abc-new", rel=R2, cost=2.0)
        self.assertEqual(pick([old, new], availability={"prov/abc-new": {"reason": "limit", "retry_at": NOW + 99}})[0], "prov/abc-old")
        self.assertEqual(pick([old, dict(new, usable=False, reason="not logged in")])[0], "prov/abc-old")
        self.assertEqual(pick([old, new], avoid=[{"pattern": "abc-new"}])[0], "prov/abc-old")
        self.assertEqual(pick([old, dict(new, plan="flat", allowance_pct_left=0)])[0], "prov/abc-old")

    def test_a_tried_newer_version_does_not_send_a_retry_back_to_the_older(self):
        old, new = cand("prov/abc-old", rel=R1, cost=1.0), cand("prov/abc-new", rel=R2, cost=2.0)
        self.assertIsNone(pick([old, new], exclude=["prov/abc-new"])[0])

    def test_a_newer_version_with_a_thick_bad_record_never_sends_work_back_to_the_older(self):
        old, new = cand("prov/abc-old", rel=R1, cost=1.0), cand("prov/abc-new", rel=R2, cost=2.0)
        other = cand("prov/xyz-2", cost=3.0, maker="xyz")
        records = attempts("prov/abc-new", 10, 1, difficulty=1) + attempts("prov/xyz-2", 10, 10, difficulty=1)
        self.assertEqual(pick([old, new, other], records)[0], "prov/xyz-2")
        self.assertEqual(pick([old, new], records)[0], "prov/abc-new")  # nobody else: still not the older version

    def test_the_same_model_through_two_providers_is_one_model(self):
        old_a = cand("prova/abc-old", rel=R1, plan="flat", cost=0.0)
        new_a, new_b = cand("prova/abc-new", rel=R2, cost=5.0), cand("provb/abc-new", rel=R2, cost=2.0)
        who, r = pick([old_a, new_a, new_b])
        self.assertEqual(who, "provb/abc-new")  # the existing cost comparison picks the provider
        self.assertEqual(sorted(w for w, why in r["passed_over"] if why.startswith("superseded")), ["prova/abc-old"])
        self.assertEqual(pick([old_a, new_a, new_b], availability={"provb": {"reason": "limit", "retry_at": NOW + 9}})[0], "prova/abc-new")

    def test_a_bare_host_alias_is_the_newest_of_its_class(self):
        alias = cand("abc", host_native=True, cost=9.0)
        versioned = cand("prov/abc-9", rel=R4, cost=0.1)
        self.assertEqual(pick([alias, versioned])[0], "abc")
        self.assertEqual(pick([cand("abc", host_native=True, known=False, cost=9.0), versioned])[0], "prov/abc-9")

    def test_the_asking_line_names_workers_with_nothing_recorded_when_a_choice_is_made_among_several(self):
        a, b = cand("prov/abc-a", known=False), cand("prov/abc-b", rel=R2)
        self.assertEqual(pick([a, b])[1]["class_ask"]["classify"], ["prov/abc-a"])
        self.assertEqual(pick([a])[1]["class_ask"]["classify"], [])
        self.assertEqual(pick([cand("prov/abc-a", rel=R1), cand("prov/abc-b", rel=R2)])[1]["class_ask"]["classify"], [])


class SupersessionPropertyTests(unittest.TestCase):
    def fleet(self, rng):
        cands, records, down = [], [], {}
        for maker in rng.sample(["abc", "xyz", "qrs"], rng.randint(1, 3)):
            for cls in rng.sample(["standard", "flash", "mini", "wonder"], rng.randint(1, 3)):
                for rel in rng.sample(["2026-01-05", "2026-03-01", "2026-06-01", "2026-09-30", "2026-10-02", None], rng.randint(1, 4)):
                    for prov in rng.sample(["pa", "pb"], rng.randint(1, 2)):
                        w = "%s/%s-%s-%s" % (prov, maker, cls, rel)
                        c = cand(w, cls=cls, rel=rel, maker=maker, plan=rng.choice(["flat", "per-use", None]),
                                 cost=rng.choice([None, 0.1, 1.0, 5.0]), allowance_pct_left=rng.choice([None, 0, 50]),
                                 known=rng.random() < 0.9)
                        cands.append(c)
                        if rng.random() < 0.15:
                            down[w] = {"reason": "limit", "retry_at": NOW + 99}
                        for d in (1, 2, 3):
                            if rng.random() < 0.5:
                                n = rng.choice([3, 10, 12])
                                records += attempts(w, n, rng.randint(0, n), difficulty=d)
        return cands, records, down

    def usable(self, c, down):
        return c["worker"] not in down and not (c["plan"] == "flat" and c["allowance_pct_left"] == 0)

    def test_the_chosen_worker_is_never_an_older_version_of_a_class_with_a_newer_usable_version(self):
        """Property: whatever the fleet, ledger, plans and availability."""
        rng = random.Random(20261123)
        checked = 0
        for _ in range(300 * ITERS):
            cands, records, down = self.fleet(rng)
            who, r = pick(cands, records, rng.choice([1, 2, 3]), availability=down)
            if who is None:
                continue
            chosen = next(c for c in cands if c["worker"] == who)
            lc = chosen["lineage"]
            for c in cands:
                if c is chosen or not self.usable(c, down) or not lc["key"]:
                    continue
                if c["lineage"]["key"] == lc["key"]:
                    self.assertLessEqual(routing.compare_release(c["lineage"], lc), 0, (who, c["worker"]))
                    checked += 1
            for w, why in r["passed_over"]:
                if why.startswith("superseded by "):
                    newer = why[len("superseded by "):].split(" ")[0]
                    a = next(c for c in cands if c["worker"] == w)["lineage"]
                    b = next(c for c in cands if c["worker"] == newer)["lineage"]
                    self.assertEqual(a["key"], b["key"], "a model never supersedes one of another maker or class")
                    self.assertIsNotNone(a["key"])
                    self.assertGreater(routing.compare_release(b, a), 0)
        self.assertGreater(checked, 100)

    def test_adding_a_newer_version_of_the_chosen_model_never_makes_the_choice_an_older_model_of_that_class(self):
        rng = random.Random(77)
        done = 0
        for _ in range(200 * ITERS):
            cands, records, down = self.fleet(rng)
            d = rng.choice([1, 2, 3])
            who, _r = pick(cands, records, d, availability=down)
            if who is None:
                continue
            lc = next(c for c in cands if c["worker"] == who)["lineage"]
            if not lc["key"] or not lc["released"]:
                continue
            new = cand("pc/newest", cls=lc["class"], maker=lc["maker"], rel="2027-01-01", cost=rng.choice([None, 0.1, 5.0]))
            after, _ = pick(cands + [new], records, d, availability=down)
            if after is None:
                continue
            got = next(c for c in cands + [new] if c["worker"] == after)["lineage"]
            if got["key"] == lc["key"]:
                self.assertGreaterEqual(routing.compare_release(got, lc), 0, (who, after))
            done += 1
        self.assertGreater(done, 30)

    def test_a_model_with_nothing_recorded_never_triggers_supersession(self):
        rng = random.Random(5)
        for _ in range(100 * ITERS):
            cands = [cand("prov/m-%d" % i, known=False, cost=rng.choice([None, 1.0, 2.0])) for i in range(rng.randint(2, 5))]
            who, r = pick(cands)
            self.assertFalse([w for w, why in r["passed_over"] if why.startswith("superseded")])


if __name__ == "__main__":
    unittest.main()
