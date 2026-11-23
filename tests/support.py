import json, os, subprocess, sys, tempfile, unittest

import warnings
sys.warnoptions.append("ignore::ResourceWarning")  # keeps unittest from re-enabling them
warnings.simplefilter("ignore", ResourceWarning)  # tests read small files inline
REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO)
ITERS = max(1, int(os.environ.get("SISI_TEST_ITERS", "1")))  # scale property tests up with SISI_TEST_ITERS=10
BIN = os.path.join(REPO, "bin", "sisi")


_CURRENT = []  # the temp root of the test now running (empty outside a SisiCase)


def _guarded(name):
    """Every resolved root (home, state, personal data) must lie inside the running test's temp dir. A path that
    resolves into the real home, state or personal data dir fails the test at once, not by luck on a busy machine."""
    from sisi import paths
    orig = getattr(paths, name)

    def wrapper(*a, **kw):
        r = orig(*a, **kw)
        if _CURRENT and not os.path.realpath(r).startswith(_CURRENT[-1] + os.sep):
            raise AssertionError("isolation leak: paths.%s() resolved to %s, outside the test's temp dir %s" % (name, r, _CURRENT[-1]))
        return r
    wrapper.__wrapped__ = orig
    setattr(paths, name, wrapper)


for _n in ("home", "state", "data", "lib"):
    _guarded(_n)


class SisiCase(unittest.TestCase):
    """Every test gets a fresh SISI_HOME and SISI_STATE in temp dirs. Real config is never touched."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = os.path.realpath(self._tmp.name)
        self.home = os.path.join(self.tmp, "home")
        self.state = os.path.join(self.tmp, "state")
        self.data = os.path.join(self.tmp, "data")
        self.proj = os.path.join(self.tmp, "proj")
        for d in (self.home, self.proj):
            os.makedirs(d)
        tool_env = ("CODEX_HOME", "COPILOT_HOME", "PI_CODING_AGENT_DIR", "OPENCODE_CONFIG_DIR",
                    "GROK_HOME", "XDG_CONFIG_HOME")
        saved = {k: os.environ.get(k) for k in ("SISI_HOME", "SISI_STATE", "SISI_DATA", "SISI_TOOL", "SISI_SESSION_ID", "SISI_RETRO_REQUIRED", "SISI_NOTES") + tool_env}
        os.environ.update(SISI_HOME=self.home, SISI_STATE=self.state, SISI_DATA=self.data,
                          SISI_RETRO_REQUIRED="0")  # retro tests turn it on
        for k in ("SISI_NOTES",) + tool_env:  # tool config-dir overrides must not leak the real ones in
            os.environ.pop(k, None)
        _CURRENT.append(self.tmp)
        self.addCleanup(_CURRENT.pop)
        for k in ("SISI_TOOL", "SISI_SESSION_ID"):
            os.environ.pop(k, None)

        def restore():
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.addCleanup(restore)

    def sisi_proc(self, *args, cwd=None, stdin=None, env=None):
        """Run bin/sisi as a real subprocess (for timing tests and process-level behaviour)."""
        e = dict(os.environ, **(env or {}))
        # stdin is always closed after `stdin` (empty when none): hooks such as tick and gate read it to the end, so
        # inheriting an open pipe from whoever runs the suite makes them wait forever
        return subprocess.run([sys.executable, BIN] + list(args), cwd=cwd or self.proj, input=stdin or "",
                              capture_output=True, text=True, env=e, timeout=120)

    def sisi(self, *args, cwd=None, stdin=None, env=None):
        """Run the CLI in this process (fast). Same arguments and result shape as a subprocess run."""
        import contextlib, io
        from unittest import mock
        from sisi import cli
        out, err = io.StringIO(), io.StringIO()
        old_cwd = os.getcwd()
        os.chdir(cwd or self.proj)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                    mock.patch.object(sys, "stdin", io.StringIO(stdin or "")), mock.patch.dict(os.environ, env or {}):
                try:
                    rc = cli.main(list(args))
                except SystemExit as e:
                    rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        finally:
            os.chdir(old_cwd)
        return subprocess.CompletedProcess(args, rc or 0, out.getvalue(), err.getvalue())

    def git_init(self, d=None):
        d = d or self.proj
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "i"],
                       cwd=d, check=True)

    def write_contract(self, c, d=None, trusted=True):
        d = d or self.proj
        if trusted:
            from sisi import trust
            trust.add(d)
        os.makedirs(os.path.join(d, ".sisi"), exist_ok=True)
        with open(os.path.join(d, ".sisi", "contract.json"), "w") as f:
            json.dump(c, f)

    def results(self):
        p = os.path.join(self.state, "results.jsonl")
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return [json.loads(l) for l in f]


def check(id, cmd, rung=3, kind="general", exit=0, timeout_s=10, **expect):
    if cmd == "true":  # a passing check that can fail (bare `true` is vacuous and refused)
        cmd = "test -f .sisi/contract.json"
    return {"id": id, "claim": "claim " + id, "kind": kind, "rung": rung, "cmd": cmd,
            "expect": dict({"exit": exit}, **expect), "timeout_s": timeout_s}


def human(id, rung=5, kind="general"):
    return {"id": id, "claim": "claim " + id, "kind": kind, "rung": rung}


def contract(checks, invariants=()):
    return {"id": "t", "goal": "make the feature work", "risk": {"profile": "isolated"}, "checks": list(checks),
            "invariants": list(invariants), "assumptions": [], "questions": []}


def skip_timing_if_busy(case):
    """Skip a wall-clock speed assertion when the machine is overloaded.

    A speed test measures sisi only when the machine has spare capacity. With more runnable work
    than processors it measures the queue, and a failure says nothing about the code.
    """
    import os
    try:
        load, cpus = os.getloadavg()[0], os.cpu_count() or 1
    except OSError:
        return
    if load > cpus:
        case.skipTest("machine overloaded (load %.0f on %d processors): speed not measured" % (load, cpus))
