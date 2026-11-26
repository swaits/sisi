"""Learned rules: what retros and the person add to the instructions.

A rule is one line. It is in force as soon as it is added: rules for all of the person's work become the last
section of the rulebook every session loads, and a project's rules live in `.sisi/rules.md` at its root.
Now and then a cheap worker audits and organizes them. Store changes are committed and can be undone."""
import contextlib, hashlib, json, os, re, time
from . import store

USER, PROJECT = "user", "project"
OWNER = re.compile(r"\[owner\b[^\]]*\]")
_owner, _retro = lambda l: bool(OWNER.search(l)), lambda ls: [l for l in ls if not _owner(l)]
_snap = lambda u, p: hashlib.sha1(("\n".join(u) + "\0" + "\n".join(p)).encode()).hexdigest()[:16]
_TAGS = " [owner] lines are the person's words; [agent ...] lines are an agent's reading, which a later owner statement or a measurement overrides."
HEAD_USER = "## Learned here\n\nAdded by retros and by the person. These add to the rules above and never relax them." + _TAGS + "\n"
HEAD_PROJECT = "sisi: learned in this project (these add to the rules and never relax them)." + _TAGS
SMELL = re.compile(r"(?i)\bone (?:build|test|run|worker|job)\b.{0,60}\bat a time|\bflock\b|\b(?:shared?|one)\b.{0,30}\bbuild (?:folder|dir)")

ORGANIZE = """You are a worker. Do this task yourself; do not delegate it further.

Audit and organize the learned rules below. They are instructions an AI engineering agent reads at the start
of every session: the first list in every project, the second only in the project "%(name)s". Retros add to
them one line at a time, so they pile up, repeat and go stale.

The objective the rules serve: %(objective)s

Rewrite both lists so they serve that objective best:
- Merge rules that say the same thing. Drop fragments, rules that are stale or contradicted by a later one,
  and rules too specific to come up again.
- Word each rule as a direct instruction with its reason, on one line, standing on its own.
- A rule seen in more than one project, or about how the person wants to be worked with, belongs in the
  first list. A rule about this project's own code belongs in the second.
- Lines marked [owner ...] are the person's own words: copy every one of them verbatim, unchanged by even
  one character (you may reorder them). Only the other lines ([retro ...], [agent ...]) may be merged, reworded or dropped.
- Flag, but do not change, any [owner ...] line whose text does not read as the person's own words (a paraphrase, an
  agent's conclusion, third person), and any rule that limits builds, tests or workers to one at a time or tells
  checkouts to share one build folder. List each under a final `## flags` section with its proposed corrected or
  retagged form, for the person to accept.
- Keep the [source date] mark at the end of every line.
- A `better` that recurs across retros has earned a rule: add it, worded as an instruction, marked [retro <date>].
- Non-owner ([retro ...]) lines in each list: at most %(lines)d lines and %(chars)d characters. Fewer is better.

Answer with exactly this shape and nothing else:
## user
- ...
## project
- ...
## flags
- ... (only if there are any)

=== The first list now (all projects) ===
%(user)s

=== The second list now (project "%(name)s") ===
%(project)s

=== Flagged for the person (likely wrong; propose a fix) ===
%(flagged)s

=== What recent retros found, newest last (context only) ===
%(retros)s
"""


def path(scope, cwd=None):
    """Where a list is kept; for a project "" inside a git directory or bare repository, where none is kept."""
    top, inside = store.root(cwd) if scope == PROJECT else ("", False)
    return store.data("rules", "user.md") if scope == USER else "" if inside else os.path.join(top, ".sisi", "rules.md")


def _legacy(cwd=None):
    return os.path.join(store.DATA, "rules", "projects", store.project_key(cwd) + ".md")


def _parse(text):
    return [l.rstrip() for l in text.lstrip("\ufeff").splitlines() if l.startswith("- ")]


def lines(p):
    return _parse(store.read(p))


def _text(p):
    """What a regular file holds now, None when absent; OSError when unusable or not UTF-8."""
    why, raw = store.regular(p, True)
    if why:
        raise OSError("%s is %s" % (p, why))
    try:
        return None if raw is None else raw.decode("utf-8")
    except UnicodeDecodeError:
        raise OSError(".sisi/rules.md is not valid UTF-8")


