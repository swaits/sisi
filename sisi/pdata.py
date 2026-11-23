"""The personal data folder: a local git repository holding everything sisi learned for this person.

Layout (see docs/personal-data.md):
  VERSION            format version of this folder
  oracle.md          what the person wants
  overlay/           learned changes to the base rulebook, verifiers and recipes
  notes/             field notes per verifier or recipe id
  config.json, trusted.json, lessons.jsonl, retest.jsonl, *.jsonl (notes, proposals, quarantine)
  retro.db           the lessons database (sqlite; kept out of git, lessons.jsonl is its committed dump)
  generated/         the effective rulebook (rebuildable; kept out of git)
  install/           manifest and backups of the files `sisi install` edited (machine specific; out of git)
  backups/           timestamped copies taken before a migration or an update (out of git)

Git here is private bookkeeping: author "sisi", no global git config needed, no hooks, never pushed.
"""
import contextlib, os, subprocess, time

from . import paths

FORMAT_VERSION = 1
GITIGNORE = "retro.db\nretro.db-*\ngenerated/\ninstall/\nbackups/\n.lock\n*.tmp*\n"
IDENT = {"GIT_AUTHOR_NAME": "sisi", "GIT_AUTHOR_EMAIL": "sisi@localhost",
         "GIT_COMMITTER_NAME": "sisi", "GIT_COMMITTER_EMAIL": "sisi@localhost"}


class DataError(Exception):
    pass


def _env():
    e = dict(os.environ)
    e.update(IDENT)
    e.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        e.pop(k, None)
    return e


def git(*args, check=True):
    cmd = ["git", "-c", "core.hooksPath=" + os.devnull, "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false",
           "-c", "core.quotepath=off"] + list(args)
    p = subprocess.run(cmd, cwd=paths.data(), capture_output=True, text=True, env=_env(), timeout=60)
    if check and p.returncode != 0:
        raise DataError("git %s failed: %s" % (" ".join(args[:2]), (p.stderr or p.stdout).strip()))
    return p


@contextlib.contextmanager
def lock():
    """One writer at a time across processes (sessions run concurrently)."""
    os.makedirs(paths.data(), exist_ok=True)
    f = open(paths.data_file(".lock"), "a")
    try:
        try:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX)
        except ImportError:
            pass
        yield
    finally:
        f.close()


def exists():
    return os.path.isdir(paths.data_file(".git"))


def ensure():
    """Create the folder, its git repository, .gitignore and VERSION if missing. Cheap when everything is there."""
    d = paths.data()
    if exists() and os.path.exists(paths.data_file("VERSION")):
        return d
    with lock():
        fresh = not exists()
        if fresh:
            git("init", "-q", "-b", "main", "--template=")
        if not os.path.exists(paths.data_file(".gitignore")):
            write_text(".gitignore", GITIGNORE)
        if not os.path.exists(paths.data_file("VERSION")):
            write_text("VERSION", "%d\n" % FORMAT_VERSION)
        if fresh or git("rev-parse", "--verify", "-q", "HEAD", check=False).returncode != 0:
            _commit("sisi: create personal data (format %d)" % FORMAT_VERSION, [".gitignore", "VERSION"])
    return d


def write_text(rel, text):
    """Atomic write inside the data folder."""
    p = paths.data_file(rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, p)


def read_text(rel, default=None):
    try:
        with open(paths.data_file(rel), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return default


def _known(spec):
    """Is this path present, or tracked? (git refuses pathspecs that match nothing.)"""
    return os.path.lexists(paths.data_file(spec)) or bool(git("ls-files", "--", spec, check=False).stdout.strip())


def _commit(msg, pathspecs):
    if pathspecs:
        pathspecs = [s for s in pathspecs if _known(s)]
        if not pathspecs:
            return None
        ok = git("add", "-A", "--", *pathspecs, check=False).returncode == 0
        if not ok:  # a pathspec that matches nothing makes git add refuse them all: add what exists one by one
            for s in pathspecs:
                git("add", "-A", "--", s, check=False)
        # A pathspec whose files were all deleted before ever being tracked (an emptied notes
        # folder, say) matches nothing in the index either, and git commit refuses it: commit
        # only the pathspecs that actually staged something.
        staged = git("diff", "--cached", "--name-only", check=False).stdout.splitlines()
        pathspecs = [s for s in pathspecs
                     if any(f == s or f.startswith(s.rstrip("/") + "/") for f in staged)]
        if not pathspecs:
            return None
        spec = ["--"] + list(pathspecs)
    else:
        git("add", "-A")
        spec = []
    r = git("commit", "-q", "-m", msg, *spec, check=False)
    if r.returncode != 0:
        if "nothing" in (r.stdout + r.stderr) and "commit" in (r.stdout + r.stderr):
            return None  # nothing changed
        raise DataError("git commit failed: %s" % (r.stderr or r.stdout).strip())
    return "committed"


def commit(msg, pathspecs=None, strict=False):
    """Commit changes (optionally only under pathspecs) with a clear message. Returns "committed", or None
    when nothing changed. A failure is logged and swallowed unless strict: learning must never break a command."""
    try:
        ensure()
        with lock():
            return _commit(msg, pathspecs)
    except Exception as e:
        if strict:
            raise
        from . import store
        store.log_error("pdata-commit", e)
        return None


def version():
    t = read_text("VERSION")
    try:
        return int((t or "").strip())
    except ValueError:
        return 0


# format migrations: {from_version: function(); the function brings the folder to from_version + 1}
MIGRATIONS = {}


def upgrade():
    """Bring the personal data format up to date. Returns a list of notes."""
    ensure()
    v = version()
    if v > FORMAT_VERSION:
        raise DataError("personal data is format %d but this sisi understands up to %d; update sisi first"
                        % (v, FORMAT_VERSION))
    notes = []
    while v < FORMAT_VERSION:
        fn = MIGRATIONS.get(v)
        if fn is None:
            raise DataError("no migration from personal data format %d" % v)
        fn()
        v += 1
        write_text("VERSION", "%d\n" % v)
        commit("format: personal data upgraded to version %d" % v, ["VERSION"] , strict=True)
        notes.append("personal data format upgraded to %d" % v)
    return notes


def backup_dir(reason):
    """A fresh timestamped folder under backups/."""
    base = paths.data_file("backups")
    os.makedirs(base, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    n, d = 0, None
    while d is None or os.path.exists(d):
        d = os.path.join(base, "%s-%s%s" % (stamp, reason, "-%d" % n if n else ""))
        n += 1
    os.makedirs(d)
    return d
