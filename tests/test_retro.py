import io, json, os, random, shutil, sqlite3, sys, time, unittest
from unittest import mock
from support import *
from sisi import cli, gate, retro, store
from test_verifiers import LibCase, vfile, dfile

GOOD = dict(aim="verified",
            moment="I ran `cargo test` for 4 minutes before noticing that the fuzz verifier for parser work was never chosen",
            cause="the parser-or-codec recipe does not list the fuzz verifier under Checks",
            change_kind="recipe",
            change="Add the fuzz verifier to the Checks of the parser-or-codec recipe so parser work picks it by default",
            when="parser, fuzzing, codec, hostile input, generated input, parsing",
            scope="everywhere", target="parser-or-codec", pattern="Reach for the familiar tool instead of the check that fits the claim")


def argv(f):
    out = []
    for k, v in f.items():
        if k == "new":
            out.append("--new")
        else:
            out += ["--" + k.replace("_", "-"), v]
    return out


class RetroCase(LibCase):
    def setUp(self):
        super().setUp()
        os.environ["SISI_RETRO_REQUIRED"] = "1"
        self.put("prove/fuzz.md", vfile("fuzz"))
        self.put("parser-or-codec.md", dfile("parser-or-codec"), self.ddir)
        self.notes = os.path.join(self.data, "notes")

    def retro(self, f=None, env=None, **kw):
        return self.sisi("retro", *argv(dict(GOOD, **(f or {}), **kw)), env=env)

    def lessons(self):
        con = retro.connect()
        try:
            return [dict(r) for r in con.execute("SELECT * FROM lessons ORDER BY id")]
        finally:
            con.close()

    def occurrences(self):
        con = retro.connect()
        try:
            return con.execute("SELECT count(*) FROM occurrences").fetchone()[0]
        finally:
            con.close()