def _append(text, new):
    return (text or "") + ("\n" if text and not text.endswith("\n") else "") + "".join(l + "\n" for l in new)


def _check_writable(p):
    if not p:
        raise OSError("this folder is inside a git directory or a bare repository")
    for t, label, folder in ((os.path.dirname(p), ".sisi", True), (p, ".sisi/rules.md", False)):
        why = (("a symlink" if os.path.islink(t) else "not a directory" if os.path.lexists(t) and not os.path.isdir(t) else "") if folder
               else store.regular(t)[0]) or ("read-only" if os.path.exists(t) and not os.access(t, os.W_OK) else "")
        if why:
            raise OSError("%s is %s" % (label, why))
    if not os.path.exists(os.path.dirname(p)) and not os.access(os.path.dirname(os.path.dirname(p)), os.W_OK):
        raise OSError("the project folder cannot be written")


def note(where, write=True):
    """Keep one marked note in `AGENTS.md` (write=True), or report whether it is there (write=False)."""
    root = os.path.dirname(os.path.dirname(where if write else path(PROJECT, where))) or where
    target, _, why = store.agents_target(root)
    try:
        if not target:
            raise OSError(why)
        if write and os.path.exists(target) and not (os.stat(target).st_mode & 0o200):
            raise OSError("it is read-only")
        text = _text(target) or ""
        if not write:
            return "in AGENTS.md" if store.NOTE_RE.search(text) else "missing from AGENTS.md"
        if not store.NOTE_RE.search(text):
            nl = "\r\n" if "\r\n" in text else "\n"
            sep = "" if not text or text.endswith(nl * 2) else nl if text.endswith(nl) else nl * 2
            store.write(target, "%s%s<!-- sisi:begin -->%s%s%s<!-- sisi:end -->%s" % (text, sep, nl, store.NOTE, nl, nl))
    except OSError as e:
        why = "it is not valid UTF-8" if "UTF-8" in str(e) else str(e)
        return print("sisi: could not add the rules note to %s (%s)." % (os.path.join(root, "AGENTS.md"), why)) if write else "missing (%s)" % why


def _move(dest, old):
    """Move the store's old file into `.sisi/rules.md` under the project lock. Returns a warning, or ""."""
    if not os.path.isfile(old):
        return ""
    raw = store.read(old)
    try:
        _check_writable(dest)
        before = _text(dest)
        extra = [l for l in dict.fromkeys(_parse(raw)) if l not in set(_parse(before or ""))]
        rel = os.path.relpath(old, store.DATA)
        uncommitted = not os.path.isdir(os.path.join(store.DATA, ".git")) or store.git(["status", "--porcelain", "--", rel], store.DATA)[1].strip()
        if uncommitted and not store.commit("project rules before move to .sisi/rules.md", old):
            raise OSError("could not commit store")
        extra and store.write(dest, _append(before, extra))
        (extra or _parse(raw)) and note(dest)
        os.remove(old)
        if not store.commit("project rules moved to .sisi/rules.md", old):
            raise OSError("could not commit store")
    except OSError as e:
        not os.path.exists(old) and store.write(old, raw)
        return "sisi: could not move this project's rules to %s (%s); keeping the copy in your store." % (dest, e)
    return ""


def _migrate(cwd=None, wait=True):
    """Move this project's rules out of the store if an old file exists. Returns (rules, warning)."""
    dest, old = path(PROJECT, cwd), _legacy(cwd)
    msg = ("sisi: project rules are not kept inside a git directory or a bare repository." if not dest
           else "sisi: %s is a link, and sisi does not use a linked .sisi; its rules are not read." % d if os.path.islink(d := os.path.dirname(dest))
           else "sisi: %s is %s; its rules are not read." % (dest, why) if not os.path.isfile(old) and (why := "not a directory" if os.path.lexists(d) and not os.path.isdir(d) else store.regular(dest)[0]) else "")
    if not msg and os.path.isfile(old):
        with store.lock(dest, wait=wait) as ok:
            msg = _move(dest, old) if ok else ""
    return scope_lines(PROJECT, cwd, migrate=False), msg


