"""Small git helpers. Working-tree change measurement for the gate."""
import os, subprocess

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _git(cwd, *args, timeout=5):
    p = subprocess.run(("git",) + args, cwd=cwd, capture_output=True, timeout=timeout)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def root(cwd):
    try:
        rc, out = _git(cwd, "rev-parse", "--show-toplevel")
    except (OSError, subprocess.SubprocessError):
        return None
    return out.strip() if rc == 0 and out.strip() else None


def head(cwd):
    try:
        rc, out = _git(cwd, "rev-parse", "--verify", "-q", "HEAD")
    except (OSError, subprocess.SubprocessError):
        return None
    return out.strip() if rc == 0 else None


_EXCLUDE = ":(exclude).sisi"  # sisi's own records are never part of the work being measured


def _is_sisi(rel):
    return rel == ".sisi" or rel.startswith(".sisi/")


def measure(cwd, base=None, max_untracked=200):
    """Return {'lines': n, 'files': [paths]} for the working tree vs `base` (default HEAD)."""
    cwd = root(cwd) or cwd
    base = base or head(cwd) or EMPTY_TREE
    lines, files = 0, set()
    rc, out = _git(cwd, "diff", "--numstat", base, "--", ".", _EXCLUDE, timeout=10)
    if rc == 0:
        for ln in out.splitlines():
            parts = ln.split("\t", 2)
            if len(parts) == 3:
                files.add(parts[2])
                for x in parts[:2]:
                    if x.isdigit():
                        lines += int(x)
                    elif x == "-":
                        lines += 1  # binary change counts as one line
    rc, out = _git(cwd, "ls-files", "--others", "--exclude-standard", timeout=10)
    if rc == 0:
        top = cwd
        for rel in [r for r in out.splitlines() if not _is_sisi(r)][:max_untracked]:
            files.add(rel)
            try:
                fp = os.path.join(top, rel)
                if os.path.getsize(fp) < 1_000_000:
                    with open(fp, "rb") as f:
                        lines += f.read().count(b"\n") or 1
            except OSError:
                pass
    return {"lines": lines, "files": sorted(files)[:2000]}


def snapshot(cwd, max_files=200000):
    """Stat-only working-tree snapshot: {relative path: [size, mtime_ns]}, [-1, -1] for a tracked
    file that is gone. Tracked plus untracked-but-not-ignored files inside a git tree (via
    `git ls-files`, so .gitignore is honoured and .git itself never appears — a commit therefore
    changes nothing here); a plain directory walk skipping .git outside one. No file content is
    read, so a change that keeps both size and mtime is invisible to it."""
    _root = root(cwd)
    top = _root or os.path.abspath(cwd)
    rels = []
    if _root:
        rc, out = _git(top, "ls-files", "-c", "-o", "--exclude-standard", "-z", timeout=10)
        if rc == 0:
            rels = [r for r in out.split("\0") if r]
    if not rels:
        for dirpath, dirs, names in os.walk(top):
            dirs[:] = sorted(d for d in dirs if d != ".git")
            for n in sorted(names):
                rels.append(os.path.relpath(os.path.join(dirpath, n), top))
    files = {}
    for rel in rels[:max_files]:
        try:
            st = os.stat(os.path.join(top, rel))
            files[rel] = [st.st_size, st.st_mtime_ns]
        except OSError:
            files[rel] = [-1, -1]
    return {"root": top, "files": files}


def snapshot_diff(before, after):
    """Sorted relative paths whose stat entry appeared, vanished or changed between snapshots."""
    a, b = (before or {}).get("files", {}), (after or {}).get("files", {})
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def fingerprint(cwd, extra_files=()):
    """Cheap hash of the working-tree state: HEAD, the diff against it, untracked files (path, size, mtime),
    plus the content of `extra_files` (e.g. the contract, which may be git-ignored). None outside git."""
    import hashlib
    top = root(cwd)
    if not top:
        return None
    h = hashlib.sha1()
    base = head(top) or EMPTY_TREE
    h.update(base.encode())
    p = subprocess.run(["git", "diff", "--no-ext-diff", "--no-textconv", "--no-color", base, "--", ".", _EXCLUDE],
                       cwd=top, capture_output=True, timeout=10)
    h.update(b"\0diff\0" + p.stdout)
    p = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=top,
                       capture_output=True, timeout=10)
    for rel in p.stdout.split(b"\0")[:2000]:
        if not rel or _is_sisi(os.fsdecode(rel)):
            continue
        try:
            st = os.stat(os.path.join(top, os.fsdecode(rel)))
            h.update(rel + b"\0%d:%d\0" % (st.st_size, st.st_mtime_ns))
        except OSError:
            h.update(rel + b"\0gone\0")
    for f in extra_files:
        if f:
            try:
                with open(f, "rb") as fh:
                    h.update(b"\0extra\0" + fh.read())
            except OSError:
                h.update(b"\0extra-missing\0")
    return h.hexdigest()
