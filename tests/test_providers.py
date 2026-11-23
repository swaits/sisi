"""One tool, several providers: per-provider plans, the owner's vouch, allowance probes and failure phrases.

Requirements: R-7.2-1 and R-7.2-2 (the least expensive sufficiently capable worker: a flat plan with allowance left
costs nothing extra, a lighter model of the plan first), R-7.2-3 (empirical and revisable: a vouch is a prior that the
judged record replaces), R-7.3-1 (cost counts what a plan really charges), R-16-3 and R-16-4 (a key is used for one
request and never stored, printed or logged; least privilege: a redirect never carries it), R-16-6 and R-16-7
(tool output and server answers are data, validated), R-16-8 (a consequential definition waits for the owner),
R-16-11 (an agent cannot widen what routing trusts: a relayed vouch counts up to difficulty 2)."""
import http.server, json, os, threading, time, unittest
from unittest import mock

import test_discovery as TD
from support import *
from sisi import discovery, routing, workers

SECRET = "SECRETKEYVALUE123456"

MULTI = """#!/bin/sh
if [ "$1" = "models" ]; then echo "zai/a"; echo "zai/b"; echo "other/c"; exit 0; fi
if [ -n "$FAKE_MARK" ]; then echo "$@" >> "$FAKE_MARK"; fi
n=0; last=""
for a in "$@"; do n=$((n+1)); last="$a"; done
model=""; prev=""
for a in "$@"; do if [ "$prev" = "--model" ]; then model="$a"; fi; prev="$a"; done
case "$FAKE_MODE:$model" in
  quota:zai/*) echo "weekly allowance used up for this plan"; exit 0 ;;
  code1113:zai/*) echo '{"error":{"code":"1113","message":"Insufficient balance or no resource package","usage limit":true}}'; exit 1 ;;
  reset:zai/*) echo '{"error":{"code":"1308","message":"limit reached","resetAt":"RESETAT"}}'; exit 1 ;;
esac
echo "$last"
exit 0
"""

AUTH_EXPORT = ('#!/bin/sh\necho \'[{"integrationID":"other","active":true,"value":{"type":"api","key":"NOTTHISKEYXXXX"}},'
               '{"integrationID":"zai","active":true,"value":{"type":"api","key":"%s"}}]\'\n' % SECRET)
LEAKY_EXPORT = '#!/bin/sh\necho "%s" ; echo "%s" >&2\nexit 1\n' % (SECRET, SECRET)
PATHS = ["--remaining-path", "data.limits[type=CREDIT_LIMIT].remaining", "--reset-path", "data.limits[type=CREDIT_LIMIT].nextResetTime",
         "--total-path", "data.limits[type=CREDIT_LIMIT].total"]


