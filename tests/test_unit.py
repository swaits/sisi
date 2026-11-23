"""The work-unit record (SPEC 10), telemetry and the scorecard (SPEC 6.1, 13), `sisi status`, and
scratch pruning (docs/target.md sections 2, 4, 6)."""
import json, os, subprocess, time, unittest
from unittest import mock
from support import *
from sisi import contract as C, harvest, scorecard, store, unit as U, workers

SCORE_DIMENSIONS = ("intent_fulfilment", "correctness_and_assurance", "delivery_velocity", "resource_efficiency",
                    "parallelism", "human_experience", "lifecycle_quality", "organizational_improvement")


def real(id, cmd, **kw):
    return dict(check(id, cmd), **kw)


class UnitCase(SisiCase):
    def setUp(self):
        super().setUp()
        self.git_init()
        self.contract_path = os.path.join(self.proj, ".sisi", "contract.json")

    def start(self, checks=None, **fields):
        r = self.sisi("contract", "init", "--goal", "make the thing")
        self.assertEqual(r.returncode, 0, r.stdout)
        c = C.load(self.contract_path)
        c["checks"] = checks or [real("works", "test -f done.txt")]
        c.update(fields)
        C.save(self.contract_path, c)
        return c

    def finish_green(self):
        open(os.path.join(self.proj, "done.txt"), "w").write("x")
        r = self.sisi("verify")
        self.assertEqual(r.returncode, 0, r.stdout)

    def archive(self, uid):
        return json.load(open(os.path.join(self.proj, ".sisi", "units", "%s.json" % uid)))

    def commit_all(self, msg="c"):
        subprocess.run(["git", "add", "-A"], cwd=self.proj, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg], cwd=self.proj, check=True)


