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

Exit status 0 only when all four hold. Options: --keep (leave the temporary folder), --model NAME, --max-usd N.
"""
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile, time

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO)

MAIN_MODEL = "haiku"                     # the host's least expensive model, the main thread
WORKERS = (("sonnet", 3), ("opus", 15))  # fixture workers (names the host's subagent tool accepts) and a price each
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


def run_agent(args, tmp, proj, env, log):
    settings = os.path.join(tmp, "home", ".claude", "settings.json")
    cmd = ["claude", "-p", PROMPT, "--model", args.model, "--output-format", "stream-json", "--verbose",
           "--include-hook-events", "--setting-sources", "project", "--settings", settings,
           "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence",
           "--permission-mode", "bypassPermissions", "--max-budget-usd", str(args.max_usd),
           "--tools", "Bash,Read,Edit,Write,Glob,Grep,Agent"]
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


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--model", default=MAIN_MODEL)
    ap.add_argument("--max-usd", type=float, default=1.0)
    args = ap.parse_args(argv)
    if shutil.which("claude") is None:
        print("live check: the host's command-line tool (claude) is not installed here; nothing was run")
        return 2
    tmp = tempfile.mkdtemp(prefix="sisi-live-")
    data, state, lib, home, proj = (os.path.join(tmp, n) for n in ("data", "state", "lib", "home", "proj"))
    os.makedirs(os.path.join(home, ".claude"))
    os.makedirs(lib)
    build_project(proj)
    real = real_data_dir()
    before_real = snapshot(real)
    base_env = dict(os.environ, SISI_DATA=data, SISI_STATE=state, SISI_LIB=lib)
    for k in ("SISI_HOME", "SISI_TOOL", "SISI_SESSION_ID", "SISI_WORKER_RUN"):
        base_env.pop(k, None)
    inst = subprocess.run([sys.executable, os.path.join(REPO, "bin", "sisi"), "install"], cwd=proj, capture_output=True,
                          text=True, env=dict(base_env, SISI_HOME=home))
    if inst.returncode != 0:
        print("live check: install into the temporary home failed:\n" + inst.stdout + inst.stderr)
        return 1
    fixture_ledger(data)
    tmpbin = os.path.join(tmp, "bin")
    os.makedirs(tmpbin)
    os.symlink(os.path.join(REPO, "bin", "sisi"), os.path.join(tmpbin, "sisi"))
    env = dict(base_env, PATH=tmpbin + os.pathsep + os.environ.get("PATH", ""))
    log = os.path.join(tmp, "stream.jsonl")
    rc, err, secs = run_agent(args, tmp, proj, env, log)
    calls, results, events = parse(log)
    failures, report = [], []

    # (a) a refusal from sisi's hook, as the agent received it
    refused = [(i, c) for i, c in enumerate(calls) if results.get(c[0], ("", False))[1]
               and "sisi: " in results[c[0]][0] and "direct tool calls" in results[c[0]][0]]
    if not refused:
        failures.append("(a) no tool call was refused by sisi's meter (calls: %d; the host's exit status %s)" % (len(calls), rc))
    else:
        first_i, first = refused[0]
        report.append("refusal text the agent received (call #%d, %s):\n%s" % (first_i + 1, first[1], results[first[0]][0]))
        after = calls[first_i + 1:first_i + 3]
        report.append("the next two tool calls after it:\n" + "\n".join(
            "  %s %s" % (c[1], json.dumps(c[2])[:300]) for c in after))
        # (b) a delegation naming a model, or a recorded reason
        later = calls[first_i + 1:]
        deleg = [c for c in later if c[1] in ("Agent", "Task") and str((c[2] or {}).get("model") or "").strip()]
        direct = [c for c in later if c[1] == "Bash" and "unit direct" in str((c[2] or {}).get("command") or "")]
        if not deleg and not direct:
            failures.append("(b) after the refusal the session neither delegated with a model nor ran `sisi unit direct`")
        # (c) the matching record in the temporary data
        ledger = [json.loads(l) for l in open(os.path.join(data, "delegations.jsonl")) if l.strip()] \
            if os.path.exists(os.path.join(data, "delegations.jsonl")) else []
        runs = [r for r in ledger if r.get("kind") in ("run", "run-end")]
        evfile = os.path.join(state, "orchestration.jsonl")
        evs = [json.loads(l) for l in open(evfile) if l.strip()] if os.path.exists(evfile) else []
        exts = [e for e in evs if e.get("ev") == "extension"]
        if deleg and not [r for r in runs if r.get("kind") == "run"]:
            failures.append("(c) the session delegated but the ledger holds no run record")
        if direct and not deleg and not exts:
            failures.append("(c) the session ran `sisi unit direct` but no extension was recorded "
                            "(its reasons may have been refused as generic)")
        report.append("ledger lines after the run:\n" + "\n".join("  " + json.dumps(r) for r in runs[-4:] or ["  (none)"]))
        report.append("orchestration events (state):\n" + "\n".join(
            "  " + json.dumps(e) for e in [e for e in evs if e.get("ev") != "chars"][-8:] or ["  (none)"]))
    # (d) the real sisi data is untouched
    if snapshot(real) != before_real:
        failures.append("(d) files under the real sisi data folder (%s) changed" % real)
    report.append("tool calls made by the main thread: %d; refused: %d; host exit status %s; %.0fs"
                  % (len(calls), len(refused), rc, secs))
    print("\n\n".join(report))
    if rc not in (0, None) and not calls:
        print("\nhost stderr:\n" + (err or "")[-1500:])
    if failures:
        print("\nLIVE CHECK FAILED:\n  " + "\n  ".join(failures))
        print("temporary folder kept: %s" % tmp)
        return 1
    print("\nLIVE CHECK PASSED (a, b, c, d)")
    if args.keep:
        print("temporary folder kept: %s" % tmp)
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
