"""The newest usable version of a maker's class always wins over its older versions (hard rule), however good the
older record or cheap its plan. Pure routing tests over invented ids shaped like real ones.
Requirement ids: R-7.2-1, R-7.2-2, R-7.2-3."""
import json, os, random, unittest
from support import *
from sisi import modelid, routing

WORDS = json.load(open(os.path.join(REPO, "canon", "model-words.json")))
NOW = 1000000.0


def cand(worker, plan="per-use", cost=1.0, fact=None, host_native=False, standing=None, **kw):
    model = worker.rsplit("/", 1)[-1]
    c = {"worker": worker, "tool": worker.split("/")[0] if "/" in worker else None, "model": model, "maker": "abc",
         "plan": plan, "cost": cost, "allowance_pct_left": None, "usable": True, "standing": standing,
         "aliases": [worker, model], "lineage": modelid.resolve(worker, WORDS, fact=fact, host_native=host_native)}
    c.update(kw)
    return c


def attempts(worker, n, good, kind="impl", difficulty=1, start=0):
    return [{"kind": "attempt", "id": "%s-%d-%d" % (worker, difficulty, start + i), "type": kind, "difficulty": difficulty,
             "worker": worker, "outcome": "accepted" if i < good else "rejected", "check": "tests", "ts": NOW - 10}
            for i in range(n)]


def pick(cands, records=(), difficulty=1, availability=None, **kw):
    r = routing.choose(cands, list(records), availability or {}, "impl", difficulty, now=NOW, **kw)
    return (r["choice"] or {}).get("worker"), r


