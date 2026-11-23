#!/usr/bin/env python3
"""Live proof that orchestration is enforced: a real headless agent session, not synthetic hook input.

Run it before any release that touches the hooks or the rulebook (docs/developing.md). It costs a little money and
needs the host's login, so it is not part of the unit suite.

What it does:
  1. builds a small temporary git project (about fifteen short source files, one planted bug);
  2. installs sisi's hooks with `bin/sisi install` into a temporary home, so the settings file is exactly what the
     installer writes, pointing at THIS checkout's bin/sisi (SISI_LIB is empty, so no stable copy is used);
  3. puts a fixture ledger with two usable workers in a temporary SISI_DATA (SISI_STATE is temporary too) and a
     temporary `sisi` first on PATH, so nothing the agent runs can reach the real sisi data;
  4. starts the host's command-line tool headless with its least expensive model as the main thread and a task that
     needs well over six direct tool calls, capturing the stream of events;
  5. asserts from the events and the temporary data that (a) a tool call was refused by sisi's hook with the meter's
     message, (b) afterwards the session started a delegation naming a model or recorded a reason with
     `sisi unit direct`, (c) the temporary ledger or unit telemetry holds the matching record, (d) nothing under the
     real sisi data folder changed.

A second short scenario proves the automatic fallback: the fixture has one prefixed provider whose fake
command-line tool always prints a quota error with a reset time, and another usable worker; the main thread is
asked to delegate a small task to the cheapest worker. It asserts that the provider was marked down until the
parsed time, that the session went on to use another worker, that it never called the question dialog, and that
its final message to the person says nothing about the provider, a quota, a limit or a fallback.

Exit status 0 only when everything holds. Options: --keep (leave the temporary folder), --model NAME, --max-usd N,
--only 1|2 (run one scenario).
"""
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile, time

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO)

MAIN_MODEL = "haiku"                     # the host's least expensive model, the main thread
WORKERS = (("sonnet", 3), ("opus", 15))  # fixture workers (names the host's subagent tool accepts) and a price each
RESET = "2036-12-01T00:00:00Z"            # the reset time the fake provider's error message names
QUOTA_TEXT = ("API error 429 [request_id=req_live]: Subscription quota exhausted. Your usage window resets at " + RESET)
PROMPT2 = ("This project is in the current directory. Delegate one small task to the cheapest worker: list the python "
           "files in src/, one per line. Ask `sisi route --kind research --difficulty 1` who that is, write the brief "
           "(`sisi delegate brief` prints the template; save it as brief.md), and run it with "
           "`sisi delegate --kind research --difficulty 1 --brief brief.md`. The list is what I want back: reply with it.")
PROMPT = ("This project is in the current directory. Find and fix the bug (a test in tests/ fails), then tell me "
          "what each file in src/ does, one line per file.")


def build_project(root):
    os.makedirs(os.path.join(root, "src"))
    os.makedirs(os.path.join(root, "tests"))
    for i in range(1, 15):
        body = ["def f%d(x):" % i, "    \"\"\"Module %d: step %d of a small pipeline.\"\"\"" % (i, i),
                "    return x + %d" % i, ""]
        if i == 7:  # the planted bug: the result should be doubled
            body = ["def f7(x):", "    \"\"\"Module 7: doubles a number after adding seven.\"\"\"",
                    "    return (x + 7) * 3", ""]
        with open(os.path.join(root, "src", "mod%02d.py" % i), "w") as f:
            f.write("\n".join(body))
    with open(os.path.join(root, "src", "__init__.py"), "w") as f:
        f.write("")
    with open(os.path.join(root, "tests", "test_mod07.py"), "w") as f:
        f.write("import sys, os\nsys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))\n"
                "from src.mod07 import f7\n\n\ndef test_f7():\n    assert f7(1) == 16\n")
    with open(os.path.join(root, "README.md"), "w") as f:
        f.write("A pipeline of small steps; run the tests with `python3 -m pytest tests` (or call them by hand).\n")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "start"], cwd=root, check=True)


def fixture_ledger(data):
    os.makedirs(data, exist_ok=True)
    rows = []
    for w, _price in WORKERS:
        for kind in ("research", "implementation"):
            rows.append({"kind": "attempt", "id": "%s%s" % (w[:3], kind[:2]), "run_id": None, "ts": 1, "project": "fixture",
                         "type": kind, "difficulty": 1, "worker": w, "outcome": "accepted", "check": "read"})
    with open(os.path.join(data, "delegations.jsonl"), "w") as f:
        f.write("".join(json.dumps(r) + "\n" for r in rows))
    with open(os.path.join(data, "worker-prices.json"), "w") as f:
        json.dump({"models": {w: {"cost_per_million_tokens": p} for w, p in WORKERS}}, f)


