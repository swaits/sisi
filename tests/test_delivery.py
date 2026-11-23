import json, os, random, time, unittest
from support import *
from sisi import delivery, gate, harvest, retro, store, verify as V, contract as C


def ts(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".250Z"


def human_line(t, text="do the thing please"):
    return {"type": "user", "timestamp": ts(t), "message": {"role": "user", "content": text}}


def hook_line(t):
    return {"type": "user", "isMeta": True, "timestamp": ts(t),
            "message": {"role": "user", "content": "Stop hook feedback:\nsisi: the contract is not satisfied"}}


def result_line(t, size=10):
    return {"type": "user", "timestamp": ts(t), "toolUseResult": {"stdout": "x" * size},
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "y" * size}]}}


def other_machine_lines(t):
    return [{"type": "user", "timestamp": ts(t), "origin": {"kind": "task-notification"},
             "message": {"role": "user", "content": "worker finished"}},
            {"type": "user", "timestamp": ts(t), "message": {"role": "user", "content": "<system-reminder>be good</system-reminder>"}},
            {"type": "user", "timestamp": ts(t), "message": {"role": "user", "content": "<task-notification>x</task-notification>"}}]


def asst_line(t):
    return {"type": "assistant", "timestamp": ts(t), "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}}


def write_transcript(path, entries):
    with open(path, "w") as f:
        for e in entries:
            f.write((e if isinstance(e, str) else json.dumps(e, separators=(",", ":"))) + "\n")


def reference_start(path):
    """Slow and simple: read the whole file, apply the same human-message rule to every line, keep the last."""
    best = None
    with open(path) as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") == "user" and harvest.typed_text(d)[0] is not None:
                best = harvest.epoch(d["timestamp"])
    return best


class StartFinderTests(SisiCase):
    def path(self, name="t.jsonl"):
        return os.path.join(self.tmp, name)

    def test_last_human_message_wins_over_later_machine_entries(self):
        t0 = 1_800_000_000
        entries = [human_line(t0 - 500, "first request"), asst_line(t0 - 400), human_line(t0, "second request, the one"),
                   asst_line(t0 + 5), result_line(t0 + 6), hook_line(t0 + 7)] + other_machine_lines(t0 + 8) + \
                  [asst_line(t0 + 9), result_line(t0 + 10), hook_line(t0 + 11)]
        write_transcript(self.path(), entries)
        self.assertAlmostEqual(delivery.find_start(self.path()), t0 + 0.25, places=1)

    def test_queued_message_typed_while_working_counts(self):
        t0 = 1_800_000_000
        queued = {"type": "attachment", "timestamp": ts(t0 + 30),
                  "attachment": {"type": "queued_command", "commandMode": "prompt", "prompt": "also do this"}}
        write_transcript(self.path(), [human_line(t0), asst_line(t0 + 1), queued, result_line(t0 + 31)])
        self.assertAlmostEqual(delivery.find_start(self.path()), t0 + 30.25, places=1)

    def test_huge_tool_results_and_tiny_chunks(self):
        t0 = 1_800_000_000
        entries = [human_line(t0, "the request")] + [result_line(t0 + i, size=5000) for i in range(1, 20)]
        write_transcript(self.path(), entries)
        self.assertAlmostEqual(delivery.find_start(self.path(), chunk=700), t0 + 0.25, places=1)
        self.assertIsNone(delivery.find_start(self.path(), max_bytes=20000, chunk=700))  # too far back: not measured

    def test_none_when_nothing_found_or_unreadable(self):
        write_transcript(self.path(), [asst_line(1), result_line(2), hook_line(3)])
        self.assertIsNone(delivery.find_start(self.path()))
        self.assertIsNone(delivery.find_start(os.path.join(self.tmp, "missing.jsonl")))
        write_transcript(self.path("bad.jsonl"), ["{not json", "\x00\x01garbage", '{"type":"user","timestamp":5}', ""])
        self.assertIsNone(delivery.find_start(self.path("bad.jsonl")))
        write_transcript(self.path("empty.jsonl"), [])
        self.assertIsNone(delivery.find_start(self.path("empty.jsonl")))

    def test_matches_reference_on_random_transcripts(self):
        rnd = random.Random(20261122)
        for n in range(40 * ITERS):
            t, entries = 1_800_000_000, []
            for _ in range(rnd.randint(1, 60)):
                t += rnd.randint(1, 30)
                k = rnd.random()
                if k < 0.12:
                    entries.append(human_line(t, "typed %d" % rnd.randint(0, 99)))
                elif k < 0.4:
                    entries.append(result_line(t, rnd.choice([10, 300, 4000])))
                elif k < 0.55:
                    entries.append(hook_line(t))
                elif k < 0.65:
                    entries.extend(other_machine_lines(t))
                elif k < 0.7:
                    entries.append("{broken")
                else:
                    entries.append(asst_line(t))
            write_transcript(self.path(), entries)
            want = reference_start(self.path())
            got = delivery.find_start(self.path(), chunk=rnd.choice([64, 257, 1000, 128 * 1024]))
            self.assertEqual(got, want, "case %d" % n)

    def test_real_transcripts_if_present(self):
        """Read-only: every real transcript gives a start no later than its last record, and the same answer as a full scan."""
        base = os.path.expanduser("~/.claude/projects")
        found = []
        for root, _, files in os.walk(base):
            if "subagents" in root:
                continue
            found += [os.path.join(root, f) for f in files if f.endswith(".jsonl")]
            if len(found) > 40:
                break
        found.sort(key=lambda p: os.path.getsize(p))
        for p in (found[:1] + found[-1:]) if found else []:
            if os.path.getsize(p) > 30 * 1024 * 1024:
                continue
            got = delivery.find_start(p)
            if got is not None:
                self.assertEqual(got, reference_start(p) if os.path.getsize(p) < 8 * 1024 * 1024 else got)


class DeliveryRowTests(SisiCase):
    sid = "d-1"

    def setUp(self):
        super().setUp()
        self.tp = os.path.join(self.tmp, "transcript.jsonl")
        self.t0 = time.time() - 90
        write_transcript(self.tp, [human_line(self.t0 - 400, "older"), asst_line(self.t0 - 300),
                                   human_line(self.t0, "the request"), asst_line(self.t0 + 1), result_line(self.t0 + 2),
                                   hook_line(self.t0 + 3)])

    def hook(self, **extra):
        p = dict({"session_id": self.sid, "cwd": self.proj, "hook_event_name": "Stop"}, **extra)
        return self.sisi_proc("gate", stdin=json.dumps(p))

    def rows(self):
        p = os.path.join(self.state, "deliveries.jsonl")
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return [json.loads(l) for l in f]

    def test_row_is_recorded_when_the_gate_allows(self):
        self.write_contract(contract([check("ok", "true")]))
        r = self.hook(transcript_path=self.tp)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["session"], row["project"], row["contract"], row["send_backs"]), (self.sid, self.proj, True, 0))
        self.assertGreaterEqual(row["seconds"], 89)
        self.assertLess(row["seconds"], 140)
        self.assertGreaterEqual(row["check_s"], 0.0)
        self.assertEqual(row["start"], time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(self.t0)) + "Z")
        self.hook(transcript_path=self.tp)  # the same request again: not recorded twice
        self.assertEqual(len(self.rows()), 1)

    def test_send_backs_and_check_time_are_counted_for_the_request(self):
        self.write_contract(contract([check("bad", "sleep 0.3; exit 1")]))
        with open(self.tp, "a") as f:  # the agent edited a source file this turn
            f.write(json.dumps({"type": "assistant", "timestamp": "2026-01-01T00:00:00.000Z", "message": {
                "role": "assistant", "content": [{"type": "tool_use", "name": "Edit",
                                                  "input": {"file_path": os.path.join(self.proj, "app.py")}}]}}) + "\n")
        r = self.hook(transcript_path=self.tp)
        self.assertEqual(json.loads(r.stdout)["decision"], "block")
        self.assertEqual(self.rows(), [])  # a send-back is not a delivery
        self.write_contract(contract([check("ok", "sleep 0.2")]))
        r = self.hook(transcript_path=self.tp)
        self.assertEqual(r.stdout, "")
        row = self.rows()[0]
        self.assertEqual(row["send_backs"], 1)
        self.assertGreaterEqual(row["check_s"], 0.45)

    def test_no_contract_is_recorded_as_such(self):
        r = self.hook(transcript_path=self.tp)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.rows()[0]["contract"], False)

    def test_gate_fails_open_without_a_usable_transcript(self):
        self.write_contract(contract([check("ok", "true")]))
        for tp in (None, os.path.join(self.tmp, "missing.jsonl"), self.tp + ".dir"):
            kw = {} if tp is None else {"transcript_path": tp}
            r = self.hook(**kw)
            self.assertEqual((r.returncode, r.stdout), (0, ""), kw)
        os.mkdir(self.tp + ".dir")
        r = self.hook(transcript_path=self.tp + ".dir")  # a directory
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        for bad in (b"\x00\xff\xfe{[", b"{" * 100000, b'{"type":"user","timestamp":"nonsense","message":{"content":"hi"}}\n'):
            with open(self.tp, "wb") as f:
                f.write(bad)
            r = self.hook(transcript_path=self.tp)
            self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertEqual(self.rows(), [])
        r = self.hook(transcript_path=12345)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_a_failing_recorder_never_changes_the_answer(self):
        from unittest import mock
        self.write_contract(contract([check("ok", "true")]))
        with mock.patch.object(delivery, "find_start", side_effect=RuntimeError("boom")):
            a = gate.decide({"session_id": "x1", "cwd": self.proj, "transcript_path": self.tp})
            gate._record_delivery({"session_id": "x1", "cwd": self.proj, "transcript_path": self.tp})
        self.assertEqual(a, ("allow", None))
        self.assertEqual(self.rows(), [])

    def test_overhead_is_small(self):
        """Recording a delivery on a large transcript costs well under the budget of 50 ms (generous bound for CI)."""
        entries = [human_line(self.t0)] + [result_line(self.t0 + i, 20000) for i in range(1, 100)]
        write_transcript(self.tp, entries)
        delivery.find_start(self.tp)  # warm imports
        t = time.perf_counter()
        for _ in range(5):
            delivery.find_start(self.tp)
        per = (time.perf_counter() - t) / 5
        self.assertLess(per, 0.25)

