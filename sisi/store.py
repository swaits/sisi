"""The shared store: append-only jsonl files, config, session records, error log."""
import json, os, re, time

from . import paths

FILES = {"results": "results.jsonl",
         "learn": "learn.jsonl", "quarantine": "learn.jsonl", "waivers": "waivers.jsonl",
         "deliveries": "deliveries.jsonl", "units": "units.jsonl", "subagents": "subagents.jsonl"}


def _migrate_learn():
    """Lossless one-time move of the old quarantine file into the live learn store.

    Statements used to be parked in learn-quarantine.jsonl, which no agent read. They now take
    effect at once from learn.jsonl. Every old line (quoted words, date, scope, context) is
    copied across unchanged, then the old file is removed so nothing is read twice."""
    try:
        new = paths.data_file("learn.jsonl")
        olds = [paths.data_file("learn-quarantine.jsonl"), paths.state_file("learn-quarantine.jsonl")]
        lines = []
        for old in olds:
            if os.path.realpath(old) == os.path.realpath(new) or not os.path.exists(old):
                continue
            with open(old, encoding="utf-8") as f:
                lines += [l.rstrip("\n") for l in f if l.strip()]
        if not lines and not any(os.path.exists(o) and os.path.realpath(o) != os.path.realpath(new) for o in olds):
            return
        have = set()
        if os.path.exists(new):
            with open(new, encoding="utf-8") as f:
                have = {l.rstrip("\n") for l in f if l.strip()}
        add = [l for l in lines if l not in have]
        if add:
            os.makedirs(os.path.dirname(new), exist_ok=True)
            with open(new, "a", encoding="utf-8") as f:
                for l in add:
                    f.write(l + "\n")
        for old in olds:
            if os.path.realpath(old) != os.path.realpath(new) and os.path.exists(old):
                os.unlink(old)
        # the old two-way scope is now three tiers: an everywhere statement is not yet tiered
        if os.path.exists(new):
            with open(new, encoding="utf-8") as f:
                raw = f.read()
            if '"everywhere"' in raw:
                out = []
                for line in raw.splitlines():
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        out.append(line)
                        continue
                    if isinstance(rec, dict) and rec.get("scope") == "everywhere":
                        rec["scope"] = "unscoped-tier"
                        out.append(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
                    else:
                        out.append(line)
                tmp = new + ".tmp%d" % os.getpid()
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write("".join(l + "\n" for l in out))
                os.replace(tmp, new)
    except OSError:
        pass


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def tool():
    t = os.environ.get("SISI_TOOL")
    if t:
        return t
    if os.environ.get("CLAUDECODE"):
        return "claude-code"
    if os.environ.get("OPENCODE"):
        return "opencode"
    return None


def session_id():
    return os.environ.get("SISI_SESSION_ID") or None


PERSONAL = ("learn", "quarantine", "units")  # what the person told or taught sisi: personal data, the rest is scratch


def file_path(name):
    if name in PERSONAL:
        return paths.personal(FILES[name])
    return paths.state_file(FILES.get(name, name))


def read_stdin(wait=None):
    """What a hook was sent on stdin. A hook's stdin always ends; if it does not (an inherited pipe nobody closes),
    give up after `wait` seconds (SISI_STDIN_WAIT, default 5) rather than hold the session or a test forever."""
    import select, sys
    f = sys.stdin
    if f is None or f.isatty():
        return ""
    try:
        fd = f.fileno()
    except (AttributeError, ValueError, OSError):
        return f.read()  # an in-memory stand-in
    try:
        wait = float(os.environ.get("SISI_STDIN_WAIT", "5")) if wait is None else wait
    except ValueError:
        wait = 5.0
    end, chunks = time.time() + wait, []
    while True:
        left = end - time.time()
        if left <= 0 or not select.select([fd], [], [], left)[0]:
            break
        b = os.read(fd, 65536)
        if not b:
            break
        chunks.append(b)
    return b"".join(chunks).decode("utf-8", "replace")


def append(name, rec):
    if name in ("learn", "quarantine"):
        _migrate_learn()
    path = file_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line.encode())  # one write call: appends stay whole lines
    finally:
        os.close(fd)