def scope_lines(scope, cwd=None, migrate=True):
    if scope == USER:
        return lines(path(USER))
    if migrate:
        return _migrate(cwd)[0]
    dest, old = path(PROJECT, cwd), _legacy(cwd)
    raw = store.regular(dest, True)[1] if dest and not os.path.islink(os.path.dirname(dest)) else None
    return list(dict.fromkeys((_parse(raw.decode("utf-8", "replace")) if raw is not None else []) + lines(old)))


def _commit(msg, *paths, snap=None):
    if snap:
        p = store.data("rules", "last-project.json")
        store.write(p, json.dumps(dict(zip(("path", "before", "after"), snap))))
        paths = (p,) + paths
    if not store.commit(msg, *paths):
        raise OSError("store git commit failed")


def add(text, scope, source, cwd=None, log=None, means=""):
    """Put one rule in force; returns (line, warning). Raises OSError before writing when the list cannot be written."""
    line, *more = ["- %s [%s %s]" % (" ".join(str(t).split()), src, time.strftime("%Y-%m-%d")) for t, src in ((text, source), (means, "agent reading")) if t]  # one commit holds both
    dest = path(scope, cwd)
    scope == PROJECT and not dest and _check_writable(dest)
    with store.lock(dest if scope == PROJECT else "user"):
        if scope == USER:
            [store.append(dest, l) for l in [line, *more]]
        else:
            _check_writable(dest)
            msg = _move(dest, _legacy(cwd))
            msg and print(msg)
            before = _text(dest)
            after = _append(before, [line, *more])
            store.write(dest, after)
            note(dest)
        try:
            log and store.append(*log)
            extra = ([dest] if scope == USER else []) + ([log[0]] if log else [])
            _commit("rule added (%s, %s)" % (scope, source), *extra, snap=(dest, before, after) if scope == PROJECT else None)
            warn = ""
        except OSError as e:
            warn = "the rule is in %s; it could not be recorded for undo: %s" % (dest, e)
    scope == USER and build_rulebook()
    return line, warn


def _fit(ls):
    cfg, keep, n, chars = store.config(), set(), 0, 0
    for i in range(len(ls) - 1, -1, -1):
        if not _owner(ls[i]):
            if n >= cfg["rules_lines"] or chars + len(ls[i]) > cfg["rules_chars"]:
                break
            keep.add(i)
            n, chars = n + 1, chars + len(ls[i])
    return [l for i, l in enumerate(ls) if _owner(l) or i in keep]


def delivered(p):
    """The newest rules that fit the budget, oldest first. The rest wait for organizing."""
    return _fit(lines(p))


def build_rulebook():
    """Write the always-loaded instructions: the product's rulebook, then the person's learned rules."""
    text = store.read(os.path.join(store.ROOT, "canon", "core.md")).rstrip() + "\n"
    mine = delivered(path(USER))
    if mine:
        text += "\n" + HEAD_USER + "\n" + "\n".join(mine) + "\n"
    out = store.data("generated", "core.md")
    store.write(out, text)
    try:  # the copies of it that sisi put into a tool's real instructions file follow
        from . import install
        install.refresh(out)
    except Exception:
        pass  # this runs inside hooks: it must never raise
    return out


def project_text(cwd):
    ls, note = _migrate(cwd, wait=False)
    mine = _fit(ls)
    return "\n".join(x for x in (note, HEAD_PROJECT + "\n" + "\n".join(mine) if mine else "") if x)


def objective():
    m = re.search(r"(?ms)^## The objective\s*\n(.*?)(?=^## )", store.read(os.path.join(store.ROOT, "canon", "core.md")))
    return " ".join(m.group(1).split()) if m else ""


def _organized(rel=("rules", "organized.json")):
    try:
        return json.loads(store.read(os.path.join(store.DATA, *rel)) or "{}")
    except ValueError:
        return {}


def _mark_key(scope, cwd=None):
    return "rules/user.md" if scope == USER else os.path.realpath(path(PROJECT, cwd))