def fixture_fallback(data, tmpbin):
    """Scenario 2: the cheapest worker is a fake provider whose command-line tool always answers with a quota error."""
    os.makedirs(data, exist_ok=True)
    rows = []
    for w in ("fakeprov/fake-model", "sonnet", "opus"):
        rows.append({"kind": "attempt", "id": "x%s" % w[:3], "run_id": None, "ts": 1, "project": "fixture",
                     "type": "research", "difficulty": 1, "worker": w, "outcome": "accepted", "check": "read"})
    with open(os.path.join(data, "delegations.jsonl"), "w") as f:
        f.write("".join(json.dumps(r) + "\n" for r in rows))
    with open(os.path.join(data, "worker-prices.json"), "w") as f:
        json.dump({"models": {"fakeprov/fake-model": {"cost_per_million_tokens": 0.1}, "sonnet": {"cost_per_million_tokens": 3},
                              "opus": {"cost_per_million_tokens": 15}}}, f)
    with open(os.path.join(data, "workers.json"), "w") as f:  # a fresh discovery, so no real tool is ever listed
        json.dump({"checked": time.time(), "tools": [{"name": "opencode", "installed": True, "usable": True,
                                                      "models": ["fakeprov/fake-model"], "learned_by_use": False}]}, f)
    with open(os.path.join(data, "config.json"), "w") as f:
        json.dump({"workers": {"refresh_after_s": 1e12}}, f)
    exe = os.path.join(tmpbin, "opencode")
    with open(exe, "w") as f:
        f.write("#!/bin/sh\nif [ \"$1\" = models ]; then echo fakeprov/fake-model; exit 0; fi\n"
                "echo '%s' >&2\nexit 1\n" % QUOTA_TEXT)
    os.chmod(exe, 0o755)


def real_data_dir():
    env = dict(os.environ)
    for k in ("SISI_DATA", "SISI_HOME"):
        env.pop(k, None)
    out = subprocess.run([sys.executable, "-c", "from sisi import paths; print(paths.data())"], cwd=REPO, env=dict(
        env, PYTHONPATH=REPO), capture_output=True, text=True)
    return out.stdout.strip()


def snapshot(d):
    """(path, size, mtime) of every file under d except the personal-data repository's own git internals (its
    commits are made by any other sisi session running on this machine at the same time)."""
    rows = []
    for dp, dns, fns in os.walk(d):
        dns[:] = sorted(x for x in dns if x != ".git")
        for n in sorted(fns):
            p = os.path.join(dp, n)
            try:
                st = os.lstat(p)
                rows.append((os.path.relpath(p, d), st.st_size, st.st_mtime_ns))
            except OSError:
                pass
    return rows


def run_agent(args, tmp, proj, env, log, prompt=PROMPT):
    settings = os.path.join(tmp, "home", ".claude", "settings.json")
    cmd = ["claude", "-p", prompt, "--model", args.model, "--output-format", "stream-json", "--verbose",
           "--include-hook-events", "--setting-sources", "project", "--settings", settings,
           "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence",
           "--permission-mode", "bypassPermissions", "--max-budget-usd", str(args.max_usd),
           "--tools", "Bash,Read,Edit,Write,Glob,Grep,Agent,AskUserQuestion"]
    t0 = time.time()
    with open(log, "w") as f:
        p = subprocess.run(cmd, cwd=proj, env=env, stdout=f, stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL,
                           timeout=900)
    return p.returncode, p.stderr, time.time() - t0


def parse(log):
    """(tool calls in order [(id, name, input)], results {id: (text, is_error)}, raw events)."""
    calls, results, events = [], {}, []
    with open(log) as f:
        for line in f:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            events.append(ev)
            if ev.get("parent_tool_use_id"):
                continue
            msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                if ev.get("type") == "assistant" and b.get("type") == "tool_use":
                    calls.append((b.get("id"), b.get("name"), b.get("input") or {}))
                elif ev.get("type") == "user" and b.get("type") == "tool_result":
                    c = b.get("content")
                    if isinstance(c, list):
                        c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
                    results[b.get("tool_use_id")] = (c or "", bool(b.get("is_error")))
    return calls, results, events