class RecordTests(UnitCase):
    def test_close_archives_all_fourteen_items(self):
        """R-10.2-1, R-10.2-2, R-10.2-3, R-10.2-4, R-10.2-5, R-10.2-6, R-10.2-7, R-10.2-8, R-10.2-9,
        R-10.2-10, R-10.2-11, R-10.2-12, R-10.2-13, R-10.2-14, R-10.2-15: the archived record carries
        every item of SPEC 10.2, and a summary line goes to the user store."""
        self.start(parent="request-9", scope={"in": ["app"], "out": ["docs"]}, plan=["write it", "check it"],
                   requirements=[{"id": "q1", "kind": "explicit", "text": "it works", "decision": "now", "check": "works"}],
                   risk={"profile": "isolated"}, limitations=["only tested here"],
                   deferred=[{"what": "perf run", "why": "slow", "safe_because": "no hot path"}])
        self.finish_green()
        r = self.sisi("unit", "close")
        self.assertEqual(r.returncode, 0, r.stdout)
        rec = self.archive("proj")
        for key in ("id", "parent", "goal", "scope", "requirements", "checks", "invariants", "risk", "plan",
                    "workers", "models", "budgets", "started", "ended", "telemetry", "changed_artifacts",
                    "verification", "deferred", "limitations", "delivery_status", "scorecard", "retro_findings",
                    "learning_ids", "policy_version", "start_commit", "closing_commit"):
            self.assertIn(key, rec, key)
        self.assertEqual(rec["parent"], "request-9")
        self.assertEqual(rec["risk"]["declared"], "isolated")
        self.assertIn("floor", rec["risk"])
        self.assertTrue(rec["policy_version"] and rec["start_commit"])
        self.assertEqual(rec["closing_commit"], rec["start_commit"])  # nothing committed in this unit
        self.assertEqual(rec["delivery_status"], "delivered-with-deferred")  # the contract defers something
        self.assertEqual(set(rec["scorecard"]), set(SCORE_DIMENSIONS))
        lines = store.read("units")
        self.assertEqual(len(lines), 1)
        for key in ("id", "project", "closed_at", "risk", "delivery_status", "scorecard"):
            self.assertIn(key, lines[0], key)

    def test_policy_version_is_stable_and_follows_the_policies(self):
        """R-10.2-6: the hash does not depend on the project's path and changes when its risk table does."""
        c = {"id": "x"}
        a = U.policy_version(self.proj, c)
        self.assertEqual(a, U.policy_version(self.proj, c))
        os.makedirs(os.path.join(self.proj, ".sisi"), exist_ok=True)
        with open(os.path.join(self.proj, ".sisi", "risk.json"), "w") as f:
            json.dump({"patterns": []}, f)
        self.assertNotEqual(a, U.policy_version(self.proj, c))
        other = os.path.join(self.tmp, "elsewhere")
        os.makedirs(other)
        self.assertEqual(U.policy_version(other, c), a)

    def test_start_and_closing_commits_and_changed_artifacts(self):
        """R-10.2-10: the start commit, the closing commit and the changed files come from git."""
        self.start()
        base = json.load(open(self.contract_path))["base_head"]
        open(os.path.join(self.proj, "done.txt"), "w").write("x\n")
        self.commit_all("work")
        self.assertEqual(self.sisi("verify").returncode, 0)
        self.sisi("unit", "close")
        rec = self.archive("proj")
        self.assertEqual(rec["start_commit"], base)
        self.assertNotEqual(rec["closing_commit"], base)
        self.assertIn("done.txt", rec["changed_artifacts"]["files"])
        self.assertNotIn(".sisi/units/proj.json", rec["changed_artifacts"]["files"])

    def test_risk_floor_is_stored_beside_the_declared_profile(self):
        """R-10.2-6: the floor comes from the changed paths; the declared profile is kept as declared."""
        self.start(risk={"profile": "trivial", "why": "docs"})
        os.makedirs(os.path.join(self.proj, "auth"))
        open(os.path.join(self.proj, "auth", "password_reset.py"), "w").write("secret = 1\n")
        open(os.path.join(self.proj, "done.txt"), "w").write("x")
        self.assertEqual(self.sisi("verify").returncode, 0)
        self.sisi("unit", "close")
        risk = self.archive("proj")["risk"]
        self.assertEqual(risk["declared"], "trivial")
        self.assertEqual(risk["floor"]["class"], "measured")
        self.assertNotEqual(risk["floor"]["value"], "trivial")  # authorization paths raise the floor

    def test_findings_and_delegations_come_from_their_stores(self):
        """R-10.2-7, R-10.2-15: the record holds the retro findings recorded for the unit and the
        delegations the ledger has for the project in its window."""
        self.start()
        self.finish_green()
        r = self.sisi("retro", "--finding", "the check failed once because done.txt did not exist yet",
                      "--cause", "the file was created after the first run, not before", "--impact", "time",
                      "--disposition", "record", "--limits", "only for tasks that create files")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        now = time.time()
        for i, (start, minutes) in enumerate(((now - 600, 8), (now - 500, 5))):
            workers.append_record({"kind": "attempt", "id": "d%d" % i, "ts": int(now), "project": "proj",
                                   "type": "impl", "difficulty": 1, "worker": "w", "outcome": "accepted",
                                   "check": "tests", "minutes": minutes, "started": start, "ended": start + minutes * 60})
        workers.append_record({"kind": "attempt", "id": "z", "ts": int(now), "project": "elsewhere", "worker": "w"})
        self.sisi("unit", "close")
        rec = self.archive("proj")
        self.assertEqual(len(rec["retro_findings"]), 1)
        self.assertEqual(rec["telemetry"]["retro_findings"], {"value": 1, "class": "measured"})
        self.assertEqual(len(rec["workers"]), 2)
        par = rec["scorecard"]["parallelism"]
        self.assertEqual(par["delegations"]["value"], 2)
        self.assertEqual(par["overlapped_delegations"]["value"], 1)  # the two ran at the same time
        self.assertEqual(par["worker_minutes"]["class"], "estimated")

    def test_the_closed_unit_is_offered_to_the_evaluation_harness(self):
        """R-13.3-3: a close calls the harness's capture, and a failure there never stops the close."""
        self.start()
        self.finish_green()
        with mock.patch("sisi.evaluate.capture_case") as cap:
            self.assertEqual(self.sisi("unit", "close").returncode, 0)
        cap.assert_called_once()
        view = cap.call_args[0][0]
        self.assertEqual((view["id"], view["delivery_status"]), ("proj", "delivered"))
        self.assertTrue(view["start_commit"])
        self.sisi("contract", "init")
        self.finish_green_again()
        with mock.patch("sisi.evaluate.capture_case", side_effect=RuntimeError("harness down")):
            self.assertEqual(self.sisi("unit", "close").returncode, 0)
        self.assertEqual({r["id"] for r in store.read("units")}, {"proj", "proj-2"})

    def finish_green_again(self):
        c = C.load(self.contract_path)
        c["checks"] = [real("again", "test -f done.txt")]
        C.save(self.contract_path, c)
        self.assertEqual(self.sisi("verify").returncode, 0)

    def test_a_real_benchmark_case_is_stored_for_a_repository_unit(self):
        """R-13.3-3: a unit with a start commit and a command check becomes a stored case."""
        from sisi import evaluate
        self.start()
        self.finish_green()
        self.sisi("unit", "close")
        self.assertIsNotNone(evaluate.get_case("case-proj"))