def due(cwd, claim=False):
    """One line when the learned rules need organizing, else ""."""
    cfg, seen, cl, now, need = store.config(), _organized(), _organized(("locks", "organize.json")), time.time(), []
    active = lambda c, k: type(c.get("claim:" + k)) in (int, float) and 0 <= now - c["claim:" + k] < 1800
    for scope in (USER, PROJECT):
        ls, k = _retro(scope_lines(scope, cwd, migrate=False)), _mark_key(scope, cwd)
        prev = int(seen.get(k, seen.get("rules/projects/%s.md" % store.project_key(cwd), 0) if scope == PROJECT else 0))
        over = len(ls) > cfg["rules_lines"] or sum(map(len, ls)) > cfg["rules_chars"]
        if not active(cl, k) and (over or len(ls) - prev >= cfg["organize_after"]):
            need.append((k, "%s rules: %d lines, %s" % (scope, len(ls), "over the budget" if over else "%d new" % (len(ls) - prev))))
    if not need:
        return ""
    if claim:
        with store.lock("organize", wait=False) as ok:
            cl = _organized(("locks", "organize.json")) if ok else {}
            if not ok or not (need := [(k, m) for k, m in need if not active(cl, k)]):
                return ""
            cl.update({"claim:" + k: now for k, _ in need})
            with contextlib.suppress(OSError):
                store.write(store.data("locks", "organize.json"), json.dumps(cl))
    return ("sisi: the learned rules need organizing (%s). In the background, give the output of "
            "`sisi rules organize` to a cheap worker and record its answer with `sisi rules organize --record FILE`."
            % "; ".join(m for _, m in need))


def organize_brief(cwd):
    cfg, u, p = store.config(), lines(path(USER)), scope_lines(PROJECT, cwd)
    with contextlib.suppress(OSError), store.lock("organize"):
        cl = _organized(("locks", "organize.json"))
        cl["snap:" + _mark_key(PROJECT, cwd)] = _snap(u, p)
        store.write(store.data("locks", "organize.json"), json.dumps(cl))
    return ORGANIZE % {
        "name": os.path.basename(store.project_root(cwd)), "objective": objective(),
        "lines": cfg["rules_lines"], "chars": cfg["rules_chars"],
        "flagged": "\n".join(l for l in u + p if SMELL.search(l)) or "(none)",
        "user": "\n".join(u) or "(none)", "project": "\n".join(p) or "(none)",
        "retros": "\n".join(store.read(store.data("retro.jsonl")).splitlines()[-40:]) or "(none)"}