def setup(prefix):
    """A temporary world: project, temporary sisi data and state, hooks installed from this checkout's launcher, a
    temporary `sisi` first on PATH. Returns a dict, or None when the install failed."""
    tmp = tempfile.mkdtemp(prefix=prefix)
    data, state, lib, home, proj = (os.path.join(tmp, n) for n in ("data", "state", "lib", "home", "proj"))
    os.makedirs(os.path.join(home, ".claude"))
    os.makedirs(lib)
    build_project(proj)
    base_env = dict(os.environ, SISI_DATA=data, SISI_STATE=state, SISI_LIB=lib)
    for k in ("SISI_HOME", "SISI_TOOL", "SISI_SESSION_ID", "SISI_WORKER_RUN"):
        base_env.pop(k, None)
    inst = subprocess.run([sys.executable, os.path.join(REPO, "bin", "sisi"), "install"], cwd=proj, capture_output=True,
                          text=True, env=dict(base_env, SISI_HOME=home))
    if inst.returncode != 0:
        print("live check: install into the temporary home failed:\n" + inst.stdout + inst.stderr)
        return None
    tmpbin = os.path.join(tmp, "bin")
    os.makedirs(tmpbin)
    os.symlink(os.path.join(REPO, "bin", "sisi"), os.path.join(tmpbin, "sisi"))
    env = dict(base_env, PATH=tmpbin + os.pathsep + os.environ.get("PATH", ""))
    return {"tmp": tmp, "data": data, "state": state, "proj": proj, "bin": tmpbin, "env": env,
            "log": os.path.join(tmp, "stream.jsonl")}


def jsonl(path):
    return [json.loads(l) for l in open(path) if l.strip()] if os.path.exists(path) else []


def bash_cmd(call):
    return str((call[2] or {}).get("command") or "") if call[1] == "Bash" else ""


def final_message(events):
    for ev in reversed(events):
        if ev.get("type") == "result":
            return str(ev.get("result") or "")
    return ""


def scenario_orchestration(args):
    """The meter, the delegation guard and the record, in a real session. Returns (failures, report lines, ctx)."""
    w = setup("sisi-live-1-")
    if w is None:
        return ["install failed"], [], None
    fixture_ledger(w["data"])
    rc, err, secs = run_agent(args, w["tmp"], w["proj"], w["env"], w["log"])
    calls, results, events = parse(w["log"])
    failures, report = [], []
    refused = [(i, c) for i, c in enumerate(calls) if results.get(c[0], ("", False))[1]
               and "sisi: " in results[c[0]][0] and "direct tool calls" in results[c[0]][0]]
    if not refused:
        failures.append("(a) no tool call was refused by sisi's meter (calls: %d; the host's exit status %s)" % (len(calls), rc))
    else:
        first_i, first = refused[0]
        report.append("refusal text the agent received (call #%d, %s):\n%s" % (first_i + 1, first[1], results[first[0]][0]))
        report.append("the next two tool calls after it:\n" + "\n".join(
            "  %s %s" % (c[1], json.dumps(c[2])[:300]) for c in calls[first_i + 1:first_i + 3]))
        later = calls[first_i + 1:]
        routes = [i for i, c in enumerate(later) if "sisi route" in bash_cmd(c)]
        deleg = [i for i, c in enumerate(later) if c[1] in ("Agent", "Task") and str((c[2] or {}).get("model") or "").strip()]
        direct = [c for c in later if "unit direct" in bash_cmd(c)]
        routed_then_delegated = any(d > r for r in routes for d in deleg)
        if not routed_then_delegated and not direct:
            failures.append("(b) after the refusal the session neither ran `sisi route` and then delegated with a model "
                            "nor ran `sisi unit direct`")
        ledger = jsonl(os.path.join(w["data"], "delegations.jsonl"))
        runs = [r for r in ledger if r.get("kind") in ("run", "run-end")]
        evs = jsonl(os.path.join(w["state"], "orchestration.jsonl"))
        exts = [e for e in evs if e.get("ev") == "extension"]
        if routed_then_delegated and not [r for r in runs if r.get("kind") == "run"]:
            failures.append("(c) the session delegated but the ledger holds no run record")
        if routed_then_delegated and not [e for e in evs if e.get("ev") == "route"]:
            failures.append("(c) the session ran `sisi route` but no routing decision was recorded")
        if direct and not routed_then_delegated and not exts:
            failures.append("(c) the session ran `sisi unit direct` but no extension was recorded "
                            "(its reasons may have been refused as generic)")
        report.append("ledger lines after the run:\n" + "\n".join("  " + json.dumps(r) for r in runs[-4:] or ["  (none)"]))
        report.append("orchestration events (state):\n" + "\n".join(
            "  " + json.dumps(e) for e in [e for e in evs if e.get("ev") != "chars"][-8:] or ["  (none)"]))
    report.append("scenario 1: tool calls made by the main thread: %d; refused: %d; host exit status %s; %.0fs"
                  % (len(calls), len(refused), rc, secs))
    return failures, report, w


