"""Two scales kept apart (benchmark standing, measured accepted rate) and prices as published (input and output,
blended for ranking). Requirement ids: R-7.2-1, R-7.2-2, R-7.2-3, R-7.3-1. Workers are host-native (bare ids from
the ledger) so no command-line tool is needed."""
import json, os, time, unittest
from support import *


class FactsCase(SisiCase):
    def seed(self, workers, kind="read", difficulty=1, n=1):
        os.makedirs(self.data, exist_ok=True)
        with open(os.path.join(self.data, "delegations.jsonl"), "a") as f:
            for w in workers:
                for i in range(n):
                    f.write(json.dumps({"kind": "attempt", "id": "%s-%d-%s-%d" % (w, i, kind, difficulty), "ts": round(time.time()) - i,
                                        "project": "p", "type": kind, "difficulty": difficulty, "worker": w,
                                        "outcome": "accepted", "check": "tests", "minutes": 1}) + "\n")

    def run_sisi(self, *args):
        r = self.sisi(*args, env=dict(PATH=""))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def stored(self, name):
        return json.load(open(os.path.join(self.data, name)))


class StandingFieldTests(FactsCase):
    LEGACY = {"models": {"wk-a": {"score": 64.5, "source": "fixture board https://example.test/x read 2000-01-01", "date": "2000-01-01"},
                         "wk-b": {"score": 40, "source": "fixture board", "date": "2000-01-02", "maker": "mk"}}}

    def write_legacy(self):
        os.makedirs(self.data, exist_ok=True)
        json.dump(self.LEGACY, open(os.path.join(self.data, "model-strength.json"), "w"))

    def test_existing_score_facts_move_to_standing_with_their_sources(self):
        """R-7.2-3: `sisi workers` renames each stored score to standing, keeping source, date and maker; repeating it
        changes nothing."""
        self.seed(["wk-a", "wk-b"])
        self.write_legacy()
        self.run_sisi("workers")
        got = self.stored("model-strength.json")["models"]
        self.assertEqual(got["wk-a"], {"standing": 64.5, "source": self.LEGACY["models"]["wk-a"]["source"], "date": "2000-01-01"})
        self.assertEqual(got["wk-b"], {"standing": 40, "source": "fixture board", "date": "2000-01-02", "maker": "mk"})
        before = open(os.path.join(self.data, "model-strength.json")).read()
        self.run_sisi("workers")
        self.assertEqual(open(os.path.join(self.data, "model-strength.json")).read(), before)

    def test_routing_reads_an_unmigrated_score_fact(self):
        """Nothing is lost if `sisi route` runs before the migration: the old field is read as standing."""
        self.seed(["wk-a", "wk-b"])
        self.write_legacy()
        self.run_sisi("workers", "fact", "wk-a", "--price", "9", "--source", "fixture")
        self.run_sisi("workers", "fact", "wk-b", "--price", "1", "--source", "fixture")
        # restore the legacy file: fact above may have migrated it
        self.write_legacy()
        r = self.run_sisi("route", "--kind", "read", "--difficulty", "3", "--explain")
        self.assertEqual(r.stdout.splitlines()[0], "wk-a")          # 40 is under 85 percent of 64.5
        self.assertIn("benchmark standing", r.stdout)

    def test_fact_standing_and_the_old_score_flag_both_store_standing(self):
        """R-7.2-3: the stored fact has its own name; --score stays as an alias."""
        self.run_sisi("workers", "fact", "wk-a", "--standing", "70", "--source", "fixture board")
        self.run_sisi("workers", "fact", "wk-b", "--score", "55", "--source", "fixture board")
        got = self.stored("model-strength.json")["models"]
        self.assertEqual(got["wk-a"]["standing"], 70)
        self.assertEqual(got["wk-b"]["standing"], 55)
        self.assertNotIn("score", got["wk-a"])
        self.assertNotIn("score", got["wk-b"])
        bad = self.sisi("workers", "fact", "wk-a", "--standing", "101", "--source", "x", env=dict(PATH=""))
        self.assertNotEqual(bad.returncode, 0)

    def test_workers_shows_standing_and_accepted_rate_under_their_own_names(self):
        self.seed(["wk-a"], kind="read", difficulty=1, n=9)
        self.run_sisi("workers", "fact", "wk-a", "--standing", "64.5", "--source", "fixture board", "--date", "2000-01-01")
        out = self.run_sisi("workers").stdout
        self.assertIn("benchmark standing 64.5", out)
        self.assertIn("fixture board", out)
        self.assertIn("Accepted rate", out)
        self.assertNotIn("score", out.lower().replace("scorecard", ""))

    def test_the_session_line_compares_standing_with_standing_only(self):
        """A worker measured at 100 percent accepted with a low standing is not 'among the strongest' on the strength
        of that rate; a worker with a record but no standing has no standing to compare."""
        from sisi import routing, workers
        cands = [{"worker": "wk-a", "model": "wk-a", "standing": 40.0, "aliases": ["wk-a"]},
                 {"worker": "wk-b", "model": "wk-b", "standing": 60.0, "aliases": ["wk-b"]},
                 {"worker": "wk-c", "model": "wk-c", "standing": None, "aliases": ["wk-c"]}]
        recs = [{"kind": "attempt", "id": "r%d" % i, "type": "read", "difficulty": 1, "worker": w, "outcome": "accepted"}
                for w in ("wk-a", "wk-c") for i in range(20)]
        os.makedirs(self.data, exist_ok=True)
        json.dump({"models": {"wk-a": {"standing": 40, "source": "s"}, "wk-b": {"standing": 60, "source": "s"}}},
                  open(os.path.join(self.data, "model-strength.json"), "w"))
        got = workers.strength_scores(cands)
        self.assertEqual({w: s for w, (s, _how) in got.items()}, {"wk-a": 40.0, "wk-b": 60.0})
        self.assertIn("benchmark standing", got["wk-a"][1])


