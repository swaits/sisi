"""Run a contract: every check and invariant with a cmd, in the project dir, with a timeout."""
import json, os, signal, subprocess, time

from . import contract as C, store

TAIL = 1500


def _tail(s):
    s = s.strip()
    return s[-TAIL:] if len(s) > TAIL else s


def run_cmd(cmd, cwd, timeout, expect):
    """Return (status, duration, tail). status: passed/failed/timeout."""
    t0 = time.time()
    if timeout <= 0:
        return "timeout", 0.0, "not run: time budget exhausted"
    try:
        p = subprocess.Popen(cmd, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        return "failed", 0.0, "could not start: %s" % e
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            p.communicate(timeout=5)
        except Exception:
            pass
        return "timeout", time.time() - t0, "timed out after %gs" % timeout
    dur = time.time() - t0
    o, e = out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
    tail = _tail(o + ("\n" if o and e else "") + e)
    want = expect.get("exit", 0)
    if p.returncode != want:
        return "failed", dur, "exit %d, expected %d\n%s" % (p.returncode, want, tail)
    sc = expect.get("stdout_contains")
    if sc is not None and sc not in o:
        return "failed", dur, "stdout does not contain %r\n%s" % (sc, tail)
    return "passed", dur, tail


def tree_fp(project, contract_path):
    """The working-tree fingerprint shared by verify, deep runs and the gate."""
    from . import gitutil
    try:
        return gitutil.fingerprint(project, [contract_path])
    except Exception:
        return None


MAX_PARALLEL = 4


def _run_item(item, x, tier, project, deadline, default_timeout):
    r = {"item": item, "id": x["id"], "kind": x.get("kind"), "rung": x.get("rung"), "claim": x.get("claim"),
         "tier": tier}
    if x.get("rung") in (5, 6):
        r.update(status="awaiting-human", duration_s=0.0, tail="")
    else:
        to = float(x.get("timeout_s", default_timeout))
        if deadline is not None:
            to = min(to, deadline - time.time())
        st, dur, tail = run_cmd(x["cmd"], project, to, x.get("expect", {"exit": 0}))
        r.update(status=st, duration_s=round(dur, 3), tail=tail)
    return r


def run(c, project, deadline=None, default_timeout=60, tiers=("fast",)):
    """Run the items of the given tiers. Returns list of result dicts (with 'tail'), in contract order.
    deadline is a time.time() value. With top-level "parallel": true in the contract, fast-tier items run together
    (at most MAX_PARALLEL at a time), except items marked "serial": true, which run alone afterwards."""
    items = [("check", x) for x in c["checks"]] + [("invariant", x) for x in c.get("invariants", [])]
    items = [(item, x, x.get("tier", "fast")) for item, x in items if x.get("tier", "fast") in tiers]
    res = [None] * len(items)
    par = [i for i, (_, x, tier) in enumerate(items) if c.get("parallel") is True and tier == "fast" and not x.get("serial")]
    if len(par) > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as ex:
            futs = {i: ex.submit(_run_item, items[i][0], items[i][1], items[i][2], project, deadline, default_timeout)
                    for i in par}
            for i, f in futs.items():
                res[i] = f.result()
    for i, (item, x, tier) in enumerate(items):
        if res[i] is None:
            res[i] = _run_item(item, x, tier, project, deadline, default_timeout)
    for f in (C.floor_failures(c) if "fast" in tiers else []):
        res.append({"item": "floor", "tier": "fast", "id": "floor:" + f["kind"], "kind": f["kind"], "rung": None,
                    "claim": f["message"], "status": "failed", "duration_s": 0.0, "tail": f["message"]})
    return res


def ok(results):
    return all(r["status"] in ("passed", "awaiting-human") for r in results)


def record(c, project, results, fp=None):
    run_id = "%x-%d" % (time.time_ns(), os.getpid())
    for r in results:
        store.append("results", {"ts": store.now(), "contract": c["id"], "project": project,
                                 "check": r["id"], "item": r["item"], "kind": r["kind"], "rung": r["rung"],
                                 "status": r["status"], "duration_s": r["duration_s"],
                                 "tool": store.tool(), "session": store.session_id(), "run": run_id,
                                 "tier": r.get("tier", "fast"), "fp": fp})


def format_table(results):
    rows = [("ID", "KIND", "RUNG", "TIER", "STATUS", "SECS")]
    for r in results:
        rows.append((r["id"], r["kind"] or "-", str(r["rung"] or "-"), r.get("tier", "fast"), r["status"], "%.1f" % r["duration_s"]))
    w = [max(len(row[i]) for row in rows) for i in range(6)]
    return "\n".join("  ".join(v.ljust(w[i]) for i, v in enumerate(row)).rstrip() for row in rows)


def failure_report(results, limit=4000):
    parts = []
    for r in results:
        if r["status"] in ("failed", "timeout"):
            parts.append("- %s %s [%s]: %s\n%s" % (r["item"], r["id"], r["status"], r.get("claim") or "",
                                                  "\n".join("    " + l for l in (r["tail"] or "").splitlines()[-15:])))
    s = "\n".join(parts)
    return s if len(s) <= limit else s[:limit] + "\n... (truncated)"


def cmd_verify(args, cwd=None, out=print):
    from . import deep, trust
    cwd = cwd or os.getcwd()
    path = C.find(cwd)
    if not path:
        out("sisi: no contract found (run `sisi contract init`)")
        return 2
    try:
        c = C.load(path)
    except (OSError, ValueError) as e:
        out("sisi: cannot read %s: %s" % (path, e))
        return 1
    project = C.project_dir(path)
    if not trust.is_trusted(project):
        out("sisi: refusing to run: " + trust.hint(project))
        return 3
    errs = C.validate(c)
    if errs:
        out("sisi: invalid contract %s" % path)
        for e in errs:
            out("  - " + e)
        return 1
    fp = tree_fp(project, path)
    as_json = "--json" in args
    if "--deep" in args and "--all" in args:
        out("sisi: use either --deep or --all")
        return 1
    if "--state" in args:
        ds = deep.deep_state(c, project, fp)
        if as_json:
            out(json.dumps(deep.public(ds), indent=2))
        else:
            out(deep.describe(ds) or "deep checks: none in this contract")
        return 0
    tiers = ("deep",) if "--deep" in args else ("fast", "deep") if "--all" in args else ("fast",)
    if "--background" in args:
        if "--deep" not in args:
            out("sisi: --background needs --deep")
            return 1
        if not deep.deep_items(c):
            out("sisi: this contract has no deep items")
            return 0
        started, info = deep.start_background(project, fp)
        if started:
            out("deep run started in the background; log: %s" % info)
            out("check progress with `sisi verify --state`")
        else:
            out("a deep run is already running for this project (pid %s, started %s ago, against %s). "
                "Not starting another." % (info.get("pid"), deep._ago(time.time() - info.get("ts", time.time())),
                                           "the current tree" if info.get("fp") == fp else "an older tree"))
        return 0
    locked = False
    if "deep" in tiers and deep.deep_items(c):
        locked, info = deep.adopt(project, fp) if "--worker" in args else deep.acquire(project, fp)
        if not locked:
            out("a deep run is already running for this project (pid %s, against %s); not starting another."
                % (info.get("pid"), "the current tree" if info.get("fp") == fp else "an older tree"))
            tiers = tuple(t for t in tiers if t != "deep")
            if not tiers:
                return 0
    cfg = store.config()
    try:
        results = run(c, project, default_timeout=cfg["verify"]["default_timeout_s"], tiers=tiers)
        record(c, project, results, fp)
        if locked:
            deep.save_state(project, c["id"], fp, results, [x["id"] for x in deep.deep_items(c)])
    finally:
        if locked:
            deep.release(project)
    good = ok(results)
    ds = deep.deep_state(c, project, fp)
    if as_json:
        out(json.dumps({"contract": c["id"], "project": project, "ok": good, "tiers": list(tiers), "fingerprint": fp,
                        "deep_state": deep.public(ds), "results": results}, indent=2))
    else:
        if results:
            out(format_table(results))
        if not good:
            out("\nFAILED:\n" + failure_report(results))
        else:
            waiting = [r["id"] for r in results if r["status"] == "awaiting-human"]
            out("\nOK" + (" (awaiting human: %s)" % ", ".join(waiting) if waiting else ""))
        for w in C.warnings(c):
            out("warning: " + w)
        if ds:
            out(deep.describe(ds))
    return 0 if good else 1