class RefusalTests(RetroCase):
    def test_good_answer_accepted(self):
        r = self.retro()
        self.assertEqual(r.returncode, 0, r.stdout)
        l = self.lessons()
        # a recipe lesson with a valid target takes effect at once, on its first occurrence
        self.assertEqual((len(l), l[0]["count"], l[0]["status"], l[0]["aim"]), (1, 1, "applied", "verified"))
        self.assertEqual(self.occurrences(), 1)

    def test_each_refusal(self):
        # Structural checks only: presence, length, enums, moment-is-not-change, exact empty answers.
        bad = {
            "missing aim": {"aim": ""}, "missing moment": {"moment": ""}, "missing cause": {"cause": " "},
            "missing change": {"change": ""}, "bad aim": {"aim": "vibes"}, "bad kind": {"change_kind": "magic"},
            "nothing change": {"change": "None"}, "na cause": {"cause": "n/a"},
            "nothing moment exact": {"moment": "nothing"},
            "be more careful exact": {"change": "be more careful"},
            "short moment": {"moment": "it was slow"}, "short change": {"change": "fix the rule"},
            "short cause": {"cause": "bad"},
            "same text": {"moment": GOOD["change"], "change": GOOD["change"]},
        }
        for name, over in bad.items():
            with self.subTest(name):
                r = self.retro(over)
                self.assertEqual(r.returncode, 2, r.stdout)
                self.assertIn("refused", r.stdout)
                self.assertIn("(check:", r.stdout)  # every refusal names the check that failed
        self.assertEqual(self.lessons(), [])
        self.assertEqual(self.occurrences(), 0)

    VALID = [
        ("Dates in the report were one day early for users in Sydney",
         "the code formatted UTC timestamps without the user's time zone",
         "For anything that shows or compares dates, test with a time zone ahead of and behind UTC and across a daylight saving change"),
        ("Everything looked fine on my machine and then failed for everyone in the beta",
         "my local data was a week old and far too small",
         "Anything that reads user data should always be checked against a large recent copy before shipping"),
        ("Nothing could be imported after the upgrade and nobody noticed for a day",
         "the importer swallowed every error and reported success",
         "An import should never report success when everything was skipped; zero imported is a failure"),
        ("The button did nothing at all when pressed quickly twice in a row",
         "the handler always waited for the first request to finish",
         "Buttons that start work should disable themselves until the work settles, always"),
        ("It was never clear which of the three copies was the newest one",
         "each tool kept its own copy and none said which was live",
         "Anything installed in two places should print which copy is running and how old it is"),
        ("Everything was rebuilt from scratch even for a one-word edit",
         "the build never reused anything between runs at all",
         "A build should always say what it reused and what it redid, so waste is visible"),
        ("The search found nothing for a perfectly ordinary plural word",
         "matching compared whole words only, with no stemming at all",
         "Search over user text should stem words so plurals and verb forms meet"),
        ("Users in Auckland saw tomorrow's date on everything after midnight",
         "dates were formatted in the server zone, never the viewer's",
         "For anything dated, format in the viewer's zone and test both sides of UTC"),
        ("The whole page went blank whenever one record had no title",
         "rendering assumed every field is always present on every record",
         "Rendering should survive any single record missing any optional field"),
        ("Nobody could tell whether the job had finished or was still running",
         "long work reported nothing between starting and ending",
         "Anything that takes more than a few seconds should say what stage it is at"),
        ("The same invoice was sent twice to the same customer in one morning",
         "a retry after a timeout could not tell the first send had landed",
         "Anything sent to a customer should carry an id that makes a retry harmless"),
        ("Accented names vanished from the list after the upgrade finished",
         "the new code compared names byte for byte across normalisation forms",
         "Names should be normalised the same way on write and on every later read"),
        ("The report said twenty thousand users when nothing had been measured",
         "a file count was presented as a session count without checking",
         "Any number a decision depends on should come from measuring the thing it names"),
        ("Saving appeared to work while nothing was actually written anywhere",
         "the write error was logged once and the indicator stayed green",
         "A failed save should be visible where the save was asked for, never only in a log"),
        ("The oldest message in the inbox was never shown to anyone at all",
         "paging always sorted newest first and the tail fell off the page",
         "Any list that pages should be checked for items that can never be reached"),
        ("Everything slowed down only when the office came online at nine",
         "every client retried at the same second after any failure",
         "Retries should always spread out with jitter so clients never stampede together"),
        ("A file that should never change was quietly rewritten by the installer",
         "the install step wrote everywhere instead of only where asked",
         "Installers should write nothing outside the places the user was told about"),
        ("The totals never matched the spreadsheet by exactly one cent",
         "money travelled as floats and rounded differently in two places",
         "Money should be integer minor units from end to end, always, no exceptions"),
        ("Nobody could open the attachment because its name had spaces in it",
         "the download path was built by joining text with no escaping anywhere",
         "Anything that turns a name into a path should be tested with spaces and accents"),
        ("The night run silently did nothing because the clock had moved",
         "a fixed local time never occurred on the spring-forward night",
         "Scheduled work should say what happens when its local time never occurs"),
        ("Search results showed records the signed-in person should never see",
         "the filter ran after results were already assembled for display",
         "Visibility should be decided before anything user-shaped is assembled for output"),
        ("The copy on the laptop and the copy at work disagreed about everything",
         "sync copied files both ways with nothing recording which won",
         "Sync should record, for every conflict, which side won and why it won"),
        ("It always picked the first answer even when the first was clearly stale",
         "ranking never considered how old a result was at selection time",
         "Anything cached should carry its age and prefer a fresh answer over a stale one"),
        ("Nothing was logged when the payment provider answered with an error",
         "the error path returned early without touching the log at all",
         "Every early return on an error path should leave exactly one log line behind"),
        ("The whole import stopped on one row that nobody could identify later",
         "rows were counted from one in the file and from zero in the message",
         "Errors about a row should name it the way the person holding the file counts it"),
        ("Settings changed on one machine never appeared on the other machine",
         "settings were read once at startup and never watched afterwards",
         "Anything read at startup that users can edit should say when a restart is needed"),
        ("The preview and the printed page never agreed about the typeface",
         "the preview used a font the printer substituted without telling anyone",
         "Anything printable should be checked in the form it is finally printed in"),
        ("Undo brought back a version nobody recognised from any point in time",
         "undo restored whole files while other work had landed in between",
         "Undo should reverse one change exactly and refuse when later work touches it"),
        ("The helper kept asking questions that the request had already answered",
         "it never read the answers already recorded earlier in the session",
         "Before asking anything, an agent should check what was already settled and say so"),
        ("Everything passed locally and the first real user hit a crash at once",
         "tests only ever used the small tidy examples written by hand",
         "Anything parsing outside files should be tested on generated hostile examples"),
    ]

    def test_valid_lessons_in_varied_wording_are_all_accepted(self):
        self.assertGreaterEqual(len(self.VALID), 30)
        for moment, cause, change in self.VALID:
            f = dict(GOOD, moment=moment, cause=cause, change=change)
            self.assertEqual(retro.validate(f), [], moment)
        # and through the real command, Sydney included (no digit, no path, no ALLCAPS in the moment)
        m, c, ch = self.VALID[0]
        r = self.retro({"moment": m, "cause": c, "change": ch})
        self.assertEqual(r.returncode, 0, r.stdout)

    EMPTY = [
        {"moment": "nothing"}, {"moment": "None."}, {"cause": "n/a"}, {"cause": "nothing"},
        {"change": "be more careful"}, {"change": "test more"}, {"change": "none"},
        {"moment": "ok"}, {"cause": "all good"}, {"change": "short"}, {"moment": "it went well"},
        {"cause": "fine"}, {"change": "no"},
    ]

    def test_empty_answers_are_refused_with_the_check_named(self):
        self.assertGreaterEqual(len(self.EMPTY), 12)
        for over in self.EMPTY:
            with self.subTest(over):
                errs = retro.validate(dict(GOOD, **over))
                self.assertTrue(errs)
                self.assertTrue(any("(check:" in e for e in errs), errs)
        r = self.retro({"change": "be more careful"})
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn('change is an empty answer: "be more careful"', r.stdout)

    def test_missing_message_names_the_field(self):
        r = self.sisi("retro", "--aim", "speed")
        self.assertEqual(r.returncode, 2)
        for w in ("moment", "cause", "change-kind", "change", "--when"):
            self.assertIn(w, r.stdout)
        self.assertIn("at least 5 terms", r.stdout)

    def test_when_is_required_with_five_terms_for_new_lessons(self):
        no_when = dict(GOOD); no_when.pop("when")
        r = self.sisi("retro", *argv(no_when))
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("--when needs at least 5 terms", r.stdout)
        self.assertIn("delimited file", r.stdout)  # the worked example in the refusal
        few = self.retro({"when": "parser, fuzzing"})
        self.assertEqual(few.returncode, 2, few.stdout)
        self.assertIn("--when has 2 term(s)", few.stdout)
        self.assertEqual(self.lessons(), [])
        self.assertEqual(self.retro().returncode, 0)  # five-plus terms: accepted and stored
        self.assertIn("fuzzing", self.lessons()[0]["when_terms"])
        same = self.sisi("retro", "--same-as", "1", "--moment", "again `cargo test` ran for 5 minutes with no fuzz verifier chosen")
        self.assertEqual(same.returncode, 0, same.stdout)  # --same-as needs no --when

    def test_json_on_stdin(self):
        r = self.sisi("retro", "--json", "-", stdin=json.dumps({k.replace("_", "-"): v for k, v in GOOD.items()}))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(len(self.lessons()), 1)
        self.assertEqual(self.sisi("retro", "--json", "-", stdin="not json").returncode, 2)
        self.assertEqual(self.sisi("retro", "--json", "-", stdin=json.dumps({"aim": "speed"})).returncode, 2)

    def test_property_refused_answers_are_never_stored(self):
        # Only structural failures belong here now: exact empty answers, too-short text, bad enums.
        generic = ["nothing", "n/a", "none", "it went well", "be more careful", "test more", "short", "", "   ", "ok"]
        for seed in [0, 1, random.randrange(2 ** 32)] + [random.randrange(2 ** 32) for _ in range(ITERS - 1)]:
            rng = random.Random(seed)
            for _ in range(8 * ITERS):
                f = dict(GOOD)
                for k in rng.sample(["aim", "moment", "cause", "change_kind", "change"], rng.randint(1, 3)):
                    f[k] = rng.choice(generic)
                with self.subTest(seed=seed, f=f):
                    argv_ = []
                    for k, v in f.items():
                        argv_ += ["--" + k.replace("_", "-"), v]
                    self.assertEqual(retro.validate({k: v for k, v in f.items()}) != [], True)
                    r = self.sisi("retro", *argv_)
                    self.assertEqual(r.returncode, 2, r.stdout)
        self.assertEqual(self.lessons(), [])
        self.assertEqual(self.occurrences(), 0)


