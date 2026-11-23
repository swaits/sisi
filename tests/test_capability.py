"""Choosing the cheapest worker that is capable enough for a kind and difficulty, from the best evidence
about each worker: judged record (exact, a harder difficulty, all kinds), then benchmark standing against other
workers' standing only, then nothing known (difficulty 1 only). Requirement ids: R-7.2-1, R-7.2-2, R-7.2-3,
R-7.3-3. Property tests are seeded and scale with SISI_TEST_ITERS."""
import json, os, random, unittest
from support import *
from sisi import routing

KIND = "research"


def cand(name, cost=None, standing=None, plan="per-use", allowance=None, maker=None, usable=True):
    w = "t/%s" % name
    return {"worker": w, "tool": "t", "model": name, "maker": maker or name.split("-")[0], "plan": plan,
            "cost": cost, "allowance_pct_left": allowance, "usable": usable, "reason": None,
            "standing": standing, "standing_source": "fixture benchmark", "standing_date": "2000-01-01",
            "aliases": [w, name]}


_n = [0]


def attempts(worker, kind, difficulty, good, bad, kind_name="attempt"):
    rows = []
    for i in range(good + bad):
        _n[0] += 1
        rows.append({"kind": kind_name, "id": "x%d" % _n[0], "type": kind, "difficulty": difficulty,
                     "worker": worker, "outcome": "accepted" if i < good else "rejected", "check": "tests"})
    return rows


def pick(cands, records, difficulty, kind=KIND, **kw):
    return routing.choose(cands, records, {}, kind, difficulty, now=1000.0, **kw)


def chosen(cands, records, difficulty, **kw):
    r = pick(cands, records, difficulty, **kw)
    return r["choice"]["worker"] if r["choice"] else None


