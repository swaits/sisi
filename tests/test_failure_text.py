"""A worker's failure is read from the END of what it printed, never from everything it read.

A worker's output holds every file it read, so a run that did its work was thrown away as "not logged in" or a
limit because the words were in a file it had opened, and its provider was marked down for days. A tool's own failure
message is the last thing it prints and a tool that failed to start prints little: `workers.failure_text` returns the
only text any classifier may read (the last 1,500 characters of each stream; nothing when the run exited 0 and printed
more than 4,000). The fixtures are trimmed parts of three real runs that exited 0 (each recorded as an auth failure
on 2026-11-23) and one that ended in a connection error.

Requirements: R-6-1 and R-9.7 (worker availability is recorded only when the worker was unavailable), R-4-4 (a result
that did not fail is not reported as failed)."""
import contextlib, io, json, os, time, unittest
from unittest import mock

import test_meter as TM
import test_providers as TP
from support import *
from sisi import fallback, orchestration, workers

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
SOURCE_LINE = '            notes.append("%s is unavailable (%s: %s); trying the next choice" % (cand["worker"], reason, note))'


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def big_exit0_output(size=60000, final="Done. The monthly usage limit was never an issue for this run."):
    """About `size` characters: a real run's opening, its middle (files it read: they hold the words 'rate limit'
    and the number 1113) repeated with the other failure phrases added, and a closing line."""
    middle = fixture("exit0_middle.txt")
    sprinkle = "not logged in\n401 unauthorized\nbilling\nrate limit\n1113\n"
    parts = [fixture("exit0_head.txt")]
    while sum(len(p) for p in parts) < size - 400:
        parts.append(middle + sprinkle)
    parts.append(fixture("exit0_tail.txt").replace("--- stderr ---", ""))
    parts.append(final + "\n")
    return "".join(parts)


def phrases_only_in_the_middle():
    """A large output whose last 1,500 characters are plain: what a failed run printed before its error."""
    return big_exit0_output() + "a plain line of the report\n" * 100


class FailureTextUnit(unittest.TestCase):
    def test_a_run_that_exited_zero_and_printed_a_lot_is_never_classified(self):
        out = big_exit0_output()
        self.assertGreater(len(out), 50000)
        self.assertEqual(workers.failure_text(out, "", 0), "")
        self.assertIsNone(workers.classify_failure(workers.failure_text(out, "", 0), 0))

    def test_a_short_exit_zero_run_is_read_whole(self):
        msg = "OpenCode Go monthly usage limit reached. Resets in 3 days."
        self.assertIn(msg, workers.failure_text(msg, "", 0))
        self.assertEqual(workers.classify_failure(workers.failure_text(msg, "", 0), 0)[0], "limit")

    def test_a_failed_run_is_read_from_the_end_of_each_stream(self):
        out = "usage limit reached\n" + "x" * 20000 + "\nthe end of stdout"
        err = "not logged in\n" + "y" * 20000 + "\nError: Transport: ECONNRESET"
        text = workers.failure_text(out, err, 1)
        self.assertIn("the end of stdout", text)
        self.assertIn("ECONNRESET", text)
        self.assertNotIn("usage limit", text)
        self.assertNotIn("not logged in", text)
        self.assertLessEqual(len(text), 2 * workers.FAILURE_TAIL_CHARS + 1)
        self.assertIsNone(workers.classify_failure(text, 1))

    def test_the_two_numbers_are_named_constants(self):
        self.assertEqual((workers.FAILURE_TAIL_CHARS, workers.QUIET_SUCCESS_CHARS), (1500, 4000))

    def test_missing_output_is_not_a_crash(self):
        self.assertEqual(workers.failure_text(None, None, None).strip(), "")