class SimilarityAndSameAsTests(RetroCase):
    def test_similar_lessons_listed_exit_4_then_new_or_same_as(self):
        self.retro()
        near = dict(moment="I again ran `cargo test` for 6 minutes before noticing that the fuzz verifier for parser work was never chosen",
                    change="Add the fuzz verifier to the parser-or-codec recipe Checks so parser work picks it")
        r = self.retro(near)
        self.assertEqual(r.returncode, 4)
        self.assertIn("#1", r.stdout)
        self.assertIn("seen 1", r.stdout)
        self.assertIn("--same-as", r.stdout)
        self.assertEqual(len(self.lessons()), 1)  # nothing stored
        self.assertEqual(self.retro(near, new=True).returncode, 0)
        self.assertEqual(len(self.lessons()), 2)

    def test_dissimilar_lesson_accepted_directly(self):
        self.retro()
        other = dict(aim="speed", change_kind="tool", target="", scope="everywhere",
                     pattern="Reach for the familiar tool instead of the check that fits the claim",
                     moment="the screenshot comparison in `web-ui` waited 90 seconds on a dev server that never started",
                     cause="no readiness probe before the browser step",
                     when="browser, screenshot, dev server, port waiting, ui checks, startup",
                     change="Make sisi verify wait for the declared port instead of sleeping a fixed time")
        other.pop("target")
        self.assertEqual(self.sisi("retro", *argv(other)).returncode, 0)
        self.assertEqual(len(self.lessons()), 2)

    def test_same_as_adds_one_occurrence_to_exactly_one_lesson(self):
        self.retro()
        for i in range(3):
            self.retro(aim="speed", change_kind="tool", moment="distinct %d: `make build` took 9 minutes in lib%d/src" % (i, i),
                       cause="a cold cache every time on this machine", change="Cache the build artefacts between %d runs in the gate config" % (1000 + i * 7919),
                       target="", new=True) if False else None
        self.assertEqual(len(self.lessons()), 1)
        r = self.sisi("retro", "--same-as", "1", "--moment", "again `cargo test` ran for 5 minutes with no fuzz verifier chosen")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("seen 2", r.stdout)
        l = self.lessons()
        self.assertEqual((len(l), l[0]["count"]), (1, 2))
        self.assertEqual(self.occurrences(), 2)

    def test_same_as_needs_a_real_moment_and_an_existing_id(self):
        self.retro()
        self.assertEqual(self.sisi("retro", "--same-as", "1", "--moment", "nothing").returncode, 2)
        self.assertEqual(self.sisi("retro", "--same-as", "1").returncode, 2)
        self.assertEqual(self.sisi("retro", "--same-as", "99", "--moment", "again `cargo test` ran for 5 minutes, no fuzz").returncode, 2)
        self.assertEqual(self.lessons()[0]["count"], 1)

    def test_property_same_as_increments_exactly_one(self):
        ids = []
        for i in range(4):
            r = self.retro(aim=["speed", "level", "intent", "hands-off"][i], change_kind="tool", target=None,
                           moment="unique%dx: `cmd%d --flag` hung for %d minutes at step number %d" % (i, i, 7 + i, i),
                           cause="reason %d: widget%d misconfigured" % (i, i),
                           change="Teach tool%d to %s%d automatically" % (i, ["zip", "yank", "frob", "quux"][i], i)) if False else None
            con = retro.connect()
            lid = retro.new_lesson(con, dict(GOOD, aim="speed", change_kind="tool", target=None,
                                             moment="m%d: command%d failed %d times" % (i, i, i),
                                             cause="cause%d" % i, change="change%d" % i), self.proj, None)
            con.commit()
            con.close()
            ids.append(lid)
        counts = {i: 1 for i in ids}
        for seed in [0, 1, random.randrange(2 ** 32)]:
            rng = random.Random(seed)
            for _ in range(5 * ITERS):
                lid = rng.choice(ids)
                r = self.sisi("retro", "--same-as", str(lid), "--moment", "again `cmd%d` failed in run number %d of the gate suite" % (lid, rng.randrange(1000)))
                self.assertEqual(r.returncode, 0, r.stdout)
                counts[lid] += 1
                self.assertEqual({l["id"]: l["count"] for l in self.lessons()}, counts)
        con = retro.connect()
        self.assertEqual(con.execute("SELECT count(*) FROM occurrences").fetchone()[0], sum(counts.values()))
        con.close()