class SufficientCapabilityTests(unittest.TestCase):
    def fleet(self):
        # the shape that went wrong: the cheapest worker has the weakest standing
        return [cand("weak-1", cost=0.2, standing=40.0), cand("mid-1", cost=4.0, standing=64.0),
                cand("top-1", cost=8.0, standing=66.0)]

    def test_a_hard_task_goes_to_a_worker_near_the_top_not_the_cheapest(self):
        """R-7.2-2: difficulty 3 needs at least 85 percent of the best standing; the cheapest of those wins."""
        self.assertEqual(chosen(self.fleet(), [], 3), "t/mid-1")
        self.assertEqual(chosen(self.fleet(), [], 1), "t/weak-1")   # no floor at difficulty 1
        self.assertEqual(chosen(self.fleet(), [], 2), "t/weak-1")   # 40 is 60.6 percent of 66, above the 60 percent floor

    def test_the_floor_is_configurable(self):
        got = chosen(self.fleet(), [], 2, floors={"2": 80})
        self.assertEqual(got, "t/mid-1")
        self.assertEqual(chosen(self.fleet(), [], 3, floors={3: 100}), "t/top-1")

    def test_a_flat_plan_with_low_standing_does_not_take_a_hard_task(self):
        cands = [cand("flat-1", standing=30.0, plan="flat", allowance=80), cand("pay-1", cost=5.0, standing=64.0)]
        self.assertEqual(chosen(cands, [], 3), "t/pay-1")
        self.assertEqual(chosen(cands, [], 2), "t/pay-1")           # 30 is under 60 percent of 64
        self.assertEqual(chosen(cands, [], 1), "t/flat-1")          # flat first where nothing is needed

    def test_a_judged_record_proves_capability_whatever_the_standing(self):
        """The record outranks the benchmark: 9 of 10 at this kind and difficulty beats a low standing."""
        cands = self.fleet()
        recs = attempts("t/weak-1", KIND, 3, 9, 1)
        r = pick(cands, recs, 3)
        self.assertEqual(r["choice"]["worker"], "t/weak-1")
        self.assertEqual(r["assessments"]["t/weak-1"]["tier"], "a")

    def test_a_harder_difficulty_of_the_same_kind_proves_an_easier_one(self):
        cands = [cand("a-1", cost=1.0), cand("b-1", cost=2.0)]
        recs = attempts("t/b-1", KIND, 3, 10, 0)
        r = pick(cands, recs, 2)
        self.assertEqual(r["choice"]["worker"], "t/b-1")
        self.assertEqual(r["assessments"]["t/b-1"]["tier"], "b-higher")
        self.assertFalse(r["assessments"]["t/a-1"]["capable"])

    def test_an_easier_difficulty_is_weak_evidence_used_only_as_a_last_resort(self):
        cands = [cand("a-1", cost=1.0), cand("b-1", cost=2.0)]
        recs = attempts("t/b-1", KIND, 1, 10, 0)
        r = pick(cands, recs, 3)
        self.assertEqual(r["choice"]["worker"], "t/b-1")
        self.assertEqual(r["basis"], "weak")
        # with a capable worker on hand, the weak evidence does not count
        cands2 = cands + [cand("c-1", cost=9.0, standing=70.0)]
        r2 = pick(cands2, recs, 3)
        self.assertEqual(r2["choice"]["worker"], "t/c-1")
        self.assertEqual(r2["basis"], "capable")

    def test_the_same_difficulty_across_all_kinds_counts_when_the_kind_has_no_record(self):
        cands = [cand("a-1", cost=1.0), cand("b-1", cost=2.0)]
        recs = attempts("t/b-1", "other-kind", 2, 6, 0) + attempts("t/b-1", "third-kind", 2, 5, 1)
        r = pick(cands, recs, 2)
        self.assertEqual(r["choice"]["worker"], "t/b-1")
        self.assertEqual(r["assessments"]["t/b-1"]["tier"], "b-all")

    def test_unknown_workers_are_an_exploration_at_difficulty_one_only(self):
        cands = [cand("a-1", cost=1.0), cand("b-1", cost=2.0, standing=50.0)]
        r1 = pick(cands, [], 1)
        self.assertEqual(r1["choice"]["worker"], "t/a-1")
        self.assertEqual(r1["assessments"]["t/a-1"]["tier"], "unknown")
        r2 = pick(cands, [], 2)
        self.assertEqual(r2["choice"]["worker"], "t/b-1")
        self.assertFalse(r2["assessments"]["t/a-1"]["capable"])

    def test_all_workers_unknown_still_gives_an_answer_and_says_nothing_is_proven(self):
        cands = [cand("a-1", cost=1.0), cand("b-1", cost=2.0)]
        for d in (2, 3):
            r = pick(cands, [], d)
            self.assertEqual(r["choice"]["worker"], "t/a-1")
            self.assertEqual(r["basis"], "nothing")

    def test_no_capable_worker_falls_back_to_the_strongest_known(self):
        """When the best-standing worker is itself out (a poor record), nobody clears the floor: the strongest known
        usable worker is taken and the result says that nothing is proven."""
        cands = [cand("great-1", cost=1.0, standing=99.0), cand("ok-1", cost=3.0, standing=70.0),
                 cand("low-1", cost=0.5, standing=50.0)]
        recs = attempts("t/great-1", KIND, 3, 3, 7)
        r = pick(cands, recs, 3)
        self.assertEqual(r["choice"]["worker"], "t/ok-1")
        self.assertEqual(r["basis"], "strongest")

    def test_a_great_benchmark_never_rescues_a_thick_bad_record(self):
        cands = [cand("great-1", cost=1.0, standing=99.0), cand("ok-1", cost=30.0, standing=70.0)]
        recs = attempts("t/great-1", KIND, 3, 3, 7)
        self.assertEqual(chosen(cands, recs, 3), "t/ok-1")
        # a bad record at difficulty 3 says nothing about difficulty 1: there the cheaper great-1 is fine
        self.assertEqual(chosen(cands, recs, 1), "t/great-1")

    def test_a_bad_record_at_an_easier_difficulty_also_blocks_the_benchmark(self):
        cands = [cand("great-1", cost=1.0, standing=99.0), cand("ok-1", cost=30.0, standing=98.0)]
        recs = attempts("t/great-1", KIND, 2, 2, 8)
        self.assertEqual(chosen(cands, recs, 3), "t/ok-1")
        self.assertEqual(chosen(cands, recs, 2), "t/ok-1")

    def test_a_thin_record_of_repeated_rejections_cancels_the_prior(self):
        cands = [cand("cheap-1", cost=0.2, standing=40.0), cand("mid-1", cost=4.0, standing=64.0)]
        recs = attempts("t/cheap-1", KIND, 2, 0, 2)
        r = pick(cands, recs, 2)
        self.assertEqual(r["choice"]["worker"], "t/mid-1")
        self.assertTrue(r["assessments"]["t/cheap-1"]["contradicted"])

    def test_every_usable_worker_poor_still_names_the_best_rate(self):
        cands = [cand("a-1", cost=1.0), cand("b-1", cost=2.0)]
        recs = attempts("t/a-1", KIND, 2, 1, 9) + attempts("t/b-1", KIND, 2, 4, 6)
        r = pick(cands, recs, 2)
        self.assertEqual(r["choice"]["worker"], "t/b-1")
        self.assertEqual(r["basis"], "all-bad")

    def test_equal_evidence_and_price_is_stable_and_explained(self):
        cands = [cand("b-1", cost=2.0, standing=60.0), cand("a-1", cost=2.0, standing=60.0)]
        for _ in range(3):
            r = pick(list(reversed(cands)), [], 3)
            self.assertEqual(r["choice"]["worker"], "t/a-1")
        text = " ".join(reason for _w, reason in r["passed_over"])
        self.assertIn("equal on price and load", text)

    def test_a_single_usable_worker_is_recommended_whatever_it_knows(self):
        for d in (1, 2, 3):
            self.assertEqual(chosen([cand("only-1")], [], d), "t/only-1")
            self.assertEqual(chosen([cand("only-1", standing=5.0)], [], d), "t/only-1")
        self.assertEqual(pick([cand("only-1")], [], 3)["basis"], "nothing")

    def test_the_existing_constraints_still_hold(self):
        cands = [cand("a-1", cost=1.0, standing=60.0), cand("b-1", cost=2.0, standing=60.0),
                 cand("c-contributor-1", cost=0.1, standing=60.0), cand("d-1", cost=0.5, standing=60.0, usable=False)]
        r = pick(cands, [], 2, review_of="t/a-1")
        self.assertEqual(r["choice"]["worker"], "t/b-1")                       # another maker reviews
        reasons = dict(r["passed_over"])
        self.assertIn("trains on prompts", reasons["t/c-contributor-1"])
        self.assertIn("t/d-1", reasons)
        avoided = pick(cands, [], 2, avoid=[{"pattern": "a-1", "why": "mine"}])
        self.assertEqual(avoided["choice"]["worker"], "t/b-1")
        preferred = pick(cands, [], 2, prefer=[{"pattern": "b-1"}])
        self.assertEqual(preferred["choice"]["worker"], "t/b-1")
        down = routing.choose(cands, [], {"t": {"retry_at": 5000.0, "reason": "limit"}}, KIND, 2, now=1000.0)
        self.assertIsNone(down["choice"])

    def test_the_two_scales_are_never_compared(self):
        """R-7.2-2: V (standing 60, the best) is cheaper than W (standing 55, and 5 of 5 accepted: a thin record that
        proves nothing). At difficulty 3 both clear the floor on standing and the cheaper, V, wins. A comparison of
        W's accepted rate (100) with a standing would make 100 the 'best' and V (60) incapable."""
        cands = [cand("v-1", cost=1.0, standing=60.0), cand("w-1", cost=5.0, standing=55.0)]
        recs = attempts("t/w-1", KIND, 3, 5, 0)
        r = pick(cands, recs, 3)
        self.assertEqual(r["choice"]["worker"], "t/v-1")
        self.assertEqual(r["best_standing"], 60.0)

    def test_a_standing_scaled_by_any_factor_changes_nothing(self):
        rng = random.Random(7)
        for _ in range(60 * ITERS):
            cands, recs = gen_world(rng)
            for d in (1, 2, 3):
                base = pick(cands, recs, d)
                for k in (0.01, 0.37, 3.0, 40.0):
                    scaled = [dict(c, standing=(c["standing"] * k if c["standing"] is not None else None)) for c in cands]
                    got = pick(scaled, recs, d)
                    self.assertEqual((got["choice"] or {}).get("worker"), (base["choice"] or {}).get("worker"), (d, k))
                    self.assertEqual(got["basis"], base["basis"])


