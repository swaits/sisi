"""Ground truth for harvested main sessions: repo, start commit, following commits, overlap, test command.

Repo resolution: the session cwd, if it still exists inside a git repo (a linked worktree resolves to its main
repo via --git-common-dir). A cwd that no longer exists but sits under <home>/.t3/worktrees/<repo>/... is
recovered to <home>/<Code, src, projects, ...>/<repo> when that is a git repo (how = "t3-worktree-recovery"); otherwise the nearest
existing ancestor is tried, never the home directory itself.

Start commit: sisi's own session record (state/sessions/<id>.json written by `sisi tick`) gives the exact HEAD
(start_kind "exact", only if the commit still exists). Otherwise the latest commit on `--branches --remotes`
(never `--all`: T3 adds refs/t3/.../checkpoints refs that would pollute it) whose committer date is at or
before the session's first timestamp (start_kind "estimated").

Following commits: non-merge commits reachable from any branch or remote but not from the start commit, with
committer date from the session start to its last timestamp plus 2 hours. With overlapping sibling sessions
they cannot be attributed to this session for sure, hence the overlap fields.

Overlap: another main session in the same repo whose [first, last] window intersects this session's
[first, last + 2h]. `overlap_writers` counts those that used Edit/Write-class tools or ran commit commands.
Only Claude Code transcripts are known; edits made by hand or by other tools are invisible.
"""
import json, os, re, subprocess
from concurrent.futures import ThreadPoolExecutor

from . import gitutil, paths, store

