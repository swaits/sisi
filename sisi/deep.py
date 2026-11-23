"""Deep tier: state of long-running checks, the one-run-per-project lock, and detached background runs."""
import hashlib, json, os, subprocess, sys, time

from . import paths


def key(project):
    return hashlib.sha1(os.path.realpath(project).encode()).hexdigest()[:12]


def _state_path(project):
    return os.path.join(paths.state(), "deep", key(project) + ".json")


def _lock_path(project):
    return os.path.join(paths.state(), "locks", "deep-" + key(project) + ".lock")


def deep_items(c):
    return [x for x in c.get("checks", []) + c.get("invariants", [])
            if x.get("tier") == "deep" and x.get("cmd") and x.get("rung", 3) not in (5, 6)]


def _proc_start(pid):
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def _alive(info):
    pid = info.get("pid")
    if not isinstance(pid, int):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    start = _proc_start(pid)
    return not (start and info.get("start") and start != info["start"])  # pid reuse


def read_lock(project):
    """Info of the live deep run for this project, or None. Stale locks are removed."""
    p = _lock_path(project)
    try:
        with open(p, encoding="utf-8") as f:
            info = json.load(f)
    except (OSError, ValueError):
        info = None
    if info is not None and _alive(info):
        return info
    if os.path.exists(p) and info is not None:
        try:
            os.unlink(p)
        except OSError:
            pass
    return None


def acquire(project, fp, log=None):
    """Returns (True, info) or (False, info_of_running_run)."""
    p = _lock_path(project)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    info = {"pid": os.getpid(), "start": _proc_start(os.getpid()), "fp": fp, "ts": time.time(), "log": log}
    for _ in range(3):
        try:
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            running = read_lock(project)
            if running:
                return False, running
            continue
        with os.fdopen(fd, "w") as f:
            json.dump(info, f)
        return True, info
    return False, {}


def release(project):
    try:
        with open(_lock_path(project), encoding="utf-8") as f:
            if json.load(f).get("pid") == os.getpid():
                os.unlink(_lock_path(project))
    except (OSError, ValueError):
        pass


def save_state(project, contract_id, fp, results, deep_ids):
    items = [{"id": r["id"], "status": r["status"], "tail": (r.get("tail") or "")[-1500:],
              "evidence": r.get("evidence") or ""}
             for r in results if r.get("tier") == "deep"]
    st = {"contract": contract_id, "fp": fp, "epoch": time.time(), "ids": sorted(deep_ids),
          "ok": all(i["status"] in ("passed", "skipped", "not-applicable") for i in items), "items": items}
    p = _state_path(project)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f)
    os.replace(tmp, p)


def load_state(project):
    try:
        with open(_state_path(project), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def deep_state(c, project, fp):
    """None if the contract has no deep items, else a dict with 'state' in
    fresh-pass / stale-pass / failed / running / never-run."""
    items = deep_items(c)
    if not items:
        return None
    ids = sorted(x["id"] for x in items)
    base = {"items": len(items), "fresh": False, "failed": [], "epoch": None, "lock": None}
    lock = read_lock(project)
    st = load_state(project)
    if st is not None and st.get("ids") == ids:
        base.update(epoch=st.get("epoch"), fresh=fp is not None and st.get("fp") == fp,
                    failed=[i for i in st["items"] if i["status"] in ("failed", "not-run")])
    else:
        st = None
    if lock:
        base.update(state="running", lock=lock, fresh=fp is not None and lock.get("fp") == fp, epoch=lock.get("ts"))
    elif st is None:
        base["state"] = "never-run"
    elif not st.get("ok"):
        base["state"] = "failed"
    else:
        base["state"] = "fresh-pass" if base["fresh"] else "stale-pass"
    return base


def _ago(sec):
    sec = int(max(0, sec))
    for n, u in ((86400, "d"), (3600, "h"), (60, "m")):
        if sec >= n:
            return "%d%s" % (sec // n, u)
    return "%ds" % sec


def describe(ds):
    if ds is None:
        return None
    s, n = ds["state"], ds["items"]
    parts = ["%d item%s" % (n, "" if n == 1 else "s")]
    if s == "running":
        parts.append("started %s ago on %s" % (_ago(time.time() - (ds["epoch"] or time.time())),
                                               "the current tree" if ds["fresh"] else "an older tree"))
    elif s != "never-run":
        parts.append("last run %s ago on %s" % (_ago(time.time() - (ds["epoch"] or 0)),
                                                 "the current tree" if ds["fresh"] else "an older tree"))
    if s == "failed" and ds["failed"]:
        parts.append("failing: " + ", ".join(i["id"] for i in ds["failed"]))
    return "deep checks: %s (%s)" % (s, ", ".join(parts))


def public(ds):
    if ds is None:
        return None
    return {k: v for k, v in ds.items() if k != "lock"} | {"running_pid": (ds["lock"] or {}).get("pid")}


def _rewrite_lock(project, pid):
    p = _lock_path(project)
    with open(p, encoding="utf-8") as f:
        info = json.load(f)
    info.update(pid=pid, start=_proc_start(pid))
    tmp = p + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(info, f)
    os.replace(tmp, p)


def adopt(project, fp, wait=10.0):
    """For the detached worker: take over the lock the parent made for us (it names our pid once the parent has
    started us). Falls back to acquiring it normally."""
    t = time.time()
    while time.time() - t < wait:
        try:
            with open(_lock_path(project), encoding="utf-8") as f:
                if json.load(f).get("pid") == os.getpid():
                    return True, {}
        except (OSError, ValueError):
            break
        time.sleep(0.02)
    return acquire(project, fp)


def start_background(project, fp=None):
    """Detached deep run. The lock is taken here, before the worker starts, so a second request cannot slip in.
    Returns (started, log_path_or_running_info)."""
    d = os.path.join(paths.state(), "logs")
    os.makedirs(d, exist_ok=True)
    log = os.path.join(d, "deep-%s-%d.log" % (key(project), int(time.time())))
    ok, info = acquire(project, fp, log)
    if not ok:
        return False, info
    try:
        with open(log, "ab") as lf:
            # -B: the detached worker outlives its caller; writing fresh bytecode into the shared
            # state dir after the caller has finished races whatever cleans that dir up.
            child = subprocess.Popen([sys.executable, "-B", paths.launcher(), "verify", "--deep", "--worker"], cwd=project,
                                     stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT,
                                     start_new_session=True, close_fds=True)
        _rewrite_lock(project, child.pid)
    except Exception:
        release(project)
        raise
    return True, log