class MeasuredProofBeatsABenchmarkTests(unittest.TestCase):
    """Above difficulty 1 a benchmark standing is a reason to try a worker, not to prefer it to a judged record.
    The grid's case: a cheap worker whose standing is just over the floor, no record; a dearer one with a thick,
    good record for exactly this kind and difficulty. R-7.2-2, R-7.2-3, R-7.3-3."""

    def pair(self):
        # 40 is 60.8 percent of the best usable standing, 65.8: over the difficulty-2 floor of 60
        return [cand("cheap-1", cost=0.2, standing=40.0), cand("proven-1", cost=4.0, standing=65.8)]

    def test_the_proven_worker_takes_ordinary_work_the_cheap_one_takes_routine_work(self):
        recs = attempts("t/proven-1", KIND, 2, 21, 0)
        r2 = pick(self.pair(), recs, 2)
        self.assertEqual(r2["choice"]["worker"], "t/proven-1")
        self.assertEqual(r2["assessments"]["t/proven-1"]["tier"], "a")
        self.assertTrue(r2["assessments"]["t/cheap-1"]["capable"])        # capable by standing, still not preferred
        self.assertEqual(chosen(self.pair(), recs, 1), "t/cheap-1")
        self.assertEqual(chosen(self.pair(), attempts("t/proven-1", KIND, 3, 12, 0), 3), "t/proven-1")

    def test_with_the_proven_worker_unavailable_the_cheap_one_is_taken_on_its_standing(self):
        recs = attempts("t/proven-1", KIND, 2, 21, 0)
        down = {"t/proven-1": {"retry_at": 5000.0, "reason": "limit"}}
        r = routing.choose(self.pair(), recs, down, KIND, 2, now=1000.0)
        self.assertEqual(r["choice"]["worker"], "t/cheap-1")
        self.assertIn("evidence (c)", routing.explain_choice(r, KIND, 2)[1])

    def test_the_explanation_says_why_the_cheaper_benchmark_worker_was_passed_over(self):
        recs = attempts("t/proven-1", KIND, 2, 21, 0)
        r = pick(self.pair(), recs, 2)
        lines = routing.explain_choice(r, KIND, 2)
        self.assertIn("evidence (a)", lines[1])
        self.assertIn("by a judged record", lines[0])
        self.assertTrue([l for l in lines if "cheap-1" in l and "judged record is preferred to a benchmark" in l], lines)

    def test_the_judged_record_across_all_kinds_counts_only_when_nobody_has_evidence_from_the_kind(self):
        cands = [cand("pooled-1", cost=1.0), cand("kind-1", cost=5.0)]
        pooled = attempts("t/pooled-1", "other", 2, 10, 0)
        self.assertEqual(chosen(cands, pooled, 2), "t/pooled-1")          # nobody has the kind: the pooled record counts
        both = pooled + attempts("t/kind-1", KIND, 2, 9, 1)
        r = pick(cands, both, 2)
        self.assertEqual(r["choice"]["worker"], "t/kind-1")               # the kind's own record outranks it
        self.assertEqual(r["assessments"]["t/pooled-1"]["tier"], "b-all")

    def test_a_record_from_a_harder_difficulty_of_the_kind_is_the_kinds_own_evidence(self):
        cands = [cand("cheap-1", cost=0.2, standing=40.0), cand("hard-1", cost=4.0, standing=65.8)]
        recs = attempts("t/hard-1", KIND, 3, 10, 0)
        self.assertEqual(chosen(cands, recs, 2), "t/hard-1")

    def test_nobody_with_a_record_means_the_benchmark_decides_as_before(self):
        self.assertEqual(chosen(self.pair(), [], 2), "t/cheap-1")
        self.assertEqual(chosen(self.pair(), [], 3), "t/proven-1")        # 40 is under 85 percent of 65.8

    def test_a_worker_with_a_judged_record_is_always_chosen_when_one_is_capable(self):
        """With at least one usable worker capable by a judged record at difficulty 2 or 3, the choice has a judged
        record: evidence a or b, from the kind when any usable worker has it."""
        rng = random.Random(31337)
        covered = 0
        for _ in range(400 * ITERS):
            cands, recs = gen_world(rng)
            for d in (2, 3):
                r = pick(cands, recs, d)
                a = r["assessments"]
                same_kind = [w for w in a if a[w]["tier"] in ("a", "b-higher")]
                pooled = [w for w in a if a[w]["tier"] == "b-all"]
                if not (same_kind or pooled):
                    continue
                covered += 1
                self.assertEqual(r["basis"], "capable")
                self.assertIn(a[r["choice"]["worker"]]["tier"], ("a", "b-higher") if same_kind else ("b-all",),
                              (d, a[r["choice"]["worker"]]["tier"]))
        self.assertGreater(covered, 100)

    def test_difficulty_one_is_unchanged_and_the_cheapest_capable_wins_whatever_the_evidence(self):
        rng = random.Random(77)
        for _ in range(200 * ITERS):
            cands, recs = gen_world(rng)
            r = pick(cands, recs, 1)
            if r["basis"] != "capable" or r["explored"]:
                continue
            price = lambda c: (routing._price_tier(c), c["cost"] if c.get("cost") is not None else float("inf"))
            for c in cands:
                if r["assessments"][c["worker"]]["capable"]:
                    self.assertGreaterEqual(price(c), price(r["choice"]))


