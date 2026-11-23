"""Two copies: the source folder (development) and the stable installed copy the tools run.

  <lib>/releases/<UTC timestamp>/   a copy of the product files only
  <lib>/current                     symlink to the active release, switched atomically (new symlink, then rename)

<lib> is $SISI_LIB, else <home>/.local/lib/sisi. A process that starts through `current/bin/sisi` resolves the link
once (bin/sisi uses realpath), so it runs one complete release from start to end, even while a release is made.
Release folders are built under a hidden name and renamed into place, so a half-copied release is never visible.
"""
import fcntl, getpass, hashlib, json, os, re, shutil, subprocess, sys, time

from . import paths

KEEP = 3
PRODUCT = ("bin", "sisi", "canon", "verifiers", "done", "docs", "config.default.json", "VERSION")
_SKIP_DIRS = {"__pycache__", ".git"}


class ReleaseError(Exception):
    pass


# ---- the two copies ---------------------------------------------------------
def in_lib(p):
    lib = os.path.realpath(paths.lib())
    return os.path.realpath(p).startswith(lib + os.sep)


def is_source(d):
    return all(os.path.exists(os.path.join(d, p)) for p in ("bin/sisi", "sisi/cli.py", "canon/core.md"))


def dev_source():
    s = (paths.personal_config().get("developer") or {}).get("source")
    return s if isinstance(s, str) and s else None


def source(explicit=None):
    """The source folder: the one given, else the folder sisi runs from (unless that is a release), else the
    developer setting."""
    if explicit:
        s = os.path.abspath(os.path.expanduser(explicit))
    elif not in_lib(paths.REPO):
        s = paths.REPO
    else:
        s = dev_source()
        if not s:
            raise ReleaseError("no source folder: run this from the source folder, or set it with `sisi dev on PATH`")
    if not is_source(s):
        raise ReleaseError("%s does not look like the sisi source folder (bin/sisi, sisi/, canon/core.md)" % s)
    return s


def releases():
    """Release names, oldest first."""
    try:
        return sorted(n for n in os.listdir(paths.releases_dir())
                      if not n.startswith(".") and os.path.isdir(os.path.join(paths.releases_dir(), n)))
    except OSError:
        return []


def current_name():
    try:
        return os.path.basename(os.readlink(paths.current_link()).rstrip("/"))
    except OSError:
        return None


# ---- trees ------------------------------------------------------------------
def _files(root):
    out = {}
    for entry in PRODUCT:
        top = os.path.join(root, entry)
        if os.path.isfile(top):
            out[entry] = top
            continue
        for dp, dns, fns in os.walk(top):
            dns[:] = [d for d in dns if d not in _SKIP_DIRS]
            for n in fns:
                if not n.endswith(".pyc"):
                    p = os.path.join(dp, n)
                    out[os.path.relpath(p, root)] = p
    return out


def _hash(p):
    if os.path.islink(p):
        return "link:" + os.readlink(p)
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def diff(new_root, old_root):
    """(added, changed, removed) product files going from old_root to new_root."""
    n, o = _files(new_root), _files(old_root) if old_root else {}
    added = sorted(set(n) - set(o))
    removed = sorted(set(o) - set(n))
    changed = sorted(k for k in set(n) & set(o) if _hash(n[k]) != _hash(o[k]))
    return added, changed, removed


def describe_diff(d, limit=12):
    added, changed, removed = d
    lines = ["%d added, %d changed, %d removed" % (len(added), len(changed), len(removed))]
    shown = [("+ ", x) for x in added] + [("~ ", x) for x in changed] + [("- ", x) for x in removed]
    lines += ["  " + a + b for a, b in shown[:limit]]
    if len(shown) > limit:
        lines.append("  ... and %d more" % (len(shown) - limit))
    return lines


# ---- build, switch, prune ---------------------------------------------------
def _lock():
    os.makedirs(paths.lib(), exist_ok=True)
    f = open(os.path.join(paths.lib(), ".lock"), "w")
    fcntl.flock(f, fcntl.LOCK_EX)
    return f


