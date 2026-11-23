"""Routing with host-native workers (bare names), notes, provider limits, session-start wording.
Fixture ledger is shaped like a real one: bare host names with hundreds of attempts beside
prefixed provider workers. Requirement ids: R-7.2-1..3, R-7.1-1, R-17-3, R-17-8."""
import json, os, stat, subprocess, time, unittest
from support import *

FAKE_MUSE = """#!/bin/sh
case "$1" in
  exec)
    if [ "$2" = "--list-models" ]; then echo "beta-1"; echo "beta-2"; exit 0; fi
    echo "done" ;;
  *) echo 'muse help' ;;
esac
exit 0
"""
FAKE_CODEX = """#!/bin/sh
case "$1 $2" in
  "debug models") echo '{"models":[{"slug":"alpha-1"}]}' ;;
  *) echo 'codex help' ;;
esac
exit 0
"""


class RouteCase(SisiCase):
    def setUp(self):
        super().setUp()
        self.bindir = os.path.join(self.tmp, "bin")
        os.makedirs(self.bindir)
        for name, body in (("muse", FAKE_MUSE), ("codex", FAKE_CODEX)):
            p = os.path.join(self.bindir, name)
            open(p, "w").write(body)
            os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)

    def env(self, **kw):
        return dict(PATH=self.bindir, **kw)

    def seed(self, spec, type="impl", difficulty=2):
        """spec: [(worker, attempts, accepted)]"""
        os.makedirs(self.data, exist_ok=True)
        n = 0
        with open(os.path.join(self.data, "delegations.jsonl"), "a") as f:
            for worker, attempts, accepted in spec:
                for i in range(attempts):
                    n += 1
                    f.write(json.dumps({"kind": "attempt", "id": "r%d" % n, "ts": 1760000000 + n,
                                        "project": "p", "type": type, "difficulty": difficulty,
                                        "worker": worker, "outcome": "accepted" if i < accepted else "rejected",
                                        "check": "tests", "minutes": 5}) + "\n")

    def seed_real_shape(self):
        self.seed([("wk-fast", 300, 290), ("wk-mid", 120, 100), ("muse/beta-1", 12, 11), ("codex/alpha-1", 9, 8)])

    def down(self, *providers):
        for p in providers:
            r = self.sisi("workers", "down", p, "--reason", "limit", "--until", "2099-01-02", env=self.env())
            self.assertEqual(r.returncode, 0, r.stderr)


class HostNativeTests(RouteCase):
    def test_bare_names_are_routable_host_workers(self):
        """R-7.2-1, R-7.2-3, R-7.1-1: a worker id without a provider prefix is a host subagent: routable
        with no discovered tool, and the mechanism line says to use the host's subagent tool."""
        self.seed_real_shape()
        r = self.sisi("route", "--kind", "impl", "--difficulty", "2", env=dict(PATH=""))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        first = r.stdout.splitlines()[0]
        self.assertTrue(first.startswith("wk-"), r.stdout)
        self.assertIn("host's own subagent tool with model %s" % first, r.stdout)
        self.assertNotIn("no tool for it", r.stdout)

    def test_down_host_worker_is_skipped(self):
        """R-7.2-3: a host worker marked down is passed over like any other."""
        self.seed_real_shape()
        self.sisi("workers", "down", "wk-fast", "--reason", "limit", "--until", "2099-01-02", env=self.env())
        self.sisi("workers", "down", "wk-mid", "--reason", "limit", "--until", "2099-01-02", env=self.env())
        r = self.sisi("route", "--kind", "impl", "--difficulty", "2", "--explain", env=self.env())
        self.assertNotIn("wk-", r.stdout.splitlines()[0])


if __name__ == "__main__":
    unittest.main()
