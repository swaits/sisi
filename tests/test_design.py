"""Live principles (`sisi learn`/`sisi oracle`), the contract design section, `sisi design`,
the gate's design send-back, and request-time design delivery."""
import json, os, subprocess, unittest
from support import *

PRINCIPLES = [
    "drop into any user's environment and use what is already there",
    "mechanisms over good intentions: check it, do not just advise it",
    "never set up scheduled jobs or timers for me",
]


def good_design(principles=PRINCIPLES, **over):
    d = {
        "implies": ["The tool must work in an environment sisi did not choose, so discovery of what "
                    "the host already provides comes before building any replacement for it."],
        "provided": [{"what": "git is already used for change measurement in this repository",
                      "evidence": "command:git"},
                     {"what": "the README documents the existing command surface to build on",
                      "evidence": "file:README.md"}],
        "alternatives": [
            {"name": "shell out to each tool's command line",
             "cost": "one driver per tool, each with its own quoting and login handling",
             "risk": "breaks wherever a tool has no usable command line or changes its flags"},
            {"name": "build a new agent host of our own",
             "cost": "months of work duplicating sessions, auth and tool wiring from scratch",
             "risk": "nobody's existing setup carries over, so adoption starts from zero"},
        ],
        "chosen": {"name": "use the host tool's own subagent mechanism",
                   "why": "It drops into the user's existing environment instead of rebuilding what "
                          "the host already provides, which is what the owner asked for."},
        "objections": [{"principle": p, "applicable": True,
                        "objection": "You are rebuilding something the environment already gives me.",
                        "answer": "The design calls the host mechanism and builds only the missing adapter."}
                       if i < 2 else
                       {"principle": p, "applicable": False,
                        "reason": "Nothing in this design runs on a schedule; every step is triggered by use."}
                       for i, p in enumerate(principles)],
        "challenge": {"by": "a subagent on a different model, briefed as the owner",
                      "recorded_at": "2026-01-01T00:00:00Z",
                      "objections": ["You never checked what the host already provides before designing drivers."],
                      "changes": ["Made the host subagent mechanism the main path; command lines are the fallback."]},
    }
    d.update(over)
    return d


