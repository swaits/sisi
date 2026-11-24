"""A changing environment: workers installed or reachable after sisi was installed are found and used.

Requirements: R-7.2-1 and R-7.2-2 (least expensive sufficiently capable worker, from the record), R-7.2-3 (the routing
policy is empirical and revisable: an unproven worker earns difficulty by its judged record), R-12-1 (what was learned
is persisted so it is not rediscovered), R-16-3 and R-16-7 (a driver file is untrusted input: validated, least
privilege), R-16-4 (the brief never reaches a shell), R-16-6 (a tool's output is data), R-16-8 (consequential changes
are recorded), R-16-11 (a learned driver cannot widen permissions: approvals-off waits for the owner)."""
import json, os, shutil, stat, sys, time, unittest
from unittest import mock

from support import *
from sisi import brief as brief_contract, discovery, routing, workers

FAKE_AGENT = """#!/bin/sh
# a fake agent tool: `models` lists, anything else runs one task and echoes the prompt it was given
if [ "$1" = "models" ]; then echo "fa-1"; echo "fa-2"; exit 0; fi
if [ -n "$FAKE_MARK" ]; then echo ran >> "$FAKE_MARK"; fi
n=0; last=""
for a in "$@"; do n=$((n+1)); last="$a"; done
if [ -n "$FAKE_ARGS" ]; then echo "$n" > "$FAKE_ARGS"; fi
case "$FAKE_MODE" in
  login) echo "Error: you are not authenticated. Run 'fa login'" >&2; exit 1 ;;
  quota) echo "weekly allowance used up for this plan" ; exit 0 ;;
  flag) echo "error: unknown flag --print-all" >&2; exit 2 ;;
  hang) while true; do :; done ;;
  silent) echo "hello"; exit 0 ;;
esac
echo "$last"
echo "total tokens: 321"
exit 0
"""

BRIEF = ("You are a worker.\n\n## Outcome and scope\nDo the toy task.\n\n## Context and sources of truth\nThis brief.\n\n"
         "## Constraints and interfaces\nNone.\n\n## Acceptance\nThe final report says done.\n\n"
         "## Deliverables and report format\nA short report.\n\n## Files you may change\ntoy.txt only.\n\n"
         "## Verification\nNone needed.\n\n## Budget and escalation\nFive minutes; escalate if blocked.\n")

LISTING = {"providers": [
    {"providerInstanceId": "alpha", "driverKind": "kindA", "displayName": "Alpha",
     "models": [{"id": "m-1", "label": "M One", "options": []}, {"id": "m-2", "label": "M Two", "options": []}],
     "canRunChildTask": True, "constraints": []},
    {"providerInstanceId": "beta", "driverKind": "kindB", "displayName": "Beta",
     "models": [{"id": "b-1", "label": "B One", "options": []}],
     "canRunChildTask": False, "constraints": ["Provider instance is disabled."]}]}
LISTING_TOOL = "mcp__t3-code__orchestrator_capabilities"
DELEGATE_TOOL = "mcp__t3-code__delegate_task"


def driver_file(path, **over):
    d = {"name": "fakeagent", "exe": "fakeagent", "run": ["fakeagent", "-p", "{prompt}", "{model_flag}"],
         "list": ["fakeagent", "models"], "list_kind": "lines", "model_flag": "--model", "effort_flag": None,
         "cwd_flag": None, "plan": "flat", "auth_signatures": None, "limit_signatures": ["allowance used up"],
         "tokens_regex": "total tokens: (\\d+)", "approvals_off_reason": None, "notes": "a test driver"}
    d.update(over)
    with open(path, "w") as f:
        json.dump(d, f)
    return path


def hook_payload(tool, result=None, tool_input=None):
    out = {"hook_event_name": "PostToolUse", "tool_name": tool, "session_id": "s1", "cwd": os.getcwd(),
           "tool_input": tool_input or {}}
    if result is not None:
        out["tool_response"] = result
    return out


def wrapped(listing):
    return {"content": [{"type": "text", "text": json.dumps(listing)}]}


class DiscoveryCase(SisiCase):
    def setUp(self):
        super().setUp()
        self.userbin = os.path.join(self.home, ".local", "bin")
        self.bindir = os.path.join(self.tmp, "sysbin")
        os.makedirs(self.userbin)
        os.makedirs(self.bindir)
        git = shutil.which("git")
        if git:  # decisions and the store's history need git; nothing else of the machine's tools is on this PATH
            os.symlink(git, os.path.join(self.bindir, "git"))
        self.marker = os.path.join(self.tmp, "mark")
        self.argsfile = os.path.join(self.tmp, "args")
        patcher = mock.patch.dict(os.environ, {"PATH": self.userbin + os.pathsep + self.bindir,
                                               "FAKE_MARK": self.marker, "FAKE_ARGS": self.argsfile})
        patcher.start()
        self.addCleanup(patcher.stop)
        discovery._DATA.clear()

    def exe(self, name, body=FAKE_AGENT, where=None):
        p = os.path.join(where or self.userbin, name)
        with open(p, "w") as f:
            f.write(body)
        os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
        return p

    def runs(self):
        return open(self.marker).read().split() if os.path.exists(self.marker) else []

    def write_cfg(self, obj):
        os.makedirs(self.data, exist_ok=True)
        with open(os.path.join(self.data, "config.json"), "w") as f:
            json.dump(obj, f)

    def write_data(self, name, obj):
        os.makedirs(self.data, exist_ok=True)
        with open(os.path.join(self.data, name), "w") as f:
            json.dump(obj, f)

    def feed(self, tool, result=None, tool_input=None):
        """The after-tool hook's call, in process; returns what it printed."""
        import contextlib, io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            discovery.after_tool(hook_payload(tool, result, tool_input))
        return out.getvalue()

    def host_state(self):
        with open(discovery.host_state_file()) as f:
            return json.load(f)

    def learn(self, **over):
        self.exe("fakeagent")
        f = driver_file(os.path.join(self.tmp, "driver.json"), **over)
        return self.sisi("workers", "learn", "fakeagent", "--record", f, "--by", "tester")


