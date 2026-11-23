"""`sisi prompt`: request-time delivery of the matching recipe and lessons on the human's message.

The hook must never block or fail a turn, must stay silent when nothing strictly matches, and must be
fast. Matching reuses the strict "likely to apply" test from retro.delivery; the labelled set below
phrases requests in different words from the lessons so only the when-terms can bridge them.
"""
import json, os, statistics, time, unittest
from support import *
from sisi import retro


def fields(**kw):
    f = dict(aim="verified", change_kind="recipe", target="release",
             moment="the tagged build shipped with a changelog for the previous version",
             cause="nobody compared the tag, the manifest version and the changelog before publishing",
             change="Before publishing, check the tag, the manifest version and the changelog agree",
             when="release, tagging, version, publish, changelog, package, ship it",
             short="Check tag, version and changelog agree before publishing.")
    f.update(kw)
    return f


class PromptCase(SisiCase):
    def mk(self, **kw):
        con = retro.connect()
        try:
            lid = retro.new_lesson(con, fields(**kw), self.proj, None)
            con.commit()
            return lid
        finally:
            con.close()

    def prompt(self, payload, tool=None):
        args = ["prompt"] + (["--tool", tool] if tool else [])
        return self.sisi(*args, stdin=json.dumps(payload))


class PromptHookTests(PromptCase):
    def test_release_request_gets_recipe_and_lesson_with_full_text_commands(self):
        lid = self.mk()
        r = self.prompt({"prompt": "cut a new release and tag it", "session_id": "s1", "cwd": self.proj})
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn("release", ctx)
        self.assertIn("sisi done release", ctx)
        self.assertIn("Check tag, version and changelog agree", ctx)
        self.assertIn("sisi lessons show %d" % lid, ctx)
        from sisi import prompt as P
        self.assertLessEqual(len(ctx), P.MAX_CHARS)

    def test_listing_is_counted(self):
        lid = self.mk()
        self.prompt({"prompt": "cut a new release and tag it", "session_id": "s1", "cwd": self.proj})
        con = retro.connect()
        try:
            self.assertGreaterEqual(retro.listed_count(con, lid), 1)
            places = [r[0] for r in con.execute("SELECT place FROM impressions WHERE lesson_id=?", (lid,))]
            self.assertIn("prompt", places)
        finally:
            con.close()

    def test_nothing_for_trivial_or_unmatched_messages(self):
        self.mk()
        for text in ("yes", "no thanks", "/clear", "what time is it?", "ok",
                     "rename the local variable in the slug helper to something clearer"):
            with self.subTest(text=text):
                r = self.prompt({"prompt": text, "session_id": "s1", "cwd": self.proj})
                self.assertEqual(r.returncode, 0)
                self.assertEqual(r.stdout.strip(), "")

    def test_garbage_input_exits_zero_silently(self):
        for stdin in ("not json", "", "[]", '{"prompt": 42}'):
            with self.subTest(stdin=stdin):
                r = self.sisi("prompt", stdin=stdin)
                self.assertEqual(r.returncode, 0)

    def test_other_tool_shapes(self):
        self.mk()
        payload = {"prompt": "cut a new release and tag it", "session_id": "s1", "cwd": self.proj}
        r = self.prompt(payload, tool="copilot")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("sisi done release", json.loads(r.stdout)["additionalContext"])
        r = self.prompt(payload, tool="gemini")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("sisi done release",
                      json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"])
        r = self.prompt(payload, tool="pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("sisi done release", r.stdout)

    def test_fast_enough_median_of_twenty(self):
        skip_timing_if_busy(self)
        self.mk()
        payload = json.dumps({"prompt": "cut a new release and tag it", "session_id": "s1", "cwd": self.proj})
        times = []
        for _ in range(20):
            t0 = time.time()
            r = self.sisi_proc("prompt", stdin=payload)
            times.append(time.time() - t0)
            self.assertEqual(r.returncode, 0)
        med = statistics.median(times)
        self.assertLess(med, 1.0, "median prompt-hook run %.3fs over 20 runs" % med)


class LabelledMatchingTests(PromptCase):
    """Requests rephrased away from the lessons' own wording. A hit means the lesson's short line (or
    the recipe it targets) is in the injected context; a false match means context was injected for a
    request it does not apply to."""

    def setUp(self):
        super().setUp()
        self.release_id = self.mk()
        self.csv_id = self.mk(
            target=None, change_kind="rule",
            moment="a spreadsheet export broke on a field containing a newline",
            cause="rows were joined by hand instead of with a quoting writer",
            change="Write delimited files with a quoting writer so embedded newlines survive",
            when="csv, tsv, spreadsheet, tabular data, export, delimited file, quoting",
            short="Use a quoting writer for delimited exports.")

    def ctx(self, text):
        from sisi import prompt as P
        return P.build_context(text, session="labelled")

    def test_labelled_set(self):
        # A hit: the expected lesson's short line is injected. A false match: either lesson is
        # injected for a request it does not apply to. (A recipe for the request's own kind of work
        # is the feature working, not a false match, so it is measured separately below.)
        release_short = "Check tag, version and changelog agree"
        csv_short = "Use a quoting writer"
        should = [
            ("cut a new release and tag it", release_short),
            ("publish the next version to the package index please", release_short),
            ("ship it: bump the version and push the tag", release_short),
            ("export the table as a spreadsheet file", csv_short),
            ("write these rows out as a delimited file for the spreadsheet", csv_short),
        ]
        should_not = [
            "rename the helper that formats release notes headings in the docs",
            "why is the test suite slow on this machine",
            "add a dark mode toggle to the settings page",
            "fix the off-by-one in the pagination control",
            "explain how the quoting in this shell one-liner works",
        ]
        hits = sum(1 for t, want in should if want in self.ctx(t))
        false_alarms = sum(1 for t in should_not
                           if release_short in self.ctx(t) or csv_short in self.ctx(t))
        self.assertEqual((hits, false_alarms), (len(should), 0),
                         "lesson hits %d/%d, false matches %d/%d" % (hits, len(should), false_alarms, len(should_not)))
        # the release request also names the right recipe, not a neighbour
        self.assertIn("sisi done release", self.ctx("cut a new release and tag it"))


if __name__ == "__main__":
    unittest.main()