class AutoApplyAndLessonsTests(RetroCase):
    def occ(self, sid, lid=None):
        env = {"SISI_SESSION_ID": sid}
        if lid is None:
            return self.retro(env=env)
        return self.sisi("retro", "--same-as", str(lid), "--moment", "again `cargo test` ran 5 min, no fuzz verifier chosen (%s)" % sid, env=env)

    def test_second_occurrence_from_second_session_applies_to_notes(self):
        # The learning loop changed this: the field note is written on the FIRST occurrence,
        # and later occurrences never duplicate the bullet.
        r = self.occ("s1")
        self.assertEqual(r.returncode, 0)
        self.assertIn("applied", r.stdout)
        self.assertTrue(os.path.exists(os.path.join(self.notes, "parser-or-codec.md")))
        self.assertEqual(self.lessons()[0]["status"], "applied")
        r = self.occ("s2", 1)
        self.assertEqual(r.returncode, 0, r.stdout)
        text = open(os.path.join(self.notes, "parser-or-codec.md")).read()
        self.assertIn("Add the fuzz verifier", text)
        self.assertEqual(text.count("Add the fuzz verifier"), 1)
        self.assertEqual(self.lessons()[0]["status"], "applied")
        # the entry itself is untouched, and show/done print the notes under a heading
        self.assertNotIn("Field notes", open(os.path.join(self.ddir, "parser-or-codec.md")).read())
        out = self.sisi("done", "parser-or-codec").stdout
        self.assertIn("Field notes from earlier agents", out)
        self.assertIn("Add the fuzz verifier", out)

    def test_verifier_notes_in_show_and_other_kinds_never_auto_apply(self):
        f = dict(GOOD, change_kind="verifier", target="fuzz")
        self.sisi("retro", *argv(f), env={"SISI_SESSION_ID": "a"})
        self.sisi("retro", "--same-as", "1", "--moment", "again `fuzz` was skipped in run 2", env={"SISI_SESSION_ID": "b"})
        self.assertIn("Field notes from earlier agents", self.sisi("verifiers", "show", "fuzz").stdout)
        for kind in ("rule", "oracle", "tool", "brief"):
            with self.subTest(kind):
                con = retro.connect()
                lid = retro.new_lesson(con, dict(GOOD, change_kind=kind, target="fuzz", moment="m %s" % kind, cause="c", change="x %s" % kind), self.proj, None)
                for s in ("p", "q", "r"):
                    os.environ["SISI_SESSION_ID"] = s
                    retro.add_occurrence(con, lid, "again", self.proj, None)
                    self.assertFalse(retro.maybe_auto_apply(con, lid))
                os.environ.pop("SISI_SESSION_ID")
                con.commit()
                self.assertEqual(con.execute("SELECT status FROM lessons WHERE id=?", (lid,)).fetchone()[0], "open")
                con.close()
        self.assertFalse(os.path.exists(os.path.join(self.notes, "x rule.md")))

    def test_invalid_target_is_never_applied_and_manual_apply_rules(self):
        con = retro.connect()
        a = retro.new_lesson(con, dict(GOOD, target="no-such-recipe"), self.proj, None)
        b = retro.new_lesson(con, dict(GOOD, change_kind="rule", target=None, moment="m rule", change="rule change text"), self.proj, None)
        c = retro.new_lesson(con, dict(GOOD, moment="m ok `x` 1", change="ok change for the recipe notes"), self.proj, None)
        con.commit(); con.close()
        self.assertEqual(self.sisi("lessons", "apply", str(a)).returncode, 1)
        self.assertEqual(self.sisi("lessons", "apply", str(b)).returncode, 1)
        self.assertEqual(self.sisi("lessons", "apply", str(c)).returncode, 0)
        self.assertEqual(self.sisi("lessons", "apply", str(c)).stdout.strip(), "already applied")
        self.assertEqual(open(os.path.join(self.notes, "parser-or-codec.md")).read().count("ok change"), 1)

    def test_lessons_listing_filters_order_show_set(self):
        con = retro.connect()
        mk = lambda n, **k: retro.new_lesson(con, dict(GOOD, moment="m%d `x`" % n, cause="c", change="change number %d" % n, **k), self.proj, None)
        l1 = mk(1, target=None, aim="speed", change_kind="tool") if False else None
        ids = []
        for n, (aim, kind) in enumerate([("speed", "tool"), ("intent", "rule"), ("speed", "rule")]):
            g = dict(GOOD, aim=aim, change_kind=kind, target=None, moment="m%d `x`" % n, cause="c", change="change number %d" % n)
            ids.append(retro.new_lesson(con, g, self.proj, None))
        retro.add_occurrence(con, ids[1], "again", self.proj, None)
        retro.add_occurrence(con, ids[1], "again", self.proj, None)
        con.commit(); con.close()
        out = self.sisi("lessons").stdout.splitlines()
        self.assertTrue(out[0].startswith("#%-4d" % ids[1]))  # highest count first
        self.assertEqual(len(self.sisi("lessons", "--aim", "speed").stdout.splitlines()), 2)
        self.assertEqual(len(self.sisi("lessons", "--kind", "rule", "--top", "1").stdout.splitlines()), 1)
        self.assertEqual(len(json.loads(self.sisi("lessons", "--json").stdout)), 3)
        self.assertEqual(len(self.sisi("lessons", "--repo", self.proj).stdout.splitlines()), 3)
        self.assertEqual(self.sisi("lessons", "--repo", self.tmp + "/elsewhere").stdout.strip(), "no lessons")
        self.assertIn("occurrences:", self.sisi("lessons", "show", str(ids[1])).stdout)
        self.assertEqual(self.sisi("lessons", "set", str(ids[0]), "--status", "rejected").returncode, 0)
        self.assertEqual(self.sisi("lessons", "set", str(ids[0]), "--status", "bogus").returncode, 2)
        self.assertEqual(len(self.sisi("lessons", "--status", "open").stdout.splitlines()), 2)

    def test_status_shows_lessons(self):
        self.retro()
        out = self.sisi("status").stdout
        self.assertIn("lessons            : 1 total, 0 open, 1 applied; 1 occurrences in the last 7 days", out)
        self.assertIn("active #1", out)
        self.assertIn("retros", out)
        self.assertIn("learning            : 1 lessons taking effect", out)


