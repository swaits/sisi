"""Run a contract: every selected check and invariant with a cmd, in the project dir, with a timeout.

Five statuses only: passed, failed, skipped, not-applicable, not-run. A timeout is
not-run (timed out); a rung 5/6 check is not-run (needs human); a check kept back by
change selection is skipped (not affected by this change), or not-applicable when no
file it watches exists; an identical-inputs pass is skipped (reused: passed at <time>).
Nothing that did not run is ever reported as passed, on any path.
"""
import hashlib, json, os, signal, subprocess, time
from fnmatch import fnmatch
from pathlib import PurePosixPath

from . import contract as C, store

TAIL = 1500
STATUSES = ("passed", "failed", "skipped", "not-applicable", "not-run")


def _tail(s):
    s = s.strip()
    return s[-TAIL:] if len(s) > TAIL else s


def run_cmd(cmd, cwd, timeout, expect):
    """Return (status, duration, tail). status: passed/failed/not-run (a timeout never ran to a verdict)."""
    t0 = time.time()
    if timeout <= 0:
        return "not-run", 0.0, "not run: time budget exhausted"
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
        return "not-run", time.time() - t0, "timed out after %gs" % timeout
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


def match_path(path, pattern):
    p = str(path).replace(os.sep, "/")
    pat = str(pattern).replace(os.sep, "/")
    if fnmatch(p, pat) or fnmatch(p, pat.rstrip("/") + "/*"):
        return True
    try:
        return PurePosixPath(p).match(pat)
    except ValueError:
        return False


def project_files(project, limit=5000):
    """Relative paths in the project (git-tracked plus untracked, else a walk). Bounded."""
    from . import gitutil
    if gitutil.root(project):
        try:
            rc, out = gitutil._git(project, "ls-files", "-c", "-o", "--exclude-standard", "-z", timeout=10)
            if rc == 0:
                return [r for r in out.split("\0") if r][:limit]
        except Exception:
            pass
    out = []
    for dirpath, dirs, names in os.walk(project):
        dirs[:] = [d for d in dirs if d != ".git"]
        for n in names:
            out.append(os.path.relpath(os.path.join(dirpath, n), project))
            if len(out) >= limit:
                return out
    return out


def changed_paths(c, project):
    """Paths changed since the unit started (its base_head), or in the working tree vs HEAD.
    None when it cannot be known: the caller then runs everything."""
    from . import gitutil
    if not gitutil.root(project):
        return None
    try:
        return gitutil.measure(project, c.get("base_head"))["files"]
    except Exception:
        return None


# ---------------------------------------------------------------- reuse cache

def _cache_path():
    from . import paths
    return os.path.join(paths.state(), "verify-cache.json")