class Delegations(TP.ProviderCase):
    """`sisi delegate --worker zai/b` against a tool whose output and exit status the test sets."""
    TOOL = """#!/bin/sh
if [ "$1" = "models" ]; then echo "zai/a"; echo "zai/b"; echo "other/c"; exit 0; fi
model=""; prev=""
for a in "$@"; do if [ "$prev" = "--model" ]; then model="$a"; fi; prev="$a"; done
case "$model" in
  zai/*)
    printf '%s' "$FAKE_OUT"
    printf '%s' "$FAKE_ERR" >&2
    exit ${FAKE_RC:-0} ;;
esac
echo "other worker report"
exit 0
"""

    def setUp(self):
        super().setUp()
        self.sisi("workers", "plan", "zai", "flat", "--source", "owner")
        self.sisi("workers", "vouch", "zai/a", "--up-to", "2", "--why", "words")
        self.fact("zai/a", 3)
        self.fact("zai/b", 1)
        self.fact("other/c", 2)
        self.exe("multi", self.TOOL)

    def go(self, out="", err="", rc=0, worker="zai/b"):
        with mock.patch.dict(os.environ, {"FAKE_OUT": out, "FAKE_ERR": err, "FAKE_RC": str(rc)}):
            return self.sisi("delegate", "--kind", "read", "--difficulty", "1", "--brief", self.brief(), "--worker", worker)

    def runs(self):
        return [r for r in workers.read_records() if r.get("kind") == "run"]

    def test_a_run_that_finished_its_work_is_not_down_because_of_what_it_read(self):
        out = big_exit0_output()
        r = self.go(out=out, rc=0)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("is unavailable", r.stdout)
        self.assertIn("worker: zai/b", r.stdout)
        run = self.runs()[-1]
        self.assertEqual((run["worker"], run["status"], run["exit"]), ("zai/b", "waiting", 0))
        self.assertEqual(workers.read_availability(), {})

    def test_a_short_exit_zero_limit_message_is_still_a_limit(self):
        msg = ("OpenCode Go monthly usage limit reached. Your plan renews on the first of the month; "
               "until then no request is served. " * 3)[:300]
        r = self.go(out=msg, rc=0)
        self.assertIn("zai/b is unavailable (limit", r.stdout)
        self.assertEqual(workers.read_availability()["zai"]["reason"], "limit")
        self.assertIn("worker: other/c", r.stdout)

    def test_a_failed_run_that_ended_in_a_connection_error_is_a_failed_run_not_an_unavailable_worker(self):
        err = fixture("exit1_econnreset.txt").split("--- stderr ---", 1)[1]
        r = self.go(out=phrases_only_in_the_middle(), err="rate limit seen while reading\n" + "z" * 5000 + err, rc=1)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertNotIn("is unavailable", r.stdout)
        self.assertEqual(workers.read_availability(), {})
        run = self.runs()[-1]
        self.assertEqual((run["worker"], run["status"], run["exit"]), ("zai/b", "failed", 1))

    def test_a_failed_run_whose_stderr_ends_in_a_limit_message_is_a_limit_and_the_next_choice_runs(self):
        err = "\n" + "z" * 5000 + "\nError: monthly usage limit reached for this plan\n"
        r = self.go(out=phrases_only_in_the_middle(), err=err, rc=1)
        self.assertIn("zai/b is unavailable (limit", r.stdout)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("other worker report", r.stdout)
        self.assertIn("zai", workers.read_availability())

    def test_a_provider_phrase_in_the_middle_of_a_large_successful_output_is_not_a_failure(self):
        self.assertEqual(self.sisi("workers", "signature", "zai", "--match", "re:\\b1113\\b", "--class", "auth").returncode, 0)
        out = "x" * 3000 + "\nsisi/orchestration.py has 1113 lines\n" + "y" * 3000 + "\nall done\n"
        r = self.go(out=out, rc=0)
        self.assertNotIn("is unavailable", r.stdout)
        self.assertEqual(self.runs()[-1]["status"], "waiting")
        self.assertEqual(workers.read_availability(), {})

    def test_the_same_provider_phrase_at_the_end_of_a_failed_run_is_still_read(self):
        self.sisi("workers", "signature", "zai", "--match", "re:\\b1113\\b", "--class", "auth")
        r = self.go(out="x" * 5000, err='{"error":{"code":"1113","message":"no package"}}', rc=1)
        self.assertIn("zai/b is unavailable (auth", r.stdout)
        self.assertEqual(workers.read_availability()["zai"]["reason"], "auth")


