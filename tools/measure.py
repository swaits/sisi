#!/usr/bin/env python3
"""Measure sisi: size, always-loaded characters, hook cost, and test-suite cost.

Prints one JSON object and a short table. Everything runs in temporary homes;
the user's real data is never written. With --live, the loaded characters are
also measured against a temporary COPY of the user's real data.

Standard library only. Works against older checkouts: it copes with the old
command set (for example a retired rulebook command) when it finds one.
"""
import json, os, re, shutil, statistics, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
BIN = os.path.join(ROOT, "bin", "sisi")
REQUESTS = ("fix a typo in the README", "why is the build slow?",
            "add multi-page map printing with selectable paper size")


def run(args, env, cwd=None, stdin=""):
    return subprocess.run([sys.executable, BIN] + list(args), cwd=cwd or ROOT,
                          input=stdin, capture_output=True, text=True, env=env, timeout=300)


def temp_env(base):
    home = os.path.join(base, "home")
    for d in ("home/.claude", "home/.codex", "home/.config/opencode"):
        os.makedirs(os.path.join(base, d), exist_ok=True)
    env = dict(os.environ)
    env.update(SISI_HOME=home, SISI_DATA=os.path.join(base, "data"),
               SISI_STATE=os.path.join(base, "state"), SISI_LIB=os.path.join(base, "lib"),
               HOME=home)
    for k in ("SISI_TOOL", "SISI_SESSION_ID", "SISI_VERIFIERS", "SISI_DONE", "SISI_NOTES"):
        env.pop(k, None)
    return env


def fresh_install(env):
    run(["install"], env)
    gen = os.path.join(env["SISI_DATA"], "generated", "core.md")
    if not os.path.isfile(gen):
        # Older checkouts generated the rulebook through a separate command.
        help_text = run(["help"], env).stdout
        if "build-canon" in help_text:
            run(["build-canon"], env)
    chars = None
    if os.path.isfile(gen):
        with open(gen, encoding="utf-8") as f:
            chars = len(f.read())
    return chars


def hook_chars_and_times(env):
    tick = run(["tick"], env, stdin="{}")
    prompts = {r: run(["prompt", r], env).stdout for r in REQUESTS}
    times = {}
    for name, args, stdin in (("tick", ["tick"], "{}"),
                              ("prompt", ["prompt", REQUESTS[0]], ""),
                              ("gate", ["gate"], "{}")):
        samples = []
        for _ in range(5):
            t0 = time.perf_counter()
            run(args, env, stdin=stdin)
            samples.append(round(time.perf_counter() - t0, 4))
        times[name] = statistics.median(samples)
    return len(tick.stdout), {r: len(s) for r, s in prompts.items()}, times


def count_commands(env):
    out = run(["help"], env).stdout
    cmds = set()
    for line in out.splitlines():
        m = re.match(r"\s{2}sisi ([a-z][a-z-]*)", line)
        if m:
            cmds.add(m.group(1))
    return len(cmds)


def conformance():
    p = os.path.join(ROOT, "docs", "spec", "conformance.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    rows = data if isinstance(data, list) else data.get("requirements", []) if isinstance(data, dict) else []
    by = {}
    for r in rows:
        if isinstance(r, dict):
            by[str(r.get("status", "unknown"))] = by.get(str(r.get("status", "unknown")), 0) + 1
    return by or None


def main(argv):
    live = "--live" in argv
    py_files = []
    for dp, dns, fns in os.walk(os.path.join(ROOT, "sisi")):
        dns[:] = [d for d in dns if d != "__pycache__"]
        py_files += [os.path.join(dp, n) for n in fns if n.endswith(".py")]
    lines = 0
    for p in py_files:
        with open(p, encoding="utf-8", errors="replace") as f:
            lines += sum(1 for _ in f)
    lib_files = 0
    for d in ("verifiers", "done"):
        for dp, dns, fns in os.walk(os.path.join(ROOT, d)):
            lib_files += len([n for n in fns if n.endswith(".md")])

    with tempfile.TemporaryDirectory() as tmp:
        env = temp_env(tmp)
        rulebook = fresh_install(env)
        tick_chars, prompt_chars, times = hook_chars_and_times(env)
        commands = count_commands(env)

    result = {
        "python_lines_in_sisi": lines,
        "modules": len(py_files),
        "commands_in_help": commands,
        "library_files": lib_files,
        "rulebook_chars_fresh": rulebook,
        "tick_chars_fresh": tick_chars,
        "prompt_chars": prompt_chars,
        "hook_median_seconds": times,
    }

    if live:
        src_data = os.environ.get("SISI_DATA") or os.path.join(os.path.expanduser("~"), ".local", "share", "sisi")
        with tempfile.TemporaryDirectory() as tmp:
            env = temp_env(tmp)
            if os.path.isdir(src_data):
                shutil.copytree(src_data, env["SISI_DATA"], dirs_exist_ok=True)  # copy first; original never written
            rc = run(["doctor"], env)
            m = re.search(r"rulebook (\d+) lines.*?(\d+) characters", rc.stdout)
            result["rulebook_chars_live_copy"] = int(m.group(2)) if m else rulebook
            tick = run(["tick"], env, stdin="{}")
            result["tick_chars_live_copy"] = len(tick.stdout)

    t0 = time.perf_counter()
    suite = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "run_parallel.py")],
                           capture_output=True, text=True, timeout=900)
    result["test_suite_seconds"] = round(time.perf_counter() - t0, 2)
    counts = [int(x) for x in re.findall(r"Ran (\d+) tests in \d+ modules", suite.stdout + suite.stderr)]
    if not counts:
        counts = [int(x) for x in re.findall(r"Ran (\d+) tests", suite.stdout + suite.stderr)]
    result["test_count"] = max(counts) if counts else None
    conf = conformance()
    if conf is not None:
        result["conformance_by_status"] = conf

    print(json.dumps(result, indent=2, sort_keys=True))
    print()
    print("%-28s %s" % ("python lines in sisi/", result["python_lines_in_sisi"]))
    print("%-28s %s" % ("modules", result["modules"]))
    print("%-28s %s" % ("commands in sisi help", result["commands_in_help"]))
    print("%-28s %s" % ("library files", result["library_files"]))
    print("%-28s %s" % ("rulebook chars (fresh)", result["rulebook_chars_fresh"]))
    print("%-28s %s" % ("tick chars (fresh)", result["tick_chars_fresh"]))
    for r in REQUESTS:
        print("%-28s %s" % ("prompt chars", "%d  %s" % (result["prompt_chars"][r], r)))
    for k, v in sorted(result["hook_median_seconds"].items()):
        print("%-28s %s" % ("hook median s: " + k, v))
    print("%-28s %s" % ("test suite seconds", result["test_suite_seconds"]))
    print("%-28s %s" % ("test count", result["test_count"]))
    if conf is not None:
        print("%-28s %s" % ("conformance by status", json.dumps(conf, sort_keys=True)))
    if live:
        print("%-28s %s" % ("rulebook chars (live copy)", result.get("rulebook_chars_live_copy")))
        print("%-28s %s" % ("tick chars (live copy)", result.get("tick_chars_live_copy")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
