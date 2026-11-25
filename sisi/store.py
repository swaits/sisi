"""Where sisi keeps things, and the few file operations the rest uses.

Three places: the product (this copy, never written at run time), the person's store (learned rules, the
models table, the retro log; a git repository, so every change can be undone), and scratch (session state)."""
import contextlib, fcntl, hashlib, json, os, re, stat, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
HOME = os.path.expanduser("~")
NOTE = "This project's learned rules are in `.sisi/rules.md`. Read that file before any work here and follow it."
NOTE_RE = re.compile(r"^<!-- sisi:begin -->\r?\n" + re.escape(NOTE) + r"\r?\n<!-- sisi:end -->(?:\r?\n|$)", re.M)
def _where(own, xdg, fallback):
    """The folder in the environment variable `own`, else `xdg`/sisi, else the default under the home."""
    base = os.environ.get(xdg)
    return os.environ.get(own) or (os.path.join(base, "sisi") if base else os.path.join(HOME, *fallback, "sisi"))


DATA = _where("SISI_DATA", "XDG_DATA_HOME", (".local", "share"))
STATE = _where("SISI_STATE", "XDG_STATE_HOME", (".local", "state"))
LIB = os.environ.get("SISI_LIB") or os.path.join(HOME, ".local", "lib", "sisi")

# Every setting there is. The person overrides one under "core" in config.json in their store.
DEFAULTS = {"gate": True, "meter": True, "direct_calls": 8, "direct_extension": 8,
            "rules_lines": 30, "rules_chars": 4000, "organize_after": 8, "research_days": 7, "shell_workers": False,
            "worker_minutes": 15, "retro_minutes": 5}


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
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return default


def records(name):
    """The JSON objects in a data file, one per line; a damaged or non-object line is skipped."""
    out = []
    for line in read(data(name)).splitlines():
        try:
            o = json.loads(line)
        except (ValueError, RecursionError):
            continue
        out += [o] if isinstance(o, dict) else []
    return out


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        with contextlib.suppress(OSError):
            os.chmod(tmp, stat.S_IMODE(os.stat(path).st_mode))  # a rewritten file keeps its permissions
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise


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
    with lock("store"):
        os.path.isdir(os.path.join(DATA, ".git")) or git(["init", "-q"], DATA)
        rel = [os.path.relpath(p, DATA) for p in paths]
        return (git(["add", "-A", "--"] + rel, DATA)[0] == 0 and
                (git(["status", "--porcelain", "--"] + rel, DATA) == (0, "") or
                 git(["-c", "user.name=sisi", "-c", "user.email=sisi@localhost", "commit", "-q", "-m", message, "--"] + rel, DATA)[0] == 0))


_roots = {}


def root(cwd=None):
    """(project root, inside a git directory or bare repository). In git the root is the main checkout's, shared by
    its worktrees; when git cannot answer, the nearest folder holding `.git`; outside git, the folder itself."""
    cwd = os.path.abspath(cwd or os.getcwd())
    if cwd not in _roots:
        rc, out = git(["rev-parse", "--path-format=absolute", "--is-inside-git-dir", "--git-common-dir", "--show-toplevel"], cwd)
        inside, common, top = (out.splitlines() + ["", "", ""])[:3]
        cur = cwd
        while rc and inside != "true" and not os.path.lexists(os.path.join(cur, ".git")) and cur != os.path.dirname(cur):
            bare = os.path.basename(cur) == ".git" or all(os.path.exists(os.path.join(cur, n)) for n in ("HEAD", "objects", "refs"))
            inside, cur = ("true", cur) if bare else ("", os.path.dirname(cur))
        top = os.path.dirname(common) if os.path.basename(common) == ".git" else top if rc == 0 else cur if os.path.lexists(os.path.join(cur, ".git")) else cwd
        _roots[cwd] = (cwd, True) if inside == "true" else (top, False)
    return _roots[cwd]


def project_root(cwd=None):
    """The project a folder belongs to. Every checkout of one repository is the same project."""
    return root(cwd)[0]


def project_key(cwd=None):
    root = project_root(cwd)
    return "%s-%s" % (os.path.basename(root) or "root", hashlib.sha1(root.encode()).hexdigest()[:8])


def regular(path, load=False):
    """("", bytes|None) if `path` is absent or a regular non-link file within 64,000 bytes, else (reason, None)."""
    try:
        st = os.lstat(path)
        why = "a symlink" if stat.S_ISLNK(st.st_mode) else "not a regular file" if not stat.S_ISREG(st.st_mode) else "over 64,000 bytes" if st.st_size > 64000 else ""
        if why or not load:
            return why, None
        with open(path, "rb") as f:
            return ("", raw) if len(raw := f.read(64001)) <= 64000 else ("over 64,000 bytes", None)
    except (FileNotFoundError, NotADirectoryError):
        return "", None


def agents_target(root):
    """(real_path, rel_path, "") for `root/AGENTS.md` when safe, else (None, "", reason)."""
    agents, real_root = os.path.join(root, "AGENTS.md"), os.path.realpath(root)
    real, link = os.path.realpath(agents) if os.path.islink(agents) else os.path.join(real_root, "AGENTS.md"), os.path.islink(agents)
    rel = os.path.relpath(real, real_root) if link else "AGENTS.md"
    why = ("it is a dangling symlink" if link and not os.path.exists(agents) else "it is a directory" if os.path.isdir(agents)
           else "it is a symlink outside the project" if link and os.path.commonpath([real_root, real]) != real_root
           else "it is a symlink into " + rel.split(os.sep)[0] if link and rel.split(os.sep)[0] in (".git", ".sisi")
           else "it is " + issue if (issue := regular(real if link else agents)[0]) else "")
    return (None, "", why) if why else (real, rel, "")


def snapshot(cwd):
    """A fingerprint of the working tree: the commit, what is uncommitted, what is untracked. "" outside git."""
    rc, out = git(["rev-parse", "--path-format=absolute", "--show-toplevel", "HEAD"], cwd)
    top = (out.splitlines() or [""])[0]
    if not top:
        return ""
    real, rel, _ = agents_target(top)
    spec = ["--", ":(top)", ":(top,exclude).sisi"] + ([":(top,exclude)" + rel] if rel else [])
    head, status, diff = (out if rc == 0 else ""), git(["status", "--porcelain"] + spec, cwd)[1], git(["diff", "HEAD"] + spec, cwd)[1]
    body = NOTE_RE.sub("", (regular(real, True)[1] or b"").decode("utf-8", "replace") if real else "").rstrip("\r\n")
    return hashlib.sha1((head + status + diff + "\0" + body).encode()).hexdigest()[:16]


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


@contextlib.contextmanager
def lock(key, wait=True):
    """Exclusive lock in the store for one project (or user); with wait=False, yields False if busy."""
    p, ok = data("locks", "%s-%s.lock" % (os.path.basename(key) or "root", hashlib.sha1(key.encode()).hexdigest()[:8])), True
    with open(p, "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError:
            ok = False
        yield ok


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
