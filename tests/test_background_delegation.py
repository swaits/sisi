"""A background delegation is not finished when its launch call returns (R-7.1-1 the main agent owns and judges the
outcome, so it is asked to judge a result only once there is one; R-7.2-3 the routing record must not hold a
run's time as 0.01 minutes). The launch result and the later completion message are what the host's delegation tool
really sends: `{"taskId", "childThreadId", "status": "starting"|"running", "workState"}` and a message naming the task
with `[completed]`, `[failed]` or `[interrupted]`."""
import json, unittest
from support import *
import test_meter as TM
from sisi import orchestration, workers

TOOL = "mcp__t3-code__delegate_task"
INP = {"title": "Fix greeting parser", "task": "Outcome: x\nAcceptance: y\nFiles you may change: none",
       "target": {"model": "alpha-small"}}
LAUNCH = {"taskId": "tk-77", "childThreadId": "th-88", "status": "running", "workState": "working"}


class Background(TM.MeterBase):
    def launch(self, result=LAUNCH, use_id="u1", wrap=False):
        self.prompt()
        denied, text, _ = self.pre(TOOL, INP, tool_use_id=use_id)
        self.assertFalse(denied, text)
        resp = [{"type": "text", "text": json.dumps(result)}] if wrap else result
        self.post(TOOL, INP, response=resp, tool_use_id=use_id)
        return self.runs()[0]

    def runs(self):
        return workers.merged_runs()

    def stop(self):
        r = self.sisi("gate", "--tool", "claude-code", stdin=json.dumps(
            {"session_id": self.sid, "cwd": self.proj, "hook_event_name": "Stop", "stop_hook_active": False}))
        return json.loads(r.stdout) if r.stdout.strip() else {}

    def age(self, seconds):
        with orchestration.Meter(self.sid) as m:
            for e in m["pending"].values():
                e["t0"] -= seconds

    def notice(self, text):
        return self.prompt(text, route=False)

    def test_a_running_launch_stays_pending_and_the_gate_says_nothing(self):
        for wrap in (False, True):
            with self.subTest(wrapped=wrap):
                self.setUp()
                run = self.launch(wrap=wrap)
                self.assertEqual(run["status"], "pending")
                self.assertEqual(workers.unjudged_runs(), [])
                self.assertNotIn("not judged", self.stop().get("reason", ""))

    def test_the_completion_message_finishes_it_with_the_real_duration_and_the_gate_asks_once(self):
        run = self.launch()
        self.age(120)
        self.notice("[completed] Task tk-77 (Fix greeting parser) finished: the parser now greets.")
        run = self.runs()[0]
        self.assertEqual(run["status"], "waiting")
        self.assertAlmostEqual(run["minutes"], 2.0, delta=0.1)
        first = self.stop()
        self.assertEqual(first.get("decision"), "block")
        self.assertIn("not judged yet", first["reason"])
        self.assertIn(run["id"], first["reason"])
        self.assertNotEqual(self.stop().get("decision"), "block")        # once

    def test_the_message_may_name_the_task_by_its_title_instead_of_an_id(self):
        self.launch()
        self.notice("[completed] \"Fix greeting parser\" is done.")
        self.assertEqual(self.runs()[0]["status"], "waiting")

    def test_a_failed_message_with_a_quota_error_marks_the_provider_down_and_hands_over_the_fallback(self):
        self.launch()
        r = self.notice("[failed] Task tk-77: 429 rate limit exceeded, quota exhausted for alpha-small")
        self.assertIn("unavailable", r.stdout)
        self.assertEqual(self.runs()[0]["status"], "superseded")
        self.assertEqual(workers.unjudged_runs(), [])
        self.assertIn("alpha-small", workers.read_availability())

    def test_a_failed_message_that_is_not_unavailability_awaits_judgement(self):
        self.launch()
        self.notice("[failed] Task tk-77: the tests it was asked to make pass still fail")
        self.assertEqual(self.runs()[0]["status"], "failed")
        self.assertEqual([r["id"] for r in workers.unjudged_runs()], [self.runs()[0]["id"]])

    def test_an_interrupted_message_supersedes_it_and_it_is_never_asked_for(self):
        self.launch()
        self.notice("[interrupted] Task tk-77 was stopped.")
        self.assertEqual(self.runs()[0]["status"], "superseded")
        self.assertNotIn("not judged", self.stop().get("reason", ""))

    def test_a_synchronous_delegation_carrying_the_report_is_finished_at_once(self):
        run = self.launch(result={"status": "completed", "taskId": "tk-1", "result": "the parser now greets by name"})
        self.assertEqual(run["status"], "waiting")
        self.assertEqual(self.stop().get("decision"), "block")

    def test_a_listed_tool_with_no_launch_data_and_a_bare_fast_result_is_a_launch(self):
        self.prompt()
        self.pre("Agent", {"description": "d", "prompt": "Outcome: x\nAcceptance: y", "model": "alpha-small"}, tool_use_id="a1")
        self.post("Agent", {"description": "d"}, response={"agentRef": "z9", "status": "queued"}, tool_use_id="a1")
        self.assertEqual(self.runs()[0]["status"], "pending")

    def test_an_unrelated_prompt_is_not_taken_for_a_notice(self):
        self.launch()
        self.prompt("please also fix the [failed] tests in other_module")
        self.assertEqual(self.runs()[0]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