class DeliveryStatusTests(UnitCase):
    def test_deferred_and_human_checks_close_as_delivered_with_deferred(self):
        """R-10.3-4, R-10.3-5: a check that needs a person is not-run (needs human) and does not
        block; the unit says so in its delivery status and lists it."""
        self.start(checks=[real("works", "test -f done.txt"), human("eyes", 5)])
        self.finish_green()
        self.sisi("unit", "close")
        rec = self.archive("proj")
        self.assertEqual(rec["delivery_status"], "delivered-with-deferred")
        self.assertEqual(rec["deferred_checks"], ["eyes"])

    def test_a_failing_check_refuses_a_close_as_delivered(self):
        """R-10.3-4: required verification must have passed."""
        self.start()
        r = self.sisi("unit", "close")
        self.assertEqual(r.returncode, 1)
        self.assertIn("cannot close as delivered", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.proj, ".sisi", "units")))
        self.assertEqual(store.read("units"), [])

    def test_gate_release_after_send_backs_closes_as_unverified(self):
        """R-10.3-5: a unit the gate released with failures standing is `unverified`."""
        self.start()
        self.sisi("verify")
        store.append("results", {"ts": store.now(), "contract": "proj", "project": self.proj, "check": "gate",
                                 "item": "gate", "status": "unverified", "duration_s": 0.0})
        self.assertEqual(self.sisi("unit", "close").returncode, 0)
        self.assertEqual(self.archive("proj")["delivery_status"], "unverified")

    def test_abandon_records_the_reason_and_needs_one(self):
        """R-10.3-8: a unit may be stopped; the disposition and reason are recorded."""
        self.start()
        self.assertEqual(self.sisi("unit", "close", "--abandon").returncode, 1)
        self.assertEqual(self.sisi("unit", "close", "--abandon", "premise disproven").returncode, 0)
        rec = self.archive("proj")
        self.assertEqual((rec["delivery_status"], rec["abandon_reason"]), ("abandoned", "premise disproven"))

    def test_only_the_five_delivery_statuses_exist(self):
        """R-10.2-13."""
        self.assertEqual(set(U.DELIVERY_STATUSES),
                         {"delivered", "delivered-with-deferred", "deviation", "unverified", "abandoned"})