def organize_record(answer_file, cwd):
    """Replace both lists with the worker's answer. Returns why not, or None when it is done."""
    cfg = store.config()
    body, *flags = re.split(r"(?im)^##\s*flags\s*$", store.read(answer_file), 1)  # the flags are for the person, not rules
    flags = "".join(flags)
    parts = re.split(r"(?m)^## (user|project)[ \t]*$", body)
    got = {parts[i]: [l.rstrip() for l in parts[i + 1].splitlines() if l.startswith("- ")]
           for i in range(1, len(parts) - 1, 2)}
    if set(got) != {USER, PROJECT}:
        return "the answer needs a `## user` section and a `## project` section, each a list of `- ` lines"
    for scope, ls in got.items():
        r = _retro(ls)
        if len(r) > cfg["rules_lines"] or sum(map(len, r)) > cfg["rules_chars"]:
            return "the %s list is over the budget of %d lines and %d characters (it has %d and %d)" % (
                scope, cfg["rules_lines"], cfg["rules_chars"], len(r), sum(map(len, r)))
    up, pp = path(USER), path(PROJECT, cwd)
    if not pp or os.path.islink(os.path.dirname(pp)):
        return _migrate(cwd)[1].removeprefix("sisi: ")
    with store.lock(pp):
        msg = _move(pp, _legacy(cwd))
        if msg:
            return msg.removeprefix("sisi: ")
        had = {USER: lines(up), PROJECT: scope_lines(PROJECT, cwd, migrate=False)}
        if (want := _organized(("locks", "organize.json")).get("snap:" + _mark_key(PROJECT, cwd))) and _snap(had[USER], had[PROJECT]) != want:
            return "the rules changed since `sisi rules organize` ran; run `sisi rules organize` again"
        for scope in (USER, PROJECT):
            if miss := [l for l in had[scope] if _owner(l) and got[scope].count(l) < had[scope].count(l)]:
                return "owner rule missing or changed (%s): %s" % (scope, miss[0])
        if not any(got.values()) and any(had.values()):
            return "the answer holds no rules at all"
        try:
            before = _text(pp)
            after = "".join(l + "\n" for l in got[PROJECT]) if got[PROJECT] or before is not None else None
            after is not None and _check_writable(pp)
            wrote = after is not None and after != before
            wrote and store.write(pp, after)
        except OSError as e:
            return "could not write %s (%s)" % (pp, e)
        after is not None and note(pp)
        wrote_u = False
        try:
            store.write(up, "".join(l + "\n" for l in got[USER]))
            wrote_u = True
            seen = _organized()
            seen.update({_mark_key(USER): len(_retro(got[USER])), _mark_key(PROJECT, cwd): len(_retro(got[PROJECT]))})
            seen.pop("rules/projects/%s.md" % store.project_key(cwd), None)
            marks = store.data("rules", "organized.json")
            store.write(marks, json.dumps(seen))
            _commit("rules organized", marks, up, snap=(pp, before, after))
        except OSError as e:
            wrote_u and build_rulebook()
            if not wrote and not wrote_u:
                return "could not write %s (%s)" % (up, e)
            print("the organized rules are in %s; they could not be recorded for undo: %s" % (pp if wrote else up, e))
            return None
    with contextlib.suppress(OSError), store.lock("organize"):
        cl = {k: v for k, v in _organized(("locks", "organize.json")).items()
              if k not in ("claim:" + _mark_key(USER), "claim:" + _mark_key(PROJECT, cwd), "snap:" + _mark_key(PROJECT, cwd))}
        store.write(store.data("locks", "organize.json"), json.dumps(cl))
    build_rulebook()
    for scope in (USER, PROJECT):
        print("%s rules: %d lines (were %d)" % (scope, len(got[scope]), len(had[scope])))
    flags.strip() and print("Flagged for you (not changed):" + flags.rstrip())
    return None


def revert():
    """Undo the last rule change (learn, retro or organize): a project's list only while it holds what that change left."""
    files = ("rules/user.md", "rules/last-project.json", "rules/owner.log", "rules/organized.json")
    advice = " (edit by hand or restore with git)"
    if os.path.isdir(os.path.join(store.DATA, ".git")) and store.git(["status", "--porcelain", "--", *files], store.DATA)[1].strip():
        return "the store has uncommitted rule changes, so the previous change cannot be undone" + advice
    rc, out = store.git(["log", "-1", "--format=%H %s", "--name-only", "--", *files], store.DATA)
    if rc != 0 or not out.strip():
        return "there is no change to the learned rules to undo"
    (commit, _, subject), changed = out.splitlines()[0].partition(" "), out.splitlines()[1:]
    redo = len(re.match(r'(Revert ")*', subject).group(0)) // 8 % 2
    snap = {}
    if "rules/last-project.json" in changed or "(project," in subject or "organized" in subject:
        raw = store.git(["show", commit + "^" * redo + ":rules/last-project.json"], store.DATA)[1] if "rules/last-project.json" in changed else ""
        try:
            snap = json.loads(raw)
        except ValueError:
            snap = None
        if (not isinstance(snap, dict) or not {"path", "before", "after"} <= set(snap) or not isinstance(sp := snap["path"], str)
                or not os.path.isabs(sp) or os.path.normpath(sp) != sp or not sp.endswith("/.sisi/rules.md") or ".git" in sp.split(os.sep)
                or any(snap[k] is not None and not isinstance(snap[k], str) for k in ("before", "after"))):
            return "the undo record for `%s` is missing, corrupt or outside .sisi/rules.md, so it cannot be undone%s" % (subject, advice)
    p, (now, want) = snap.get("path"), (snap.get("before"), snap.get("after"))[::1 if redo else -1]
    with store.lock(p or "user"), store.lock("store"):
        if store.git(["log", "-1", "--format=%H", "--", *files], store.DATA)[1].strip() != commit:
            return "another rule change finished while waiting; run `sisi rules revert` again"
        try:
            cur = p and _text(p)
            if p and (cur != now or not os.path.isdir(os.path.dirname(os.path.dirname(p)))):
                return "%s has changed since `%s`, or its folder moved or is gone, so that change cannot be undone%s" % (p, subject, advice)
            p and _check_writable(p)
            p and (os.remove(p) if want is None and cur is not None else want != cur and store.write(p, want))
        except OSError as e:
            return "could not restore %s (%s)%s" % (p, e, advice)
        if store.git(["-c", "user.name=sisi", "-c", "user.email=sisi@localhost", "revert", "--no-edit", commit], store.DATA)[0]:
            store.git(["revert", "--abort"], store.DATA)
            p and want != cur and (store.write(p, cur) if cur is not None else os.path.lexists(p) and os.remove(p))
            return "could not undo `%s`%s" % (subject, advice)
    build_rulebook()
    print("undone: %s" % subject)
    return None