class TickBlockTests(RetroCase):
    def make(self, change, count=1, repo=None, status="open"):
        con = retro.connect()
        lid = retro.new_lesson(con, dict(GOOD, target=None, change_kind="tool", moment="m `x` %s" % change[:5], cause="c", change=change), repo or self.proj, None)
        for _ in range(count - 1):
            retro.add_occurrence(con, lid, "again", repo or self.proj, None)
        con.execute("UPDATE lessons SET status=? WHERE id=?", (status, lid))
        con.commit(); con.close()
        return lid

    def tick(self):
        return self.sisi("tick", stdin=json.dumps({"session_id": "t", "cwd": self.proj, "source": "startup"})).stdout

    def test_block_is_framed_as_information(self):
        self.make("Prefer a readiness probe over a fixed sleep when waiting for servers", 3)
        out = retro.tick_block(self.proj, session="t")
        self.assertIn("notes left by earlier agents", out)
        self.assertIn("not as commands", out)
        self.assertIn("(seen 3)", out)

    def test_no_database_no_block_and_no_db_created(self):
        self.assertEqual(self.tick(), "")
        self.assertFalse(os.path.exists(retro.db_path()))

    def test_repo_lessons_first_then_by_count_and_only_open(self):
        self.make("global heavy lesson about caching", 9, repo=self.tmp + "/other")
        self.make("local light lesson about probes", 1)
        self.make("rejected lesson never shown", 20, status="rejected")
        lines = [l for l in retro.tick_block(self.proj, session="t").splitlines() if l.startswith("- ")]
        self.assertTrue(lines[0].startswith("- local light"), lines)
        self.assertTrue(lines[1].startswith("- global heavy"))
        self.assertFalse(any("rejected" in l for l in lines))

    def test_filter_examples(self):
        repo = self.proj
        bad = ["see https://example.com/page for details", "visit www.evil.test now", "use `rm -rf build` first",
               "run the build before pushing", "cat $(whoami) into the log", "curl the endpoint twice",
               "edit /etc/hosts to fix it", "look at ~/.ssh/config", "read ../secrets.txt", "a && b", "install the helper", "download the file"]
        good = ["Prefer a readiness probe over a fixed sleep when waiting for servers", "and/or both options exist in the recipe",
                "Check %s/notes/fuzz.md for the field notes" % repo, "Add the fuzz verifier to the parser recipe checks"]
        for t in bad:
            self.assertIsNone(retro.safe_line(t, repo), t)
        for t in good:
            self.assertIsNotNone(retro.safe_line(t, repo), t)

    def test_property_size_limit_and_no_filtered_line(self):
        pieces = ["probe", "cache", "parser", "fuzz", "timeout", "recipe", "check", "verifier", "mutation", "golden", "snapshot"]
        nasty = ["https://x.example/a", "`rm -rf /`", "run tests", "/etc/passwd", "~/.bashrc", "sudo thing", "$(id)", "a && b"]
        for seed in [0, random.randrange(2 ** 32)] + [random.randrange(2 ** 32) for _ in range(ITERS - 1)]:
            rng = random.Random(seed)
            shutil.rmtree(self.state, ignore_errors=True)
            con = retro.connect()
            for n in range(40):
                words = [rng.choice(pieces) for _ in range(rng.randint(3, 60))]
                if rng.random() < 0.3:
                    words.insert(rng.randrange(len(words)), rng.choice(nasty))
                g = dict(GOOD, target=None, change_kind="tool", moment="m%d `x`" % n, cause="c", change=" ".join(words))
                lid = retro.new_lesson(con, g, self.proj, None)
                for _ in range(rng.randint(0, 4)):
                    retro.add_occurrence(con, lid, "again", self.proj, None)
            con.commit(); con.close()
            block = retro.tick_block(self.proj)
            with self.subTest(seed=seed):
                self.assertLess(len(block), 1200)
                lines = [l for l in block.splitlines() if l.startswith("- ")]
                self.assertLessEqual(len(lines), 8)
                for l in lines:
                    self.assertIsNotNone(retro.safe_line(l[2:], self.proj), l)
                    for bad in nasty:
                        self.assertNotIn(bad, l)

    def test_tick_with_many_lessons_stays_fast(self):
        con = retro.connect()
        for i in range(150):
            lid = retro.new_lesson(con, dict(GOOD, target=None, change_kind="tool", moment="m `x` %d" % i, cause="c",
                                             change="lesson number %d about caching and probes" % i), self.proj, None)
            for _ in range(i % 3):
                retro.add_occurrence(con, lid, "again", self.proj, None)
        con.commit(); con.close()
        self.tick()
        best = 9
        for _ in range(5):
            t = time.perf_counter()
            self.tick()
            best = min(best, time.perf_counter() - t)
        __import__('support').skip_timing_if_busy(self)
        self.assertLess(best, 0.2)

    def test_env_file_export_when_claude_provides_one(self):
        envf = os.path.join(self.tmp, "envfile")
        self.sisi("tick", stdin=json.dumps({"session_id": "abc 1", "cwd": self.proj, "source": "startup"}), env={"CLAUDE_ENV_FILE": envf})
        self.assertIn("export SISI_SESSION_ID='abc 1'", open(envf).read())