class Timeout(TP.ProviderCase):
    def setUp(self):
        super().setUp()
        self.fact("zai/b", 1)

    def delegate(self, *extra, cfg=None):
        if cfg:
            self.write_cfg(dict({"discovery": {"allowance_timeout_s": 1}}, **cfg))
        seen = []

        def fake_run(cmd, **kw):
            seen.append(kw.get("timeout"))
            import subprocess
            return subprocess.CompletedProcess(cmd, 0, "report\n", "")
        out = io.StringIO()
        with mock.patch.object(workers.subprocess, "run", side_effect=fake_run), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            rc = workers.cmd_delegate(["--kind", "read", "--difficulty", "1", "--brief", self.brief(),
                                       "--worker", "zai/b", *extra])
        return rc, seen

    def test_timeout_min_overrides_the_configured_limit_for_that_run(self):
        rc, seen = self.delegate("--timeout-min", "45", cfg={"workers": {"timeout_s": 100}})
        self.assertEqual(rc, 0)
        self.assertEqual(seen[-1], 45 * 60)

    def test_without_it_the_default_and_the_configured_limit_are_unchanged(self):
        self.assertEqual(self.delegate()[1][-1], workers.DEFAULT_RUN_TIMEOUT_S)
        self.assertEqual(self.delegate(cfg={"workers": {"timeout_s": 100}})[1][-1], 100)

    def test_a_value_outside_one_to_one_hundred_twenty_is_refused_and_nothing_runs(self):
        for bad in ("0", "121", "-3", "abc", "1.5", ""):
            with self.subTest(value=bad):
                rc, seen = self.delegate("--timeout-min", bad)
                self.assertEqual(rc, 1)
                self.assertEqual(seen, [])
        self.assertEqual(self.delegate("--timeout-min", "1")[1][-1], 60)
        self.assertEqual(self.delegate("--timeout-min", "120")[1][-1], 7200)

    def test_the_help_says_so(self):
        text = self.sisi("help", "delegate").stdout
        self.assertIn("--timeout-min N", text)