class Quota:
    """A local stand-in for a provider's allowance endpoint."""

    def __init__(self):
        owner = self
        self.hits, self.leaks, self.mode = [], [], "ok"
        self.windows = [(100, 1000, 4102444800000), (900, 1000, 4102444900000)]

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                auth = self.headers.get("Authorization")
                if self.path == "/leak":
                    owner.leaks.append(auth)
                    self.send_response(200); self.end_headers(); self.wfile.write(b"{}")
                    return
                owner.hits.append(auth)
                if owner.mode == "redirect":
                    self.send_response(302); self.send_header("Location", "http://127.0.0.1:%d/leak" % owner.port); self.end_headers()
                elif owner.mode == "hang":
                    time.sleep(3)
                elif auth != SECRET:
                    body = ('{"error":"bad key %s"}' % auth).encode()
                    self.send_response(401); self.end_headers(); self.wfile.write(body)
                else:
                    body = json.dumps({"data": {"limits": [{"type": "CREDIT_LIMIT", "remaining": r, "total": t, "nextResetTime": n}
                                                           for r, t, n in owner.windows]}}).encode()
                    self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
                    self.wfile.write(body)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return "http://127.0.0.1:%d/quota" % self.port

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class ProviderCase(TD.DiscoveryCase):
    def setUp(self):
        super().setUp()
        self.exe("multi", MULTI)
        f = TD.driver_file(os.path.join(self.tmp, "m.json"), name="multi", exe="multi",
                           run=["multi", "{model_flag}", "-p", "{prompt}"], list=["multi", "models"], plan=None,
                           limit_signatures=["allowance used up"], tokens_regex=None)
        r = self.sisi("workers", "learn", "multi", "--record", f)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.write_cfg({"learning": {"agent_relayed_approval": True}, "discovery": {"allowance_timeout_s": 1}})

    def cands(self):
        return {c["worker"]: c for c in workers.build_candidates()}

    def brief(self):
        p = os.path.join(self.proj, "brief.md")
        open(p, "w").write(TD.BRIEF)
        return p

    def fact(self, worker, price, plan=None):
        args = ["workers", "fact", worker, "--price", str(price), "--source", "test"] + (["--plan", plan] if plan else [])
        self.assertEqual(self.sisi(*args).returncode, 0)

    def define_probe(self, quota, approve=True, export=AUTH_EXPORT, extra=()):
        self.exe("authexport", export)
        r = self.sisi("workers", "allowance", "zai", "--url", quota.url, "--header", "Authorization={secret}",
                      "--secret-from-command", "authexport", "--secret-path", "[integrationID=zai][active=true].value.key",
                      *PATHS, *extra)
        self.assertEqual(r.returncode, 0, r.stdout)
        if approve:
            self.assertEqual(self.sisi("approve", "probe-zai", "--yes").returncode, 0)
        return r


# ---------------------------------------------------------------- item 7: one tool, several providers


def c(worker, tool, **kw):
    model = worker if "/" in worker else worker.split("/")[-1]
    return dict({"worker": worker, "tool": tool, "model": worker if tool == "multi" else worker.split("/", 1)[-1],
                 "plan": "flat", "cost": None, "usable": True, "allowance_pct_left": None, "aliases": [worker],
                 "maker": "m"}, **kw)


class PerProviderConstraints(unittest.TestCase):
    """A constraint on provider `a-b` never reaches provider `a-b-c`, nor a model `a-b` under another tool."""

    def setUp(self):
        self.ab, self.abc, self.other = c("a-b/x", "multi"), c("a-b-c/y", "multi"), c("other/a-b", "other")

    def test_a_provider_pattern_matches_the_provider_exactly(self):
        hits = [w["worker"] for w in (self.ab, self.abc, self.other) if routing._pattern_match(w, [{"pattern": "a-b/"}])]
        self.assertEqual(hits, ["a-b/x"])
        self.assertEqual(routing._pattern_match(c("xa-b/z", "multi"), [{"pattern": "a-b/"}]), None)

    def test_avoid_and_prefer_by_provider_pattern(self):
        avoid = routing.choose([self.ab, self.abc, self.other], [], {}, "read", 1, now=1.0, avoid=[{"pattern": "a-b/"}])
        self.assertNotEqual(avoid["choice"]["worker"], "a-b/x")
        self.assertIn(avoid["choice"]["worker"], ("a-b-c/y", "other/a-b"))
        prefer = routing.choose([self.abc, self.other, self.ab], [], {}, "read", 1, now=1.0, prefer=[{"pattern": "a-b/"}])
        self.assertEqual(prefer["choice"]["worker"], "a-b/x")

    def test_a_provider_availability_mark_reaches_that_provider_only(self):
        down = {"a-b": {"reason": "limit", "retry_at": 9e9, "scope": "provider"}}
        self.assertIsNotNone(routing._down_entry(self.ab, down, 1.0))
        self.assertIsNone(routing._down_entry(self.abc, down, 1.0))
        self.assertIsNone(routing._down_entry(self.other, down, 1.0), "a model named a-b under another tool is not the provider")
        r = routing.choose([self.ab, self.abc, self.other], [], down, "read", 1, now=1.0)
        self.assertNotEqual(r["choice"]["worker"], "a-b/x")

    def test_only_scopes_to_its_provider(self):
        kept, out = workers.apply_limits([self.ab, self.abc, self.other],
                                         {"only": [{"provider": "a-b", "patterns": ["zzz"], "why": "w"}]})
        self.assertEqual([w["worker"] for w in kept], ["a-b-c/y", "other/a-b"])
        self.assertEqual([w for w, _ in out], ["a-b/x"])

    def test_notes_by_provider_pattern(self):
        by = {w["worker"]: w for w in (self.ab, self.abc, self.other)}
        lines = workers.notes_for(by, self.abc, [("a-b/x", "r"), ("other/a-b", "r")], notes=[{"pattern": "a-b/", "text": "T", "why": "w"}])
        self.assertEqual(len(lines), 1)
        self.assertIn("passed over: a-b/x", lines[0])
        self.assertNotIn("the chosen worker", lines[0])
        self.assertNotIn("other/a-b", lines[0])