# ---------------------------------------------------------------- item 2: a new tool on PATH


class NewToolOnPath(DiscoveryCase):
    def test_first_run_prints_nothing_second_run_names_the_new_tool_once(self):
        self.exe("oldtool", "#!/bin/sh\n")
        self.assertEqual(discovery.session_start(now=1000.0), "")  # stores the list, says nothing
        time.sleep(0.02)
        self.exe("shinyagent", "#!/bin/sh\necho ran >> %s\n" % self.marker)
        line = discovery.session_start(now=1001.0)
        self.assertIn("shinyagent", line)
        self.assertNotIn("oldtool", line)
        self.assertIn("sisi workers learn", line)
        self.assertEqual(len(line.splitlines()), 1)
        self.assertEqual(discovery.session_start(now=1002.0), "", "the same name is announced once")
        self.assertEqual(discovery.session_start(now=1000.0 + 7 * 3600), "", "and not again after the age passes")
        self.assertEqual(self.runs(), [], "nothing on PATH is ever executed")

    def test_a_name_that_leaves_and_comes_back_is_not_announced_again(self):
        discovery.session_start(now=1.0)
        time.sleep(0.02)
        p = self.exe("wanderer")
        self.assertIn("wanderer", discovery.session_start(now=2.0))
        time.sleep(0.02)
        os.unlink(p)
        self.assertEqual(discovery.session_start(now=3.0), "")
        time.sleep(0.02)
        self.exe("wanderer")
        self.assertEqual(discovery.session_start(now=4.0), "")

    def test_the_tick_hook_prints_the_notice_once_over_two_session_starts(self):
        env = {"PATH": self.userbin + os.pathsep + os.environ["PATH"]}
        first = self.sisi_proc("tick", stdin=json.dumps({"session_id": "a1", "source": "startup", "cwd": self.proj}), env=env)
        self.assertNotIn("new command-line tool", first.stdout)
        time.sleep(0.02)
        self.exe("brandnew")
        second = self.sisi_proc("tick", stdin=json.dumps({"session_id": "a2", "source": "startup", "cwd": self.proj}), env=env)
        self.assertEqual(second.stdout.count("brandnew"), 1, second.stdout + second.stderr)
        third = self.sisi_proc("tick", stdin=json.dumps({"session_id": "a3", "source": "startup", "cwd": self.proj}), env=env)
        self.assertNotIn("brandnew", third.stdout)

    def test_only_user_level_folders_are_listed(self):
        discovery.session_start(now=1.0)
        self.exe("sysonly", where=self.bindir)  # outside the home: a system folder
        self.assertEqual(self.sisi_free(), "")

    def sisi_free(self):
        return discovery.session_start(now=2.0)

    def test_at_most_five_names_agent_looking_ones_first(self):
        discovery.session_start(now=1.0)
        time.sleep(0.02)
        for n in ("aaa", "bbb", "ccc", "ddd", "eee", "fff", "my-agent"):
            self.exe(n)
        line = discovery.session_start(now=2.0)
        self.assertIn("my-agent", line)
        self.assertIn("and 2 more", line)
        self.assertEqual(sum(1 for n in ("aaa", "bbb", "ccc", "ddd", "eee", "fff", "my-agent") if n in line), 5)

    def test_shells_and_tools_sisi_already_knows_are_not_announced(self):
        discovery.session_start(now=1.0)
        time.sleep(0.02)
        for n in ("bash", "codex"):
            self.exe(n)
        self.assertEqual(discovery.session_start(now=2.0), "")

    def test_the_cached_list_is_not_rescanned_until_something_changes(self):
        discovery.session_start(now=1.0)
        with mock.patch.object(discovery, "list_executables", side_effect=AssertionError("rescanned")):
            self.assertEqual(discovery.session_start(now=2.0), "")
        # the counter and the age each force a rescan
        with mock.patch.object(discovery, "list_executables", return_value=[]) as m:
            discovery.session_start(now=1.0 + 7 * 3600)
            self.assertTrue(m.called)
        self.write_cfg({"discovery": {"path_every_starts": 2}})
        with mock.patch.object(discovery, "list_executables", return_value=[]) as m:
            discovery.session_start(now=1.0 + 7 * 3600 + 1)
            self.assertFalse(m.called)
            discovery.session_start(now=1.0 + 7 * 3600 + 2)
            self.assertTrue(m.called)