def show(cwd):
    print("rulebook (loaded in every session): %s" % store.data("generated", "core.md"))
    proj, note = _migrate(cwd)
    note and print("\n" + note)
    for title, ls in (("Learned, all projects", lines(path(USER))), ("Learned, this project", proj)):
        print("\n%s (%d):\n%s" % (title, len(ls), "\n".join(ls) or "  (none)"))
    if due(cwd):
        print("\n" + due(cwd))


def run(args, cwd=None):
    cwd = cwd or os.getcwd()
    if not args:
        show(cwd)
        return 0
    if args[0] == "organize" and len(args) == 1:
        print(organize_brief(cwd))
        return 0
    if args[0] == "organize" and len(args) == 3 and args[1] == "--record":
        why = organize_record(args[2], cwd)
    elif args == ["revert"]:
        why = revert()
    else:
        why = "usage: sisi rules | sisi rules organize [--record FILE] | sisi rules revert"
    if why:
        print("sisi rules: %s. Nothing was changed." % why if not why.startswith("usage") else why)
    return 1 if why else 0


_norm = lambda t: " ".join(re.sub(r"[\W_]+", " ", t.lower()).split())


def _said(words, cwd):
    """True when the words are a quotation of one of the person's recent messages in this session."""
    try:
        sid = store.current_session(cwd)
        said = json.loads(store.read(store._session_path(sid)) or "{}").get("said") if sid else None
    except (OSError, ValueError, AttributeError):
        return False
    return isinstance(said, list) and any(" %s " % _norm(words) in " %s " % _norm(m) for m in said if isinstance(m, str))


def learn(args, cwd=None):
    """`sisi learn [--project] "<the person's exact words>" [--means "<how I will apply it>"]`: a rule at once; the
    owner tag only when the words are found in the person's recent messages, else the agent's own tag."""
    i = args.index("--means") if "--means" in args else len(args)
    args, means = list(args[:i]), " ".join(args[i + 1:])
    scope = PROJECT if "--project" in args else USER
    text = " ".join(a for a in args if a != "--project").strip()
    if len(text.split()) < 3 or (means and len(means.split()) < 3):
        print('usage: sisi learn [--project] "<what the person said, in their words>" [--means "<how I will apply it>"]')
        return 1
    heard = _said(text, cwd)
    log = os.path.join(store.DATA, "rules", "owner.log")  # their exact words are kept, whatever organizing later does to the rule
    try:
        line, warn = add(text, scope, "owner" if heard else "agent, attributed to owner", cwd, (log, "%s %s %s" % (time.strftime("%Y-%m-%d"), scope, " ".join(text.split()))), means)
    except OSError as e:
        print("sisi learn: could not write %s (%s). Nothing was changed, and your words were not kept." % (path(scope, cwd) or cwd or os.getcwd(), e))
        return 1
    heard or print("sisi learn: these words were not found in the person's recent messages, so the rule carries the weaker tag [agent, attributed to owner]; a later owner statement or a measurement overrides it.")
    print(warn or "in force from the next session: %s" % line)
    return 0