class ProviderPlans(ProviderCase):
    def test_a_providers_plan_costs_its_workers_as_flat_and_others_stay_unknown(self):
        self.assertEqual(self.sisi("workers", "plan", "zai", "flat", "--source", "owner", "--note", "quarterly subscription").returncode, 0)
        cands = self.cands()
        self.assertEqual(cands["zai/a"]["plan"], "flat")
        self.assertEqual(cands["zai/b"]["plan"], "flat")
        self.assertEqual(cands["other/c"]["plan"], "per-use")  # unproven and no plan fact: per-use
        shown = self.sisi("workers").stdout
        self.assertIn("provider zai: flat-rate plan - quarterly subscription (owner,", shown)
        self.assertIn("models: a, b", shown)

    def test_free_counts_as_flat_and_a_models_own_plan_fact_wins(self):
        self.sisi("workers", "plan", "zai", "free", "--source", "s")
        self.assertEqual(self.cands()["zai/a"]["plan"], "flat")
        self.fact("zai/a", 2, plan="per-use")
        self.assertEqual(self.cands()["zai/a"]["plan"], "per-use")
        self.assertEqual(self.cands()["zai/b"]["plan"], "flat")

    def test_the_lighter_model_of_a_flat_plan_takes_routine_work(self):
        self.sisi("workers", "plan", "zai", "flat", "--source", "owner")
        self.fact("zai/a", 3)
        self.fact("zai/b", 1)
        r = self.sisi("route", "--kind", "read", "--difficulty", "1")
        self.assertEqual(r.stdout.splitlines()[0], "zai/b", r.stdout)

    def test_a_plan_needs_a_source_and_a_known_kind_and_can_be_removed(self):
        for args in (("zai", "flat"), ("zai", "monthly", "--source", "s"), ("Bad Name", "flat", "--source", "s"), ()):
            self.assertEqual(self.sisi("workers", "plan", *args).returncode, 1, args)
        self.sisi("workers", "plan", "zai", "flat", "--source", "s")
        self.assertEqual(self.sisi("workers", "plan", "zai", "--remove").returncode, 0)
        self.assertEqual(self.cands()["zai/a"]["plan"], "per-use")


# ---------------------------------------------------------------- item 8: the owner's word


