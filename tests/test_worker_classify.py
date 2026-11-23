"""`sisi workers classify`: the question for a cheap, fast worker and the validated recording of its answer.
Invented ids. Requirement ids: R-7.2-1, R-7.2-3."""
import json, os, unittest
from support import *
from test_worker_models import ModelCase

MODELS = ("abc-old", "abc-new", "xyz-one")
ANSWER = {"workers": {"muse/abc-old": {"maker": "abc", "class": "standard", "released": "2026-03"},
                      "muse/abc-new": {"maker": "abc", "class": "standard", "released": "2026-09-01"},
                      "muse/xyz-one": {"maker": "xyz", "class": "unknown", "released": "unknown"}},
          "classes": {"abc": ["standard", "flash"]}}


class ClassifyCase(ModelCase):
    def setUp(self):
        super().setUp()
        self.seed([("muse/abc-old", 12, 12), ("muse/abc-new", 3, 3), ("muse/xyz-one", 12, 12)], difficulty=2)
        self.file = os.path.join(self.tmp, "answer.json")

    def classify(self, *args):
        return self.sisi("workers", "classify", *args, env=self.env(MODELS))

    def answer(self, obj, wrap=lambda t: t):
        open(self.file, "w").write(wrap(obj if isinstance(obj, str) else json.dumps(obj)))
        return self.classify("--record", self.file, "--by", "cheap-worker-x")

    def stored(self):
        p = os.path.join(self.data, "worker-models.json")
        return json.load(open(p)) if os.path.exists(p) else {}


class QuestionTests(ClassifyCase):
    def test_it_prints_a_short_instruction_and_the_ids_that_have_no_classification(self):
        out = self.classify().stdout.splitlines()
        ids = [l for l in out if l.startswith("muse/")]
        self.assertEqual(sorted(ids), ["muse/abc-new", "muse/abc-old", "muse/xyz-one"])
        self.assertLessEqual(len(out) - len(ids), 15, out)
        text = "\n".join(out)
        for must in ("maker", "class", "release date", "unknown", "JSON"):
            self.assertIn(must, text)

    def test_classified_workers_are_not_asked_again_and_nothing_is_left_to_ask_at_the_end(self):
        self.record("muse/abc-old", "standard", "2026-03-01", models=MODELS)
        ids = [l for l in self.classify().stdout.splitlines() if l.startswith("muse/")]
        self.assertEqual(sorted(ids), ["muse/abc-new", "muse/xyz-one"])
        self.assertEqual(self.answer({"workers": {w: ANSWER["workers"][w] for w in ids}}).returncode, 0)
        self.assertIn("every routable worker is classified", self.classify().stdout)


class RecordTests(ClassifyCase):
    def test_a_valid_answer_is_stored_with_the_classifying_worker_as_the_source(self):
        r = self.answer(ANSWER)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("3 classification(s) (1 unknown) and 1 class order(s)", r.stdout)
        data = self.stored()
        self.assertEqual(data["models"]["muse/abc-new"]["source"], "classified by cheap-worker-x")
        self.assertEqual((data["models"]["muse/abc-old"]["class"], data["models"]["muse/abc-old"]["released"]), ("standard", "2026-03"))
        self.assertEqual(data["classes"]["abc"]["order"], ["standard", "flash"])
        self.assertEqual(data["models"]["muse/xyz-one"]["class"], "unknown")
        self.assertNotIn("released", data["models"]["muse/xyz-one"])

    def test_an_answer_wrapped_in_prose_or_a_code_fence_is_read(self):
        r = self.answer(ANSWER, wrap=lambda t: "Here you go:\n```json\n%s\n```\nDone." % t)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_an_id_that_was_not_asked_about_is_refused_and_nothing_is_recorded(self):
        bad = json.loads(json.dumps(ANSWER))
        bad["workers"]["muse/never-heard-of-it"] = {"maker": "abc", "class": "standard", "released": "2026-01"}
        r = self.answer(bad)
        self.assertEqual(r.returncode, 1)
        self.assertIn("muse/never-heard-of-it", r.stderr)
        self.assertEqual(self.stored(), {})
        self.record("muse/abc-old", "standard", models=MODELS)    # an id that is already classified is not asked about either
        r = self.answer({"workers": {"muse/abc-old": ANSWER["workers"]["muse/abc-old"]}})
        self.assertEqual(r.returncode, 1)

    def test_malformed_answers_are_refused_and_nothing_is_recorded(self):
        for bad in ("not json at all", "[1, 2]", json.dumps({"workers": []}),
                    json.dumps({"workers": {"muse/abc-old": {"maker": "abc", "class": "so l", "released": "2026-01"}}}),
                    json.dumps({"workers": {"muse/abc-old": {"maker": "abc", "class": "x", "released": "last year"}}}),
                    json.dumps({"workers": {"muse/abc-old": "standard"}})):
            self.assertEqual(self.answer(bad).returncode, 1, bad)
        self.assertEqual(self.stored(), {})
        self.assertEqual(self.classify("--record", os.path.join(self.tmp, "missing.json")).returncode, 1)

    def test_a_recorded_class_order_is_never_overwritten_by_an_answer(self):
        self.sisi("workers", "classes", "abc", "flash", "standard", "--source", "owner", env=self.env(MODELS))
        self.answer(ANSWER)
        self.assertEqual(self.stored()["classes"]["abc"]["order"], ["flash", "standard"])

    def test_an_unknown_answer_changes_nothing_in_routing_and_is_not_asked_again(self):
        def route():
            return self.sisi("route", "--kind", "impl", "--difficulty", "2", "--explain", env=self.env(MODELS)).stdout
        before = route()
        self.answer({"workers": {w: {"maker": "unknown", "class": "unknown", "released": "unknown"} for w in ANSWER["workers"]}})
        after = route()
        strip = lambda t: [l for l in t.splitlines() if not l.startswith("sisi:")]
        self.assertEqual(strip(before), strip(after))
        self.assertIn("every routable worker is classified", self.classify().stdout)
        self.assertNotIn("sisi: no maker", after)

    def test_after_recording_the_newest_version_wins(self):
        self.answer(ANSWER)
        r = self.sisi("route", "--kind", "impl", "--difficulty", "2", "--explain", env=self.env(MODELS))
        self.assertEqual(r.stdout.splitlines()[0], "muse/abc-new", r.stdout)
        self.assertIn("superseded by muse/abc-new", r.stdout)
        self.assertIn("the record of its predecessor muse/abc-old", r.stdout)


class AskingLineTests(ClassifyCase):
    def test_route_asks_only_when_an_unclassified_worker_is_in_the_running(self):
        r = self.sisi("route", "--kind", "impl", "--difficulty", "2", env=self.env(MODELS))
        self.assertEqual(len([l for l in r.stdout.splitlines() if "sisi workers classify" in l]), 1, r.stdout)
        self.assertLessEqual(len(r.stdout.splitlines()), 7)
        self.answer(ANSWER)
        r = self.sisi("route", "--kind", "impl", "--difficulty", "2", env=self.env(MODELS))
        self.assertNotIn("sisi workers classify", r.stdout)

    def test_session_start_names_the_unclassified_workers_in_its_one_facts_line(self):
        from sisi import workers
        r = self.sisi("tick", stdin=json.dumps({"session_id": "s-cls", "cwd": self.proj, "source": "startup", "model": "mystery-9"}),
                      env=self.env(MODELS))
        lines = [l for l in r.stdout.splitlines() if "worker facts" in l or "sisi workers classify" in l]
        self.assertEqual(len(lines), 1, r.stdout)


if __name__ == "__main__":
    unittest.main()
