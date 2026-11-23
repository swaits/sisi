"""Evaluation harness tests. Each test names the requirements it proves (docs/spec/requirements.json)."""
import json, os, stat, subprocess, sys, time, unittest
from support import *

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_cases")


def git(cwd, *args):
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t"] + list(args),
                       cwd=cwd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise AssertionError("git %s failed: %s" % (args, r.stderr))
    return r.stdout.strip()


def make_repo(case):
    """A temp repo: start commit has value.txt=broken, fix commit has value.txt=fixed."""
    d = os.path.join(case.tmp, "repo")
    os.makedirs(d, exist_ok=True)
    git(d, "init", "-q")
    open(os.path.join(d, "value.txt"), "w").write("broken\n")
    git(d, "add", "-A"); git(d, "commit", "-q", "-m", "start")
    start = git(d, "rev-parse", "HEAD")
    open(os.path.join(d, "value.txt"), "w").write("fixed\n")
    git(d, "add", "-A"); git(d, "commit", "-q", "-m", "fix")
    fix = git(d, "rev-parse", "HEAD")
    return d, start, fix


def case_dict(cid, kind, repo, start, fix, split="dev", cmd="grep -qx fixed value.txt", tags=("synthetic",)):
    return {"id": cid, "kind": kind, "source": {"unit": "u-" + cid, "learning": ""},
            "project": {"repo": repo, "start_commit": start, "fix_commit": fix},
            "request": "make value.txt contain fixed",
            "checks": [{"id": "value", "cmd": cmd, "expect": {"exit": 0}}],
            "tags": list(tags), "split": split, "added": "2026-01-01"}


def fixture_case(case, name):
    repo, start, fix = case.repo, case.start, case.fix
    text = open(os.path.join(FIXTURES, name)).read()
    return json.loads(text.replace("@REPO@", repo).replace("@START@", start).replace("@FIX@", fix))


def fake_worker(request, cwd, policy_dir=None, case=None, **kw):
    """Deterministic fake worker: does the fix unless the policy text says BAD."""
    bad = False
    p = os.path.join(policy_dir, "generated", "core.md") if policy_dir else None
    if p and os.path.exists(p):
        bad = "BAD" in open(p).read()
    open(os.path.join(cwd, "value.txt"), "w").write("wrong\n" if bad else "fixed\n")
    return {"worker": "alpha-1", "minutes": 1.0, "minutes_class": "measured",
            "tokens": 100, "tokens_class": "measured", "cost": 3, "cost_class": "measured",
            "text": "done"}


class EvalCase(SisiCase):
    def setUp(self):
        super().setUp()
        self.repo, self.start, self.fix = make_repo(self)
        self.store = self.data
        from sisi import evaluate
        self.ev = evaluate

    def save(self, *cases):
        for c in cases:
            self.ev.save_case(c, store_dir=self.store)

    def worktrees(self):
        return git(self.repo, "worktree", "list", "--porcelain")