class Vouch(unittest.TestCase):
    def new(self, worker, **kw):
        return dict(c(worker, "multi"), unproven=True, unproven_ok=True, **kw)

    def test_a_vouched_worker_is_capable_up_to_its_level_with_the_owners_word_as_evidence(self):
        a = self.new("zai/a", vouch={"level": 2, "why": "Verified by hand", "date": "2026-11-23", "relayed": False})
        for d, ok in ((1, True), (2, True), (3, False)):
            r = routing.choose([a], [], {}, "impl", d, now=1.0)
            self.assertEqual(r["choice"] is not None, ok, d)
        r = routing.choose([a], [], {}, "impl", 2, now=1.0)
        text = "\n".join(routing.explain_choice(r, "impl", 2))
        self.assertIn("evidence (the owner's word): vouched for up to difficulty 2", text)
        self.assertIn("Verified by hand", text)

    def test_proof_before_benchmark_a_vouch_outranks_a_benchmark_above_routine_work(self):
        vouched = self.new("zai/a", vouch={"level": 2, "why": "w", "date": "d", "relayed": False}, cost=5.0)
        bench = dict(c("big/b", "multi"), standing=95.0, cost=1.0)
        r = routing.choose([bench, vouched], [], {}, "impl", 2, now=1.0)
        self.assertEqual(r["choice"]["worker"], "zai/a")
        self.assertTrue(r["judged_first"])

    def test_a_vouch_ranks_with_judged_proof_and_a_thick_bad_record_overrides_it(self):
        recs = TD.attempts("old/p", 8, "impl", 2)
        vouched = self.new("zai/a", vouch={"level": 2, "why": "w", "date": "d", "relayed": False}, cost=0.1)
        proven = c("old/p", "multi", cost=9.0)
        self.assertEqual(routing.choose([vouched, proven], recs, {}, "impl", 2, now=1.0)["choice"]["worker"], "zai/a",
                         "both are proof: the cheaper takes it")
        dear = dict(vouched, cost=20.0)
        self.assertEqual(routing.choose([dear, proven], recs, {}, "impl", 2, now=1.0)["choice"]["worker"], "old/p")
        bad = TD.attempts("zai/a", 8, "impl", 2, outcome="rejected")
        a = routing.assess(routing.candidate_stats([vouched], bad), "zai/a", "impl", 2, vouch=2)
        self.assertTrue(a["bad"])
        self.assertFalse(a["capable"])

    def test_a_thin_record_with_repeated_rejections_cancels_the_word(self):
        a = routing.assess(routing.candidate_stats([c("zai/a", "multi")], TD.attempts("zai/a", 2, "impl", 2, outcome="rejected")),
                           "zai/a", "impl", 2, vouch=2)
        self.assertFalse(a["capable"])

    def test_an_unvouched_new_worker_stays_on_routine_work(self):
        flash = self.new("zai/flash")
        self.assertIsNone(routing.choose([flash], [], {}, "impl", 2, now=1.0)["choice"])
        self.assertEqual(routing.choose([flash], [], {}, "impl", 1, now=1.0)["choice"]["worker"], "zai/flash")


class VouchCommand(ProviderCase):
    def route_line(self, *a):
        return self.sisi("route", *a).stdout.splitlines()[:1]

    def setup_prices(self):
        self.sisi("workers", "plan", "zai", "flat", "--source", "owner")
        self.fact("zai/a", 3)
        self.fact("zai/b", 1)

    def typed_session(self, words):
        from sisi import store
        tp = os.path.join(self.tmp, "t.jsonl")
        with open(tp, "w") as f:
            f.write(json.dumps({"type": "user", "message": {"content": words}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "the agent says: invented owner words"}]}}) + "\n")
        store.save_session("s1", {"session_id": "s1", "transcript_path": tp})
        return {"SISI_SESSION_ID": "s1"}

    def test_the_owner_vouches_and_routing_uses_it_then_remove_undoes_it(self):
        self.setup_prices()
        self.assertNotEqual(self.route_line("--kind", "impl", "--difficulty", "2"), ["zai/a"])
        env = self.typed_session("Verified: opencode run -m zai/a completes a tool-using edit-and-test task")
        r = self.sisi("workers", "vouch", "zai/a", "--up-to", "2", "--why", "Verified: opencode run -m zai/a completes a tool-using edit-and-test task", env=env)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("typed by the owner", r.stdout)
        out = self.sisi("route", "--kind", "impl", "--difficulty", "2", "--explain").stdout
        self.assertEqual(out.splitlines()[0], "zai/a", out)
        self.assertIn("the owner's word", out)
        self.assertIn("unproven: check this result", out, "a vouched worker is still checked a level more carefully")
        self.assertNotEqual(self.route_line("--kind", "impl", "--difficulty", "3"), ["zai/a"])
        self.assertIn("Vouched: zai/a up to difficulty 2", self.sisi("workers").stdout)
        self.assertEqual(self.sisi("workers", "vouch", "zai/a", "--remove").returncode, 0)
        self.assertNotEqual(self.route_line("--kind", "impl", "--difficulty", "2"), ["zai/a"])

    def test_a_vouch_with_invented_owner_words_counts_only_up_to_difficulty_two(self):
        self.setup_prices()
        for env in (None, self.typed_session("something else the owner typed entirely")):
            r = self.sisi("workers", "vouch", "zai/a", "--up-to", "3", "--why", "the owner said it works for everything", env=env)
            self.assertEqual(r.returncode, 0)
            self.assertIn("relayed by an agent", r.stdout)
            self.assertIn("counted only up to difficulty 2", r.stdout)
            self.assertEqual(discovery.load_vouches()["zai/a"]["origin"], "relayed by an agent")
            self.assertEqual(self.cands()["zai/a"]["vouch"]["level"], 2)
            self.assertEqual(self.route_line("--kind", "impl", "--difficulty", "2"), ["zai/a"])
            self.assertNotEqual(self.route_line("--kind", "impl", "--difficulty", "3"), ["zai/a"])
        env = self.typed_session("Verified by hand: it handles everything")
        self.sisi("workers", "vouch", "zai/a", "--up-to", "3", "--why", "Verified by hand: it handles everything", env=env)
        self.assertEqual(self.cands()["zai/a"]["vouch"]["level"], 3)

    def test_once_it_has_its_own_thick_record_the_vouch_is_ignored(self):
        self.setup_prices()
        self.sisi("workers", "vouch", "zai/a", "--up-to", "2", "--why", "x words")
        self.assertIn("vouch", self.cands()["zai/a"])
        for row in TD.attempts("zai/a", 8, "impl", 1):
            workers.append_record(row)
        self.assertNotIn("vouch", self.cands()["zai/a"])
        self.assertIn("ignored now: its own record decides", self.sisi("workers").stdout)

    def test_bad_arguments_are_refused(self):
        for args in (("zai/a",), ("zai/a", "--up-to", "5", "--why", "x"), ("zai/a", "--up-to", "2"), ("zai/a", "--up-to", "2", "--why", " ")):
            self.assertEqual(self.sisi("workers", "vouch", *args).returncode, 1, args)
        self.assertEqual(discovery.load_vouches(), {})