# ---------------------------------------------------------------- item 1: what the host can reach


class HostListing(DiscoveryCase):
    def test_listing_records_enabled_workers_exactly_as_named_and_says_so_once(self):
        out = self.feed(LISTING_TOOL, wrapped(LISTING))
        msg = json.loads(out)
        self.assertIn("2 new workers", msg["systemMessage"])
        self.assertEqual(len(out.splitlines()), 1)
        prov = self.host_state()["hosts"]["t3-code"]["providers"]
        self.assertEqual(sorted(prov["alpha"]["models"]), ["m-1", "m-2"])
        self.assertTrue(prov["alpha"]["usable"])
        self.assertFalse(prov["beta"]["usable"])
        self.assertEqual(self.feed(LISTING_TOOL, wrapped(LISTING)), "", "once per set of new workers")
        bigger = json.loads(json.dumps(LISTING))
        bigger["providers"][0]["models"].append({"id": "m-3", "label": "M Three"})
        self.assertIn("1 new worker ", json.loads(self.feed(LISTING_TOOL, bigger))["systemMessage"])

    def test_every_shape_a_host_may_wrap_the_result_in_is_read(self):
        for result in (LISTING, wrapped(LISTING), json.dumps(LISTING), [{"type": "text", "text": json.dumps(LISTING)}]):
            if os.path.exists(discovery.host_state_file()):
                os.unlink(discovery.host_state_file())
            self.assertIn("2 new workers", self.feed(LISTING_TOOL, result))

    def test_a_disabled_provider_is_never_routable(self):
        self.feed(LISTING_TOOL, wrapped(LISTING))
        cands = {c["worker"]: c for c in workers.build_candidates()}
        self.assertTrue(cands["alpha/m-1"]["usable"])
        self.assertFalse(cands["beta/b-1"]["usable"])
        self.assertIn("disabled", cands["beta/b-1"]["reason"])
        self.assertFalse(cands["beta/b-1"].get("unproven_ok"))
        self.assertNotIn("beta/b-1", workers.facts_line())
        self.assertIn("alpha/m-1", workers.facts_line())
        self.assertNotIn("beta", self.sisi("route", "--kind", "read", "--difficulty", "1").stdout.splitlines()[0])
        shown = self.sisi("workers").stdout
        self.assertIn("beta - not usable now", shown)
        self.assertIn("alpha - usable now", shown)

    def test_a_routed_host_worker_names_the_provider_and_model_to_pass_to_the_hosts_delegation_tool(self):
        self.feed(LISTING_TOOL, wrapped(LISTING))
        r = self.sisi("route", "--kind", "read", "--difficulty", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0], "alpha/m-1")
        self.assertIn("mechanism: use the host's cross-provider delegation", lines[1])
        self.assertIn("delegate_task", lines[1])
        self.assertIn("target.providerInstanceId=alpha", lines[1])
        self.assertIn("target.model=m-1", lines[1])
        self.assertIn("unproven: check this result with at least the tests or a read of the diff", r.stdout)

    def test_sisi_delegate_does_not_run_a_host_worker_it_says_how_the_host_starts_it(self):
        self.feed(LISTING_TOOL, wrapped(LISTING))
        brief = os.path.join(self.proj, "b.md")
        open(brief, "w").write(BRIEF)
        r = self.sisi("delegate", "--kind", "read", "--difficulty", "1", "--brief", brief, "--worker", "alpha/m-1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("target.providerInstanceId=alpha", r.stdout)
        self.assertIn("target.model=m-1", r.stdout)

    def test_a_worker_gone_from_enough_listings_is_dropped(self):
        self.feed(LISTING_TOOL, wrapped(LISTING))
        only_beta = {"providers": [LISTING["providers"][1]]}
        self.feed(LISTING_TOOL, wrapped(only_beta))
        self.feed(LISTING_TOOL, wrapped(only_beta))
        self.assertIn("alpha", self.host_state()["hosts"]["t3-code"]["providers"], "two listings: still kept")
        self.feed(LISTING_TOOL, wrapped(only_beta))
        self.assertNotIn("alpha", self.host_state()["hosts"]["t3-code"]["providers"])
        self.write_cfg({"discovery": {"drop_after_listings": 1}})
        self.feed(LISTING_TOOL, wrapped(LISTING))
        self.feed(LISTING_TOOL, wrapped(only_beta))
        self.assertNotIn("alpha", self.host_state()["hosts"]["t3-code"]["providers"])

    def test_a_delegation_seen_in_use_is_recorded_and_not_announced(self):
        out = self.feed(DELEGATE_TOOL, tool_input={"task": "x", "target": {"providerInstanceId": "gamma", "model": "g-1"}})
        self.assertEqual(out, "")
        rec = self.host_state()["hosts"]["t3-code"]["providers"]["gamma"]["models"]["g-1"]
        self.assertEqual(rec["source"], "delegation")
        self.assertEqual([c["worker"] for c in workers.build_candidates() if c["tool"] == "gamma"], ["gamma/g-1"])
        self.feed(DELEGATE_TOOL, tool_input={"target": {"providerInstanceId": 5, "model": None}})  # malformed: ignored

    def test_hundreds_of_models_are_stored_but_only_used_priced_or_ranked_ones_are_candidates(self):
        big = {"providers": [{"providerInstanceId": "big", "driverKind": "k", "displayName": "Big", "canRunChildTask": True,
                              "constraints": [], "models": [{"id": "m-%d" % i, "label": "m"} for i in range(300)]}]}
        self.assertEqual(self.feed(LISTING_TOOL, wrapped(big)), "", "a catalogue is not announced worker by worker")
        self.assertEqual(len(self.host_state()["hosts"]["t3-code"]["providers"]["big"]["models"]), 300)
        self.write_data("worker-prices.json", {"models": {"big/m-7": {"plan": "per-use", "cost_per_million_tokens": 2.0,
                                                                     "source": "s", "date": "2026-11-01"}}})
        self.write_data("model-strength.json", {"models": {"big/m-9": {"standing": 50, "source": "s", "date": "2026-11-01"}}})
        cands = workers.build_candidates()
        self.assertEqual(len([c for c in cands if c["tool"] == "big"]), 300)
        keep, cold, excluded = workers.routable_candidates(cands, [])
        self.assertEqual(sorted(c["worker"] for c in keep), ["big/m-7", "big/m-9"])
        self.assertEqual(excluded, 298)
        self.assertFalse(cold)

    def test_input_that_is_not_json_is_ignored(self):
        env = {"SISI_STATE": self.state}
        for stdin in ("this is not json", "[1,2]", "", '{"tool_name": 7}', json.dumps(hook_payload(LISTING_TOOL, "not json at all"))):
            r = self.sisi_proc("watch", "--after", stdin=stdin, env=env)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout, "")
        self.assertFalse(os.path.exists(discovery.host_state_file()))

    def test_the_real_hook_command_records_and_prints_one_line(self):
        r = self.sisi_proc("watch", "--after", stdin=json.dumps(hook_payload(LISTING_TOOL, wrapped(LISTING))))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(r.stdout.splitlines()), 1, r.stdout)
        self.assertIn("2 new workers", json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"])

    def test_a_payload_that_is_not_an_object_does_nothing(self):
        for payload in (None, [1], "x", 5, {}, {"tool_name": None}, {"tool_name": LISTING_TOOL}):
            discovery.after_tool(payload)
        self.assertFalse(os.path.exists(discovery.host_state_file()))

    def test_other_tools_cost_nothing_and_are_left_alone(self):
        self.assertEqual(self.feed("Read", {"x": 1}), "")
        self.assertEqual(self.feed("Bash"), "")
        self.assertFalse(os.path.exists(discovery.host_state_file()))

    def test_forgetting_a_host_provider(self):
        self.feed(LISTING_TOOL, wrapped(LISTING))
        r = self.sisi("workers", "forget", "alpha")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("alpha", self.host_state()["hosts"]["t3-code"]["providers"])
        self.assertEqual(self.sisi("workers", "forget", "nobody").returncode, 1)


# ---------------------------------------------------------------- item 3: a driver learned as data


class LearnedDriver(DiscoveryCase):
    def check_file(self, **over):
        self.exe("fakeagent")
        f = driver_file(os.path.join(self.tmp, "d.json"), **over)
        return self.sisi("workers", "learn", "fakeagent", "--check", f)

    def test_the_brief_is_a_valid_delegation_contract_naming_the_format(self):
        self.exe("fakeagent")
        r = self.sisi("workers", "learn", "fakeagent")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(brief_contract.missing_required(r.stdout), [])
        for word in ("{prompt}", "approvals_off_reason", "--record", "tokens_regex", "limit_signatures", "help"):
            self.assertIn(word, r.stdout)
        self.assertEqual(self.sisi("workers", "learn", "nosuchtool").returncode, 1)

    def test_record_validates_stores_runs_one_smoke_task_and_marks_the_driver_usable(self):
        r = self.learn()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PASSED", r.stdout)
        self.assertEqual(self.runs(), ["ran"], "exactly one task: the smoke task")
        rec = discovery.load_drivers()["fakeagent"]
        self.assertEqual(rec["state"], "usable")
        self.assertEqual(rec["learned_by"], "tester")
        self.assertEqual(rec["models"], ["fa-1", "fa-2"])
        shown = self.sisi("workers").stdout
        self.assertIn("fakeagent - usable now", shown)
        self.assertIn("learned by tester on", shown)
        self.assertIn("models: fa-1, fa-2", shown)
        self.assertTrue(os.path.exists(os.path.join(self.data, "worker-drivers.json")))

    def test_a_template_that_tries_shell_injection_through_the_placeholder_is_refused(self):
        self.exe("fakeagent")
        cases = [dict(run=["sh", "-c", "fakeagent {prompt}"], exe="sh"),
                 dict(run=["fakeagent", "-p", "--prompt={prompt}"]),
                 dict(run=["fakeagent", "-c", "echo {prompt}; {prompt}"]),
                 dict(run=["fakeagent", "-p", "{prompt}", "{prompt}"]),
                 dict(run=["fakeagent", "-p", "x"]),
                 dict(run=["fakeagent", "-p", "{prompt}\n; rm -rf ~"]),
                 dict(run=["fakeagent", "-p", "{prompt}", "{unknown}"]),
                 dict(run=["bash", "-c", "{prompt}"], exe="bash", name="fakeagent")]
        for over in cases:
            f = driver_file(os.path.join(self.tmp, "bad.json"), **over)
            r = self.sisi("workers", "learn", "fakeagent", "--record", f)
            self.assertEqual(r.returncode, 1, (over, r.stdout))
            self.assertIn("not valid", r.stdout)
        self.assertEqual(self.runs(), [], "a refused file never runs anything")
        self.assertEqual(discovery.load_drivers(), {})

    def test_a_binary_not_on_path_or_another_tool_than_the_one_named_is_refused(self):
        self.exe("fakeagent")
        for over in (dict(exe="ghostagent", name="ghostagent", run=["ghostagent", "{prompt}"]),
                     dict(exe="/bin/sh", run=["/bin/sh", "{prompt}"]),
                     dict(exe="fakeagent", name="codex"),
                     dict(unexpected=1)):
            f = driver_file(os.path.join(self.tmp, "bad.json"), **over)
            self.assertEqual(self.sisi("workers", "learn", "fakeagent", "--record", f).returncode, 1, over)
        other = self.exe("otheragent")
        f = driver_file(os.path.join(self.tmp, "o.json"), name="otheragent", exe="otheragent", run=["otheragent", "{prompt}"],
                        list=None, list_kind=None)
        r = self.sisi("workers", "learn", "fakeagent", "--record", f)  # a file for another tool than the one named
        self.assertEqual(r.returncode, 1)
        self.assertIn("must both be 'fakeagent'", r.stdout)
        self.assertEqual(self.runs(), [])

    def test_a_shell_or_interpreter_is_not_a_tool_even_when_the_name_matches(self):
        self.exe("sh")  # a command on PATH that is not an agent tool
        f = driver_file(os.path.join(self.tmp, "sh.json"), name="sh", exe="sh", run=["sh", "{prompt}"], list=None,
                        list_kind=None, model_flag=None)
        r = self.sisi("workers", "learn", "sh", "--check", f)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("shell or interpreter", r.stdout)

    def test_a_file_that_is_not_json_or_too_large_is_refused(self):
        self.exe("fakeagent")
        p = os.path.join(self.tmp, "x.json")
        open(p, "w").write("{not json")
        self.assertEqual(self.sisi("workers", "learn", "fakeagent", "--record", p).returncode, 1)
        open(p, "w").write(json.dumps({"name": "fakeagent", "notes": "x" * 30000}))
        self.assertEqual(self.sisi("workers", "learn", "fakeagent", "--record", p).returncode, 1)
        self.assertEqual(self.sisi("workers", "learn", "fakeagent", "--record", os.path.join(self.tmp, "nope")).returncode, 1)

    def test_the_brief_reaches_the_tool_as_one_argument_never_a_shell_string(self):
        self.learn()
        os.unlink(self.marker)
        brief = os.path.join(self.proj, "b.md")
        pwn = os.path.join(self.tmp, "pwned")
        open(brief, "w").write(BRIEF + '\n"; touch %s; $(touch %s) `touch %s` \'\n' % (pwn, pwn, pwn))
        r = self.sisi("delegate", "--kind", "read", "--difficulty", "1", "--brief", brief, "--worker", "fakeagent/default")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(pwn))
        self.assertEqual(open(self.argsfile).read().strip(), "2", "the tool saw -p and ONE prompt argument")

    def test_a_learned_driver_runs_like_a_built_in_one_usage_and_judging(self):
        self.learn()
        r = self.sisi("delegate", "--kind", "read", "--difficulty", "1", "--brief", self.brief())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Do the toy task", r.stdout)  # the report: the tool echoed the brief
        self.assertIn("worker: fakeagent/default", r.stdout)
        self.assertIn("unproven: check this result with at least the tests or a read of the diff", r.stdout)
        run = [x for x in workers.read_records() if x.get("kind") == "run"][-1]
        self.assertEqual(run["tokens"], 321)
        self.assertEqual(run["tokens_class"], "measured")
        j = self.sisi("delegate", "judge", run["id"], "--outcome", "accepted", "--check", "read")
        self.assertEqual(j.returncode, 0, j.stdout + j.stderr)
        self.assertEqual([r["worker"] for r in workers.read_records() if r.get("kind") == "attempt"], ["fakeagent/default"])

    def brief(self):
        p = os.path.join(self.proj, "brief.md")
        open(p, "w").write(BRIEF)
        return p

    def test_the_drivers_own_limit_phrase_is_unavailability_and_the_next_worker_runs(self):
        self.learn()
        self.exe("second", FAKE_AGENT.replace("echo \"$last\"", "echo \"$last\"; echo \"second worker report\""))
        f = driver_file(os.path.join(self.tmp, "s.json"), name="second", exe="second", run=["second", "-p", "{prompt}"],
                        list=None, list_kind=None, model_flag=None)
        self.assertEqual(self.sisi("workers", "learn", "second", "--record", f).returncode, 0)
        # `fakeagent` now reports its allowance used up (the learned phrase); the second tool answers
        self.exe("fakeagent", FAKE_AGENT.replace('case "$FAKE_MODE"', 'FAKE_MODE=quota\ncase "$FAKE_MODE"'))
        r = self.sisi("delegate", "--kind", "read", "--difficulty", "1", "--brief", self.brief(), "--worker", "fakeagent/default")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("second worker report", r.stdout)
        self.assertIn("fakeagent/default is unavailable (limit", r.stdout)

    def test_a_smoke_task_that_fails_leaves_the_driver_unusable_with_the_reason(self):
        for mode, kind in (("login", "login"), ("quota", "quota"), ("flag", "bad-template"), ("silent", "no-answer")):
            discovery.save_drivers({})
            with mock.patch.dict(os.environ, {"FAKE_MODE": mode}):
                r = self.learn()
            self.assertEqual(r.returncode, 1, (mode, r.stdout))
            self.assertIn("FAILED (%s)" % kind, r.stdout)
            rec = discovery.load_drivers()["fakeagent"]
            self.assertNotEqual(rec["state"], "usable")
            self.assertIn(kind, rec["reason"])
            self.assertIsNone(discovery.driver_for("fakeagent"))
            shown = self.sisi("workers").stdout
            self.assertIn("fakeagent - not usable now", shown)
            self.assertIn(kind, shown)
            cands = {c["worker"]: c for c in workers.build_candidates()}
            self.assertFalse(cands["fakeagent/default"]["usable"])
        # a login the owner then completes: --verify proves it
        discovery.save_drivers({})
        with mock.patch.dict(os.environ, {"FAKE_MODE": "login"}):
            self.learn()
            self.assertEqual(self.sisi("workers", "learn", "fakeagent", "--verify").returncode, 1)
        r = self.sisi("workers", "learn", "fakeagent", "--verify")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIsNotNone(discovery.driver_for("fakeagent"))

    def test_a_task_that_waits_for_a_question_is_stopped_by_the_time_limit(self):
        self.write_cfg({"discovery": {"smoke_timeout_s": 1}})
        with mock.patch.dict(os.environ, {"FAKE_MODE": "hang"}):
            r = self.learn()
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAILED (timeout)", r.stdout)
        self.assertEqual(discovery.load_drivers()["fakeagent"]["state"], "failed")

    def test_the_smoke_task_runs_in_a_temporary_folder_with_no_input(self):
        body = FAKE_AGENT.replace('echo "$last"', 'pwd > "$FAKE_ARGS.cwd"; read x && echo "got input" >> "$FAKE_ARGS.cwd"; echo "$last"')
        self.exe("fakeagent", body)
        f = driver_file(os.path.join(self.tmp, "d.json"))
        self.assertEqual(self.sisi("workers", "learn", "fakeagent", "--record", f).returncode, 0)
        seen = open(self.argsfile + ".cwd").read()
        self.assertIn("sisi-smoke-", seen)
        self.assertNotIn("got input", seen)
        self.assertFalse(os.path.exists(seen.splitlines()[0]), "the temporary folder is removed")

    def test_forget_removes_a_learned_driver(self):
        self.learn()
        self.assertEqual(self.sisi("workers", "forget", "fakeagent").returncode, 0)
        self.assertEqual(discovery.load_drivers(), {})
        self.assertNotIn("fakeagent", self.sisi("workers").stdout)

    def test_the_bypass_flag_patterns_catch_the_known_spellings(self):
        for flag in ("--dangerously-skip-permissions", "--dangerously-bypass-approvals-and-sandbox", "--yolo", "-y",
                     "--always-approve", "--allow-all", "--force", "--auto", "--no-sandbox", "--full-auto",
                     "--approval-mode=yolo", "--sandbox=off"):
            self.assertEqual(discovery.bypass_args(["t", "-p", flag]), [flag], flag)
        for flag in ("-p", "--print", "--model", "--output-format", "--sandbox", "text"):
            self.assertEqual(discovery.bypass_args(["t", flag]), [], flag)