def _stamp():
    """A release name that sorts after every existing one (the UTC second, with -02, -03 ... when needed)."""
    base = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    newest = max(releases(), default="")
    name, i = base, 1
    while name <= newest:
        i += 1
        name = "%s-%02d" % (base, i)
    return name


def make_release(src):
    """Copy the product files of src into a new release folder. Returns its name. Visible only when complete."""
    rd = paths.releases_dir()
    os.makedirs(rd, exist_ok=True)
    name = _stamp()
    tmp = os.path.join(rd, ".tmp-" + name)
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        for entry in PRODUCT:
            s = os.path.join(src, entry)
            if not os.path.lexists(s):
                continue
            d = os.path.join(tmp, entry)
            if os.path.isdir(s) and not os.path.islink(s):
                shutil.copytree(s, d, symlinks=True,
                                ignore=shutil.ignore_patterns("__pycache__", ".git", "*.pyc"))
            else:
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copy2(s, d, follow_symlinks=False)
        os.rename(tmp, os.path.join(rd, name))
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return name


def switch(name):
    """Point `current` at the release, atomically: write a new symlink beside it, then rename it over the old one."""
    link = paths.current_link()
    tmp = "%s.new-%d" % (link, os.getpid())
    try:
        os.unlink(tmp)
    except OSError:
        pass
    os.symlink(os.path.join("releases", name), tmp)
    try:
        os.replace(tmp, link)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def prune(keep=KEEP):
    """Delete all but the newest `keep` releases (never the active one). Returns the names removed."""
    names, cur, gone = releases(), current_name(), []
    for n in names[:-keep] if keep else names:
        if n != cur:
            shutil.rmtree(os.path.join(paths.releases_dir(), n), ignore_errors=True)
            gone.append(n)
    for n in os.listdir(paths.releases_dir()) if os.path.isdir(paths.releases_dir()) else []:
        if n.startswith(".tmp-") and time.time() - os.stat(os.path.join(paths.releases_dir(), n)).st_mtime > 3600:
            shutil.rmtree(os.path.join(paths.releases_dir(), n), ignore_errors=True)
    return gone


def _rebuild_rulebook():
    """Regenerate the rulebook with the code that is now live (not the code that is switching it)."""
    launcher = os.path.join(paths.current_link(), "bin", "sisi")
    r = subprocess.run([sys.executable, launcher, "build-canon"], capture_output=True, text=True)
    return (r.stdout + r.stderr).strip(), r.returncode