# ---------------------------------------------------------------- item 9: allowance probes and failure phrases


class PathLanguage(unittest.TestCase):
    def test_paths_over_the_shapes_the_probe_reads(self):
        export = [{"integrationID": "x", "active": True, "value": {"key": "k0"}},
                  {"integrationID": "zai", "active": False, "value": {"key": "k1"}},
                  {"integrationID": "zai", "active": True, "value": {"key": "k2"}}]
        self.assertEqual(discovery.path_values(export, "[integrationID=zai][active=true].value.key"), ["k2"])
        self.assertEqual(discovery.path_values(export, "[2].value.key"), ["k2"])
        self.assertEqual(discovery.path_values(export, "[*].integrationID"), ["x", "zai", "zai"])
        body = {"data": {"limits": [{"type": "A", "remaining": 1}, {"type": "CREDIT_LIMIT", "remaining": 2}, {"type": "CREDIT_LIMIT", "remaining": 3}]}}
        self.assertEqual(discovery.path_values(body, "data.limits[type=CREDIT_LIMIT].remaining"), [2, 3])
        self.assertEqual(discovery.path_values("tokens left: 42 of 100", "re:left: (\\d+)"), ["42"])
        self.assertEqual(discovery.path_values(body, "data.nothing.here"), [])
        for bad in ("", "data..x", "data[", "a b"):
            with self.assertRaises(ValueError):
                discovery.path_values(body, bad)

    def test_times_in_seconds_milliseconds_and_dates(self):
        self.assertEqual(discovery.time_value(1795000000), 1795000000.0)
        self.assertEqual(discovery.time_value(1795000000000), 1795000000.0)
        self.assertEqual(discovery.time_value("1795000000000"), 1795000000.0)
        self.assertEqual(discovery.time_value("2026-11-23T10:00:00+00:00"), 1795428000.0)
        self.assertIsNone(discovery.time_value("soon"))
        self.assertIsNone(discovery.time_value(True))

    def test_several_windows_decide_by_the_smallest_remaining_and_the_reset_that_restores_service(self):
        st = discovery.allowance_state({"windows": [{"remaining": 0, "reset": 100.0}, {"remaining": 0, "reset": 500.0}, {"remaining": 9, "reset": 50.0}]})
        self.assertTrue(st["exhausted"])
        self.assertEqual(st["until"], 500.0, "back only when every exhausted window has reset")
        st = discovery.allowance_state({"windows": [{"remaining": 0, "reset": 100.0, "total": 10}, {"remaining": 5, "reset": 500.0, "total": 10}]})
        self.assertEqual(st["until"], 100.0)
        self.assertEqual(st["pct"], 0.0)
        self.assertIsNone(discovery.allowance_state({"windows": [{"remaining": 0, "reset": None}]})["until"])
        self.assertFalse(discovery.allowance_state({"windows": [{"remaining": 3, "reset": 1.0}]})["exhausted"])