class NeverLostTests(UnitCase):
    def test_contract_init_refuses_an_open_unit_and_replaces_a_closed_one(self):
        """R-10.2-1, R-10.3-1: `sisi contract init` on an open unit refuses and names the abandon
        command; on a closed unit it starts a new one and the old record stays."""
        self.start()
        before = open(self.contract_path).read()
        r = self.sisi("contract", "init")
        self.assertEqual(r.returncode, 1)
        self.assertIn('sisi unit close --abandon "<reason>"', r.stdout)
        self.assertEqual(open(self.contract_path).read(), before)
        self.finish_green()
        self.sisi("unit", "close")
        old = open(os.path.join(self.proj, ".sisi", "units", "proj.json"), "rb").read()
        self.assertEqual(self.sisi("contract", "init").returncode, 0)
        c = C.load(self.contract_path)
        self.assertEqual((c["id"], c["status"]), ("proj-2", "open"))
        self.assertEqual(open(os.path.join(self.proj, ".sisi", "units", "proj.json"), "rb").read(), old)

    def test_closing_twice_changes_nothing(self):
        """R-10.2-1: a record is never overwritten or duplicated."""
        self.start()
        self.finish_green()
        self.sisi("unit", "close")
        p = os.path.join(self.proj, ".sisi", "units", "proj.json")
        old, lines = open(p, "rb").read(), open(os.path.join(self.data, "units.jsonl")).read()
        r = self.sisi("unit", "close")
        self.assertEqual(r.returncode, 0)
        self.assertIn("already closed", r.stdout)
        self.assertEqual(open(p, "rb").read(), old)
        self.assertEqual(open(os.path.join(self.data, "units.jsonl")).read(), lines)

    def test_abandoning_then_starting_again_keeps_every_record(self):
        """R-10.2-1."""
        for n in range(3):
            self.start()
            self.assertEqual(self.sisi("unit", "close", "--abandon", "try %d" % n).returncode, 0)
        names = sorted(os.listdir(os.path.join(self.proj, ".sisi", "units")))
        self.assertEqual(names, ["proj-2.json", "proj-3.json", "proj.json"])
        self.assertEqual(len(store.read("units")), 3)

    def test_a_crash_between_archive_and_reset_loses_nothing_and_converges(self):
        """R-10.2-1: the archive written, the summary line and the contract reset not: closing again
        keeps the archive byte for byte, adds the missing summary once and marks the contract closed."""
        c = self.start()
        self.finish_green()
        c = C.load(self.contract_path)
        rec = U.build_record(c, self.proj, "delivered", time.time())
        path, created = U.archive_record(rec, self.proj)
        self.assertTrue(created)
        before = open(path, "rb").read()
        self.assertEqual(store.read("units"), [])
        self.assertEqual(self.sisi("contract", "init").returncode, 1)  # still open: refused
        self.assertEqual(self.sisi("unit", "close").returncode, 0)
        self.assertEqual(open(path, "rb").read(), before)
        self.assertEqual(len(store.read("units")), 1)
        self.assertEqual(C.load(self.contract_path)["status"], "closed")
        self.sisi("unit", "close")
        self.assertEqual(len(store.read("units")), 1)

    def test_an_archive_that_belongs_to_another_unit_is_never_overwritten(self):
        """R-10.2-1: a hand-made id collision moves the new unit to a fresh id."""
        self.start()
        self.finish_green()
        os.makedirs(os.path.join(self.proj, ".sisi", "units"))
        p = os.path.join(self.proj, ".sisi", "units", "proj.json")
        with open(p, "w") as f:
            json.dump({"id": "proj", "started": "2001-01-01T00:00:00Z", "project": self.proj}, f)
        before = open(p, "rb").read()
        r = self.sisi("unit", "close")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(open(p, "rb").read(), before)
        self.assertTrue(os.path.exists(os.path.join(self.proj, ".sisi", "units", "proj-2.json")))

    def test_an_interrupted_write_leaves_no_partial_archive(self):
        """R-10.2-1: the archive appears whole or not at all."""
        self.start()
        self.finish_green()
        with mock.patch("os.fsync", side_effect=OSError("disk gone")):
            with self.assertRaises(OSError):
                U.archive_record({"id": "proj"}, self.proj)
        self.assertEqual([n for n in os.listdir(os.path.join(self.proj, ".sisi", "units")) if n == "proj.json"], [])

    def test_show_and_list(self):
        """R-10.2-1: `sisi unit show [ID]` and `sisi unit list`."""
        self.start()
        self.assertIn('"id": "proj"', self.sisi("unit", "show").stdout)  # the open unit
        self.assertIn("open", self.sisi("unit", "list").stdout)
        self.finish_green()
        self.sisi("unit", "close")
        self.assertEqual(json.loads(self.sisi("unit", "show", "proj").stdout)["delivery_status"], "delivered")
        self.assertIn("delivered", self.sisi("unit", "list").stdout)
        self.assertEqual(self.sisi("unit", "show", "nope").returncode, 1)