class WaitsForTheOwner(DiscoveryCase):
    def bypass(self):
        self.exe("fakeagent")
        f = driver_file(os.path.join(self.tmp, "d.json"), run=["fakeagent", "--dangerously-skip-permissions", "-p", "{prompt}"],
                        approvals_off_reason="cannot run unattended without it")
        return self.sisi("workers", "learn", "fakeagent", "--record", f)

    def test_an_approvals_off_driver_is_stored_waiting_and_nothing_runs(self):
        r = self.bypass()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("WAITING FOR THE OWNER", r.stdout)
        self.assertIn("fakeagent --dangerously-skip-permissions -p {prompt}", r.stdout)
        self.assertIn("cannot run unattended without it", r.stdout)
        self.assertEqual(discovery.load_drivers()["fakeagent"]["state"], "waiting-owner")
        self.assertEqual(self.runs(), [], "not even the smoke task ran")
        self.assertIsNone(discovery.driver_for("fakeagent"))
        cands = {c["worker"]: c for c in workers.build_candidates()}
        self.assertFalse(cands["fakeagent/default"]["usable"])
        self.assertIn("waiting for the owner", self.sisi("workers").stdout)
        self.assertNotEqual(self.sisi("route", "--kind", "read", "--difficulty", "1").stdout.splitlines()[:1], ["fakeagent/default"])
        brief = os.path.join(self.proj, "b.md")
        open(brief, "w").write(BRIEF)
        d = self.sisi("delegate", "--kind", "read", "--difficulty", "1", "--brief", brief, "--worker", "fakeagent/default")
        self.assertEqual(d.returncode, 1)
        self.assertEqual(self.runs(), [])
        self.assertEqual(self.sisi("workers", "learn", "fakeagent", "--verify").returncode, 1)
        self.assertEqual(self.runs(), [])

    def test_approve_lists_the_exact_command_and_an_agent_cannot_decide(self):
        self.bypass()
        listing = self.sisi("approve").stdout
        self.assertIn("drv-fakeagent", listing)
        self.assertIn("fakeagent --dangerously-skip-permissions -p {prompt}", listing)
        refused = self.sisi("approve", "drv-fakeagent", "--yes")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("typed at a terminal", refused.stderr)
        self.assertEqual(discovery.load_drivers()["fakeagent"]["state"], "waiting-owner")
        self.assertEqual(self.runs(), [])
        self.assertEqual(self.sisi("approve", "drv-ghost", "--yes").returncode, 2)

    def test_the_owners_yes_runs_the_smoke_task_and_only_then_the_driver_is_usable(self):
        self.bypass()
        owner = terminal()  # the owner's own terminal: the full action is shown and the word typed back
        with owner:
            r = self.sisi("approve", "drv-fakeagent", "--yes")
        t = owner.fake
        self.assertIn("fakeagent --dangerously-skip-permissions -p {prompt}", t.text)
        self.assertIn("Type the word", t.text)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PASSED", r.stdout)
        self.assertEqual(discovery.load_drivers()["fakeagent"]["state"], "usable")
        self.assertEqual(self.runs(), ["ran"])

    def test_the_owners_no_removes_the_driver(self):
        self.bypass()
        with terminal():
            self.assertEqual(self.sisi("approve", "drv-fakeagent", "--no").returncode, 0)
        self.assertEqual(discovery.load_drivers(), {})
        self.assertEqual(self.runs(), [])


