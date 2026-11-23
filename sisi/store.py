"""The shared store: append-only jsonl files, config, session records, error log."""
import json, os, re, time

from . import paths

FILES = {"results": "results.jsonl", "notes": "notes.jsonl", "proposals": "proposals.jsonl",
         "quarantine": "learn-quarantine.jsonl", "waivers": "waivers.jsonl",
         "deliveries": "deliveries.jsonl"}


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


PERSONAL = ("notes", "proposals", "quarantine")  # what the person told or taught sisi: personal data, the rest is scratch


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
    path = file_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line.encode())  # one write call: appends stay whole lines
    finally:
        os.close(fd)


def read(name):
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


DEFAULTS = {"gate": {"enabled": True, "budget_s": 120, "max_blocks": 3, "growth_lines": 40, "growth_files": 3},
            "verify": {"default_timeout_s": 60, "fast_limit_s": 60},
            "retro": {"required": True}}


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


def log_error(where, exc):
    try:
        append("errors.log", {"ts": now(), "where": where, "error": repr(exc)})
    except Exception:
        pass