class CheckReplayTests(EvalCase):
    def test_check_validated_only_when_it_fails_then_passes(self):
        """R-11.5-6, R-20.3-2: validated needs red at start_commit and green at fix_commit."""
        c = fixture_case(self, "check-case.json")
        out = self.ev.validate_check(c, store_dir=self.store)
        self.assertEqual(out["outcome"], "validated", out)

    def test_check_passing_at_both_is_failed_to_fail(self):
        """R-11.5-6: a check that passes at the start commit proves nothing."""
        c = case_dict("pass-both", "check", self.repo, self.start, self.fix, cmd="test -f value.txt")
        out = self.ev.validate_check(c, store_dir=self.store)
        self.assertEqual(out["outcome"], "failed-to-fail", out)

    def test_check_failing_at_both_is_failed_to_pass(self):
        """R-11.5-6: a check still red at the fix commit is a failed case, not validated."""
        c = case_dict("fail-both", "check", self.repo, self.start, self.fix, cmd="grep -qx never value.txt")
        out = self.ev.validate_check(c, store_dir=self.store)
        self.assertEqual(out["outcome"], "failed-to-pass", out)

    def test_counterexample_check_must_still_pass(self):
        """R-11.6-3, R-20.3-2: a counterexample is validated by passing at both commits."""
        c = case_dict("counter", "check", self.repo, self.start, self.fix,
                      split="counterexample", cmd="test -f value.txt")
        out = self.ev.validate_check(c, store_dir=self.store)
        self.assertEqual(out["outcome"], "validated", out)
        bad = dict(c, id="counter-bad", checks=[{"id": "value", "cmd": "grep -qx never value.txt", "expect": {"exit": 0}}])
        self.assertNotEqual(self.ev.validate_check(bad, store_dir=self.store)["outcome"], "validated")

    def test_missing_commit_and_gone_repo_are_not_run_with_reason(self):
        """R-13.4-2: missing evidence is not-run with a reason, never a pass."""
        c = case_dict("gone-commit", "check", self.repo, "0" * 40, self.fix)
        out = self.ev.validate_check(c, store_dir=self.store)
        self.assertEqual(out["outcome"], "not-run", out)
        self.assertIn("commit", out["reason"])
        c2 = case_dict("gone-repo", "check", os.path.join(self.tmp, "nope"), self.start, self.fix)
        out2 = self.ev.validate_check(c2, store_dir=self.store)
        self.assertEqual(out2["outcome"], "not-run", out2)
        self.assertIn("repositor", out2["reason"])

    def test_replay_is_isolated_and_cleans_up_on_timeout(self):
        """R-11.6-3: replay never touches the user's tree; worktrees go even on timeout."""
        before = open(os.path.join(self.repo, "value.txt")).read()
        before_wt = self.worktrees()
        slow = case_dict("slow", "check", self.repo, self.start, self.fix, cmd="sleep 5")
        out = self.ev.validate_check(slow, store_dir=self.store, timeout_s=1)
        self.assertEqual(out["outcome"], "not-run", out)
        self.assertIn("timed out", out["reason"])
        self.assertEqual(open(os.path.join(self.repo, "value.txt")).read(), before)
        self.assertEqual(self.worktrees(), before_wt)
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")

    def test_replay_cleans_up_on_failure(self):
        """R-11.6-3: a failing run also removes its temporary worktree."""
        before_wt = self.worktrees()
        c = case_dict("fail-clean", "check", self.repo, self.start, self.fix, cmd="exit 3")
        self.ev.validate_check(c, store_dir=self.store)
        self.assertEqual(self.worktrees(), before_wt)


class TaskReplayTests(EvalCase):
    def test_task_replay_with_fake_worker_is_deterministic(self):
        """R-13.3-2, R-13.4-1, R-20.3-2: same case+policy+fake worker, same outcome; values carry a class."""
        c = fixture_case(self, "task-case.json")
        self.save(c)
        r1 = self.ev.run_case(c, store_dir=self.store, worker_runner=fake_worker)
        r2 = self.ev.run_case(c, store_dir=self.store, worker_runner=fake_worker)
        self.assertEqual(r1["outcome"], "passed", r1)
        self.assertEqual(r1["outcome"], r2["outcome"])
        self.assertEqual(r1["worker"], "alpha-1")
        self.assertEqual(r1["tokens_class"], "measured")
        self.assertEqual(r1["cost_class"], "measured")
        self.assertTrue(r1["policy"])
        self.assertEqual(git(self.repo, "status", "--porcelain"), "", "task replay leaked into the user's tree")

    def test_task_without_worker_is_not_run(self):
        """R-13.4-2: a task case with no way to run a worker is not-run, never passed."""
        c = fixture_case(self, "task-case.json")
        saved = os.environ.pop("SISI_EVAL_WORKER_CMD", None)
        try:
            r = self.ev.run_case(c, store_dir=self.store, worker_runner=lambda **kw: None)
        finally:
            if saved:
                os.environ["SISI_EVAL_WORKER_CMD"] = saved
        self.assertEqual(r["outcome"], "not-run", r)