class PauseTests(UnitCase):
    def test_pause_lets_the_turn_end_and_a_change_ends_the_wait(self):
        """R-6.1-5: a pause is recorded, the gate makes no demands while nothing changes, a new change
        ends the wait, and the wait is telemetry."""
        self.start()
        self.assertEqual(self.sisi("unit", "pause", "").returncode, 1)
        self.assertEqual(self.sisi("unit", "pause", "the owner's decision").returncode, 0)
        c = C.load(self.contract_path)
        self.assertEqual(c["status"], "paused")
        self.assertEqual(c["pauses"][0]["what"], "the owner's decision")
        stop = json.dumps({"session_id": "p1", "cwd": self.proj, "hook_event_name": "Stop", "stop_hook_active": False})
        self.sisi("tick", stdin=json.dumps({"session_id": "p1", "cwd": self.proj, "hook_event_name": "SessionStart"}))
        open(os.path.join(self.proj, "new.txt"), "w").write("x")  # a change after the pause
        self.assertIn("block", self.sisi("gate", stdin=stop).stdout)
        self.assertEqual(C.load(self.contract_path)["status"], "open")  # the wait ended
        self.assertTrue(C.load(self.contract_path)["pauses"][0]["until"])
        self.finish_green()
        self.sisi("unit", "close")
        wait = self.archive("proj")["telemetry"]["time_in_waits_s"]
        self.assertEqual(wait["class"], "measured")

    def test_a_paused_unit_with_no_change_passes_silently(self):
        """R-6.1-5."""
        self.start()
        self.sisi("unit", "pause", "waiting for a review")
        stop = json.dumps({"session_id": "p2", "cwd": self.proj, "hook_event_name": "Stop", "stop_hook_active": False})
        self.sisi("tick", stdin=json.dumps({"session_id": "p2", "cwd": self.proj, "hook_event_name": "SessionStart"}))
        r = self.sisi("gate", stdin=stop)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))