class SupersessionTests(unittest.TestCase):
    def test_the_newer_version_wins_over_an_older_one_with_a_better_record_and_a_cheaper_plan(self):
        """The owner's rule: no evidence exception, no price exception."""
        old = cand("prov/abc-5.3", plan="flat", cost=0.0)
        new = cand("prov/abc-5.4", plan="per-use", cost=9.0)
        records = attempts("prov/abc-5.3", 30, 30, difficulty=1)
        who, r = pick([old, new], records)
        self.assertEqual(who, "prov/abc-5.4")
        self.assertIn(("prov/abc-5.3", "superseded by prov/abc-5.4 (a newer version of the same class)"), r["passed_over"])

    def test_numeric_version_order(self):
        self.assertEqual(pick([cand("prov/abc-5.9"), cand("prov/abc-5.10")])[0], "prov/abc-5.10")
        self.assertEqual(pick([cand("prov/abc-5.3"), cand("prov/abc-5-4-20261101")])[0], "prov/abc-5-4-20261101")

    def test_the_tier_word_before_or_after_the_version_is_one_class(self):
        self.assertEqual(pick([cand("prov/abc-5.3-flash"), cand("prov/abc-flash-5.4")])[0], "prov/abc-flash-5.4")

    def test_different_classes_never_supersede_each_other(self):
        flash, std = cand("prov/abc-5.3-flash", cost=0.1), cand("prov/abc-5.4", cost=5.0)
        who, r = pick([flash, std])
        self.assertEqual(who, "prov/abc-5.3-flash")  # the cheaper class still competes
        self.assertFalse([w for w, why in r["passed_over"] if why.startswith("superseded")])

    def test_two_named_lines_of_one_maker_are_different_classes(self):
        a, b = cand("prov/abc-wonder-1.0", cost=1.0), cand("prov/abc-ember-1.3", cost=2.0)
        who, r = pick([a, b])
        self.assertEqual(who, "prov/abc-wonder-1.0")
        self.assertFalse([w for w, why in r["passed_over"] if why.startswith("superseded")])

    def test_unknown_class_never_supersedes_or_is_superseded(self):
        a, b = cand("prov/abc-6.2-sol", cost=1.0), cand("prov/abc-6.3-sol", cost=2.0)
        self.assertIsNone(a["lineage"]["key"])
        who, r = pick([a, b])
        self.assertEqual(who, "prov/abc-6.2-sol")
        self.assertFalse([w for w, why in r["passed_over"] if why.startswith("superseded")])

    def test_a_recorded_class_makes_an_unknown_one_comparable(self):
        fact = {"class": "sol", "maker": "abc"}
        a, b = cand("prov/abc-6.2-sol", fact=fact, cost=1.0), cand("prov/abc-6.3-sol", fact=fact, cost=2.0)
        self.assertEqual(pick([a, b])[0], "prov/abc-6.3-sol")

    def test_the_newer_one_unusable_lets_the_older_compete_again(self):
        old, new = cand("prov/abc-5.3", cost=1.0), cand("prov/abc-5.4", cost=2.0)
        self.assertEqual(pick([old, new], availability={"prov/abc-5.4": {"reason": "limit", "retry_at": NOW + 99}})[0], "prov/abc-5.3")
        new2 = dict(new, usable=False, reason="not logged in")
        self.assertEqual(pick([old, new2])[0], "prov/abc-5.3")
        self.assertEqual(pick([old, new], avoid=[{"pattern": "5.4"}])[0], "prov/abc-5.3")
        spent = dict(new, plan="flat", allowance_pct_left=0)
        self.assertEqual(pick([old, spent])[0], "prov/abc-5.3")

    def test_a_tried_newer_version_does_not_send_a_retry_back_to_the_older(self):
        old, new = cand("prov/abc-5.3", cost=1.0), cand("prov/abc-5.4", cost=2.0)
        who, r = pick([old, new], exclude=["prov/abc-5.4"])
        self.assertIsNone(who)

    def test_a_newer_version_with_a_thick_bad_record_never_sends_work_back_to_the_older(self):
        old, new, other = cand("prov/abc-5.3", cost=1.0), cand("prov/abc-5.4", cost=2.0), cand("prov/xyz-2.0", cost=3.0, maker="xyz")
        records = attempts("prov/abc-5.4", 10, 1, difficulty=1) + attempts("prov/xyz-2.0", 10, 10, difficulty=1)
        who, r = pick([old, new, other], records)
        self.assertEqual(who, "prov/xyz-2.0")
        who, r = pick([old, new], records)
        self.assertEqual(who, "prov/abc-5.4")  # nobody else: the bad newer model is still not replaced by the older

    def test_the_same_model_through_two_providers_is_one_model(self):
        old_a = cand("prova/abc-5.3", plan="flat", cost=0.0)
        new_a, new_b = cand("prova/abc-5.4", cost=5.0), cand("provb/abc-5.4", cost=2.0)
        who, r = pick([old_a, new_a, new_b])
        self.assertEqual(who, "provb/abc-5.4")  # the existing cost comparison picks the provider
        self.assertEqual(sorted(w for w, why in r["passed_over"] if why.startswith("superseded")), ["prova/abc-5.3"])
        who, _ = pick([old_a, new_a, new_b], availability={"provb": {"reason": "limit", "retry_at": NOW + 9}})
        self.assertEqual(who, "prova/abc-5.4")

    def test_a_bare_host_alias_with_a_recorded_class_is_the_newest(self):
        alias = cand("abc", fact={"class": "standard", "maker": "abc"}, host_native=True, cost=9.0)
        versioned = cand("prov/abc-9.9", cost=0.1)
        self.assertEqual(pick([alias, versioned])[0], "abc")
        bare = cand("abc", host_native=True, cost=9.0)  # class not recorded: no comparison
        self.assertEqual(pick([bare, versioned])[0], "prov/abc-9.9")

    def test_guessed_classes_take_part_unless_the_config_says_only_recorded_ones(self):
        old, new = cand("prov/abc-5.3", cost=1.0), cand("prov/abc-5.4", cost=2.0)
        self.assertEqual(pick([old, new])[0], "prov/abc-5.4")
        self.assertEqual(pick([old, new], opts={"supersede_guessed": False})[0], "prov/abc-5.3")
        fact = {"class": "standard"}
        old_r, new_r = cand("prov/abc-5.3", fact=fact, cost=1.0), cand("prov/abc-5.4", fact=fact, cost=2.0)
        self.assertEqual(pick([old_r, new_r], opts={"supersede_guessed": False})[0], "prov/abc-5.4")

    def test_the_asking_line_is_only_for_a_class_that_could_not_be_read(self):
        a, b = cand("prov/abc-6.2-sol", cost=1.0), cand("prov/abc-6.3-luna", cost=2.0)
        r = pick([a, b])[1]
        self.assertEqual(sorted(r["class_ask"]["classify"]), ["prov/abc-6.2-sol", "prov/abc-6.3-luna"])
        lone = pick([cand("prov/abc-6.2-sol"), cand("prov/xyz-1.0", maker="xyz")])[1]
        self.assertEqual(lone["class_ask"]["classify"], [])  # no sibling of the same maker: it cannot matter
        guessed = pick([cand("prov/abc-5.3"), cand("prov/abc-5.4")])[1]
        self.assertEqual(guessed["class_ask"]["classify"], [])  # read with confidence: no question
        fact = {"class": "sol", "maker": "abc"}
        settled = pick([cand("prov/abc-6.2-sol", fact=fact), cand("prov/abc-6.3-luna", fact=fact)])[1]
        self.assertEqual(settled["class_ask"]["classify"], [])