class CaptureAndImportTests(EvalCase):
    def test_capture_case_from_closed_unit_is_deterministic_and_idempotent(self):
        """R-20.3-1, R-19-10: benchmark cases grow from real units, with a stable split."""
        unit = {"id": "unit-1", "goal": "make value.txt contain fixed", "project": self.repo,
                "start_commit": self.start, "fix_commit": self.fix,
                "checks": [{"id": "value", "cmd": "grep -qx fixed value.txt", "expect": {"exit": 0}}],
                "risk": {"profile": "isolated"}}
        c1 = self.ev.capture_case(unit, store_dir=self.store)
        self.assertIsNotNone(c1)
        c2 = self.ev.capture_case(unit, store_dir=self.store)
        self.assertEqual(c1["id"], c2["id"])
        self.assertIn(c1["split"], ("dev", "holdout"))
        self.assertEqual(len(self.ev.load_cases(store_dir=self.store)), 1)
        self.assertIsNone(self.ev.capture_case({"id": "empty"}, store_dir=self.store))

    def test_harvested_task_becomes_case_with_deterministic_split(self):
        """R-20.3-1, R-11.6-3: harvested tasks keep the id-hash dev/holdout split."""
        from sisi import taskset
        row = {"id": "h-abc123", "kind": "human", "grade": "A", "split": taskset.split_of("h-abc123"),
               "repo_root": self.repo, "start_commit": self.start, "test_cmd": "grep -qx fixed value.txt",
               "request": "make value.txt contain fixed", "session_id": "s1"}
        c = taskset.to_benchmark_case(row, [{"sha": self.fix}])
        self.assertIsNotNone(c)
        self.assertEqual(c["split"], taskset.split_of("h-abc123"))
        self.assertEqual(c["project"]["fix_commit"], self.fix)
        self.assertIsNone(taskset.to_benchmark_case(dict(row, grade="C"), [{"sha": self.fix}]))
        self.assertIsNone(taskset.to_benchmark_case(dict(row, test_cmd=None), [{"sha": self.fix}]))


class HoldoutDisciplineTests(EvalCase):
    def test_dev_selection_never_includes_holdout(self):
        """R-11.6-3, R-20.3-2: a tuning (dev) run must not touch held-out cases."""
        dev = case_dict("dev-case", "check", self.repo, self.start, self.fix, split="dev")
        hold = case_dict("hold-case", "check", self.repo, self.start, self.fix, split="holdout")
        self.save(dev, hold)
        picked = self.ev.select_cases(self.ev.load_cases(store_dir=self.store), split="dev", purpose="tuning")
        self.assertEqual([c["id"] for c in picked], ["dev-case"])
        with self.assertRaises(ValueError):
            self.ev.select_cases(self.ev.load_cases(store_dir=self.store), split="holdout", purpose="tuning")
        with self.assertRaises(ValueError):
            self.ev.select_cases(self.ev.load_cases(store_dir=self.store), split="holdout", purpose="shadow")

    def test_shadow_never_runs_holdout_even_when_sample_names_it(self):
        """R-11.6-3, R-11.6-4: shadow runs dev+counterexample; a named holdout is excluded."""
        dev = case_dict("dev-case", "check", self.repo, self.start, self.fix, split="dev")
        hold = case_dict("hold-case", "check", self.repo, self.start, self.fix, split="holdout")
        counter = case_dict("counter", "check", self.repo, self.start, self.fix,
                            split="counterexample", cmd="test -f value.txt")
        self.save(dev, hold, counter)
        cand = os.path.join(self.tmp, "cand")
        os.makedirs(os.path.join(cand, "generated"))
        open(os.path.join(cand, "generated", "core.md"), "w").write("candidate rules\n")
        comp = self.ev.compare_for_candidate(cand, sample=["dev-case", "hold-case"], store_dir=self.store)
        self.assertIn("hold-case", comp["excluded_holdout"], comp)
        ran = {r["case"] for r in self.ev.read_results(store_dir=self.store)}
        self.assertNotIn("hold-case", ran)
        self.assertIn("counter", ran)


class ShadowTests(EvalCase):
    def test_shadow_compares_current_and_candidate_policies(self):
        """R-11.6-4, R-11.5-6: a candidate store is compared on the same cases before promotion."""
        c = fixture_case(self, "task-case.json")
        self.save(c)
        cand = os.path.join(self.tmp, "cand")
        os.makedirs(os.path.join(cand, "generated"))
        open(os.path.join(cand, "generated", "core.md"), "w").write("BAD rules\n")
        comp = self.ev.compare_for_candidate(cand, sample=5, store_dir=self.store,
                                             worker_runner=fake_worker, tasks_limit=5)
        self.assertEqual(comp["common"], ["synth-task"], comp)
        self.assertIn("synth-task", comp["regressions"], comp)
        self.assertIn("not an improvement", comp["verdict"])