def run_checks(src, deep=False):
    """Run the source's own `sisi verify` (fast; with --all also the slow ones). Returns (ok, output)."""
    cmd = [sys.executable, os.path.join(src, "bin", "sisi"), "verify"] + (["--all"] if deep else [])
    r = subprocess.run(cmd, cwd=src, capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def cmd_release(args):
    deep = "--deep" in args
    rest = [a for a in args if a != "--deep"]
    try:
        src = source(rest[0] if rest else None)
    except ReleaseError as e:
        print("sisi release: %s" % e, file=sys.stderr)
        return 1
    print("checking %s (%s checks)..." % (src, "fast and slow" if deep else "fast"))
    ok, out = run_checks(src, deep)
    if not ok:
        tail = "\n".join(out.splitlines()[-25:])
        print("sisi release: refused, the checks did not pass:\n%s" % tail, file=sys.stderr)
        return 1
    with _lock():
        prev = current_name()
        old_root = os.path.join(paths.releases_dir(), prev) if prev else None
        name = make_release(src)
        new_root = os.path.join(paths.releases_dir(), name)
        d = diff(new_root, old_root if old_root and os.path.isdir(old_root) else None)
        switch(name)
        gone = prune()
    msg, rc = _rebuild_rulebook()
    print("released %s%s" % (name, " (was %s)" % prev if prev else " (first release)"))
    for l in describe_diff(d):
        print(l)
    if gone:
        print("removed old releases: " + ", ".join(gone))
    ok = rc == 0 or os.path.isfile(paths.generated())  # over the line budget still writes the file: a warning
    print("rulebook: " + (" ".join(msg.split()) if msg else "rebuilt") if ok else "rulebook: NOT rebuilt (%s)" % msg)
    from . import wiring
    if not wiring.live_wired():
        print("the tools are not wired to the stable copy yet: run `sisi install`")
    return 0 if ok else 1


def cmd_rollback(args):
    with _lock():
        names, cur = releases(), current_name()
        if cur not in names or names.index(cur) == 0:
            print("sisi rollback: there is no earlier release to go back to", file=sys.stderr)
            return 1
        prev = names[names.index(cur) - 1]
        switch(prev)
    msg, rc = _rebuild_rulebook()
    print("rolled back: %s -> %s" % (cur, prev))
    ok = rc == 0 or os.path.isfile(paths.generated())
    print("rulebook: " + (" ".join(msg.split()) if msg else "rebuilt") if ok else "rulebook: NOT rebuilt (%s)" % msg)
    return 0 if ok else 1


# ---- developer mode ---------------------------------------------------------
def cmd_dev(args):
    sub = args[0] if args else "status"
    if sub == "on":
        cand = args[1] if len(args) > 1 else (os.getcwd() if is_source(os.getcwd()) else
                                               (paths.REPO if not in_lib(paths.REPO) else None))
        if not cand:
            print("usage: sisi dev on PATH", file=sys.stderr)
            return 1
        cand = os.path.abspath(os.path.expanduser(cand))
        if not is_source(cand):
            print("sisi dev: %s does not look like the sisi source folder" % cand, file=sys.stderr)
            return 1
        paths.set_personal_config(("developer", "source"), cand, "developer mode on: " + cand)
        print("developer mode on: source is %s" % cand)
        return 0
    if sub == "off":
        paths.set_personal_config(("developer", "source"), None, "developer mode off")
        print("developer mode off")
        return 0
    if sub == "status":
        s = dev_source()
        print("developer mode: " + ("on, source %s%s" % (s, "" if is_source(s) else " (NOT a sisi source folder)") if s else "off"))
        print("live copy: " + live_text())
        return 0
    print("usage: sisi dev on [PATH] | off | status", file=sys.stderr)
    return 1


def live_text():
    cur = current_name()
    if not cur or not os.path.isdir(paths.current_link()):
        return "the clone %s (no release made)" % paths.REPO
    s = dev_source() or (paths.REPO if not in_lib(paths.REPO) and is_source(paths.REPO) else None)
    txt = "release %s at %s" % (cur, os.path.realpath(paths.current_link()))
    if s and is_source(s):
        a, c, r = diff(s, paths.current_link())
        n = len(a) + len(c) + len(r)
        txt += "; source %s is %s" % (s, "ahead (%d file%s differ)" % (n, "" if n == 1 else "s") if n else "in step")
    return txt


# ---- promote ----------------------------------------------------------------
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")


def _terms():
    """[(text, replacement)] in the order they are scrubbed: longest, most specific first."""
    home = os.path.expanduser("~")
    t = []
    for h in {home, paths.home()}:
        if h and h != "/":
            t.append((h, "~"))
    user = os.environ.get("USER") or ""
    try:
        user = user or getpass.getuser()
    except Exception:
        pass
    if len(user) >= 3:
        t.append((user, "<user>"))
    cfg = (paths.personal_config().get("developer") or {}).get("personal_terms") or []
    for x in cfg:
        if isinstance(x, str) and x.strip():
            t.append((x.strip(), "<personal>"))
    return sorted(t, key=lambda p: -len(p[0]))


def _word(t):
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(t) + r"(?![A-Za-z0-9])")


def scrub(text):
    """Returns (clean text, [what was scrubbed], [(line number, line) still holding a personal term])."""
    found = []
    for t, rep in _terms():
        pat = re.compile(re.escape(t)) if t.startswith("/") else _word(t)
        if pat.search(text):
            found.append(t)
            text = pat.sub(rep, text)
    ems = sorted(set(EMAIL.findall(text)))
    if ems:
        found += ems
        text = EMAIL.sub("<email>", text)
    left = []
    probes = [re.compile(r"(?<![A-Za-z0-9])" + re.escape(t) + r"(?![A-Za-z0-9])", re.I) for t, r in _terms() if r != "~"]
    homes = [t for t, r in _terms() if r == "~"]
    for i, line in enumerate(text.split("\n"), 1):
        if any(p.search(line) for p in probes) or any(h.lower() in line.lower() for h in homes) or EMAIL.search(line):
            left.append((i, line))
    return text, found, left