def gen_world(rng, kinds=("research", "edit")):
    """Generated workers and a judged ledger: prices, plans, standings (or none), cells of every size."""
    cands, recs = [], []
    for i in range(rng.randint(1, 6)):
        flat = rng.random() < 0.2
        c = cand("w%d-%d" % (i, rng.randint(0, 9)), cost=None if flat else rng.choice([None, 0.2, 1.0, 4.0, 8.0, 30.0]),
                 standing=rng.choice([None, None, rng.uniform(10, 100)]), plan="flat" if flat else rng.choice(["per-use", None]),
                 allowance=rng.choice([None, 40, 90]) if flat else None)
        cands.append(c)
        for kind in kinds:
            for d in (1, 2, 3):
                n = rng.choice([0, 0, 2, 3, 8, 8, 12, 30])
                good = rng.randint(0, n)
                recs += attempts(c["worker"], kind, d, good, n - good)
    rng.shuffle(recs)
    return cands, recs


class CapabilityPropertyTests(unittest.TestCase):
    def test_raising_the_difficulty_never_gives_weaker_evidence(self):
        """R-7.2-2, R-7.2-3: for the same data, a worker capable at difficulty d+1 is capable at d, its evidence at d is
        at least as strong, and the worker chosen for a harder task on evidence is capable on the easier one."""
        rng = random.Random(20261123)
        for _ in range(300 * ITERS):
            cands, recs = gen_world(rng)
            runs = {d: pick(cands, recs, d) for d in (1, 2, 3)}
            for d in (1, 2):
                lo, hi = runs[d]["assessments"], runs[d + 1]["assessments"]
                for w in lo:
                    self.assertLessEqual(hi[w]["capable"], lo[w]["capable"], (d, w, lo[w], hi[w]))
                    self.assertGreaterEqual(lo[w]["level"], hi[w]["level"], (d, w, lo[w], hi[w]))
                got = runs[d + 1]["choice"]
                if got is not None and runs[d + 1]["basis"] == "capable":
                    self.assertTrue(lo[got["worker"]]["capable"], (d, got["worker"]))

    def test_a_capable_worker_that_is_as_good_and_cheaper_is_never_passed_over(self):
        """R-7.2-2: the choice is the cheapest of the capable workers that compete (above difficulty 1 those capable
        by a judged record when there are any); a prefer pattern aside, none here."""
        rng = random.Random(4242)
        for _ in range(300 * ITERS):
            cands, recs = gen_world(rng)
            for d in (1, 2, 3):
                r = pick(cands, recs, d)
                if r["choice"] is None or r["basis"] != "capable":
                    continue
                x = r["choice"]
                price = lambda c: (routing._price_tier(c), c["cost"] if c.get("cost") is not None else float("inf"))
                capable = [c for c in cands if r["assessments"][c["worker"]]["capable"]]
                competing, _judged = routing._prefer_judged(capable, r["assessments"], d)
                self.assertIn(x["worker"], [c["worker"] for c in competing])
                for c in competing:
                    if c["worker"] != x["worker"]:
                        self.assertGreaterEqual(price(c), price(x), (d, c["worker"], x["worker"]))

    def test_a_thick_bad_record_is_never_chosen_over_a_usable_worker_without_one(self):
        """R-7.2-3, R-7.3-3."""
        rng = random.Random(99)
        seen = 0
        for _ in range(400 * ITERS):
            cands, recs = gen_world(rng)
            for d in (1, 2, 3):
                r = pick(cands, recs, d)
                if r["choice"] is None:
                    continue
                cell = routing._cell(r["stats"], r["choice"]["worker"], KIND, d)
                if cell["n"] >= routing.MIN_ATTEMPTS and cell["good"] / cell["n"] < routing.MIN_ACCEPTED_RATE:
                    seen += 1
                    self.assertTrue(all(a["bad"] for a in r["assessments"].values()), (d, r["choice"]["worker"]))
        self.assertGreater(seen, 0, "the generator never produced the case it is meant to test")

    def test_the_choice_does_not_depend_on_candidate_order(self):
        rng = random.Random(5)
        for _ in range(120 * ITERS):
            cands, recs = gen_world(rng)
            d = rng.choice([1, 2, 3])
            a = chosen(cands, recs, d)
            b = chosen(list(reversed(cands)), recs, d)
            self.assertEqual(a, b)