class CompareTests(EvalCase):
    def _run_results(self, policy, outcomes, minutes, cost):
        for cid, outcome in outcomes.items():
            self.ev.append_result({"id": "r-%s-%s" % (policy, cid), "kind": "run", "case": cid,
                                   "case_kind": "task", "split": "dev", "tags": ["synthetic"],
                                   "policy": policy, "worker": "alpha-1", "outcome": outcome,
                                   "minutes": minutes, "minutes_class": "measured",
                                   "tokens": 10, "tokens_class": "measured",
                                   "cost": cost, "cost_class": "measured" if cost is not None else "unavailable",
                                   "ts": "2026-01-01T00:00:00Z"}, store_dir=self.store)

    def test_comparison_reports_missing_and_refuses_thin_claims(self):
        """R-13.5-1, R-13.4-2: one-sided cases are reported; under five common cases is 'too few'."""
        for i in range(3):
            self.save(case_dict("c%d" % i, "task", self.repo, self.start, self.fix))
        self._run_results("v1", {"c0": "passed", "c1": "passed", "c2": "passed"}, 5, 10)
        self._run_results("v2", {"c0": "passed", "c1": "passed"}, 1, 1)
        comp = self.ev.compare_versions("v1", "v2", store_dir=self.store)
        self.assertEqual(comp["only_a"], ["c2"], comp)
        self.assertTrue(comp["too_few"], comp)
        self.assertIn("too few", self.ev.format_comparison(comp))

    def test_faster_but_regressing_is_not_an_improvement(self):
        """R-13.5-1: faster/cheaper while failing cases the baseline passed is not an improvement."""
        outs_a = {"c%d" % i: "passed" for i in range(6)}
        outs_b = dict(outs_a, c0="failed")
        for i in range(6):
            self.save(case_dict("c%d" % i, "task", self.repo, self.start, self.fix))
        self._run_results("v1", outs_a, 10, 10)
        self._run_results("v2", outs_b, 1, 1)
        comp = self.ev.compare_versions("v1", "v2", store_dir=self.store)
        self.assertIn("not an improvement", comp["verdict"], comp)
        self.assertIn("c0", comp["regressions"])
        text = self.ev.format_comparison(comp)
        self.assertIn("not an improvement", text)
        self.assertIn("median", text)

    def test_unavailable_cost_is_never_zero_or_cheaper(self):
        """R-13.4-1, R-13.4-2, R-13.5-1: unknown cost cannot make a candidate look cheaper."""
        outs = {"c%d" % i: "passed" for i in range(6)}
        for i in range(6):
            self.save(case_dict("c%d" % i, "task", self.repo, self.start, self.fix))
        self._run_results("v1", outs, 10, 10)
        self._run_results("v2", outs, 10, None)
        comp = self.ev.compare_versions("v1", "v2", store_dir=self.store)
        self.assertIsNone(comp["metrics"]["v2"]["cost_median"], comp)
        self.assertNotIn("cheaper", comp["verdict"])
        self.assertIn("unknown", self.ev.format_comparison(comp))


class JudgeTests(EvalCase):
    def _task_result(self):
        c = fixture_case(self, "task-case.json")
        self.save(c)
        return self.ev.run_case(c, store_dir=self.store, worker_runner=fake_worker)

    def test_independent_judge_from_another_maker_is_recorded(self):
        """R-13.3-4, R-20.3-3: a different maker's verdict is stored with judged_by."""
        r = self._task_result()
        def judge(prompt, case=None, result=None, **kw):
            return {"worker": "beta-1", "items": [{"id": "value", "verdict": "met", "reason": "check passed"}]}
        j = self.ev.judge_result(r["id"], store_dir=self.store, judge_runner=judge)
        self.assertEqual(j["judged_by"], "beta-1", j)
        merged = [x for x in self.ev.read_results(store_dir=self.store) if x["id"] == r["id"]][0]
        self.assertEqual(merged["judged_by"], "beta-1")

    def test_same_maker_judge_is_never_independent(self):
        """R-13.3-6: the worker's own maker cannot be recorded as an independent judge."""
        r = self._task_result()
        def judge(prompt, case=None, result=None, **kw):
            return {"worker": "alpha-2", "items": [{"id": "value", "verdict": "met", "reason": "ok"}]}
        j = self.ev.judge_result(r["id"], store_dir=self.store, judge_runner=judge)
        self.assertNotEqual(j.get("outcome"), "judged", j)
        merged = [x for x in self.ev.read_results(store_dir=self.store) if x["id"] == r["id"]][0]
        self.assertNotIn("judged_by", merged)