def scenario_fallback(args):
    """The automatic fallback in a real session (item 9g)."""
    w = setup("sisi-live-2-")
    if w is None:
        return ["install failed"], [], None
    fixture_fallback(w["data"], w["bin"])
    rc, err, secs = run_agent(args, w["tmp"], w["proj"], w["env"], w["log"], prompt=PROMPT2)
    calls, results, events = parse(w["log"])
    failures, report = [], []
    avail = {}
    try:
        with open(os.path.join(w["data"], "worker-availability.json")) as f:
            avail = json.load(f)
    except (OSError, ValueError):
        pass
    sys.path.insert(0, REPO)
    from sisi import workers
    want = workers._parse_time(RESET)
    down = avail.get("fakeprov") or {}
    if down.get("retry_at") != want:
        failures.append("(g1) the provider was not marked down until the parsed reset time (availability: %s)"
                        % json.dumps(avail)[:300])
    delegate_i = next((i for i, c in enumerate(calls) if "sisi delegate" in bash_cmd(c) and "brief" not in bash_cmd(c).split("delegate")[1][:8]), None)
    after = calls[delegate_i + 1:] if delegate_i is not None else []
    other = [c for c in after if c[1] in ("Agent", "Task") and str((c[2] or {}).get("model") or "").strip()
             and "fake" not in str((c[2] or {}).get("model")).lower()]
    ledger_runs = [r for r in jsonl(os.path.join(w["data"], "delegations.jsonl")) if r.get("kind") == "run"]
    if delegate_i is None:
        failures.append("(g2) the session never ran `sisi delegate`")
    elif not other:
        failures.append("(g2) after the failed worker the session did not go on to use another worker (the host's own subagent tool)")
    dialog = [c for c in calls if c[1] == "AskUserQuestion"]
    if dialog:
        failures.append("(g3) the session called the question dialog %d time(s): %s" % (len(dialog), json.dumps(dialog[0][2])[:200]))
    final = final_message(events)
    leaked = [t for t in ("fakeprov", "fake-model", "opencode", "quota", "limit", "fallback", "unavailable", "429")
              if t in final.lower()]
    if leaked:
        failures.append("(g4) the final message to the person mentions %s: %s" % (leaked, final[:300]))
    report.append("scenario 2: availability file: %s" % json.dumps(avail))
    report.append("calls after the failed worker: " + "; ".join("%s %s" % (c[1], json.dumps(c[2])[:120]) for c in after[:4]))
    report.append("ledger runs: " + ("; ".join(json.dumps(r)[:200] for r in ledger_runs[-2:]) or "(none)"))
    report.append("question dialog calls: %d; final message to the person: %r" % (len(dialog), final[:300]))
    report.append("scenario 2: %d tool calls; host exit status %s; %.0fs" % (len(calls), rc, secs))
    return failures, report, w


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--model", default=MAIN_MODEL)
    ap.add_argument("--max-usd", type=float, default=1.0)
    ap.add_argument("--only", choices=("1", "2"))
    args = ap.parse_args(argv)
    if shutil.which("claude") is None:
        print("live check: the host's command-line tool (claude) is not installed here; nothing was run")
        return 2
    real = real_data_dir()
    before_real = snapshot(real)
    failures, report, worlds = [], [], []
    for n, fn in (("1", scenario_orchestration), ("2", scenario_fallback)):
        if args.only in (None, n):
            f, r, w = fn(args)
            failures += f
            report += r
            worlds.append(w)
    if snapshot(real) != before_real:
        failures.append("(d) files under the real sisi data folder (%s) changed" % real)
    print("\n\n".join(report))
    if failures:
        print("\nLIVE CHECK FAILED:\n  " + "\n  ".join(failures))
        print("temporary folders kept: %s" % ", ".join(w["tmp"] for w in worlds if w))
        return 1
    print("\nLIVE CHECK PASSED (a, b, c, d, g)")
    for w in worlds:
        if w and args.keep:
            print("temporary folder kept: %s" % w["tmp"])
        elif w:
            shutil.rmtree(w["tmp"], ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
