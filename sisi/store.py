"""Where sisi keeps things, and the few file operations the rest uses.

Three places: the product (this copy, never written at run time), the person's store (learned rules, the
models table, the retro log; a git repository, so every change can be undone), and scratch (session state)."""
import contextlib, fcntl, hashlib, json, os, stat, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
HOME = os.path.expanduser("~")
def _where(own, xdg, fallback):
    """The folder in the environment variable `own`, else `xdg`/sisi, else the default under the home."""
    base = os.environ.get(xdg)
    return os.environ.get(own) or (os.path.join(base, "sisi") if base else os.path.join(HOME, *fallback, "sisi"))


DATA = _where("SISI_DATA", "XDG_DATA_HOME", (".local", "share"))
STATE = _where("SISI_STATE", "XDG_STATE_HOME", (".local", "state"))
LIB = os.environ.get("SISI_LIB") or os.path.join(HOME, ".local", "lib", "sisi")

# Every setting there is. The person overrides one under "core" in config.json in their store.
DEFAULTS = {"gate": True, "meter": True, "direct_calls": 8, "direct_extension": 8,
            "rules_lines": 30, "rules_chars": 4000, "organize_after": 8, "research_days": 7, "shell_workers": False}


def config():
    cfg = dict(DEFAULTS)
    try:
        mine = json.loads(read(os.path.join(DATA, "config.json")) or "{}").get("core") or {}
        cfg.update({k: v for k, v in mine.items() if k in DEFAULTS})
    except (ValueError, AttributeError):
        pass
    return cfg


def data(*parts):
    path = os.path.join(DATA, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def read(path, default=""):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return default


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        os.chmod(tmp, stat.S_IMODE(os.stat(path).st_mode))  # a rewritten file keeps its permissions
    except OSError:
        pass
    os.replace(tmp, path)


def append(path, line):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line.rstrip("\n") + "\n")


def git(args, cwd, timeout=15):
    try:
        r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def commit(message, *paths):
    """One commit in the person's store holding only these paths, so the change can be undone on its own."""
    if not os.path.isdir(os.path.join(DATA, ".git")):
        git(["init", "-q"], DATA)
    rel = [os.path.relpath(p, DATA) for p in paths]
    git(["add", "--"] + rel, DATA)
    git(["-c", "user.name=sisi", "-c", "user.email=sisi@localhost", "commit", "-q", "-m", message, "--"] + rel, DATA)


def project_root(cwd=None):
    """The project a folder belongs to. Every checkout of one repository is the same project."""
    cwd = cwd or os.getcwd()
    rc, out = git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)
    if rc == 0 and os.path.basename(out.strip()) == ".git":
        return os.path.dirname(out.strip())
    return os.path.abspath(cwd)


def project_key(cwd=None):
    root = project_root(cwd)
    return "%s-%s" % (os.path.basename(root) or "root", hashlib.sha1(root.encode()).hexdigest()[:8])


def snapshot(cwd):
    """A fingerprint of the working tree: the commit, what is uncommitted, what is untracked. "" outside git."""
    rc, status = git(["status", "--porcelain"], cwd)
    if rc != 0:
        return ""
    head, diff = git(["rev-parse", "HEAD"], cwd)[1], git(["diff", "HEAD"], cwd)[1]
    return hashlib.sha1((head + status + diff).encode()).hexdigest()[:16]


def _session_path(sid):
    return os.path.join(STATE, "core-sessions", "".join(c for c in str(sid) if c.isalnum() or c in "-_")[:80] + ".json")


@contextlib.contextmanager
def session(sid):
    """Read, change and write one session's state under a lock: parallel tool calls run their hooks at once."""
    path = _session_path(sid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            state = json.loads(read(path) or "{}")
        except ValueError:
            state = {}
        yield state
        write(path, json.dumps(state))


def current_session(cwd=None):
    """The session a command typed by an agent belongs to: the id session start exported, else the most
    recently active lead (not worker) session of this project. None when there is none (a person at a terminal)."""
    if os.environ.get("SISI_SESSION_ID"):
        return os.environ["SISI_SESSION_ID"]
    folder, key, best = os.path.join(STATE, "core-sessions"), project_key(cwd), (0, None)
    for name in os.listdir(folder) if os.path.isdir(folder) else []:
        path = os.path.join(folder, name)
        if name.endswith(".json") and os.path.getmtime(path) > best[0]:
            try:
                state = json.loads(read(path) or "{}")
                if state.get("project") == key and not state.get("worker"):
                    best = (os.path.getmtime(path), name[:-5])
            except ValueError:
                pass
    return best[1]