class TelemetryHonestyTests(UnitCase):
    def transcript(self, with_usage, model="model-one"):
        now = store.now()
        assistant = {"model": model, "content": [{"type": "tool_use", "name": "AskUserQuestion", "input": {}}]}
        if with_usage:
            assistant["usage"] = {"input_tokens": 1000, "output_tokens": 500}
        lines = [{"type": "user", "timestamp": now, "message": {"role": "user", "content": "please build the thing"}},
                 {"type": "assistant", "timestamp": now, "message": assistant},
                 {"type": "user", "timestamp": now, "message": {"role": "user", "content": "no, that is wrong"}}]
        tp = os.path.join(self.tmp, "t.jsonl")
        with open(tp, "w") as f:
            f.write("\n".join(json.dumps(x) for x in lines) + "\n")
        store.save_session("s-tel", {"cwd": self.proj, "transcript_path": tp, "started": store.now()})
        return tp

    def close_and_load(self):
        self.finish_green()
        self.assertEqual(self.sisi("unit", "close").returncode, 0)
        return self.archive("proj")["telemetry"]

    def test_without_a_transcript_nothing_is_measured_and_nothing_is_zero(self):
        """R-13.4-1, R-13.4-2: no transcript: tokens, cost, messages and dialogs are unavailable, with
        no value, never 0 and never measured."""
        self.start()
        tel = self.close_and_load()
        for k in ("tokens_by_category", "tokens_by_model", "cost", "human_messages", "question_dialogs",
                  "human_corrections"):
            self.assertEqual(tel[k], {"value": None, "class": "unavailable"}, k)

    def test_a_transcript_without_usage_gives_no_tokens_and_no_cost(self):
        """R-13.4-2: the host wrote a transcript but no usage numbers: the human counts are measured,
        and no token or cost figure may be shown as measured."""
        self.start()
        self.transcript(with_usage=False)
        tel = self.close_and_load()
        self.assertEqual(tel["human_messages"], {"value": 2, "class": "measured"})
        self.assertEqual(tel["question_dialogs"], {"value": 1, "class": "measured"})
        self.assertEqual(tel["human_corrections"]["class"], "inferred")
        self.assertEqual(tel["human_corrections"]["value"], 1)
        for k in ("tokens_by_category", "tokens_by_model", "cost"):
            self.assertEqual(tel[k]["class"], "unavailable", k)
            self.assertIsNone(tel[k]["value"], k)

    def test_with_usage_tokens_are_measured_by_category_and_model_and_cost_needs_a_price(self):
        """R-13.3-2, R-13.4-1: usage in the transcript is measured by category and by model; a cost
        is only ever estimated, and only from a recorded price."""
        self.start()
        self.transcript(with_usage=True)
        tel = self.close_and_load()
        self.assertEqual(tel["tokens_by_category"]["class"], "measured")
        self.assertEqual(tel["tokens_by_category"]["value"]["input"], 1000)
        self.assertEqual(tel["tokens_by_model"]["value"]["model-one"]["output"], 500)
        self.assertEqual(tel["cost"], {"value": None, "class": "unavailable"})  # no price recorded
        self.sisi("contract", "init")
        self.finish_green_again()
        with open(os.path.join(self.data, "worker-prices.json"), "w") as f:
            json.dump({"models": {"model-one": {"cost_per_million_tokens": 2.0, "source": "test", "date": "2026-01-01"}}}, f)
        self.sisi("unit", "close")
        cost = self.archive("proj-2")["telemetry"]["cost"]
        self.assertEqual(cost["class"], "estimated")
        self.assertAlmostEqual(cost["value"], 0.003)

    def finish_green_again(self):
        c = C.load(self.contract_path)
        c["checks"] = [real("again", "test -f done.txt")]
        C.save(self.contract_path, c)
        self.assertEqual(self.sisi("verify").returncode, 0)

    def test_every_scorecard_value_carries_a_class_and_unavailable_has_no_value(self):
        """R-13.1-1, R-13.4-1: the eight dimensions, each leaf classed; nothing missing reads as a number."""
        self.start()
        self.close_and_load()
        card = self.archive("proj")["scorecard"]
        self.assertEqual(list(card), list(SCORE_DIMENSIONS))
        for dim, vals in card.items():
            for k, v in vals.items():
                self.assertIn(v["class"], ("measured", "inferred", "estimated", "unavailable"), "%s.%s" % (dim, k))
                if v["class"] == "unavailable":
                    self.assertIsNone(v["value"], "%s.%s" % (dim, k))

    def test_first_useful_result_and_completion_time_are_recorded(self):
        """R-6.1-2, R-6.1-3, R-6.1-4: time to first useful result (first green run) and to validated completion."""
        self.start()
        tel = self.close_and_load()
        self.assertEqual(tel["time_to_validated_completion_s"]["class"], "measured")
        self.assertEqual(tel["time_to_first_useful_result_s"]["class"], "inferred")
        self.assertEqual(tel["time_in_checks_s"]["class"], "measured")
        self.assertEqual(tel["files_changed"]["class"], "measured")

    def test_a_window_start_does_not_turn_a_first_in_window_message_into_a_non_correction(self):
        """R-6.1-2: only the transcript's own first message is exempt from correction counting."""
        tp = os.path.join(self.tmp, "w.jsonl")
        rows = [("2026-01-01T00:00:00Z", "start the work"), ("2026-01-01T01:00:00Z", "no, that is wrong")]
        with open(tp, "w") as f:
            for ts, text in rows:
                f.write(json.dumps({"type": "user", "timestamp": ts, "message": {"content": text}}) + "\n")
        st = harvest.transcript_stats(tp, harvest.epoch("2026-01-01T00:30:00Z"), harvest.epoch("2026-01-01T02:00:00Z"))
        self.assertEqual((st["human_messages"], st["corrections"]), (1, 1))
        self.assertIsNone(st["usage"])