class GateRetroTests(RetroCase):
    sid = "gr"

    def setUp(self):
        super().setUp()
        self.git_init()
        self.write_contract(contract([check("ok", "true")]))
        self.tick()

    def tick(self):
        self.sisi("tick", stdin=json.dumps({"session_id": self.sid, "cwd": self.proj, "source": "startup"}))

    def gate(self, sid=None):
        return gate.decide({"session_id": sid or self.sid, "cwd": self.proj})

    def work(self, text="x"):
        with open(os.path.join(self.proj, "work.txt"), "a") as f:
            f.write(text + "\n")

    def do_retro(self, n=0):
        r = self.sisi("retro", *argv(dict(GOOD, moment="`cargo test` run %d took 4 minutes before the fuzz verifier showed up" % n,
                                          change="Add the fuzz verifier to the parser-or-codec recipe Checks, variant %d" % n, new=True)))
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_question_only_turn_is_never_asked(self):
        self.assertEqual(self.gate(), ("allow", None))
        self.assertEqual(self.gate(), ("allow", None))

    def test_real_work_needs_a_retro_for_this_tree_state(self):
        self.work()
        a, msg = self.gate()
        self.assertEqual(a, "block")
        self.assertIn("sisi retro --scope", msg)
        self.assertIn("--change-kind", msg)
        self.assertIn("how, not whether", msg)
        self.do_retro()
        self.assertEqual(self.gate()[0], "allow")
        self.assertEqual(self.gate()[0], "allow")  # unchanged since: not asked again
        self.work("more")  # the tree changed after the retro
        self.assertEqual(self.gate()[0], "block")

    def test_same_as_also_satisfies(self):
        self.do_retro()
        self.work()
        self.assertEqual(self.gate()[0], "block")
        self.assertEqual(self.sisi("retro", "--same-as", "1", "--moment", "again `cargo test` ran 5 min with no fuzz verifier").returncode, 0)
        self.assertEqual(self.gate()[0], "allow")

    def test_three_strike_release_and_switch(self):
        self.work()
        self.assertEqual([self.gate()[0] for _ in range(3)], ["block"] * 3)
        a, msg = self.gate()
        self.assertEqual(a, "allow")
        self.assertIn("retrospective", msg)
        self.assertNotIn("unverified", [r["status"] for r in self.results()])  # a missing retro is not an unverified result
        os.environ["SISI_RETRO_REQUIRED"] = "0"
        self.work("again")
        self.assertEqual(self.gate("other")[0], "allow")

    def test_waiver_counts_as_real_work(self):
        shutil.rmtree(os.path.join(self.proj, ".sisi"))
        self.tick()
        self.work()
        self.assertEqual(self.gate()[0], "allow")  # small change, no waiver: not real work
        self.sisi("contract", "waive", "typo")
        self.work("typo fix")
        self.assertEqual(self.gate()[0], "block")
        self.do_retro()
        self.assertEqual(self.gate()[0], "allow")

    def test_hook_output_is_a_block_for_claude(self):
        self.work()
        r = self.sisi("gate", stdin=json.dumps({"session_id": self.sid, "cwd": self.proj}))
        d = json.loads(r.stdout)
        self.assertEqual(d["decision"], "block")
        self.assertIn("sisi retro", d["reason"])

    def test_property_no_pass_after_real_work_without_a_retro(self):
        for seed in [0, 1, random.randrange(2 ** 32)] + [random.randrange(2 ** 32) for _ in range(ITERS - 1)]:
            rng = random.Random(seed)
            for n in range(4 * ITERS):
                sid = "pr-%d-%d" % (seed, n)
                self.tick_for(sid)
                did_work = rng.random() < 0.7
                recorded = rng.random() < 0.5
                if did_work:
                    self.work("%d-%d" % (seed, n))
                if did_work and recorded:
                    self.do_retro(seed % 1000 * 100 + n)
                with self.subTest(seed=seed, n=n, work=did_work, retro=recorded):
                    if not did_work:
                        self.assertEqual(self.gate(sid)[0], "allow")  # nothing changed: never asked
                    elif recorded:
                        self.assertEqual(self.gate(sid)[0], "allow")
                    else:
                        self.assertEqual([self.gate(sid)[0] for _ in range(3)], ["block"] * 3)  # never passes early
                        self.assertEqual(self.gate(sid)[0], "allow")  # only the 3-strike release

    def tick_for(self, sid):
        self.sisi("tick", stdin=json.dumps({"session_id": sid, "cwd": self.proj, "source": "startup"}))


