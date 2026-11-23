import json, os, unittest
from support import *


class EndToEnd(SisiCase):
    def test_full_flow(self):
        for d in (".claude", ".codex", ".config/opencode"):
            os.makedirs(os.path.join(self.home, d))
        with open(os.path.join(self.home, ".claude", "settings.json"), "w") as f:
            json.dump({"hooks": {"SessionStart": [{"matcher": "*", "hooks": [{"type": "command", "command": "existing"}]}]}}, f)
        self.git_init()
        self.assertEqual(self.sisi("install").returncode, 0)
        doc = self.sisi("doctor").stdout
        self.assertIn("claude-code  wired", doc)
        payload = json.dumps({"session_id": "e2e", "cwd": self.proj, "hook_event_name": "SessionStart", "source": "startup"})
        self.assertEqual(self.sisi("tick", stdin=payload).stdout, "")
        stop = json.dumps({"session_id": "e2e", "cwd": self.proj, "hook_event_name": "Stop", "stop_hook_active": False})

        self.write_contract(contract([check("feature", "test -f %s/done.txt" % self.proj, rung=3)]))
        r = self.sisi("gate", stdin=stop)
        self.assertEqual(r.returncode, 0)
        d = json.loads(r.stdout)
        self.assertEqual(d["decision"], "block")
        self.assertIn("feature", d["reason"])

        open(os.path.join(self.proj, "done.txt"), "w").close()
        r = self.sisi("gate", stdin=stop)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

        out = self.sisi("status").stdout
        self.assertIn("contracts verified : 1", out)
        self.assertIn("3: 100%", out)
        self.assertEqual(self.sisi("uninstall").returncode, 0)


if __name__ == "__main__":
    unittest.main()
