import json, os, shutil, time, unittest
from support import *
from sisi import store


class TickTests(SisiCase):
    def payload(self, **kw):
        return json.dumps(dict({"session_id": "s1", "cwd": self.proj, "hook_event_name": "SessionStart",
                                "source": "startup"}, **kw))

    def test_records_session_baseline(self):
        self.git_init()
        with open(os.path.join(self.proj, "pre.txt"), "w") as f:
            f.write("a\nb\n")
        r = self.sisi("tick", stdin=self.payload())
        self.assertEqual(r.returncode, 0)
        with open(os.path.join(self.state, "sessions", "s1.json")) as f:
            s = json.load(f)
        self.assertEqual(s["cwd"], self.proj)
        self.assertEqual(len(s["head"]), 40)
        self.assertEqual(s["baseline"]["files"], ["pre.txt"])
        self.assertGreaterEqual(s["baseline"]["lines"], 2)

    def test_prints_at_most_one_short_line(self):
        os.makedirs(os.path.join(self.home, ".claude"))  # claude present but not wired
        r = self.sisi("tick", stdin=self.payload())
        self.assertLessEqual(len(r.stdout.strip().splitlines()), 1)
        self.assertIn("sisi doctor", r.stdout)
        self.sisi("install")
        self.assertEqual(self.sisi("tick", stdin=self.payload()).stdout, "")

    def test_garbage_and_broken_state_fail_open(self):
        self.assertEqual(self.sisi("tick", stdin="garbage").returncode, 0)
        shutil.rmtree(self.state, ignore_errors=True)
        open(self.state, "w").close()
        r = self.sisi("tick", stdin=self.payload())
        self.assertEqual(r.returncode, 0)

    def test_resume_keeps_baseline(self):
        self.git_init()
        self.sisi("tick", stdin=self.payload())
        p = os.path.join(self.state, "sessions", "s1.json")
        d = json.load(open(p)); d["marker"] = 1
        json.dump(d, open(p, "w"))
        self.sisi("tick", stdin=self.payload(source="resume"))
        self.assertEqual(json.load(open(p)).get("marker"), 1)

    def test_prunes_old_session_files_only(self):
        sd = os.path.join(self.state, "sessions")
        os.makedirs(sd)
        old, new, other = (os.path.join(sd, n) for n in ("old.json", "new.json", "keep.txt"))
        for p in (old, new, other):
            open(p, "w").write("{}")
        t = time.time() - 31 * 86400
        os.utime(old, (t, t))
        os.utime(other, (t, t))
        self.sisi("tick", stdin=self.payload())
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(new))
        self.assertTrue(os.path.exists(other))  # only *.json session records are pruned
        self.assertTrue(os.path.exists(os.path.join(sd, "s1.json")))

    def test_warm_run_under_200ms(self):
        self.git_init()
        os.makedirs(os.path.join(self.home, ".claude"))
        self.sisi("install")
        self.sisi("tick", stdin=self.payload())  # warm
        best = 9
        for i in range(60):  # many session files: pruning must stay cheap
            open(os.path.join(self.state, "sessions", "x%d.json" % i), "w").write("{}")
        for _ in range(5):
            t = time.perf_counter()
            self.sisi("tick", stdin=self.payload())
            best = min(best, time.perf_counter() - t)
        __import__('support').skip_timing_if_busy(self)
        self.assertLess(best, 0.2, "tick took %.0f ms" % (best * 1000))


class StoreTests(SisiCase):
    def read(self, name):
        with open(os.path.join(self.data, name)) as f:  # what the person taught sisi is personal data
            return [json.loads(l) for l in f]

    def test_learn_records_a_statement(self):
        r = self.sisi("learn", "--scope", "user", "always record the statement plainly")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("always record the statement plainly", self.sisi("oracle").stdout)
        recs = self.read("learnings.jsonl")
        self.assertEqual(len(recs), 1)
        self.assertTrue(recs[0]["owner_statement"])

    def test_empty_learn_rejected(self):
        self.assertNotEqual(self.sisi("learn").returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.data, "learnings.jsonl")))

    def test_oracle_prints_file(self):
        r = self.sisi("oracle")
        self.assertIn("oracle", r.stdout.lower())

    def test_concurrent_appends_stay_whole_lines(self):
        import threading
        def w(i):
            for j in range(50):
                store.append("learn", {"i": i, "j": j, "pad": "x" * 200})
        ts = [threading.Thread(target=w, args=(i,)) for i in range(6)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(len(self.read("learn.jsonl")), 300)


class HelpTests(SisiCase):
    def test_help_and_unknown(self):
        out = self.sisi("help").stdout
        for w in ("verify", "gate", "tick", "install", "learn", "verifiers"):
            self.assertIn(w, out)
        self.assertNotEqual(self.sisi("bogus").returncode, 0)

    def test_every_command_in_core_md_exists(self):
        import re
        text = open(os.path.join(REPO, "canon", "core.md")).read()
        for m in set(re.findall(r"`sisi ([a-z]+)", text)):
            self.assertIn("sisi " + m, self.sisi("help").stdout, m)

    def test_version_matches_the_version_file(self):
        want = open(os.path.join(REPO, "VERSION")).read().strip()
        self.assertRegex(want, r"^\d+\.\d+\.\d+$")
        for a in ("--version", "version"):
            r = self.sisi(a)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, want), a)



if __name__ == "__main__":
    unittest.main()
