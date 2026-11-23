import json, os, unittest
from support import *


def load(path):
    with open(path) as f:
        return json.load(f)


def tool_line(name, inp):
    return {"type": "assistant", "timestamp": "2026-01-01T00:00:00.000Z",
            "message": {"role": "assistant", "content": [{"type": "tool_use", "name": name, "input": inp}]}}


class EndToEnd(SisiCase):
    """R-5.3-1, R-9-1, R-10.3-1..7, R-15-13, R-17-3, R-17-5, R-17-7: the real hook entry points with
    Claude-Code-shaped hook JSON, in a temp home and a temp git project, from install to a closed unit
    and a unit the gate had to release as unverified."""

    def setUp(self):
        super().setUp()
        os.environ["SISI_RETRO_REQUIRED"] = "1"
        self.addCleanup(lambda: os.environ.__setitem__("SISI_RETRO_REQUIRED", "0"))

    def hook(self, event, **extra):
        p = dict({"session_id": "e2e", "cwd": self.proj, "transcript_path": self.tp, "hook_event_name": event}, **extra)
        return self.sisi("tick" if event == "SessionStart" else "gate", stdin=json.dumps(p))

    def stop(self):
        r = self.hook("Stop", stop_hook_active=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        if not r.stdout.strip():
            return "allow", None
        d = json.loads(r.stdout)
        return ("block", d["reason"]) if d.get("decision") == "block" else ("allow", d.get("systemMessage"))

    def agent_writes(self, rel, text, tool="Write"):
        p = os.path.join(self.proj, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a" if tool == "Edit" else "w") as f:
            f.write(text)
        with open(self.tp, "a") as f:
            f.write(json.dumps(tool_line(tool, {"file_path": p})) + "\n")

    def agent_runs(self, command, *argv):
        with open(self.tp, "a") as f:
            f.write(json.dumps(tool_line("Bash", {"command": command})) + "\n")
        return self.sisi(*argv, env={"SISI_SESSION_ID": "e2e"})  # what the session-start hook exports to the agent's shell

    def finding(self, n):
        r = self.sisi("retro", "--finding", "`cargo test` run %d took 4 minutes with no fuzz verifier in the project" % n,
                      "--cause", "the recipe never named a fuzz verifier for parsers", "--impact", "time",
                      "--disposition", "promote",
                      "--change", "Add the fuzz verifier to the parser-or-codec recipe Checks, variant %d" % n,
                      "--mechanism", "verification", "--expect", "parser work gets a fuzz check",
                      "--validate", "run the recipe checks on a parser change", env={"SISI_SESSION_ID": "e2e"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_full_flow(self):
        for d in (".claude", ".codex", ".config/opencode"):
            os.makedirs(os.path.join(self.home, d))
        with open(os.path.join(self.home, ".claude", "settings.json"), "w") as f:
            json.dump({"hooks": {"SessionStart": [{"matcher": "*", "hooks": [{"type": "command", "command": "existing"}]}]}}, f)
        self.git_init()
        with open(os.path.join(self.proj, "README.md"), "w") as f:
            f.write("# project\n")
        self.assertEqual(self.sisi("install").returncode, 0)
        self.assertIn("claude-code  wired", self.sisi("doctor").stdout)
        self.tp = os.path.join(self.tmp, "e2e.jsonl")
        with open(self.tp, "w") as f:
            f.write(json.dumps({"type": "user", "timestamp": "2026-01-01T00:00:00.000Z",
                                "message": {"role": "user", "content": "build the feature"}}) + "\n")
        self.assertEqual(self.hook("SessionStart", source="startup").stdout, "")

        # a documentation change: silent, nothing run, nothing asked
        self.agent_writes("README.md", "more words\n", "Edit")
        self.assertEqual(self.stop(), ("allow", None))

        # a source change with no contract: sent back, with what it needs
        self.agent_writes("app.py", "def feature():\n    return 1\n")
        a, msg = self.stop()
        self.assertEqual(a, "block")
        self.assertIn("a contract for this isolated change", msg)
        self.assertIn("sisi contract init", msg)

        # a contract with a failing check: sent back with the failure
        self.agent_runs("sisi contract init --goal 'build the feature'", "contract", "init", "--goal", "build the feature")
        c = load(os.path.join(self.proj, ".sisi", "contract.json"))
        c["id"] = "feature"
        c["checks"] = [{"id": "feature", "claim": "done.flag exists", "kind": "general", "rung": 3,
                        "cmd": "test -f done.flag", "expect": {"exit": 0}}]
        self.agent_writes(os.path.join(".sisi", "contract.json"), json.dumps(c))
        a, msg = self.stop()
        self.assertEqual(a, "block")
        self.assertIn("feature", msg)
        self.assertIn("Failing checks", msg)

        # fixed: the two ways on are offered
        self.agent_writes("done.flag", "ok\n")
        a, msg = self.stop()
        self.assertEqual(a, "block")
        self.assertIn("sisi retro", msg)
        self.assertIn("sisi unit pause", msg)

        # paused: silent
        self.assertEqual(self.agent_runs("sisi unit pause 'the reviewer'", "unit", "pause", "the reviewer").returncode, 0)
        self.assertEqual(self.stop(), ("allow", None))
        self.assertIn("paused", self.sisi("status").stdout)

        # a new change ends the wait; everything is green, so the two ways on come again
        self.agent_writes("app.py", "# a change\n", "Edit")
        a, msg = self.stop()
        self.assertEqual(a, "block")
        self.assertEqual(load(os.path.join(self.proj, ".sisi", "contract.json"))["status"], "open")

        # the retro is recorded: the unit closes, is archived, and the stop is silent
        self.finding(1)
        self.assertEqual(self.stop(), ("allow", None))
        rec = load(os.path.join(self.proj, ".sisi", "units", "feature.json"))
        self.assertEqual(rec["delivery_status"], "delivered")
        out = self.sisi("status").stdout
        self.assertIn("[delivered]", out)
        self.assertIn("correctness and assurance", out)

        # a migration with no independent evidence: sent back with the list
        self.agent_writes("migrations/001_users.sql", "CREATE TABLE users (id integer);\n")
        self.agent_runs("sisi contract init --goal 'add users'", "contract", "init", "--goal", "add users")
        c = load(os.path.join(self.proj, ".sisi", "contract.json"))
        c["id"] = "users"
        c["checks"] = [{"id": "schema", "claim": "the migration file is present", "kind": "migration", "rung": 3,
                        "cmd": "test -f migrations/001_users.sql", "expect": {"exit": 0},
                        "covers": "the migration is deleted"}]
        c["invariants"] = [{"id": "readme", "claim": "the readme stays", "cmd": "test -f README.md", "expect": {"exit": 0}}]
        c["requirements"] = [{"id": "r1", "kind": "explicit", "text": "a users table exists", "decision": "now"}]
        c["risk"] = {"profile": "data", "blast_radius": "one new table; nothing reads it yet", "rollback": "drop the table"}
        c["approach"] = {"chosen": "a plain SQL migration", "why": "the project already uses them",
                         "alternatives": ["an ORM auto-migration: hides the schema"]}
        self.agent_writes(os.path.join(".sisi", "contract.json"), json.dumps(c))
        a, msg = self.stop()
        self.assertEqual(a, "block")
        self.assertIn("this data change is not ready to hand over (send-back 1 of 3)", msg)
        self.assertIn("independent evidence", msg)
        self.assertLessEqual(len(msg.splitlines()), 25)
        self.migration_message = msg

        # three send-backs in a row, then released as unverified and recorded
        self.assertEqual(self.stop()[0], "block")
        self.assertEqual(self.stop()[0], "block")
        a, msg = self.stop()
        self.assertEqual(a, "allow")
        self.assertIn("UNVERIFIED", msg)
        rows = [r for r in self.results() if r.get("check") == "gate" and r.get("status") == "unverified"]
        self.assertEqual(len(rows), 1)
        self.assertIn("independent evidence", rows[0]["reason"])
        self.assertIn("released unverified by the gate", self.sisi("status").stdout)
        self.assertEqual(self.sisi("unit", "close").returncode, 0)
        rec = load(os.path.join(self.proj, ".sisi", "units", "users.json"))
        self.assertEqual(rec["delivery_status"], "unverified")

        self.assertEqual(self.sisi("uninstall").returncode, 0)


if __name__ == "__main__":
    unittest.main()