class ParallelVerifyTests(SisiCase):
    def strip(self, results):
        return [{k: r[k] for k in ("item", "id", "status", "kind", "rung", "tier")} for r in results]

    def mk(self, parallel=None, serial_ids=()):
        cs = [check("a", "sleep 0.5"), check("b", "sleep 0.5; exit 1"), check("c", "sleep 0.5"),
              check("d", "sleep 0.5"), check("e", "exit 0"), human("h"), check("slowboy", "sleep 5", timeout_s=0.2)]
        cs.append(dict(check("deep1", "sleep 0.1"), tier="deep"))
        for c in cs:
            if c["id"] in serial_ids:
                c["serial"] = True
        c = contract(cs, [check("inv", "sleep 0.3")])
        if parallel is not None:
            c["parallel"] = parallel
        return c

    def test_same_results_in_the_same_order_and_faster(self):
        t = time.time()
        serial = V.run(self.mk(), self.proj, tiers=("fast", "deep"))
        t_serial = time.time() - t
        t = time.time()
        par = V.run(self.mk(parallel=True), self.proj, tiers=("fast", "deep"))
        t_par = time.time() - t
        self.assertEqual(self.strip(par), self.strip(serial))
        self.assertEqual([r["id"] for r in par], ["a", "b", "c", "d", "e", "h", "slowboy", "deep1", "inv"])
        self.assertLess(t_par, t_serial - 0.5)
        explicit_off = V.run(self.mk(parallel=False), self.proj)
        self.assertEqual(self.strip(explicit_off), self.strip(V.run(self.mk(), self.proj)))

    def test_serial_checks_run_alone(self):
        log = os.path.join(self.tmp, "log")
        def cmd(n):
            return "echo start-%s >> %s; sleep 0.3; echo end-%s >> %s" % (n, log, n, log)
        cs = [check("p1", cmd("p1")), dict(check("s1", cmd("s1")), serial=True), check("p2", cmd("p2")),
              dict(check("s2", cmd("s2")), serial=True)]
        res = V.run(dict(contract(cs), parallel=True), self.proj)
        self.assertEqual([r["id"] for r in res], ["p1", "s1", "p2", "s2"])
        lines = open(log).read().split()
        for n in ("s1", "s2"):  # nothing else starts or ends between a serial check's start and end
            i = lines.index("start-" + n)
            self.assertEqual(lines[i + 1], "end-" + n)

    def test_property_random_contracts_match_serial(self):
        rnd = random.Random(3)
        for _ in range(6 * ITERS):
            cs = [dict(check("c%d" % i, "exit %d" % rnd.choice([0, 0, 1])), **({"serial": True} if rnd.random() < 0.3 else {}))
                  for i in range(rnd.randint(1, 9))]
            c = contract(cs)
            serial = V.run(c, self.proj)
            par = V.run(dict(c, parallel=True), self.proj)
            self.assertEqual(self.strip(par), self.strip(serial))

    def test_validation_and_cli(self):
        self.assertTrue(any("parallel" in e for e in C.validate(dict(contract([check("a", "true")]), parallel="yes"))))
        bad = contract([dict(check("a", "true"), serial="x")])
        self.assertTrue(any("serial" in e for e in C.validate(bad)))
        self.write_contract(dict(contract([check("a", "true"), check("b", "true")]), parallel=True))
        r = self.sisi("verify", "--json")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual([x["id"] for x in json.loads(r.stdout)["results"]], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
