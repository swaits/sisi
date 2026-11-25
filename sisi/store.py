"""Where sisi keeps things, and the few file operations the rest uses.

Three places: the product (this copy, never written at run time), the person's store (learned rules, the
models table, the retro log; a git repository, so every change can be undone), and scratch (session state)."""
import contextlib, fcntl, hashlib, json, os, re, stat, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
HOME = os.path.expanduser("~")
BLOCK = re.compile(r"<!-- sisi:begin -->\r?\n.*?<!-- sisi:end -->\r?\n?", re.S)
NOTE = "This project's learned rules are in `.sisi/rules.md`. Read that file before any work here and follow it."
_NOTE_RE = re.compile(r"(?:\r?\n)*<!-- sisi:begin -->\r?\n" + re.escape(NOTE) + r"\r?\n<!-- sisi:end -->\r?\n?")
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
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    try:
        os.chmod(tmp, stat.S_IMODE(os.stat(path).st_mode))  # a rewritten file keeps its permissions
    except OSError:
        pass
    os.replace(tmp, path)


def put_block(text, body, append=False):
    """Insert or refresh the marked sisi block in `text`, collapsing duplicates."""
    nl = "\r\n" if "\r\n" in text else "\n"
    block = "<!-- sisi:begin -->%s%s%s<!-- sisi:end -->%s" % (nl, body.rstrip("\r\n"), nl, nl)
    it = iter((block,))
    new, n = BLOCK.subn(lambda m: next(it, ""), text)
    sep = "" if not append or not text or text.endswith(nl * 2) else nl if text.endswith(nl) else nl * 2
    return new if n else (text + sep + block) if append else (block + text)


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
    git(["add", "-A", "--"] + rel, DATA)
    git(["-c", "user.name=sisi", "-c", "user.email=sisi@localhost", "commit", "-q", "-m", message, "--"] + rel, DATA)


def project_root(cwd=None):
    """The project a folder belongs to. Every checkout of one repository is the same project."""
    cwd = cwd or os.getcwd()
    rc, out = git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)
    return os.path.dirname(out.strip()) if rc == 0 and os.path.basename(out.strip()) == ".git" else os.path.abspath(cwd)


def project_key(cwd=None):
    root = project_root(cwd)
    return "%s-%s" % (os.path.basename(root) or "root", hashlib.sha1(root.encode()).hexdigest()[:8])


def agents_target(root):
    """(real_path, rel_path, "") for `root/AGENTS.md` when safe, else (None, "", reason)."""
    agents, real_root = os.path.join(root, "AGENTS.md"), os.path.realpath(root)
    real, link = os.path.realpath(agents) if os.path.islink(agents) else agents, os.path.islink(agents)
    why = ("it is a dangling symlink" if link and not os.path.exists(agents) else "it is a directory" if os.path.isdir(agents)
           else "it is a symlink outside the project" if link and os.path.commonpath([real_root, real]) != real_root
           else "it is not a regular file" if os.path.lexists(agents) and not os.path.isfile(agents) else "")
    return (None, "", why) if why else (real, os.path.relpath(real, real_root), "")


def snapshot(cwd):
    """A fingerprint of the working tree: the commit, what is uncommitted, what is untracked. "" outside git."""
    rc, top = git(["rev-parse", "--path-format=absolute", "--show-toplevel"], cwd)
    if rc != 0:
        return ""
    real, rel, _ = agents_target(top.strip())
    spec = ["--", ":(top)", ":(top,exclude).sisi"] + ([":(top,exclude)" + rel] if rel else [])
    head, status, diff = git(["rev-parse", "HEAD"], cwd)[1], git(["status", "--porcelain"] + spec, cwd)[1], git(["diff", "HEAD"] + spec, cwd)[1]
    staged = git(["diff", "--cached", "--", ":(top)" + rel], cwd)[1] if rel else ""
    body = _NOTE_RE.sub("", read(real)).rstrip("\r\n") if real and os.path.isfile(real) else ""
    return hashlib.sha1((head + status + diff + staged + "\0" + body).encode()).hexdigest()[:16]


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