class StatusTests(UnitCase):
    def line(self, i, project="/w/alpha", risk="logic", model="m1", policy="p1", secs=10.0):
        return {"id": "u%d" % i, "project": project, "goal": "g%d" % i, "delivery_status": "delivered",
                "risk": {"declared": risk, "floor": risk}, "models": [model], "policy_version": policy,
                "started": "2026-01-01T00:00:00Z", "ended": "2026-01-0%dT00:00:00Z" % (1 + i % 8),
                "scorecard": {"delivery_velocity": {"time_to_validated_completion_s": {"value": secs, "class": "measured"}}}}

    def test_trends_say_too_few_under_five_and_report_median_and_p95_from_five(self):
        """R-13.1-1, R-13.5-1: trends by project, risk profile, model and policy version; no
        percentile from fewer than five units; no single score."""
        for i, s in enumerate((10, 20, 30, 40, 100)):
            store.append("units", self.line(i, secs=s))
        store.append("units", self.line(9, project="/w/beta", risk="data", model="m2", policy="p2"))
        out = self.sisi("status").stdout
        self.assertIn("by project", out)
        self.assertRegex(out, r"alpha\s+validated completion \(s\) 30/88 \(n=5\)")
        self.assertRegex(out, r"beta\s+too few")
        for kind in ("by risk profile", "by model", "by policy version"):
            self.assertIn(kind, out)
        self.assertRegex(out, r"data\s+too few")
        self.assertNotRegex(out.lower(), r"overall score|total score|score:")

    def test_unavailable_is_not_counted_as_a_number_in_trends(self):
        """R-13.4-2: a unit with no timing leaves the median to the units that have one."""
        rows = [self.line(i, secs=s) for i, s in enumerate((10, 20, 30, 40, 50))]
        rows[0]["scorecard"]["delivery_velocity"]["time_to_validated_completion_s"] = {"value": None, "class": "unavailable"}
        t = scorecard.trends(rows)["project"]["alpha"]["validated completion (s)"]
        self.assertEqual((t["n"], t["median"]), (4, 35.0))

    def test_status_with_no_units_says_so(self):
        """R-13.4-3."""
        out = self.sisi("status").stdout
        self.assertIn("no closed work units yet", out)

    def test_status_json_and_learning_view(self):
        """R-13.1-1: `--json` is machine-readable; `--learning` prints the learning report."""
        store.append("units", self.line(1))
        d = json.loads(self.sisi("status", "--json").stdout)
        self.assertEqual(d["units"][0]["id"], "u1")
        out = self.sisi("status", "--learning").stdout
        self.assertIn("Learning loop", out)

    def test_retired_reporters_are_gone_and_the_new_commands_are_listed(self):
        """R-13.1-1: `sisi time`, `sisi scoreboard` and `sisi improve` no longer exist."""
        helptext = self.sisi("help").stdout
        for gone in ("sisi time", "sisi scoreboard", "sisi improve", "sisi backlog"):
            self.assertNotIn(gone, helptext)
        for kept in ("sisi unit close", "sisi unit pause", "sisi unit show", "sisi status"):
            self.assertIn(kept, helptext)
        for cmd in ("time", "scoreboard"):
            self.assertNotEqual(self.sisi(cmd).returncode, 0, cmd)

    def test_status_after_a_real_close_shows_the_unit_with_its_scorecard(self):
        """R-13.1-1."""
        self.start()
        self.finish_green()
        self.sisi("unit", "close")
        out = self.sisi("status").stdout
        self.assertIn("[delivered]", out)
        for dim in SCORE_DIMENSIONS:
            self.assertIn(dim.replace("_", " "), out)

    def test_retro_with_no_arguments_prints_the_units_scorecard_and_what_stands_out(self):
        """R-10.3-7: `sisi retro` is grounded in the record."""
        self.start()
        self.sisi("verify")  # fails: done.txt missing
        open(os.path.join(self.proj, "done.txt"), "w").write("x")
        self.sisi("verify")
        out = self.sisi("retro").stdout
        self.assertIn("what stands out", out)
        self.assertIn("failed and then passed", out)
        self.assertIn("correctness and assurance", out)