class SubagentTests(RetroCase):
    def transcript(self, edits=True, start="2020-01-01T00:00:00.000Z", name="agent-a1.jsonl"):
        p = os.path.join(self.tmp, name)
        rows = [{"timestamp": start, "message": {"role": "user", "content": "do it"}}]
        content = [{"type": "tool_use", "name": "Edit" if edits else "Read", "input": {}}]
        rows.append({"timestamp": start, "message": {"role": "assistant", "content": content}})
        with open(p, "w") as f:
            f.write("\n".join(json.dumps(r) for r in rows) + "\n")
        return p

    def hook(self, **kw):
        payload = dict({"session_id": "s", "cwd": self.proj, "hook_event_name": "SubagentStop", "agent_id": "a1",
                        "agent_type": "general-purpose", "stop_hook_active": False}, **kw)
        return self.sisi("gate", "--subagent", stdin=json.dumps(payload))

    def test_subagent_that_edited_files_must_retro(self):
        r = self.hook(agent_transcript_path=self.transcript())
        d = json.loads(r.stdout)
        self.assertEqual(d["decision"], "block")
        self.assertIn("sisi retro", d["reason"])
        self.assertEqual(self.retro().returncode, 0)
        self.assertEqual(self.hook(agent_transcript_path=self.transcript()).stdout, "")

    def test_retro_older_than_the_subagent_does_not_count(self):
        self.retro()
        r = self.hook(agent_transcript_path=self.transcript(start="2999-01-01T00:00:00.000Z"))
        self.assertEqual(json.loads(r.stdout)["decision"], "block")

    def test_read_only_or_undeterminable_subagents_are_never_blocked(self):
        self.assertEqual(self.hook(agent_transcript_path=self.transcript(edits=False)).stdout, "")
        self.assertEqual(self.hook().stdout, "")  # no transcript path in the input
        self.assertEqual(self.hook(agent_transcript_path=self.tmp + "/missing.jsonl").stdout, "")  # fail open
        p = os.path.join(self.tmp, "garbage.jsonl")
        open(p, "w").write("not json\n{{{")
        self.assertEqual(self.hook(agent_transcript_path=p).stdout, "")

    def test_three_strikes_per_agent_and_switch_and_no_contract_checks(self):
        self.write_contract(contract([check("bad", "false")]))  # the contract is irrelevant for subagents
        t = self.transcript()
        acts = [self.hook(agent_transcript_path=t).stdout != "" for _ in range(4)]
        self.assertEqual(acts, [True, True, True, False])
        self.assertTrue(self.hook(agent_transcript_path=t, agent_id="other").stdout != "")  # separate counter
        os.environ["SISI_RETRO_REQUIRED"] = "0"
        self.assertEqual(self.hook(agent_transcript_path=t, agent_id="third").stdout, "")