class CliTests(EvalCase):
    def worker_script(self):
        p = os.path.join(self.tmp, "fake-worker.sh")
        open(p, "w").write("#!/bin/sh\nprintf 'fixed\\n' > value.txt\necho done\n")
        os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
        return p

    def test_eval_add_list_run_compare_status_via_cli(self):
        """R-19-10, R-20.3-1, R-20.3-2: the eval command surface works end to end."""
        f = os.path.join(self.tmp, "case.json")
        json.dump(case_dict("cli-check", "check", self.repo, self.start, self.fix), open(f, "w"))
        r = self.sisi("eval", "add", f)
        self.assertEqual(r.returncode, 0, r.stderr)
        json.dump(case_dict("cli-task", "task", self.repo, self.start, self.fix), open(f, "w"))
        self.assertEqual(self.sisi("eval", "add", f).returncode, 0)
        r = self.sisi("eval", "list")
        self.assertIn("cli-check", r.stdout)
        # run with no arguments: check cases only, no worker needed
        r = self.sisi("eval", "run", "--policy", "v1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ran = {x["case"] for x in self.ev.read_results(store_dir=self.store)}
        self.assertEqual(ran, {"cli-check"}, r.stdout)
        r = self.sisi("eval", "run", "--tasks", "1", "--policy", "v1",
                      "--worker-cmd", self.worker_script(), "--worker", "alpha-1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("estimated cost: unknown", r.stdout)
        r = self.sisi("eval", "run", "--policy", "v2")
        self.assertEqual(r.returncode, 0, r.stdout)
        r = self.sisi("eval", "compare", "v1", "v2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("pass rate", r.stdout)
        r = self.sisi("eval", "status")
        self.assertIn("cli-check", r.stdout + "cli-check")  # status summarises, may not name cases
        self.assertIn("check", r.stdout)

    def test_eval_list_and_status_stay_short_for_twenty_cases(self):
        """R-19-10: no eval output exceeds 40 lines for 20 cases."""
        for i in range(20):
            self.save(case_dict("bulk-%02d" % i, "check", self.repo, self.start, self.fix))
        for args in (("eval", "list"), ("eval", "status")):
            r = self.sisi(*args)
            self.assertLessEqual(len(r.stdout.splitlines()), 40, r.stdout)

    def test_task_cost_cap_from_config_refuses_known_overrun(self):
        """R-13.4-2: a configured per-invocation cap refuses a known over-running estimate."""
        self.save(case_dict("cli-task", "task", self.repo, self.start, self.fix))
        self.ev.append_result({"id": "r-old", "kind": "run", "case": "cli-task", "case_kind": "task",
                               "split": "dev", "tags": [], "policy": "v0", "worker": "alpha-1",
                               "outcome": "passed", "minutes": 1, "minutes_class": "measured",
                               "tokens": 1, "tokens_class": "measured", "cost": 50,
                               "cost_class": "measured", "ts": "2026-01-01T00:00:00Z"}, store_dir=self.store)
        os.makedirs(self.store, exist_ok=True)
        json.dump({"eval": {"max_cost_per_run": 10}}, open(os.path.join(self.store, "config.json"), "w"))
        r = self.sisi("eval", "run", "--tasks", "1", "--worker-cmd", self.worker_script())
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("cap", r.stdout + r.stderr)

    def test_folded_tasks_and_checks_commands(self):
        """R-19-10: the former hidden tasks/checks commands live under sisi eval now."""
        r = self.sisi("tasks", "list")
        self.assertNotEqual(r.returncode, 64, r.stdout + r.stderr)
        r = self.sisi("checks")
        self.assertNotEqual(r.returncode, 64, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