def _find_item(pid):
    """(kind, overlay file, destination in the source folder relative path or None for a rule)."""
    rf = paths.overlay_dir("rules", pid + ".md")
    if os.path.isfile(rf):
        return "rule", rf, os.path.join("canon", "core.md")
    vd = paths.overlay_dir("verifiers")
    for sec in sorted(os.listdir(vd)) if os.path.isdir(vd) else []:
        f = os.path.join(vd, sec, pid + ".md")
        if os.path.isfile(f):
            return "verifier", f, os.path.join("verifiers", sec, pid + ".md")
    f = paths.overlay_dir("done", pid + ".md")
    if os.path.isfile(f):
        return "recipe", f, os.path.join("done", pid + ".md")
    return None


def _merge_rule(core_text, pid, rule_md):
    """Put the rule into the base rulebook text: replace the rule with that id, or append a numbered one."""
    from . import overlay
    r = overlay.parse_rule_file(rule_md, pid)
    _, base = overlay.parse_rules(core_text)
    lines = core_text.split("\n")
    heads = [i for i, l in enumerate(lines) if l.startswith("## ")]
    for k, i in enumerate(heads):
        t = overlay.NUM.sub("", lines[i][3:].strip())
        m = overlay.ID_TAIL.search(t)
        if (m.group(1) if m else overlay.slug(t)) == pid:
            end = heads[k + 1] if k + 1 < len(heads) else len(lines)
            num = re.match(r"^(\d+)\.\s", lines[i][3:])
            head = "## %s%s {#%s}" % (num.group(0) if num else "", r["title"], pid)
            return "\n".join(lines[:i] + [head, ""] + r["body"].split("\n") + [""] + lines[end:])
    top = 0
    for i in heads:
        m = re.match(r"^(\d+)\.", lines[i][3:])
        top = max(top, int(m.group(1)) if m else 0)
    body = core_text.rstrip("\n") + "\n\n## %d. %s {#%s}\n\n%s\n" % (top + 1, r["title"], pid, r["body"])
    return body


def core_items():
    """Core-tier items not yet in the product: ([lesson rows], [statement texts])."""
    lessons = []
    try:
        from . import retro
        if os.path.exists(retro.db_path()):
            con = retro.connect()
            try:
                lessons = [dict(r) for r in con.execute(
                    "SELECT * FROM lessons WHERE scope='core' AND status IN ('open','applied') "
                    "AND COALESCE(promoted,'')='' ORDER BY id")]
            finally:
                con.close()
    except Exception:
        lessons = []
    statements = []
    try:
        from . import principles
        statements = [r["text"] for r in principles.core_statements()]
    except Exception:
        statements = []
    return lessons, statements


def _norm_text(t):
    return " ".join(str(t or "").split())


def _product_contains(target, out, kind, clean):
    """The product file now holds the promoted text (checked by reading it back)."""
    try:
        with open(target, encoding="utf-8") as fh:
            now = fh.read()
    except OSError:
        return False
    if kind == "rule":
        from . import overlay
        try:
            body = overlay.parse_rule_file(clean)["body"]
        except Exception:
            body = clean
        return _norm_text(body) in _norm_text(now)
    return now == out


def _drop_personal_copy(kind, pid, f):
    """Once the product contains the text, the personal overlay copy goes, so nothing lives
    in two places; core lessons folded into the item are marked promoted."""
    try:
        os.unlink(f)
    except OSError:
        pass
    try:
        from . import overlay
        if kind == "rule":
            overlay._set_base("rule", pid, None)
            overlay.build_canon()
    except Exception:
        pass
    try:
        from . import retro, store
        if os.path.exists(retro.db_path()):
            con = retro.connect()
            try:
                con.execute("UPDATE lessons SET promoted=? WHERE scope='core' AND "
                            "(folded_into=? OR folded_into=? OR folded_into LIKE ?)",
                            (store.now(), pid, "rule:" + pid, "%" + pid + "%"))
                con.commit()
            finally:
                con.close()
            retro.sync("lessons: core item %s promoted into the product" % pid)
    except Exception:
        pass