class PrinciplesCase(SisiCase):
    def learn_all(self):
        for p in PRINCIPLES:
            r = self.sisi("learn", "--scope", "user", p)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class LivePrinciplesTests(PrinciplesCase):
    def test_learn_takes_effect_at_once_without_quarantine_wording(self):
        r = self.sisi("learn", "--scope", "user", PRINCIPLES[0])
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("quarantin", (r.stdout + r.stderr).lower())
        out = self.sisi("oracle").stdout
        self.assertIn(PRINCIPLES[0], out)

    def test_oracle_prints_one_principle_per_statement_with_quote_and_date(self):
        self.learn_all()
        out = self.sisi("oracle").stdout
        for p in PRINCIPLES:
            self.assertIn(p, out)
            self.assertIn('"%s"' % p, out)
        self.assertIn("Standing principles", out)

    def test_quarantine_file_is_migrated_losslessly(self):
        os.makedirs(self.data, exist_ok=True)
        rec = {"ts": "2025-01-02T03:04:05Z", "cwd": self.proj, "tool": None, "session": None,
               "text": "always show options with a recommendation", "scope": "user"}
        with open(os.path.join(self.data, "learn-quarantine.jsonl"), "w") as f:
            f.write(json.dumps(rec) + "\n")
        out = self.sisi("oracle").stdout
        self.assertIn("always show options with a recommendation", out)
        self.assertIn("2025-01-02", out)
        self.assertTrue(os.path.exists(os.path.join(self.data, "learn.jsonl")))
        self.assertFalse(os.path.exists(os.path.join(self.data, "learn-quarantine.jsonl")))
        rows = [json.loads(l) for l in open(os.path.join(self.data, "learn.jsonl"))]
        self.assertEqual(rows[0]["text"], rec["text"])
        self.assertEqual(rows[0]["ts"], rec["ts"])

    def test_learn_statement_may_name_sisi_itself(self):
        # the project folder is named proj in the fixture; use a folder named sisi
        d = os.path.join(self.tmp, "sisi")
        os.makedirs(d)
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        r = self.sisi("learn", "--scope", "user",
                      "sisi should anticipate what I need from what I already said", cwd=d)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class DesignValidationTests(PrinciplesCase):
    def errs(self, design):
        from sisi import design as D
        return D.validate_design({"goal": "g", "design": design}, cwd=REPO)

    def test_good_design_passes(self):
        self.learn_all()
        self.assertEqual(self.errs(good_design()), [])

    def test_missing_design_is_an_error(self):
        from sisi import design as D
        self.assertTrue(D.validate_design({"goal": "g"}, cwd=REPO))

    def test_labelled_good_and_filler_sets(self):
        """At least 12 good and 12 filler design sections: every good one passes, every filler fails."""
        self.learn_all()
        base = good_design()
        def variant(**kw):
            d = json.loads(json.dumps(base))
            d.update(kw)
            return d
        goods = [base]
        for i in range(11):
            d = json.loads(json.dumps(base))
            d["implies"] = ["Implication %d: the result must keep working when the host, the model "
                            "and the project layout all change around it over time." % i]
            d["provided"] = [{"what": "python3 runs the whole tool and its checks already",
                              "evidence": "command:python3"},
                             {"what": "the licence file fixes the terms this ships under",
                              "evidence": "file:LICENSE"}]
            d["alternatives"][0]["name"] = "bespoke driver number %d" % i
            d["challenge"]["by"] = "independent reviewer %d on a different model" % i
            goods.append(d)
        fillers = [
            variant(implies=["As requested."]),
            variant(implies=[]),
            variant(provided=[{"what": "existing tools", "evidence": "command:no-such-command-xyz"}]),
            variant(provided=["stuff that exists somewhere in general terms"]),
            variant(provided=[]),
            variant(alternatives=[base["alternatives"][0]]),
            variant(alternatives=[dict(base["alternatives"][0], name="use the host tool's own subagent mechanism"),
                                  base["alternatives"][1]]),
            variant(alternatives=[dict(base["alternatives"][0], cost="low", risk="low"),
                                  dict(base["alternatives"][1], cost="low", risk="low")]),
            variant(chosen={"name": "use the host tool's own subagent mechanism", "why": "best"}),
            variant(objections=[{"principle": PRINCIPLES[0], "applicable": True,
                                 "objection": "x", "answer": "y"}]),
            variant(objections=[dict(o, applicable=False, reason="n/a") if o.get("applicable") else o
                                for o in base["objections"]]),
            variant(challenge={"by": "self", "recorded_at": "2026-01-01T00:00:00Z",
                               "objections": ["none"], "changes": []}),
            variant(challenge={"by": "a subagent on a different model", "recorded_at": "2026-01-01T00:00:00Z",
                               "objections": [], "changes": ["changed things in response to the review"]}),
        ]
        good_pass = sum(1 for d in goods if not self.errs(d))
        filler_fail = sum(1 for d in fillers if self.errs(d))
        self.assertGreaterEqual(len(goods), 12)
        self.assertGreaterEqual(len(fillers), 12)
        self.assertEqual((good_pass, filler_fail), (len(goods), len(fillers)),
                         "good %d/%d pass, filler %d/%d refused" % (good_pass, len(goods), filler_fail, len(fillers)))


class DesignCommandTests(PrinciplesCase):
    def test_sisi_design_prints_principles_and_questions(self):
        self.learn_all()
        r = self.sisi("design")
        self.assertEqual(r.returncode, 0, r.stderr)
        for p in PRINCIPLES:
            self.assertIn(p, r.stdout)
        for key in ("implies", "provided", "alternatives", "chosen", "objections", "challenge"):
            self.assertIn(key, r.stdout)

    def test_contract_init_prints_principles_and_design_skeleton(self):
        self.learn_all()
        r = self.sisi("contract", "init", "--goal", "build the orchestrator")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn(PRINCIPLES[0], r.stdout)
        c = json.load(open(os.path.join(self.proj, ".sisi", "contract.json")))
        self.assertIn("design", c)
        for key in ("implies", "provided", "alternatives", "chosen", "objections", "challenge"):
            self.assertIn(key, c["design"])