# ---------------------------------------------------------------- item 4: new workers earn their place


def cand(worker, plan=None, cost=None, unproven=False, **kw):
    tool, model = worker.split("/")
    return dict({"worker": worker, "tool": tool, "model": model, "plan": plan, "cost": cost, "usable": True,
                 "allowance_pct_left": None, "aliases": [worker], "maker": model, "unproven": unproven,
                 "unproven_ok": unproven}, **kw)


def attempts(worker, n, kind="read", difficulty=1, outcome="accepted"):
    return [{"kind": "attempt", "worker": worker, "type": kind, "difficulty": difficulty, "outcome": outcome,
             "id": "%s-%d-%d" % (worker, difficulty, i)} for i in range(n)]


class NewWorkersEarnTheirPlace(unittest.TestCase):
    def test_a_new_worker_is_never_chosen_above_routine_work(self):
        proven = cand("old/a", plan="flat")
        new = cand("new/b", plan="flat", unproven=True)
        records = attempts("old/a", 8, "impl", 3)
        for d in (2, 3):
            r = routing.choose([proven, new], records, {}, "impl", d, now=1.0)
            self.assertEqual(r["choice"]["worker"], "old/a")
            self.assertTrue(any(w == "new/b" and "unproven" in why for w, why in r["passed_over"]))
        alone = routing.choose([new], [], {}, "impl", 3, now=1.0)
        self.assertIsNone(alone["choice"], "nobody else: the main agent does it, the new worker is not tried on hard work")
        self.assertIsNone(routing.choose([new], [], {}, "impl", 2, now=1.0)["choice"])
        self.assertEqual(routing.choose([new], [], {}, "impl", 1, now=1.0)["choice"]["worker"], "new/b")

    def test_a_benchmark_standing_does_not_unlock_hard_work_for_an_unproven_worker(self):
        new = cand("new/b", plan="flat", unproven=True, standing=99.0)
        old = cand("old/a", plan="per-use", cost=1.0, standing=10.0)
        self.assertEqual(routing.choose([new, old], [], {}, "impl", 3, now=1.0)["choice"]["worker"], "old/a")

    def test_after_enough_judged_attempts_it_competes_by_the_ordinary_rules(self):
        worker = cand("new/b", plan="flat", unproven=False)
        r = routing.choose([worker], attempts("new/b", 8, "impl", 2), {}, "impl", 2, now=1.0)
        self.assertEqual(r["choice"]["worker"], "new/b")

    def test_a_free_new_worker_gets_one_routine_task_in_three_a_paid_one_never_by_this_slot(self):
        old = cand("old/a", plan="flat", cost=1.0)
        free = cand("new/b", plan="flat", unproven=True)
        paid = cand("new/c", plan="per-use", cost=0.5, unproven=True)
        picks = {}
        for total in range(8, 14):
            records = attempts("old/a", total)
            picks[total] = routing.choose([old, free], records, {}, "read", 1, now=1.0, explore_free_every=3)["choice"]["worker"]
        self.assertEqual([picks[t] for t in range(8, 14)],
                         ["new/b" if t % 3 == 2 else "old/a" for t in range(8, 14)], picks)
        r = routing.choose([old, free], attempts("old/a", 8), {}, "read", 1, now=1.0, explore_free_every=3)
        self.assertTrue(r["explored_free"])
        self.assertTrue(any("costs nothing extra" in why for w, why in r["passed_over"] if w == "old/a"))
        # the config knob: every task, or never
        self.assertEqual(routing.choose([old, free], attempts("old/a", 9), {}, "read", 1, now=1.0,
                                        explore_free_every=1)["choice"]["worker"], "new/b")
        self.assertEqual(routing.choose([old, free], attempts("old/a", 8), {}, "read", 1, now=1.0,
                                        explore_free_every=0)["choice"]["worker"], "old/a")
        # a paid unproven worker is not in the free slot (the existing one-in-ten covers it)
        self.assertEqual(routing.choose([old, paid], attempts("old/a", 8), {}, "read", 1, now=1.0,
                                        explore_free_every=3)["choice"]["worker"], "old/a")

    def test_the_rate_is_read_from_config(self):
        with mock.patch.object(workers, "route_cfg", return_value={"explore_free_one_in": 5}):
            self.assertEqual(workers.explore_free_every(), 5)
        with mock.patch.object(workers, "route_cfg", return_value={}):
            self.assertEqual(workers.explore_free_every(), 3)
        with mock.patch.object(workers, "route_cfg", return_value={"explore_free_one_in": "x"}):
            self.assertEqual(workers.explore_free_every(), 3)
        self.assertEqual(json.load(open(os.path.join(REPO, "config.default.json")))["route"]["explore_free_one_in"], 3)