class SupersessionPropertyTests(unittest.TestCase):
    def fleet(self, rng):
        cands, records, down = [], [], {}
        for maker in rng.sample(["abc", "xyz", "qrs"], rng.randint(1, 3)):
            for cls in rng.sample(["", "-flash", "-mini", "-wonder", "-pro"], rng.randint(1, 3)):
                for ver in rng.sample(["5.3", "5.4", "5.9", "5.10", "6", "5-4-20261101", "5.4-20250101"], rng.randint(1, 4)):
                    for prov in rng.sample(["pa", "pb"], rng.randint(1, 2)):
                        w = "%s/%s%s-%s" % (prov, maker, cls, ver)
                        if cls == "-wonder":
                            w = "%s/%s-wonder-%s" % (prov, maker, ver)
                        if any(c["worker"] == w for c in cands):
                            continue
                        cands.append(cand(w, plan=rng.choice(["flat", "per-use", None]),
                                          cost=rng.choice([None, 0.1, 1.0, 5.0]), maker=maker,
                                          allowance_pct_left=rng.choice([None, 0, 50])))
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
            if not cands:
                continue
            d = rng.choice([1, 2, 3])
            who, r = pick(cands, records, d, availability=down)
            if who is None:
                continue
            chosen = next(c for c in cands if c["worker"] == who)
            lc = chosen["lineage"]
            for c in cands:
                if c is chosen or not self.usable(c, down):
                    continue
                lo = c["lineage"]
                if lo["key"] == lc["key"]:
                    self.assertLessEqual(modelid.compare(lo, lc), 0, (who, c["worker"]))
                    checked += 1
            for w, why in r["passed_over"]:
                if why.startswith("superseded by "):
                    newer = why[len("superseded by "):].split(" ")[0]
                    a = next(c for c in cands if c["worker"] == w)["lineage"]
                    b = next(c for c in cands if c["worker"] == newer)["lineage"]
                    self.assertEqual(a["key"], b["key"], "a model never supersedes one of another maker or class")
                    self.assertGreater(modelid.compare(b, a), 0)
        self.assertGreater(checked, 100)

    def test_adding_a_newer_version_of_the_chosen_model_never_makes_the_choice_an_older_model_of_that_class(self):
        rng = random.Random(77)
        done = 0
        for _ in range(200 * ITERS):
            cands, records, down = self.fleet(rng)
            if not cands:
                continue
            d = rng.choice([1, 2, 3])
            who, _r = pick(cands, records, d, availability=down)
            if who is None:
                continue
            chosen = next(c for c in cands if c["worker"] == who)
            lc = chosen["lineage"]
            if not lc["version"] or lc["date"]:
                continue
            ver = ".".join(str(x) for x in lc["version"][:1] + (lc["version"][1] + 1 if len(lc["version"]) > 1 else 1,))
            prov = who.split("/")[0]
            maker = lc["maker"]
            tail = "" if lc["class"] == "standard" else "-" + lc["class"]
            new_w = "pc/%s%s-%s" % (maker, tail, ver) if lc["line"] == "" else None
            if new_w is None or any(c["worker"] == new_w for c in cands):
                continue
            new = cand(new_w, maker=chosen["maker"], cost=rng.choice([None, 0.1, 5.0]))
            if new["lineage"]["key"] != lc["key"] or modelid.compare(new["lineage"], lc) <= 0:
                continue
            after, _ = pick(cands + [new], records, d, availability=down)
            if after is None:
                continue
            got = next(c for c in cands + [new] if c["worker"] == after)["lineage"]
            if got["key"] == lc["key"]:
                self.assertGreaterEqual(modelid.compare(got, lc), 0, (who, after))
            done += 1
        self.assertGreater(done, 30)

    def test_a_result_read_as_unknown_never_triggers_supersession(self):
        rng = random.Random(5)
        for _ in range(200 * ITERS):
            ids = ["prov/abc-%d.%d-%s" % (rng.randint(1, 9), rng.randint(0, 9), rng.choice(["sol", "luna", "astra"])) for _ in range(rng.randint(2, 5))]
            cands = [cand(w, cost=rng.choice([None, 1.0, 2.0])) for w in dict.fromkeys(ids)]
            who, r = pick(cands)
            self.assertFalse([w for w, why in r["passed_over"] if why.startswith("superseded")])


if __name__ == "__main__":
    unittest.main()