class AllowanceProbe(ProviderCase):
    def setUp(self):
        super().setUp()
        self.q = Quota()
        self.addCleanup(self.q.close)
        self.sisi("workers", "plan", "zai", "flat", "--source", "owner")
        self.fact("zai/a", 3)
        self.fact("zai/b", 1)
        self.sisi("workers", "vouch", "zai/a", "--up-to", "2", "--why", "words")
        self.fact("other/c", 5, plan="flat")

    def everything_stored(self):
        text = ""
        for root in (self.data, self.state):
            for dp, _dn, fns in os.walk(root):
                for f in fns:
                    try:
                        text += open(os.path.join(dp, f), errors="replace").read()
                    except OSError:
                        pass
        return text

    def test_a_probe_waits_for_the_owner_and_is_never_read_before(self):
        self.define_probe(self.q, approve=False)
        self.assertIn("WAITING FOR THE OWNER", self.sisi("approve").stdout)
        shown = self.sisi("workers").stdout
        self.assertIn("allowance probe waits for the owner", shown)
        self.sisi("route", "--kind", "read", "--difficulty", "1")
        self.assertEqual(self.q.hits, [], "not one request before the owner approved")
        self.write_cfg({"discovery": {"allowance_timeout_s": 1}})  # no relay: an agent cannot decide
        self.assertEqual(self.sisi("approve", "probe-zai", "--yes").returncode, 2)
        self.assertEqual(self.q.hits, [])

    def test_workers_shows_the_allowance_and_the_key_is_used_once_and_stored_nowhere(self):
        self.define_probe(self.q)
        r = self.sisi("workers")
        self.assertIn("allowance left: 10% (smallest window)", r.stdout)
        self.assertRegex(r.stdout, "next reset (2099|2100)-")
        self.assertEqual(self.q.hits, [SECRET])
        out = self.sisi("route", "--kind", "read", "--difficulty", "1", "--explain")
        self.assertEqual(self.q.hits, [SECRET], "routing reads the cached reading: it is younger than a few minutes")
        for text in (r.stdout, r.stderr, out.stdout, out.stderr, self.everything_stored()):
            self.assertNotIn(SECRET, text)
        self.assertNotIn("NOTTHISKEYXXXX", self.everything_stored())

    def test_routing_reads_again_when_the_reading_is_old(self):
        self.define_probe(self.q)
        self.sisi("workers")
        with mock.patch.object(time, "time", return_value=time.time() + 400):
            self.sisi("route", "--kind", "read", "--difficulty", "1")
        self.assertEqual(len(self.q.hits), 2)

    def test_a_failing_probe_command_that_echoes_the_key_leaks_nothing(self):
        self.define_probe(self.q, export=LEAKY_EXPORT)
        r = self.sisi("workers")
        self.assertIn("the probe failed (the secret command exited with status 1)", r.stdout)
        for text in (r.stdout, r.stderr, self.everything_stored()):
            self.assertNotIn(SECRET, text)
        self.assertEqual(self.q.hits, [])

    def test_a_server_that_echoes_the_key_back_leaks_nothing(self):
        self.define_probe(self.q, export=AUTH_EXPORT.replace(SECRET, SECRET + "WRONG"))
        r = self.sisi("workers")
        self.assertIn("the server answered HTTP 401", r.stdout)
        for text in (r.stdout, r.stderr, self.everything_stored()):
            self.assertNotIn(SECRET + "WRONG", text)

    def test_a_redirect_is_never_followed_so_the_key_goes_nowhere_else(self):
        self.q.mode = "redirect"
        self.define_probe(self.q)
        r = self.sisi("workers")
        self.assertIn("a redirect, which is never followed", r.stdout)
        self.assertEqual(self.q.leaks, [])
        self.assertEqual(self.q.hits, [SECRET])

    def test_a_probe_that_times_out_or_fails_changes_nothing_and_says_so_in_workers_only(self):
        self.q.mode = "hang"
        self.define_probe(self.q)
        before = self.sisi("route", "--kind", "read", "--difficulty", "1")
        self.assertEqual(before.returncode, 0, before.stdout)
        self.assertNotIn("probe", before.stdout)
        self.assertEqual(workers.read_availability(), {})
        shown = self.sisi("workers").stdout
        self.assertIn("the probe failed (the request failed", shown)
        self.assertEqual(workers.read_availability(), {})

    def test_a_definition_that_could_send_the_key_somewhere_else_is_refused(self):
        self.exe("authexport", AUTH_EXPORT)
        base = ["workers", "allowance", "zai", "--header", "Authorization={secret}", "--secret-from-command", "authexport",
                "--secret-path", "a.b", *PATHS]
        for url in ("http://example.com/quota", "ftp://x/y", "https://user:pw@example.com/q", "https://example.com/q?k={secret}", ""):
            self.assertEqual(self.sisi(*base, "--url", url).returncode, 1, url)
        self.assertEqual(self.sisi("workers", "allowance", "zai", "--url", self.q.url, "--header", "Authorization=fixed",
                                   "--secret-from-command", "authexport", "--secret-path", "a.b", *PATHS).returncode, 1)
        self.assertEqual(self.sisi("workers", "allowance", "zai", "--url", self.q.url, "--header", "Authorization={secret}",
                                   "--secret-from-command", "authexport", "--secret-path", "a..b", *PATHS).returncode, 1)
        self.assertEqual(load_providers_allowance(), None)

    def test_zero_remaining_marks_the_provider_down_until_the_probe_reset_and_routing_falls_back(self):
        self.q.windows = [(0, 1000, 4102444800000), (500, 1000, 4102444900000)]
        self.define_probe(self.q)
        shown = self.sisi("workers").stdout
        self.assertIn("NONE LEFT", shown)
        down = workers.read_availability()["zai"]
        self.assertEqual(down["retry_at"], 4102444800.0)
        self.assertEqual(down["scope"], "provider")
        r = self.sisi("route", "--kind", "read", "--difficulty", "1", "--explain")
        self.assertEqual(r.stdout.splitlines()[0], "other/c", r.stdout)
        self.assertIn("zai", r.stdout)
        # the provider's allowance comes back: the probe's own mark is cleared and zai is routable again
        self.q.windows = [(800, 1000, 4102444800000)]
        with mock.patch.object(time, "time", return_value=time.time() + 400):
            r = self.sisi("route", "--kind", "read", "--difficulty", "1")
        self.assertEqual(r.stdout.splitlines()[0], "zai/b")
        self.assertNotIn("zai", workers.read_availability())

    def test_a_spent_explicit_worker_falls_back_to_another_automatically(self):
        self.q.windows = [(0, 1000, 4102444800000)]
        self.define_probe(self.q)
        r = self.sisi("delegate", "--kind", "read", "--difficulty", "1", "--brief", self.brief(), "--worker", "zai/b")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("has no allowance left until its reset; choosing another worker", r.stdout)
        self.assertNotIn("worker: zai/", r.stdout)

    def test_a_limit_failure_takes_its_reset_time_from_the_probe(self):
        self.q.windows = [(50, 1000, 4102444800000)]
        self.define_probe(self.q)
        self.sisi("workers")  # reads 5% left; the reading stays fresh for a few minutes
        self.q.windows = [(0, 1000, 4102444800000)]  # spent by the time the run fails
        with mock.patch.dict(os.environ, {"FAKE_MODE": "quota"}):
            self.sisi("delegate", "--kind", "read", "--difficulty", "1", "--brief", self.brief(), "--worker", "zai/b")
        self.assertEqual(self.q.hits.count(SECRET), 2, "once for `workers`, once more when the limit was reported")
        self.assertEqual(workers.read_availability()["zai"]["retry_at"], 4102444800.0)