class NewWorkersThroughTheCommands(DiscoveryCase):
    def test_route_says_unproven_until_the_record_has_enough_attempts(self):
        self.learn()
        r = self.sisi("route", "--kind", "read", "--difficulty", "1", "--explain")
        self.assertEqual(r.stdout.splitlines()[0], "fakeagent/default", r.stdout)
        self.assertIn("unproven: check this result with at least the tests or a read of the diff", r.stdout)
        self.assertNotEqual(self.sisi("route", "--kind", "read", "--difficulty", "3").stdout.splitlines()[:1], ["fakeagent/default"])
        for w in ("fakeagent/default", "fakeagent/fa-1", "fakeagent/fa-2"):
            for row in attempts(w, 8):
                workers.append_record(row)
        r = self.sisi("route", "--kind", "read", "--difficulty", "1")
        self.assertTrue(r.stdout.startswith("fakeagent/"))
        self.assertNotIn("unproven", r.stdout)

    def test_a_flat_plan_from_the_driver_or_a_fact_is_a_flat_plan_and_unknown_is_per_use(self):
        self.learn()
        c = {c["worker"]: c for c in workers.build_candidates()}["fakeagent/default"]
        self.assertEqual(c["plan"], "flat")
        discovery.save_drivers(dict(discovery.load_drivers(), fakeagent=dict(
            discovery.load_drivers()["fakeagent"], driver=dict(discovery.load_drivers()["fakeagent"]["driver"], plan=None))))
        c = {c["worker"]: c for c in workers.build_candidates()}["fakeagent/default"]
        self.assertEqual(c["plan"], "per-use")
        self.write_data("worker-prices.json", {"tools": {"fakeagent": {"plan": "flat", "source": "s", "date": "2026-11-01"}}})
        c = {c["worker"]: c for c in workers.build_candidates()}["fakeagent/default"]
        self.assertEqual(c["plan"], "flat")