AFTER_S = 7200
WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def _git(cwd, *args, timeout=60):
    try:
        return gitutil._git(cwd, *args, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def main_repo_of(path):
    """(repo_root, vcs) for a directory that exists, or (None, None)."""
    top = gitutil.root(path)
    if not top:
        return None, None
    rc, out = _git(top, "rev-parse", "--path-format=absolute", "--git-common-dir")
    common = out.strip()
    root = top
    if rc == 0 and common.endswith("/.git"):
        root = common[:-5] or top
    elif rc == 0 and common and not common.endswith("/.git") and os.path.basename(common) != ".git":
        root = top  # bare or unusual layout: keep the worktree top
    vcs = "jj" if os.path.isdir(os.path.join(root, ".jj")) else "git"
    return root, vcs


# Folders under the home folder where people commonly keep their repositories.
REPO_PARENTS = ("Code", "code", "src", "projects", "dev", "repos", "work", "git")


def resolve_repo(cwd, home=None):
    """(root, how, vcs). how says how it was resolved; root is None when it could not be."""
    home = home or paths.home()
    if not cwd:
        return None, "no-cwd", None
    if os.path.isdir(cwd):
        root, vcs = main_repo_of(cwd)
        return (root, "cwd", vcs) if root else (None, "not-a-git-repo", None)
    m = re.match(re.escape(os.path.join(home, ".t3", "worktrees")) + r"/([^/]+)", cwd)
    if m:
        for parent in REPO_PARENTS:
            cand = os.path.join(home, parent, m.group(1))
            if os.path.isdir(cand):
                root, vcs = main_repo_of(cand)
                if root:
                    return root, "t3-worktree-recovery", vcs
        return None, "t3-worktree-parent-missing", None
    p = os.path.dirname(cwd.rstrip("/"))
    while p and p != "/" and os.path.realpath(p) != os.path.realpath(home):
        if os.path.isdir(p):
            root, vcs = main_repo_of(p)
            return (root, "ancestor", vcs) if root else (None, "cwd-missing", None)
        p = os.path.dirname(p)
    return None, "cwd-missing", None


def _iso(t):
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def estimate_start(root, t0):
    rc, out = _git(root, "rev-list", "--max-count=1", "--branches", "--remotes", "--before=" + _iso(t0))
    out = out.strip()
    return out if rc == 0 and out else None


def fix_commit_of(commits):
    """The fix commit of a harvested task: the last following commit recorded for the
    session (commits are [{"sha": ...}] in chronological record order). None when there
    were no following commits, so such a task can seed a task case but not a check case."""
    shas = [(c.get("sha") if isinstance(c, dict) else c) for c in (commits or [])]
    shas = [s for s in shas if s]
    return shas[-1] if shas else None


def commit_exists(root, sha):
    rc, _ = _git(root, "cat-file", "-e", str(sha) + "^{commit}")
    return rc == 0


def commits_after(root, start, t0, t1, limit=300):
    """[{sha, t, files}] for non-merge commits not reachable from `start` in [t0, t1 + 2h]."""
    args = ["log", "--no-merges", "--branches", "--remotes", "--since=" + _iso(t0), "--until=" + _iso(t1 + AFTER_S),
            "--format=%x01%H%x02%ct", "--name-only", "--max-count=%d" % limit]
    if start:
        args.insert(1, "^" + start)
    rc, out = _git(root, *args)
    commits = []
    if rc != 0:
        return commits
    for block in out.split("\x01"):
        if not block.strip():
            continue
        lines = block.split("\n")
        head = lines[0].split("\x02")
        if len(head) != 2:
            continue
        files = [x for x in lines[1:] if x.strip()][:200]
        try:
            commits.append({"sha": head[0], "t": int(head[1]), "files": files})
        except ValueError:
            pass
    return commits


def _show(root, commit, path):
    if commit:
        rc, out = _git(root, "show", "%s:%s" % (commit, path))
        return out if rc == 0 else None
    try:
        with open(os.path.join(root, path), encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def test_command(root, commit):
    """(command, how) detected from files at `commit` (working tree if commit is None); (None, None) if none."""
    for name in ("justfile", "Justfile", ".justfile"):
        txt = _show(root, commit, name)
        if txt is not None:
            names = set(re.findall(r"^([A-Za-z_][\w-]*)[^\n:=]*:(?!=)", txt, re.M))
            for r in ("check", "test", "tests"):
                if r in names:
                    return "just " + r, "justfile recipe"
    if _show(root, commit, "Cargo.toml") is not None:
        return "cargo test", "Cargo.toml"
    txt = _show(root, commit, "package.json")
    if txt:
        try:
            test = ((json.loads(txt).get("scripts") or {}).get("test") or "")
            if test and "no test specified" not in test:
                return "npm test", "package.json scripts.test"
        except (ValueError, AttributeError):
            pass
    if _show(root, commit, "go.mod") is not None:
        return "go test ./...", "go.mod"
    for name in ("pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml"):
        txt = _show(root, commit, name)
        if txt and ("pytest" in txt):
            return "pytest", name
    txt = _show(root, commit, "Makefile")
    if txt and re.search(r"^test\s*:", txt, re.M):
        return "make test", "Makefile"
    if commit:
        rc, out = _git(root, "ls-tree", "--name-only", commit, "tests/")
        if rc == 0 and re.search(r"tests/test_[^/]*\.py", out):
            return "python3 -m unittest discover -s tests", "tests/test_*.py"
    return None, None


def compute_one(row, home=None):
    """Ground truth for one main session row (dict). Pure with respect to the database."""
    root, how, vcs = resolve_repo(row["cwd"], home)
    gt = dict(session_id=row["id"], repo_root=root, repo_how=how, vcs=vcs, start_commit=None, start_kind=None,
              start_note=None, commits=[], files=[], test_cmd=None, test_how=None)
    if not root or row["t0"] is None:
        return gt
    rec = store.load_session(row["id"])
    head = rec.get("head") if isinstance(rec, dict) else None
    if head and commit_exists(root, head):
        gt["start_commit"], gt["start_kind"], gt["start_note"] = head, "exact", "sisi tick record"
    else:
        est = estimate_start(root, row["t0"])
        if est:
            gt["start_commit"], gt["start_kind"] = est, "estimated"
            gt["start_note"] = "latest commit on branches/remotes at or before the session's first timestamp"
        else:
            gt["start_note"] = "no commit on branches/remotes at or before the session start"
    t1 = row["t1"] or row["t0"]
    if gt["start_commit"]:
        gt["commits"] = commits_after(root, gt["start_commit"], row["t0"], t1)
    gt["files"] = sorted({f for c in gt["commits"] for f in c["files"]})[:500]
    gt["test_cmd"], gt["test_how"] = test_command(root, gt["start_commit"])
    return gt


def run(con, home=None, workers=4, progress=None):
    """Compute or refresh ground truth for main sessions, then recompute overlap for all. Incremental: a
    session is recomputed when it has no row, its last timestamp changed, or its row was computed before its
    after-window (+2h) had closed."""
    import time
    now = time.time()
    have = {r["session_id"]: (r["t1"], r["computed_at"]) for r in con.execute("SELECT session_id,t1,computed_at FROM groundtruth")}
    rows = [dict(r) for r in con.execute("SELECT id,cwd,t0,t1 FROM sessions WHERE kind='main'")]
    todo = []
    for r in rows:
        h = have.get(r["id"])
        if h is None or h[0] != r["t1"] or (h[1] or 0) < (r["t1"] or 0) + AFTER_S:
            todo.append(r)
    stats = {"computed": 0, "skipped": len(rows) - len(todo)}
    # one worker thread per repo at a time would be gentler on git; plain threads are fine for this size
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for n, gt in enumerate(ex.map(lambda r: compute_one(r, home), todo), 1):
            r = next(x for x in todo if x["id"] == gt["session_id"])
            con.execute("INSERT OR REPLACE INTO groundtruth VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0,0,'[]',?,?)",
                        (gt["session_id"], gt["repo_root"], gt["repo_how"], gt["vcs"], gt["start_commit"], gt["start_kind"],
                         gt["start_note"], json.dumps(gt["commits"]), len(gt["commits"]), json.dumps(gt["files"]),
                         gt["test_cmd"], gt["test_how"], r["t1"], now))
            stats["computed"] += 1
            if n % 100 == 0:
                con.commit()
                if progress:
                    progress("groundtruth: %d/%d" % (n, len(todo)))
    con.commit()
    compute_overlap(con)
    return stats


def compute_overlap(con):
    rows = [dict(r) for r in con.execute(
        "SELECT s.id, s.t0, s.t1, s.tools, s.ran_commit, g.repo_root FROM sessions s JOIN groundtruth g ON g.session_id=s.id "
        "WHERE s.kind='main' AND g.repo_root IS NOT NULL AND s.t0 IS NOT NULL")]
    by = {}
    for r in rows:
        r["writer"] = bool(r["ran_commit"]) or any(k in json.loads(r["tools"] or "{}") for k in WRITE_TOOLS)
        by.setdefault(r["repo_root"], []).append(r)
    for sess in by.values():
        for r in sess:
            lo, hi = r["t0"], (r["t1"] or r["t0"]) + AFTER_S
            sib = [o for o in sess if o["id"] != r["id"] and o["t0"] <= hi and (o["t1"] or o["t0"]) >= lo]
            con.execute("UPDATE groundtruth SET overlap_any=?, overlap_writers=?, siblings=? WHERE session_id=?",
                        (len(sib), sum(1 for o in sib if o["writer"]), json.dumps([o["id"] for o in sib][:50]), r["id"]))
    con.commit()