def _load_cache():
    try:
        with open(_cache_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_cache(cache):
    try:
        p = _cache_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp%d" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        os.replace(tmp, p)
    except OSError:
        pass


def _cache_key(c, project, x):
    raw = json.dumps([os.path.realpath(project), c.get("id"), x.get("id"), x.get("cmd"),
                      x.get("expect")], sort_keys=True, default=str)
    return hashlib.sha1(raw.encode()).hexdigest()


def input_fingerprint(c, project, x, files=None, contract_path=None):
    """Hash of everything a check's verdict may depend on: its command and expectation, plus
    the contents of the files its when_changed watches, or the whole tree when it has none.
    None when it cannot be computed safely: no reuse then, the check runs."""
    h = hashlib.sha256()
    h.update(json.dumps([x.get("cmd"), x.get("expect")], sort_keys=True, default=str).encode())
    wc = x.get("when_changed")
    if not wc:
        # the whole tree, but not the contract file: a pause, a note or a status change in the
        # contract cannot change what a command shows, and must not defeat reuse
        fp = tree_fp(project, None)
        if fp is None:
            return None
        h.update(fp.encode())
        return h.hexdigest()
    files = project_files(project) if files is None else files
    matched = sorted(f for f in files if any(match_path(f, p) for p in wc))
    if len(matched) > 2000:
        return None
    for rel in matched:
        try:
            full = os.path.join(project, rel)
            if os.path.getsize(full) > 10 * 1024 * 1024:
                return None
            with open(full, "rb") as fh:
                h.update(rel.encode() + b"\0" + hashlib.sha256(fh.read()).digest())
        except OSError:
            h.update(rel.encode() + b"\0gone")
    return h.hexdigest()


def _history(c, project):
    """Past results for this contract+project: seen-failing per check, last duration per check."""
    seen_fail, last_dur = {}, {}
    try:
        rows = store.read("results")
    except Exception:
        rows = []
    started = c.get("started")
    for r in rows:
        if not isinstance(r, dict) or r.get("contract") != c.get("id") or r.get("project") != project:
            continue
        if started and isinstance(r.get("ts"), str) and r["ts"] < started:
            continue
        if r.get("status") == "failed":
            seen_fail[r.get("check")] = True
        if isinstance(r.get("duration_s"), (int, float)):
            last_dur[r.get("check")] = float(r["duration_s"])
    return seen_fail, last_dur


MAX_PARALLEL = 4


def _run_item(item, x, tier, project, deadline, default_timeout):
    r = {"item": item, "id": x["id"], "kind": x.get("kind"), "rung": x.get("rung"), "claim": x.get("claim"),
         "tier": tier, "mandatory": x.get("mandatory", True), "independent": bool(x.get("independent", False)),
         "covers": x.get("covers"), "reason": None, "saved_s": 0.0}
    if x.get("rung") in (5, 6):
        r.update(status="not-run", reason="needs human", duration_s=0.0, tail="")
    else:
        to = float(x.get("timeout_s", default_timeout))
        if deadline is not None:
            to = min(to, deadline - time.time())
        st, dur, tail = run_cmd(x["cmd"], project, to, x.get("expect", {"exit": 0}))
        reason = None
        if st == "not-run":
            reason = "timed out" if tail.startswith("timed out") else tail.removeprefix("not run: ")
        r.update(status=st, reason=reason, duration_s=round(dur, 3), tail=tail)
    return r


def _not_run_result(base_item, x, tier, status, reason, saved=0.0):
    return {"item": base_item, "id": x["id"], "kind": x.get("kind"), "rung": x.get("rung"),
            "claim": x.get("claim"), "tier": tier, "mandatory": x.get("mandatory", True),
            "independent": bool(x.get("independent", False)), "covers": x.get("covers"),
            "status": status, "reason": reason, "duration_s": 0.0, "tail": "", "saved_s": round(saved, 3)}


def run(c, project, deadline=None, default_timeout=60, tiers=("fast",), changed=None, reuse=True,
        contract_path=None, run_all=False):
    """Run the items of the given tiers, with change selection and identical-input reuse.
    Returns result dicts in contract order. `changed=None` means unknown: run everything.
    A skipped or not-applicable result is recorded with its reason; it is never a pass."""
    items = [("check", x) for x in c["checks"]] + [("invariant", x) for x in c.get("invariants", [])]
    items = [(item, x, x.get("tier", "fast")) for item, x in items if x.get("tier", "fast") in tiers]
    deferred = C.deferred_checks(c)
    seen_fail, last_dur = _history(c, project)
    cache = _load_cache() if reuse and not run_all else {}
    files = None
    if changed is None and not run_all:
        changed = changed_paths(c, project)
    res = [None] * len(items)
    fps = {}
    for i, (item, x, tier) in enumerate(items):
        if x["id"] in deferred:
            res[i] = _not_run_result(item, x, tier, "not-run", "deferred: %s" % deferred[x["id"]].get("why", ""))
            continue
        if x.get("rung") in (5, 6):
            continue  # decided in _run_item: not-run (needs human)
        wc = x.get("when_changed")
        if wc and not run_all and changed is not None:
            if files is None:
                files = project_files(project)
            if not any(match_path(f, p) for f in files for p in wc):
                res[i] = _not_run_result(item, x, tier, "not-applicable",
                                         "no file matches when_changed", last_dur.get(x["id"], 0.0))
                continue
            if not any(match_path(f, p) for f in changed for p in wc):
                res[i] = _not_run_result(item, x, tier, "skipped",
                                         "not affected by this change", last_dur.get(x["id"], 0.0))
                continue
        if reuse and not run_all:
            fp = input_fingerprint(c, project, x, files, contract_path)
            fps[i] = fp
            hit = cache.get(_cache_key(c, project, x)) if fp else None
            if hit and hit.get("fp") == fp and hit.get("status") == "passed":
                res[i] = _not_run_result(item, x, tier, "skipped",
                                         "reused: passed at %s" % hit.get("ts"), hit.get("duration_s", 0.0))
                continue
    par = [i for i, (_, x, tier) in enumerate(items)
           if res[i] is None and c.get("parallel") is True and tier == "fast" and not x.get("serial")]
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
    dirty_cache = False
    for i, (item, x, tier) in enumerate(items):
        r = res[i]
        r["seen_failing"] = bool(seen_fail.get(x["id"])) or r["status"] == "failed"
        if r["status"] == "passed" and reuse and not run_all:
            fp = fps.get(i) or input_fingerprint(c, project, x, files, contract_path)
            if fp:
                cache[_cache_key(c, project, x)] = {"fp": fp, "status": "passed", "ts": store.now(),
                                                    "duration_s": r["duration_s"]}
                dirty_cache = True
    if dirty_cache:
        _save_cache(cache)
    if "fast" in tiers:  # enforced lessons ride the same path as floors (personal overlay, trusted commands)
        try:
            from . import cycle
            extra = cycle.enforced_results(c, project, deadline, default_timeout)
            for r in extra:
                r.setdefault("reason", None)
                r.setdefault("mandatory", True)
                r.setdefault("seen_failing", r.get("status") == "failed")
            res += extra
        except Exception as e:
            store.log_error("enforced", e)
    return res


def blocking(results):
    """Results that block delivery: any failure, or a mandatory not-run for a reason other
    than a recorded deferral or needing a human."""
    out = []
    for r in results:
        if r["status"] == "failed":
            out.append(r)
        elif r["status"] == "not-run" and r.get("mandatory", True):
            reason = r.get("reason") or ""
            if not (reason.startswith("deferred") or reason == "needs human"):
                out.append(r)
    return out


def ok(results):
    return not blocking(results)


def record(c, project, results, fp=None):
    run_id = "%x-%d" % (time.time_ns(), os.getpid())
    for r in results:
        store.append("results", {"ts": store.now(), "contract": c["id"], "project": project,
                                 "check": r["id"], "item": r["item"], "kind": r.get("kind"), "rung": r.get("rung"),
                                 "status": r["status"], "reason": r.get("reason"), "duration_s": r["duration_s"],
                                 "seen_failing": bool(r.get("seen_failing")), "mandatory": r.get("mandatory", True),
                                 "independent": bool(r.get("independent", False)), "covers": r.get("covers"),
                                 "tool": store.tool(), "session": store.session_id(), "run": run_id,
                                 "tier": r.get("tier", "fast"), "fp": fp})
    return run_id


def format_table(results):
    rows = [("ID", "KIND", "RUNG", "TIER", "STATUS", "SECS")]
    for r in results:
        st = r["status"] + ((" (%s)" % r["reason"]) if r.get("reason") else "")
        rows.append((r["id"], r["kind"] or "-", str(r["rung"] or "-"), r.get("tier", "fast"), st, "%.1f" % r["duration_s"]))
    w = [max(len(row[i]) for row in rows) for i in range(6)]
    return "\n".join("  ".join(v.ljust(w[i]) for i, v in enumerate(row)).rstrip() for row in rows)


def failure_report(results, limit=4000):
    parts = []
    bad = {id(r) for r in blocking(results)} | {id(r) for r in results if r["status"] == "failed"}
    for r in results:
        if id(r) in bad:
            label = r["status"] + ((": " + r["reason"]) if r.get("reason") else "")
            parts.append("- %s %s [%s]: %s\n%s" % (r["item"], r["id"], label, r.get("claim") or "",
                                                  "\n".join("    " + l for l in (r["tail"] or "").splitlines()[-15:])))
    s = "\n".join(parts)
    return s if len(s) <= limit else s[:limit] + "\n... (truncated)"


def time_saved(results):
    return round(sum(r.get("saved_s", 0.0) for r in results if r["status"] in ("skipped", "not-applicable")), 3)


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
        results = run(c, project, default_timeout=cfg["verify"]["default_timeout_s"], tiers=tiers,
                      contract_path=path, run_all="--all" in args)
        record(c, project, results, fp)
        if locked:
            deep.save_state(project, c["id"], fp, results, [x["id"] for x in deep.deep_items(c)])
    finally:
        if locked:
            deep.release(project)
    good = ok(results)
    ds = deep.deep_state(c, project, fp)
    saved = time_saved(results)
    from . import unit as _unit
    standing = _unit.latest_results(c, _unit._unit_results(c, project, c.get("started")))
    unproven = [{"id": r["id"], "status": r["status"], "reason": r.get("reason")}
                for r in _unit.never_run(standing) if r["status"] != "failed"]  # failures are reported as failures
    if c.get("status") == "paused":
        _unit.resume(c, path)  # work resumed: the wait is over
    if as_json:
        out(json.dumps({"contract": c["id"], "project": project, "ok": good, "tiers": list(tiers), "fingerprint": fp,
                        "deep_state": deep.public(ds), "time_saved_s": saved,
                        "never_run_mandatory": unproven, "results": results}, indent=2))
    else:
        if results:
            out(format_table(results))
        if not good:
            out("\nFAILED:\n" + failure_report(results))
        else:
            waiting = [r["id"] for r in results if r["status"] == "not-run"]
            out("\nOK" + ((" (not run: %s)" % ", ".join("%s %s" % (r["id"], r.get("reason") or "")
                                                          for r in results if r["status"] == "not-run")) if waiting else ""))
        held_back = [r for r in results if r["status"] in ("skipped", "not-applicable")]
        if held_back:
            out("did not run (not a pass): " + "; ".join("%s %s (%s)" % (r["id"], r["status"], r.get("reason") or "")
                                                          for r in held_back))
        if unproven:
            out("no evidence yet: mandatory check(s) never ran to a pass: " +
                ", ".join("%s (%s)" % (u["id"], u["reason"] or u["status"]) for u in unproven) +
                "; the unit cannot close as plainly delivered")
        slow = sorted((r for r in results if r["duration_s"] > 0), key=lambda r: -r["duration_s"])[:3]
        if slow:
            out("slowest checks: " + ", ".join("%s %.1fs" % (r["id"], r["duration_s"]) for r in slow))
        if saved:
            out("time saved by selection and reuse: %.1fs" % saved)
        for w in C.warnings(c):
            out("warning: " + w)
        if ds:
            out(deep.describe(ds))
        if "--worker" not in args:  # the detached worker's output is a log; an announcement there reaches nobody
            try:
                from . import cycle
                line = cycle.due_notice()
                if line:
                    out(line)
            except Exception:
                pass
    return 0 if good else 1