def explain(cands, records, difficulty, **kw):
    r = pick(cands, records, difficulty, **kw)
    return r, routing.explain_choice(r, KIND, difficulty)


def line_with(lines, start):
    got = [l for l in lines if l.startswith(start)]
    return got


class ExplainTests(unittest.TestCase):
    """R-7.2-1, R-7.2-2: --explain says which evidence decided, why cheaper workers were not capable enough, and when
    the choice is an exploration or a fallback; one line each, 20 lines at most."""

    def test_the_evidence_for_each_tier_is_one_line_with_its_numbers(self):
        cases = []
        cands = [cand("w-1", cost=1.0)]
        _r, lines = explain(cands, attempts("t/w-1", KIND, 3, 9, 1), 3)
        cases.append((lines, ["evidence (a)", "9 of 10 accepted", "difficulty 3", "90%"]))
        _r, lines = explain(cands, attempts("t/w-1", KIND, 3, 10, 0), 2)
        cases.append((lines, ["evidence (b)", "harder difficulty", "10 of 10", "difficulty 3", "proves difficulty 2"]))
        _r, lines = explain(cands, attempts("t/w-1", "other", 2, 8, 2), 2)
        cases.append((lines, ["evidence (b)", "all kinds", "8 of 10", "difficulty 2"]))
        _r, lines = explain([cand("w-1", cost=1.0, standing=64.0), cand("w-2", cost=5.0, standing=66.0)], [], 3)
        cases.append((lines, ["evidence (c)", "benchmark standing", "64", "fixture benchmark", "2000-01-01", "85%", "66"]))
        _r, lines = explain(cands, [], 1)
        cases.append((lines, ["evidence (d)", "nothing is known", "exploration"]))
        _r, lines = explain(cands, attempts("t/w-1", KIND, 1, 10, 0), 3)
        cases.append((lines, ["evidence (b, weak)", "10 of 10", "easier difficulty 1"]))
        for lines, words in cases:
            ev = line_with(lines, "evidence")
            self.assertEqual(len(ev), 1, lines)
            for w in words:
                self.assertIn(w, ev[0], lines)

    def test_standing_and_accepted_rate_are_named_apart(self):
        _r, a = explain([cand("w-1", cost=1.0)], attempts("t/w-1", KIND, 3, 9, 1), 3)
        _r, c = explain([cand("w-1", cost=1.0, standing=64.0)], [], 3)
        self.assertNotIn("standing", line_with(a, "evidence")[0])
        self.assertNotIn("accepted", line_with(c, "evidence")[0])

    def test_cheaper_workers_that_were_not_capable_are_one_grouped_line_with_a_count(self):
        cands = [cand("c%d-1" % i, cost=0.1 + i / 100, standing=10.0 + i) for i in range(5)]
        cands += [cand("good-1", cost=4.0, standing=64.0), cand("best-1", cost=8.0, standing=66.0)]
        r, lines = explain(cands, [], 3)
        self.assertEqual(r["choice"]["worker"], "t/good-1")
        grp = [l for l in lines if "not capable enough" in l]
        self.assertEqual(len(grp), 1, lines)
        self.assertIn("passed over 5 worker(s)", grp[0])
        self.assertIn("cheaper than the choice", grp[0])
        self.assertIn("56.1", grp[0])             # the standing needed: 85 percent of 66 = 56.1
        self.assertIn("and 2 more", grp[0])      # three example names at most
        self.assertLessEqual(len(lines) + routing.EXPLAIN_TAIL_LINES, routing.MAX_EXPLAIN_LINES)

    def test_a_fallback_says_plainly_that_nothing_is_proven(self):
        cands = [cand("a-1", cost=1.0, standing=99.0), cand("b-1", cost=3.0, standing=70.0)]
        r, lines = explain(cands, attempts("t/a-1", KIND, 3, 2, 8), 3)
        self.assertEqual(r["basis"], "strongest")
        head = lines[0]
        self.assertIn("none is proven capable", head)
        self.assertIn("strongest known", head)
        self.assertEqual(len(line_with(lines, "evidence")), 1)
        _r, cold = explain([cand("a-1"), cand("b-1")], [], 3)
        self.assertIn("none is proven capable", cold[0])
        self.assertIn("nothing is recorded", cold[0] + cold[1])

    def test_an_exploration_is_called_one(self):
        cands = [cand("a-1", cost=5.0, standing=90.0), cand("b-1", cost=5.0, standing=10.0)]
        recs = attempts("t/a-1", "read", 1, 9, 0)
        r = routing.choose(cands, recs, {}, "read", 1, now=1000.0)
        self.assertEqual(r["choice"]["worker"], "t/b-1")
        lines = routing.explain_choice(r, "read", 1)
        self.assertTrue(line_with(lines, "this is an exploration pick"), lines)

    def test_the_explanation_stays_within_twenty_lines_with_many_workers(self):
        rng = random.Random(3)
        for _ in range(80 * ITERS):
            cands = [cand("w%d-%d" % (i, rng.randint(0, 5)), cost=rng.choice([None, 0.1, 2.0]),
                          standing=rng.choice([None, rng.uniform(5, 100)])) for i in range(rng.randint(1, 60))]
            cands = list({c["worker"]: c for c in cands}.values())
            d = rng.choice([1, 2, 3])
            _r, lines = explain(cands, [], d)
            self.assertLessEqual(len(lines) + routing.EXPLAIN_TAIL_LINES, routing.MAX_EXPLAIN_LINES, lines)