def _promote_overlay(pid, apply, src):
    """The long-standing overlay promote, now dropping the personal copy once verified."""
    item = _find_item(pid)
    if not item:
        return None
    kind, f, dest = item
    with open(f, encoding="utf-8") as fh:
        text = fh.read()
    clean, found, left = scrub(text)
    print("%s %s -> %s" % (kind, pid, os.path.join(src, dest)))
    print("scrubbed: " + (", ".join(found) if found else "nothing"))
    if left:
        print("sisi promote: refused, personal terms remain on these lines:", file=sys.stderr)
        for n, l in left:
            print("  %d: %s" % (n, l), file=sys.stderr)
        return 1
    target = os.path.join(src, dest)
    if kind == "rule":
        try:
            with open(target, encoding="utf-8") as fh:
                out = _merge_rule(fh.read(), pid, clean)
        except Exception as e:
            print("sisi promote: cannot merge the rule: %s" % e, file=sys.stderr)
            return 1
    else:
        out = clean
    if not apply:
        print("dry run (nothing written); the file would hold:\n" + "-" * 20)
        print(clean.rstrip("\n"))
        print("-" * 20 + "\nrun again with --apply to write it")
        return 0
    already = _product_contains(target, out, kind, clean)
    if not already:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = target + ".sisi-tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(out)
        os.replace(tmp, target)
    if not _product_contains(target, out, kind, clean):
        print("sisi promote: the product does not contain the text after writing; the personal "
              "copy is kept", file=sys.stderr)
        return 1
    _drop_personal_copy(kind, pid, f)
    print("%s: %s (not committed; an ordinary uncommitted edit for your normal review). "
          "The personal copy was dropped: the product contains the text."
          % ("already in the product" if already else "written", target))
    return 0


def _promote_lesson(lid, apply):
    from . import retro
    if not os.path.exists(retro.db_path()):
        print("sisi promote: no lessons yet", file=sys.stderr)
        return 1
    con = retro.connect()
    try:
        row = con.execute("SELECT * FROM lessons WHERE id=?", (lid,)).fetchone()
    finally:
        con.close()
    if not row:
        print("sisi promote: no lesson with id %d" % lid, file=sys.stderr)
        return 1
    r = dict(row)
    if retro._get(r, "scope") != "core":
        print("sisi promote: lesson #%d is in the %s tier, not core; only core items are queued "
              "for the product" % (lid, retro._get(r, "scope") or "unscoped-tier"), file=sys.stderr)
        return 1
    if retro._get(r, "promoted"):
        print("lesson #%d is already in the product (promoted %s)" % (lid, retro._get(r, "promoted")))
        return 0
    targets = [t.strip() for t in str(r.get("folded_into") or "").split(",") if t.strip()]
    pid = None
    for t in targets:
        cand = t[5:] if t.startswith("rule:") else t
        if cand.startswith("draft:") or cand == "enforced":
            continue
        if _find_item(cand):
            pid = cand
            break
    if pid is None:
        print("sisi promote: lesson #%d is core but is not folded into a personal rule, recipe or "
              "technique yet, so there is no product file to write. Fold it in a learning round "
              "(`sisi cycle`) first, then promote it; or send it upstream with "
              "`sisi promote --export`." % lid, file=sys.stderr)
        return 1
    src = dev_source()
    if not src or not is_source(src):
        print("sisi promote: this is not a developer install (no developer source set): nothing "
              "was written. `sisi promote --export` writes a contribution file you may send "
              "upstream; on a developer install (`sisi dev on PATH`) promote writes into the "
              "source tree.", file=sys.stderr)
        return 1
    return _promote_overlay(pid, apply, src)