def load_providers_allowance():
    return (discovery.load_providers().get("zai") or {}).get("allowance")


class FailurePhrases(ProviderCase):
    def setUp(self):
        super().setUp()
        self.sisi("workers", "plan", "zai", "flat", "--source", "owner")
        self.sisi("workers", "vouch", "zai/a", "--up-to", "2", "--why", "words")
        self.fact("zai/a", 3)
        self.fact("zai/b", 1)
        self.fact("other/c", 2)

    def run_a(self, mode, worker="zai/b"):
        with mock.patch.dict(os.environ, {"FAKE_MODE": mode}):
            return self.sisi("delegate", "--kind", "read", "--difficulty", "1", "--brief", self.brief(), "--worker", worker)

    def test_the_providers_own_code_is_an_auth_problem_not_a_limit_and_only_that_provider_is_down(self):
        text = self.run_a("code1113").stdout
        self.assertIn("is unavailable (limit", text, "without the provider's phrase the built-in classifier says limit")
        workers.write_json(workers.availability_path(), {})
        self.assertEqual(self.sisi("workers", "signature", "zai", "--match", "re:\\b1113\\b", "--class", "auth").returncode, 0)
        r = self.run_a("code1113")
        self.assertIn("zai/b is unavailable (auth", r.stdout)
        avail = workers.read_availability()
        self.assertIn("zai", avail)
        self.assertEqual(avail["zai"]["reason"], "auth")
        self.assertNotIn("multi", avail, "the tool is not marked down: its other provider still works")
        route = self.sisi("route", "--kind", "read", "--difficulty", "1").stdout.splitlines()[0]
        self.assertEqual(route, "other/c")
        self.assertIn("other/c", self.run_a("", worker="other/c").stdout)
        self.assertIn("failure phrase", self.sisi("workers").stdout)

    def test_a_phrase_can_name_the_reset_time(self):
        reset = time.time() + 7200
        iso = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(reset))
        self.sisi("workers", "signature", "zai", "--match", "limit reached", "--class", "limit", "--until-path", "error.resetAt")
        self.exe("multi", MULTI.replace("RESETAT", iso))
        self.run_a("reset")
        got = workers.read_availability()["zai"]
        self.assertEqual(got["reason"], "limit")
        self.assertAlmostEqual(got["retry_at"], reset, delta=5)

    def test_signature_arguments_are_checked_and_listed_and_removed(self):
        for args in (("zai", "--match", "ab", "--class", "auth"), ("zai", "--match", "something", "--class", "weird"),
                     ("zai", "--match", "re:(", "--class", "auth"), ("zai", "--match", "something", "--class", "auth", "--until-path", "a..b")):
            self.assertEqual(self.sisi("workers", "signature", *args).returncode, 1, args)
        self.sisi("workers", "signature", "zai", "--match", "some phrase", "--class", "error")
        self.assertIn("'some phrase' is error", self.sisi("workers", "signature").stdout)
        self.sisi("workers", "signature", "zai", "--match", "some phrase", "--remove")
        self.assertNotIn("some phrase", self.sisi("workers", "signature").stdout)

    def test_a_phrase_of_one_provider_never_classifies_another_providers_output(self):
        self.sisi("workers", "signature", "zai", "--match", "re:\\b1113\\b", "--class", "auth")
        self.assertIsNone(discovery.provider_failure({"worker": "other/c"}, "code 1113"))
        self.assertIsNone(discovery.provider_failure({"worker": "zai-x/c"}, "code 1113"))
        self.assertIsNotNone(discovery.provider_failure({"worker": "zai/c"}, "code 1113"))

    def test_the_other_provider_works_beside_one_that_is_out(self):
        self.run_a("quota")
        self.assertIn("zai", workers.read_availability())
        r = self.run_a("quota", worker="other/c")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("worker: other/c", r.stdout)


if __name__ == "__main__":
    unittest.main()