class CliHookTests(SisiCase):
    def test_learn_cli_commands_are_reachable(self):
        r = self.sisi("scoreboard", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("harvest", self.sisi("harvest", "--help").stdout)
        self.assertEqual(self.sisi("nonsense").returncode, 64)

    def test_broken_or_absent_learn_cli_does_not_break_the_cli(self):
        broken = mock.MagicMock()
        broken.register.side_effect = TypeError("boom")
        import sisi
        with mock.patch.dict(sys.modules, {"sisi.learn_cli": broken}), mock.patch.object(sisi, "learn_cli", broken, create=True):
            self.assertEqual(cli._learn_cli("harvest", []), 70)
        with mock.patch.dict(sys.modules, {"sisi.learn_cli": None}), mock.patch.object(sisi, "learn_cli", None, create=True):
            self.assertEqual(cli._learn_cli("harvest", []), 70)  # import of the module fails
        self.assertEqual(self.sisi("help").returncode, 0)

    def test_help_points_to_retro(self):
        out = self.sisi("help").stdout
        self.assertIn("sisi retro", out)
        for retired in ("note", "propose"):
            self.assertNotIn("sisi " + retired + " ", out)
            self.assertEqual(self.sisi(retired, "still works").returncode, 64)


if __name__ == "__main__":
    unittest.main()