class ExplainCliTests(SisiCase):
    def seed_world(self):
        os.makedirs(self.data, exist_ok=True)
        rows = []
        for w, d, good, bad in (("wk-mid", 2, 9, 1), ("wk-weak", 2, 0, 2)):
            for i in range(good + bad):
                rows.append({"kind": "attempt", "id": "%s-%d" % (w, i), "ts": 1760000000 + i, "project": "p", "type": "research",
                             "difficulty": d, "worker": w, "outcome": "accepted" if i < good else "rejected",
                             "check": "tests", "minutes": 1})
        open(os.path.join(self.data, "delegations.jsonl"), "w").write("".join(json.dumps(r) + "\n" for r in rows))
        json.dump({"models": {"wk-weak": {"standing": 40, "source": "fixture board", "date": "2000-01-01"},
                              "wk-mid": {"standing": 64, "source": "fixture board", "date": "2000-01-01"},
                              "wk-top": {"standing": 66, "source": "fixture board", "date": "2000-01-01"}}},
                  open(os.path.join(self.data, "model-strength.json"), "w"))
        json.dump({"models": {"wk-weak": {"cost_per_million_tokens": 0.2, "source": "fixture", "date": "2000-01-01"},
                              "wk-mid": {"cost_per_million_tokens": 4, "source": "fixture", "date": "2000-01-01"},
                              "wk-top": {"cost_per_million_tokens": 8, "source": "fixture", "date": "2000-01-01"}}},
                  open(os.path.join(self.data, "worker-prices.json"), "w"))

    def test_a_hard_task_is_not_given_to_the_cheapest_weak_worker(self):
        """The reported fault: with prices and standings recorded, a hard research task went to the cheapest, weakest
        worker. Now it goes to the cheapest worker near the top, and `--explain` says why."""
        self.seed_world()
        env = dict(PATH="")
        plain = self.sisi("route", "--kind", "research", "--difficulty", "3", env=env)
        self.assertEqual(plain.returncode, 0, plain.stderr)
        self.assertEqual(plain.stdout.splitlines()[0], "wk-mid")
        self.assertLessEqual(len(plain.stdout.splitlines()), 6)
        self.assertNotIn("evidence", plain.stdout)
        ex = self.sisi("route", "--kind", "research", "--difficulty", "3", "--explain", env=env)
        lines = ex.stdout.splitlines()
        self.assertLessEqual(len(lines), 20, ex.stdout)
        self.assertEqual(len([l for l in lines if l.startswith("evidence")]), 1, ex.stdout)
        self.assertIn("evidence (c)", ex.stdout)
        self.assertTrue([l for l in lines if l.startswith("passed over 1 worker(s) (wk-weak") and "not capable enough" in l], ex.stdout)
        easy = self.sisi("route", "--kind", "research", "--difficulty", "1", env=env)
        self.assertEqual(easy.stdout.splitlines()[0], "wk-weak")