class HookPaths(TM.MeterBase):
    FUTURE = "2036-11-30T05:00:00Z"

    def setUp(self):
        super().setUp()
        # one prefixed provider (a command-line tool's model) besides the two host-native workers
        with open(os.path.join(self.data, "workers.json"), "w") as f:
            json.dump({"checked": time.time(), "tools": [{"name": "opencode", "installed": True, "usable": True,
                                                          "models": ["provx/model-1"]}]}, f)
        with open(os.path.join(self.data, "worker-prices.json"), "w") as f:
            json.dump({"models": {"provx/model-1": {"cost_per_million_tokens": 0.1},
                                  "alpha-small": {"cost_per_million_tokens": 1},
                                  "beta-large": {"cost_per_million_tokens": 9}}}, f)

    def shell(self, command, output, event="PostToolUse"):
        key = "error" if event == "PostToolUseFailure" else "tool_response"
        r = self.sisi("watch", "--after", "--tool", "claude-code",
                      stdin=self.payload(event, "Bash", {"command": command}, **{key: output}))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_a_command_that_only_prints_sisis_source_is_not_a_delegation_result(self):
        self.prompt()
        src = "\n".join(["    \"403 forbidden\", \"not logged in\", \"login required\", \"please log in\", \"invalid api key\",",
                         "        driver = DRIVER_BY_NAME.get(cand.get('tool') or '')", SOURCE_LINE,
                         "            cand = None", "            continue"])
        cmd = "ls ~/.local/state/sisi/delegate/*.log; sed -n 1516,1560p sisi/workers.py"
        out = self.shell(cmd, "state/sisi/delegate/e7260961.log\n" + src)
        self.assertEqual(out, "")
        self.assertEqual(workers.read_availability(), {})
        self.assertEqual(self.events("unavailable"), [])

    def test_commands_that_mention_delegate_but_do_not_run_it_are_not_delegations(self):
        self.prompt()
        line = "fakeprov/model-1 is unavailable (limit: API error 429: quota exhausted); trying the next choice"
        for cmd in ("echo sisi delegate", "cat docs/sisi-delegate.md", "grep -n 'sisi delegate' README.md",
                    "sisi delegate judge abc123 --outcome accepted --check read", "sisi delegate recent",
                    "sisi delegate guide", "sisi delegate brief", "sisi delegate check b.md", "sisi delegate amend x"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.shell(cmd, line), "")
        self.assertEqual(workers.read_availability(), {})

    def test_real_delegate_command_shapes_are_recognised(self):
        for cmd in ("sisi delegate --kind research --difficulty 1 --brief b.md",
                    "bin/sisi delegate --kind research --difficulty 1 --brief b.md",
                    "/opt/tools/bin/sisi delegate --kind research --difficulty 1 --brief b.md",
                    "cd proj && sisi delegate --kind research --difficulty 1 --brief b.md",
                    "cat > b.md <<'EOF'\nx\nEOF\nsisi delegate --kind research --difficulty 1 --brief b.md",
                    "SISI_X=1 sisi delegate --kind research --difficulty 1 --brief b.md"):
            with self.subTest(cmd=cmd):
                self.assertTrue(orchestration.runs_sisi_delegate(cmd))
        for cmd in ("echo sisi delegate", "ls state/sisi/delegate/*.log", "sisi delegate judge x", "sisi route --kind x",
                    "sisi-helper delegate", "notsisi delegate"):
            with self.subTest(cmd=cmd):
                self.assertFalse(orchestration.runs_sisi_delegate(cmd))

    def test_the_last_unavailable_line_of_a_real_delegate_result_decides_the_fallback(self):
        self.prompt()
        out = ("other/x is unavailable (auth: not logged in (you are not authenticated)); trying the next choice\n"
               "fakeprov/model-1 is unavailable (limit: API error 429: Subscription quota exhausted. Your usage window resets at "
               + self.FUTURE + "); trying the next choice\nsisi: no usable worker remains for kind research at difficulty 1")
        ctx = self.shell("sisi delegate --kind research --difficulty 1 --brief b.md", out, event="PostToolUseFailure")
        text = json.loads(ctx)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("fakeprov/model-1 is unavailable", text)
        self.assertNotIn("other/x", text)
        self.assertIn("Fall back now", text)
        self.assertEqual(workers.read_availability(), {})  # `sisi delegate` recorded it itself

    def test_a_note_counts_only_at_the_start_of_a_line(self):
        self.assertIsNone(fallback.shell_notice('notes.append("%s is unavailable (%s: %s)" % (a, b, c))'))
        self.assertIsNone(fallback.shell_notice("  see: x/y is unavailable (auth: no)"))
        got = fallback.shell_notice("a/b is unavailable (auth: no); trying the next choice\n"
                                    "c/d is unavailable (limit: rate limit); trying the next choice\nmore")
        self.assertEqual(got[0], "c/d")
        self.assertTrue(got[1].startswith("c/d is unavailable (limit"))

    def test_a_long_delegation_result_that_only_mentions_a_limit_in_its_middle_is_not_a_failure(self):
        self.prompt()
        self.pre("Agent", {"description": "d", "prompt": "Outcome: x", "model": "provx/model-1"}, tool_use_id="t9")
        body = ("Error: two tests were red when I started, and I fixed them.\n" + "line of the report\n" * 400
                + "the file said: usage limit reached, not logged in, quota exhausted\n" + "line of the report\n" * 400)
        r = self.post("Agent", {"description": "d", "prompt": "p", "model": "provx/model-1"}, response=body, tool_use_id="t9")
        self.assertNotIn("is unavailable", r.stdout)
        self.assertEqual(workers.read_availability(), {})

    def test_a_long_delegation_result_that_ends_in_its_failure_is_one(self):
        self.prompt()
        self.pre("Agent", {"description": "d", "prompt": "Outcome: x", "model": "provx/model-1"}, tool_use_id="t9")
        body = "API error: the run stopped\n" + "line of the report\n" * 800 + \
               "API error 429: Subscription quota exhausted. Your usage window resets at %s\n" % self.FUTURE
        r = self.post("Agent", {"description": "d", "prompt": "p", "model": "provx/model-1"}, response=body, tool_use_id="t9")
        self.assertIn("provx/model-1 is unavailable", r.stdout)
        self.assertIn("provx", workers.read_availability())


if __name__ == "__main__":
    unittest.main()