def read(name):
    if name in ("learn", "quarantine"):
        _migrate_learn()
    path = file_path(name)
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def stamp(extra):
    rec = {"ts": now(), "cwd": os.getcwd(), "tool": tool(), "session": session_id()}
    rec.update(extra)
    return rec


DEFAULTS = {"gate": {"enabled": True, "budget_s": 120, "max_blocks": 3},
            "verify": {"default_timeout_s": 60, "fast_limit_s": 60},
            "retro": {"required": True},
            "scratch": {"session_max_age_days": 30, "prune_every": 20, "prune_max_delete": 1000,
                        "prune_budget_s": 0.25}}


def config():
    """Built-in defaults, then config.default.json in the product, then the person's config.json (personal data)."""
    cfg = json.loads(json.dumps(DEFAULTS))
    for p in (os.path.join(paths.REPO, "config.default.json"), paths.personal("config.json")):
        try:
            with open(p, encoding="utf-8") as f:
                over = json.load(f)
        except (OSError, ValueError):
            continue
        for k, v in over.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    if os.environ.get("SISI_RETRO_REQUIRED", "").lower() in ("0", "false", "no"):
        cfg.setdefault("retro", {})["required"] = False
    return cfg


def safe_id(sid):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(sid))[:128] or "unknown"


def session_path(sid):
    return os.path.join(paths.state(), "sessions", safe_id(sid) + ".json")


def load_session(sid):
    try:
        with open(session_path(sid), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_session(sid, rec):
    p = session_path(sid)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    os.replace(tmp, p)


def _transcript_alive(session_file, cutoff):
    """True when the transcript this session record names was written to since `cutoff`: the
    session is still going on in the host even though sisi has not touched its record."""
    try:
        with open(session_file, encoding="utf-8") as f:
            tp = json.load(f).get("transcript_path")
        return isinstance(tp, str) and os.stat(os.path.expanduser(tp)).st_mtime >= cutoff
    except (OSError, ValueError, AttributeError):
        return False


def prune_sessions(now=None, active_ids=(), force=False):
    """Remove session-state files older than the configured age. Runs on a counter kept in
    scratch (every Nth session start, first run included), never on a scheduler. Bounded:
    stops after the configured time budget or deletion count, and a later start continues.
    Never deletes the file of a session named active (callers pass the current session's id)
    nor of one whose transcript the host has written to within the age. Returns the number
    of files removed."""
    cfg = config().get("scratch", {})
    d = os.path.join(paths.state(), "sessions")
    counter_file = os.path.join(d, ".prune-counter")
    count = 0
    try:
        with open(counter_file, encoding="utf-8") as f:
            count = int(f.read().strip() or 0)
    except (OSError, ValueError):
        count = 0
    count += 1
    try:
        os.makedirs(d, exist_ok=True)
        with open(counter_file, "w", encoding="utf-8") as f:
            f.write(str(count))
    except OSError:
        pass
    every = max(1, int(cfg.get("prune_every", 20)))
    if not force and (count - 1) % every != 0:
        return 0  # not this start's turn: the first start and every Nth after it sweep
    now = time.time() if now is None else now
    cutoff = now - float(cfg.get("session_max_age_days", 30)) * 86400
    keep = {safe_id(s) + ".json" for s in active_ids if s}
    budget = float(cfg.get("prune_budget_s", 0.25))
    max_delete = int(cfg.get("prune_max_delete", 1000))
    removed, deadline, unfinished = 0, time.time() + budget, False
    try:
        with os.scandir(d) as it:
            for e in it:
                if removed >= max_delete or time.time() > deadline:
                    unfinished = True
                    break
                if not e.name.endswith(".json") or e.name in keep:
                    continue
                try:
                    if e.is_file(follow_symlinks=False) and e.stat().st_mtime < cutoff:
                        if _transcript_alive(e.path, cutoff):
                            continue  # the host is still writing this session's transcript
                        os.unlink(e.path)
                        removed += 1
                except OSError:
                    pass
    except OSError:
        pass
    if unfinished:  # out of budget with files left: the next start continues the sweep
        try:
            with open(counter_file, "w", encoding="utf-8") as f:
                f.write("0")
        except OSError:
            pass
    return removed


def log_error(where, exc):
    try:
        append("errors.log", {"ts": now(), "where": where, "error": repr(exc)})
    except Exception:
        pass