def retry(cands, records, difficulty, rejected, rejections, **kw):
    return routing.retry_choice(cands, records, {}, KIND, difficulty, rejected, rejections, now=1000.0, **kw)


class RetryLadderTests(unittest.TestCase):
    """The pure ladder behind `sisi route --retry-of`: the same worker for the first retry, then the cheapest capable
    worker with strictly better evidence, else the strongest known. R-7.2-2, R-7.3-1 (retries cost)."""

    def fleet(self):
        return [cand("r-1", cost=4.0, standing=64.0), cand("s-1", cost=8.0, standing=66.0),
                cand("t-1", cost=6.0, standing=65.0), cand("u-1", cost=0.5, standing=40.0)]

    def test_the_first_retry_goes_back_to_the_same_worker(self):
        r = retry(self.fleet(), [], 2, "t/r-1", 1)
        self.assertEqual((r["choice"]["worker"], r["step"]), ("t/r-1", "same"))

    def test_the_first_retry_moves_on_when_the_worker_is_not_usable(self):
        cands = self.fleet()
        cands[0]["usable"] = False
        r = retry(cands, [], 2, "t/r-1", 1)
        self.assertEqual(r["step"], "better")
        self.assertNotEqual(r["choice"]["worker"], "t/r-1")

    def test_later_retries_take_the_cheapest_capable_worker_with_better_evidence(self):
        r = retry(self.fleet(), [], 2, "t/r-1", 2)
        self.assertEqual((r["choice"]["worker"], r["step"]), ("t/t-1", "better"))   # 65 beats 64; 66 costs more; 40 is weaker
        r3 = retry(self.fleet(), [], 2, "t/t-1", 3)
        self.assertEqual((r3["choice"]["worker"], r3["step"]), ("t/s-1", "better"))

    def test_a_judged_proof_is_better_than_a_benchmark_and_a_benchmark_never_beats_a_proof(self):
        cands = [cand("r-1", cost=4.0, standing=64.0), cand("p-1", cost=9.0, standing=10.0), cand("h-1", cost=5.0, standing=100.0)]
        recs = attempts("t/p-1", KIND, 2, 9, 1)
        self.assertEqual(retry(cands[:2], recs, 2, "t/r-1", 2)["choice"]["worker"], "t/p-1")
        # r-1 has the proof now: h-1's standing 100 is not 'better' than 7 of 10 accepted; the two scales do not meet
        recs2 = attempts("t/r-1", KIND, 2, 7, 3)
        r = retry([c for c in cands if c["worker"] != "t/p-1"], recs2, 2, "t/r-1", 2)
        self.assertEqual((r["choice"]["worker"], r["step"]), ("t/h-1", "strongest"))

    def test_a_higher_accepted_rate_in_the_same_kind_of_evidence_is_better(self):
        cands = [cand("r-1", cost=4.0), cand("a-1", cost=3.0), cand("b-1", cost=2.0), cand("c-1", cost=9.0)]
        recs = (attempts("t/r-1", KIND, 2, 8, 2) + attempts("t/a-1", KIND, 2, 8, 2)     # equal: not better
                + attempts("t/b-1", KIND, 2, 7, 3) + attempts("t/c-1", KIND, 2, 10, 0))   # lower, higher
        r = retry(cands, recs, 2, "t/r-1", 2)
        self.assertEqual((r["choice"]["worker"], r["step"]), ("t/c-1", "better"))

    def test_when_nobody_has_better_evidence_the_strongest_known_other_is_taken(self):
        cands = [cand("top-1", cost=9.0, standing=90.0), cand("a-1", cost=2.0, standing=70.0), cand("b-1", cost=1.0, standing=60.0)]
        r = retry(cands, [], 3, "t/top-1", 2)
        self.assertEqual((r["choice"]["worker"], r["step"]), ("t/a-1", "strongest"))

    def test_the_rejected_worker_alone_is_returned_as_the_only_option(self):
        r = retry([cand("r-1", cost=4.0, standing=64.0)], [], 2, "t/r-1", 3)
        self.assertEqual((r["choice"]["worker"], r["step"]), ("t/r-1", "only"))
        self.assertIsNone(retry([cand("r-1", usable=False)], [], 2, "t/r-1", 3)["choice"])

    def test_a_worker_with_a_poor_record_is_never_on_the_ladder(self):
        cands = [cand("r-1", cost=4.0, standing=60.0), cand("bad-1", cost=1.0, standing=99.0), cand("ok-1", cost=9.0, standing=61.0)]
        recs = attempts("t/bad-1", KIND, 2, 2, 8)
        r = retry(cands, recs, 2, "t/r-1", 2)
        self.assertEqual(r["choice"]["worker"], "t/ok-1")

    def test_the_ladder_keeps_the_users_constraints_and_other_workers_that_are_down(self):
        cands = self.fleet()
        r = routing.retry_choice(cands, [], {"t": {"retry_at": 5000.0, "reason": "limit"}}, KIND, 2, "t/r-1", 2, now=1000.0)
        self.assertIsNone(r["choice"])
        avoided = retry(cands, [], 2, "t/r-1", 2, avoid=[{"pattern": "t-1", "why": "mine"}])
        self.assertEqual(avoided["choice"]["worker"], "t/s-1")
        tried = retry(cands, [], 2, "t/r-1", 2, exclude=["t/t-1"])
        self.assertEqual(tried["choice"]["worker"], "t/s-1")

    def test_the_ladder_over_generated_worlds(self):
        """The step names what happened: better means capable, strictly stronger, and the cheapest such; strongest
        means no capable worker was stronger and the pick has the greatest strength among the rest."""
        rng = random.Random(8128)
        steps = set()
        for _ in range(300 * ITERS):
            cands, recs = gen_world(rng)
            d = rng.choice([1, 2, 3])
            rejected = rng.choice(cands)["worker"]
            n = rng.choice([1, 2, 3])
            r = retry(cands, recs, d, rejected, n)
            steps.add(r["step"])
            if r["choice"] is None:
                continue
            a = r["assessments"]
            w = r["choice"]["worker"]
            self.assertFalse(a[w]["bad"] and r["step"] != "only", (w, r["step"]))
            if r["step"] == "same":
                self.assertEqual((w, n), (rejected, 1))
                self.assertFalse(a[w]["bad"])
                continue
            if r["step"] == "only":
                self.assertEqual(w, rejected)
                continue
            self.assertNotEqual(w, rejected)
            rejected_strength = routing.strength(a[rejected])
            stronger = [c for c in cands if a[c["worker"]]["capable"] and c["worker"] != rejected
                        and routing.strength(a[c["worker"]]) > rejected_strength]
            stronger = routing._prefer_judged(stronger, a, d)[0]
            if r["step"] == "better":
                self.assertTrue(a[w]["capable"] and routing.strength(a[w]) > rejected_strength)
                price = lambda c: (routing._price_tier(c), c["cost"] if c.get("cost") is not None else float("inf"))
                self.assertTrue(all(price(c) >= price(r["choice"]) for c in stronger))
            else:
                self.assertEqual(stronger, [])
                others = [x for x in a if x != rejected and not a[x]["bad"]]
                self.assertEqual(routing.strength(a[w]), max(routing.strength(a[x]) for x in others))
        self.assertTrue({"same", "better", "strongest"} <= steps, steps)


if __name__ == "__main__":
    unittest.main()