class DesignGateTests(PrinciplesCase):
    def gate(self, payload):
        return self.sisi("gate", stdin=json.dumps(payload))

    def large_contract_project(self, design=None):
        self.git_init()
        c = contract([check("a", "true")])
        if design is not None:
            c["design"] = design
        self.write_contract(c)
        with open(os.path.join(self.proj, "big.txt"), "w") as f:
            f.write("line\n" * 80)
        return {"session_id": "gate-design-1", "cwd": self.proj, "stop_hook_active": False}

    def test_large_change_without_design_is_sent_back_then_never_traps(self):
        self.learn_all()
        payload = self.large_contract_project()
        msgs = []
        for _ in range(5):
            r = self.gate(payload)
            out = r.stdout.strip()
            if not out:
                break
            d = json.loads(out)
            msgs.append(d)
            if d.get("decision") != "block":
                break
        self.assertTrue(any("design" in (m.get("reason") or "") for m in msgs), msgs)
        # never traps: within the send-back budget the turn is let through
        self.assertLessEqual(len([m for m in msgs if m.get("decision") == "block"]), 3)

    def test_large_change_with_good_design_is_not_sent_back_for_design(self):
        self.learn_all()
        payload = self.large_contract_project(design=good_design())
        r = self.gate(payload)
        self.assertNotIn("design section is missing", r.stdout)

    def test_small_change_needs_no_design(self):
        self.git_init()
        self.write_contract(contract([check("a", "true")]))
        with open(os.path.join(self.proj, "small.txt"), "w") as f:
            f.write("one line\n")
        r = self.gate({"session_id": "gate-design-small", "cwd": self.proj})
        self.assertNotIn("design", r.stdout)


class PromptDesignTests(PrinciplesCase):
    def test_design_work_gets_principles_and_instruction(self):
        self.learn_all()
        from sisi import prompt as P
        ctx = P.build_context("Build an automatic orchestrator that delegates work to other agents "
                              "across the tools installed here, with routing and judged outcomes")
        self.assertIn(PRINCIPLES[0], ctx)
        self.assertIn("design", ctx.lower())
        self.assertLessEqual(len(ctx), P.MAX_CHARS)

    def test_questions_and_small_edits_get_no_design_block(self):
        self.learn_all()
        from sisi import prompt as P
        for q in ("Should the orchestrator use subagents or command lines?",
                  "rename the helper that formats the orchestrator headings in the docs",
                  "fix the typo in the orchestrator help text on the second line"):
            self.assertNotIn(PRINCIPLES[0], P.build_context(q), q)

    def test_labelled_design_requests(self):
        self.learn_all()
        from sisi import prompt as P
        should = [
            "Build an automatic orchestrator that delegates work to other agents across tools",
            "Design and implement a new storage layer for session records with migration",
            "Create a command that discovers installed agent tools and routes work between them",
            "Implement a plugin system so other tools can add their own checks to the gate",
        ]
        should_not = [
            "Why does the orchestrator choose that worker for this kind of work?",
            "rename the local variable in the routing helper to something clearer",
            "fix the off-by-one in the pagination control of the list view",
            "What does the design section of a contract actually require in full?",
        ]
        hits = sum(1 for t in should if "design section" in P.build_context(t))
        false = sum(1 for t in should_not if "design section" in P.build_context(t))
        self.assertEqual((hits, false), (len(should), 0),
                         "design hits %d/%d, false %d/%d" % (hits, len(should), false, len(should_not)))


class RuleDesignTests(SisiCase):
    def test_first_rule_is_choose_the_approach_with_real_enforcement(self):
        r = self.sisi("rule", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("choose-the-approach", r.stdout)
        self.assertIn("Why:", r.stdout)
        from sisi import rulecmd
        self.assertIn("design", rulecmd.enforcement_for("choose-the-approach"))
        self.assertNotIn("not enforced", rulecmd.enforcement_for("choose-the-approach"))


if __name__ == "__main__":
    unittest.main()