def _export_core(path=None):
    lessons, statements = core_items()
    if not lessons and not statements:
        print("no core items are waiting: nothing to export")
        return 0
    extra_terms = set()
    try:
        from . import retro
        con = retro.connect()
        try:
            for r in lessons:
                for (repo,) in con.execute("SELECT repo FROM occurrences WHERE lesson_id=?", (r["id"],)):
                    if repo:
                        extra_terms.add(os.path.basename(str(repo).rstrip("/")))
        finally:
            con.close()
    except Exception:
        pass
    lines = ["# sisi core contributions", "",
             "Universal text only: no history, no user or project names. Nothing was sent "
             "anywhere; send this file upstream yourself if you choose.", ""]
    for t in statements:
        lines += ["## Statement (core)", "", t, ""]
    for r in lessons:
        pat = ""
        try:
            from . import retro
            con = retro.connect()
            try:
                if r.get("pattern_id"):
                    prow = con.execute("SELECT statement FROM patterns WHERE id=?",
                                       (r["pattern_id"],)).fetchone()
                    pat = prow[0] if prow else ""
            finally:
                con.close()
        except Exception:
            pat = ""
        lines += ["## Lesson %d (core, kind %s%s)" % (r["id"], r.get("change_kind") or "",
                                                      ", target " + r["target"] if r.get("target") else ""), ""]
        if pat:
            lines += ["Pattern: " + pat, ""]
        if r.get("short"):
            lines += [str(r["short"]), ""]
        lines += [str(r.get("change") or ""), ""]
        if r.get("when_terms"):
            lines += ["When: " + str(r["when_terms"]), ""]
    text = "\n".join(lines)
    for term in sorted(extra_terms):
        if len(term) >= 3:
            text = _word(term).sub("<project>", text)
    clean, found, left = scrub(text)
    if left:
        print("sisi promote: refused, personal terms remain on these lines:", file=sys.stderr)
        for n, l in left:
            print("  %d: %s" % (n, l), file=sys.stderr)
        return 1
    path = path or os.path.join(os.getcwd(), "sisi-core-contribution.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(clean if clean.endswith("\n") else clean + "\n")
    print("wrote %s (%d lesson(s), %d statement(s); universal text only). Nothing was sent anywhere."
          % (path, len(lessons), len(statements)))
    return 0


def cmd_promote(args):
    apply = "--apply" in args
    args = [a for a in args if a != "--apply"]
    if "--export" in args:
        rest = [a for a in args if a != "--export"]
        if len(rest) > 1:
            print("usage: sisi promote --export [PATH]", file=sys.stderr)
            return 1
        return _export_core(rest[0] if rest else None)
    if not args:
        lessons, statements = core_items()
        if not lessons and not statements:
            print("no core items are waiting to be promoted")
            print("promote one overlay rule, recipe or technique by id: sisi promote <id> [--apply]")
            return 0
        print("Core items not yet in the product (in force for you through the personal overlay):")
        for r in lessons:
            from . import retro
            print("  lesson:%d [%s] %s (`sisi promote lesson:%d --apply` on a developer install)"
                  % (r["id"], r.get("change_kind") or "", retro.heading_text(r, 100), r["id"]))
        for t in statements:
            print("  statement (core): %r (fold it into a rule in a learning round, then promote "
                  "the rule; or `sisi promote --export`)" % t[:100])
        return 0
    if len(args) != 1:
        print("usage: sisi promote [<id>|lesson:N] [--apply] | sisi promote --export [PATH]",
              file=sys.stderr)
        return 1
    pid = args[0]
    if pid.startswith("lesson:"):
        if not pid[7:].isdigit():
            print("usage: sisi promote lesson:N [--apply]", file=sys.stderr)
            return 1
        return _promote_lesson(int(pid[7:]), apply)
    try:
        src = source()
    except ReleaseError as e:
        print("sisi promote: %s" % e, file=sys.stderr)
        return 1
    rc = _promote_overlay(pid, apply, src)
    if rc is None:
        print("sisi promote: no overlay rule, verifier or recipe with id %r in %s" % (pid, paths.overlay_dir()), file=sys.stderr)
        return 1
    return rc