# ---------------------------------------------------------------- item 5: facts follow


class FactsNameTheNewWorkers(DiscoveryCase):
    def test_the_missing_facts_line_names_at_most_three_new_workers(self):
        self.write_data("worker-prices.json", {"models": {"other/x": {"plan": "per-use", "cost_per_million_tokens": 1.0,
                                                                     "source": "s", "date": time.strftime("%Y-%m-%d")}}})
        self.assertEqual(workers.facts_line(), "", "facts are fresh and nobody new lacks any")
        many = {"providers": [{"providerInstanceId": "p%d" % i, "driverKind": "k", "displayName": "P", "canRunChildTask": True,
                               "constraints": [], "models": [{"id": "m", "label": "m"}]} for i in range(7)]}
        self.feed(LISTING_TOOL, wrapped(many))
        line = workers.facts_line()
        self.assertIn("worker facts are missing for the new workers p0/m", line)
        self.assertIn("and 4 more", line)
        self.assertEqual(sum(1 for i in range(7) if "p%d/m" % i in line), 3)
        self.assertIn("sisi workers fact W --price N", line)
        for i in range(7):
            self.write_data("model-strength.json", {"models": {"p%d/m" % j: {"standing": 40, "source": "s", "date": "2026-11-01"}
                                                               for j in range(7)}})
        self.assertEqual(workers.facts_line(), "")

    def test_with_nothing_new_the_line_is_the_one_it_always_was(self):
        line = workers.facts_line()
        self.assertIn("worker facts are missing (no prices or benchmark standing recorded yet)", line)
        self.assertNotIn("new workers", line)

    def test_a_learned_tool_is_a_target_too(self):
        self.learn()
        self.assertIn("fakeagent/default", workers.facts_line())


if __name__ == "__main__":
    unittest.main()