class PriceTests(FactsCase):
    def setUp(self):
        super().setUp()
        self.seed(["wk-a", "wk-b"])

    def route(self, difficulty="1"):
        return self.run_sisi("route", "--kind", "read", "--difficulty", difficulty, "--explain").stdout

    def test_input_and_output_prices_are_stored_as_published(self):
        """R-7.3-1."""
        self.run_sisi("workers", "fact", "wk-a", "--price-in", "1", "--price-out", "9", "--source", "fixture price list")
        e = self.stored("worker-prices.json")["models"]["wk-a"]
        self.assertEqual((e["price_in"], e["price_out"], e["source"]), (1, 9, "fixture price list"))
        self.assertNotIn("cost_per_million_tokens", e)
        bad = self.sisi("workers", "fact", "wk-a", "--price-in", "1", "--source", "x", env=dict(PATH=""))
        self.assertNotEqual(bad.returncode, 0)                       # both or neither
        both = self.sisi("workers", "fact", "wk-a", "--price", "2", "--price-in", "1", "--price-out", "9", "--source", "x", env=dict(PATH=""))
        self.assertNotEqual(both.returncode, 0)

    def test_a_single_blended_price_still_works_and_replaces_an_input_output_pair(self):
        self.run_sisi("workers", "fact", "wk-a", "--price-in", "1", "--price-out", "9", "--source", "s")
        self.run_sisi("workers", "fact", "wk-a", "--price", "2", "--source", "s")
        e = self.stored("worker-prices.json")["models"]["wk-a"]
        self.assertEqual(e["cost_per_million_tokens"], 2)
        self.assertNotIn("price_in", e)

    def test_ranking_uses_the_blend_three_input_to_one_output(self):
        """wk-a: 1 in, 9 out blends to 3 at 3:1; wk-b: a single blended 3.5. wk-a is cheaper by the default ratio."""
        self.run_sisi("workers", "fact", "wk-a", "--price-in", "1", "--price-out", "9", "--source", "s")
        self.run_sisi("workers", "fact", "wk-b", "--price", "3.5", "--source", "s")
        self.assertEqual(self.route().splitlines()[0], "wk-a")

    def test_the_blend_ratio_is_configurable(self):
        """At 1:1 wk-a blends to 5, dearer than wk-b's 3.5."""
        self.run_sisi("workers", "fact", "wk-a", "--price-in", "1", "--price-out", "9", "--source", "s")
        self.run_sisi("workers", "fact", "wk-b", "--price", "3.5", "--source", "s")
        json.dump({"route": {"price_blend_input_parts": 1}}, open(os.path.join(self.data, "config.json"), "w"))
        self.assertEqual(self.route().splitlines()[0], "wk-b")

    def test_workers_shows_both_prices_and_the_blend(self):
        self.run_sisi("workers", "fact", "wk-a", "--price-in", "2", "--price-out", "10", "--source", "fixture price list")
        out = self.run_sisi("workers").stdout
        self.assertIn("wk-a", out)
        self.assertIn("2 in", out)
        self.assertIn("10 out", out)
        self.assertIn("blended 4", out)

    def test_estimated_cost_uses_the_blend(self):
        from sisi import workers
        self.assertEqual(workers.estimate_cost(2000000, {"price_in": 1, "price_out": 9}), 6.0)
        self.assertEqual(workers.estimate_cost(2000000, {"cost_per_million_tokens": 2}), 4.0)
        self.assertEqual(workers.estimate_cost(2000000, {"cost": 3}), 6.0)
        self.assertIsNone(workers.estimate_cost(2000000, {"price_in": 1}))


if __name__ == "__main__":
    unittest.main()