class PruneTests(SisiCase):
    def make(self, name, age_days, transcript_age_days=None):
        p = os.path.join(self.state, "sessions", name + ".json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        rec = {"cwd": self.proj}
        if transcript_age_days is not None:
            tp = os.path.join(self.tmp, name + ".jsonl")
            open(tp, "w").write("{}\n")
            os.utime(tp, (time.time() - transcript_age_days * 86400,) * 2)
            rec["transcript_path"] = tp
        with open(p, "w") as f:
            json.dump(rec, f)
        os.utime(p, (time.time() - age_days * 86400,) * 2)
        return p

    def test_old_sessions_go_on_the_first_start_and_every_nth_after(self):
        """R-12.1-1: pruning runs from a counter at session start, with no scheduler."""
        old, new = self.make("old", 60), self.make("new", 1)
        self.assertEqual(store.prune_sessions(), 1)  # the first start sweeps
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(new))
        again = self.make("old2", 60)
        for _ in range(store.DEFAULTS["scratch"]["prune_every"] - 1):
            self.assertEqual(store.prune_sessions(), 0)  # not their turn
        self.assertTrue(os.path.exists(again))
        self.assertEqual(store.prune_sessions(), 1)  # the Nth start
        self.assertFalse(os.path.exists(again))

    def test_the_age_is_configurable(self):
        """R-12.1-1."""
        keep = self.make("a", 10)
        os.makedirs(os.path.join(self.home, ".config", "sisi"), exist_ok=True)
        with mock.patch.object(store, "config", return_value=dict(store.DEFAULTS, scratch=dict(store.DEFAULTS["scratch"], session_max_age_days=5))):
            self.assertEqual(store.prune_sessions(), 1)
        self.assertFalse(os.path.exists(keep))

    def test_an_active_session_is_never_touched(self):
        """R-12.1-1: the named current session, and one whose transcript the host is still writing."""
        cur, live, dead = self.make("cur", 90), self.make("live", 90, transcript_age_days=1), self.make("dead", 90, transcript_age_days=90)
        self.assertEqual(store.prune_sessions(active_ids=("cur",)), 1)
        self.assertTrue(os.path.exists(cur) and os.path.exists(live))
        self.assertFalse(os.path.exists(dead))

    def test_a_run_is_bounded_and_the_next_start_continues(self):
        """R-12.1-1: at most prune_max_delete files per run; the sweep resumes at the next start."""
        paths_ = [self.make("s%d" % i, 90) for i in range(7)]
        cfg = dict(store.DEFAULTS, scratch=dict(store.DEFAULTS["scratch"], prune_max_delete=3))
        with mock.patch.object(store, "config", return_value=cfg):
            self.assertEqual(store.prune_sessions(), 3)
            self.assertEqual(store.prune_sessions(), 3)  # the very next start goes on
            self.assertEqual(store.prune_sessions(), 1)
        self.assertEqual([p for p in paths_ if os.path.exists(p)], [])

    def test_the_time_budget_bounds_a_run(self):
        """R-12.1-1."""
        for i in range(5):
            self.make("t%d" % i, 90)
        cfg = dict(store.DEFAULTS, scratch=dict(store.DEFAULTS["scratch"], prune_budget_s=0.0))
        with mock.patch.object(store, "config", return_value=cfg):
            self.assertEqual(store.prune_sessions(), 0)

    def test_session_start_runs_the_prune(self):
        """R-12.1-1: `sisi tick` prunes during normal use."""
        old = self.make("ancient", 90)
        self.sisi("tick", stdin=json.dumps({"session_id": "now1", "cwd": self.proj, "hook_event_name": "SessionStart"}))
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(os.path.join(self.state, "sessions", "now1.json")))


if __name__ == "__main__":
    unittest.main()
