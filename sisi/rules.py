"""Learned rules: what retros and the person add to the instructions.

A rule is one line. It is in force as soon as it is added: rules for all of the person's work become the last
section of the rulebook every session loads, and a project's rules live in `.sisi/rules.md` at its root.
Now and then a cheap worker audits and organizes them. Store changes are committed and can be undone."""
import json, os, re, time
from . import store

USER, PROJECT = "user", "project"
HEAD_USER = "## Learned here\n\nAdded by retros and by the person. These add to the rules above and never relax them.\n"
HEAD_PROJECT = "sisi: learned in this project (these add to the rules and never relax them):"

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
- Lines marked [owner ...] are the person's own words. Keep what each one asks for. You may tighten the
  wording or merge them, and the result stays marked [owner <date>].
- Keep the [source date] mark at the end of every line.
- A `better` that recurs across retros has earned a rule: add it, worded as an instruction, marked [retro <date>].
- Each list: at most %(lines)d lines and %(chars)d characters. Fewer is better.

Answer with exactly this shape and nothing else:
## user
- ...
## project
- ...

=== The first list now (all projects) ===
%(user)s

=== The second list now (project "%(name)s") ===
%(project)s

=== What recent retros found, newest last (context only) ===
%(retros)s
"""


def rules_root(cwd=None):
    """Where `.sisi/` lives: git worktree root (or main checkout if ignored), else nearest ancestor with `.sisi/`."""
    cwd = os.path.abspath(cwd or os.getcwd())
    rc, out = store.git(["rev-parse", "--path-format=absolute", "--show-toplevel", "--git-common-dir"], cwd)
    if rc == 0 and out.strip():
        top, common = (out.splitlines() + [""])[:2]
        main = os.path.dirname(common) if os.path.basename(common) == ".git" else top
        return main if main != top and store.git(["check-ignore", "-q", ".sisi/rules.md"], top)[0] == 0 else top
    cur = cwd
    while True:
        if os.path.isdir(os.path.join(cur, ".sisi")) and not os.path.islink(os.path.join(cur, ".sisi")):
            return cur
        if os.path.dirname(cur) == cur:
            return cwd
        cur = os.path.dirname(cur)


def path(scope, cwd=None):
    return store.data("rules", "user.md") if scope == USER else os.path.join(rules_root(cwd), ".sisi", "rules.md")


def _legacy(cwd=None):
    return os.path.join(store.DATA, "rules", "projects", store.project_key(cwd) + ".md")


def lines(p):
    return [l.rstrip() for l in store.read(p).splitlines() if l.startswith("- ")]


def _check_writable(p):
    d, parent = os.path.dirname(p), os.path.dirname(os.path.dirname(p))
    for target, label, want_dir in ((d, ".sisi", True), (p, ".sisi/rules.md", False)):
        if os.path.islink(target):
            raise OSError("%s is a symlink" % label)
        if os.path.lexists(target) and os.path.isdir(target) != want_dir:
            raise OSError("%s is %s" % (label, "not a directory" if want_dir else "a directory"))
        if os.path.exists(target) and not (os.stat(target).st_mode & 0o200):
            raise OSError("%s is read-only" % label)
    if not os.path.exists(d) and os.path.isdir(parent) and not (os.stat(parent).st_mode & 0o200):
        raise OSError("project folder is read-only")


def _migrate(cwd=None):
    """Move a legacy store rule file into `.sisi/rules.md`. Returns (lines, warning)."""
    dest, old_path = path(PROJECT, cwd), _legacy(cwd)
    cur = [] if os.path.islink(os.path.dirname(dest)) or os.path.islink(dest) else lines(dest)
    if not os.path.isfile(old_path):
        return cur, ""
    old = lines(old_path)
    try:
        if old:
            _check_writable(dest)
            extra = [l for l in dict.fromkeys(old) if l not in set(cur)]
            if extra or not os.path.exists(dest):
                raw = store.read(dest) if os.path.exists(dest) else ""
                store.write(dest, raw + ("\n" if raw and not raw.endswith("\n") else "") + "".join(l + "\n" for l in extra))
            cur = cur + extra
        rel = os.path.relpath(old_path, store.DATA)
        if not os.path.isdir(os.path.join(store.DATA, ".git")) or store.git(["status", "--porcelain", "--", rel], store.DATA)[1].strip():
            store.commit("project rules before move", old_path)
        os.remove(old_path)
        store.commit("project rules moved to .sisi/rules.md", old_path)
        return cur, ""
    except OSError as e:
        return list(dict.fromkeys(cur + old)), "sisi: could not move this project's rules to %s (%s); keeping the copy in your store." % (dest, e)


def scope_lines(scope, cwd=None):
    return lines(path(USER)) if scope == USER else _migrate(cwd)[0]


def add(text, scope, source, cwd=None):
    """Put one rule in force. `source` is "owner" for the person's own words, "retro" for a retro's finding."""
    line = "- %s [%s %s]" % (" ".join(str(text).split()), source, time.strftime("%Y-%m-%d"))
    if scope == USER:
        p = path(USER)
        store.append(p, line)
        store.commit("rule added (%s, %s)" % (scope, source), p)
        build_rulebook()
        return line
    _, note = _migrate(cwd)
    note and print(note)
    p = path(PROJECT, cwd)
    _check_writable(p)
    store.append(p, line)
    return line


def _fit(ls):
    cfg, out, chars = store.config(), [], 0
    for line in reversed(ls):
        if len(out) >= cfg["rules_lines"] or chars + len(line) > cfg["rules_chars"]:
            break
        out.append(line)
        chars += len(line)
    return out[::-1]


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
    ls, note = _migrate(cwd)
    mine = _fit(ls)
    return "\n".join(x for x in (note, HEAD_PROJECT + "\n" + "\n".join(mine) if mine else "") if x)


def objective():
    m = re.search(r"(?ms)^## The objective\s*\n(.*?)(?=^## )", store.read(os.path.join(store.ROOT, "canon", "core.md")))
    return " ".join(m.group(1).split()) if m else ""


def _organized():
    try:
        return json.loads(store.read(store.data("rules", "organized.json")) or "{}")
    except ValueError:
        return {}


def _mark_key(scope, cwd=None):
    return "rules/user.md" if scope == USER else os.path.realpath(path(PROJECT, cwd))


def due(cwd):
    """One line when the learned rules need organizing, else ""."""
    cfg, seen, why = store.config(), _organized(), []
    for scope in (USER, PROJECT):
        ls, k = scope_lines(scope, cwd), _mark_key(scope, cwd)
        prev = int(seen.get(k, seen.get("rules/projects/%s.md" % store.project_key(cwd), 0) if scope == PROJECT else 0))
        over = len(ls) > cfg["rules_lines"] or sum(map(len, ls)) > cfg["rules_chars"]
        added = len(ls) - prev
        if over or added >= cfg["organize_after"]:
            why.append("%s rules: %d lines, %s" % (scope, len(ls), "over the budget" if over else "%d new" % added))
    if not why:
        return ""
    return ("sisi: the learned rules need organizing (%s). In the background, give the output of "
            "`sisi rules organize` to a cheap worker and record its answer with `sisi rules organize --record FILE`."
            % "; ".join(why))


def organize_brief(cwd):
    cfg = store.config()
    return ORGANIZE % {
        "name": os.path.basename(store.project_root(cwd)), "objective": objective(),
        "lines": cfg["rules_lines"], "chars": cfg["rules_chars"],
        "user": "\n".join(lines(path(USER))) or "(none)",
        "project": "\n".join(scope_lines(PROJECT, cwd)) or "(none)",
        "retros": "\n".join(store.read(store.data("retro.jsonl")).splitlines()[-40:]) or "(none)"}


def organize_record(answer_file, cwd):
    """Replace both lists with the worker's answer. Returns why not, or None when it is done."""
    cfg = store.config()
    parts = re.split(r"(?m)^## (user|project)[ \t]*$", store.read(answer_file))
    got = {parts[i]: [l.rstrip() for l in parts[i + 1].splitlines() if l.startswith("- ")]
           for i in range(1, len(parts) - 1, 2)}
    if set(got) != {USER, PROJECT}:
        return "the answer needs a `## user` section and a `## project` section, each a list of `- ` lines"
    for scope, ls in got.items():
        if len(ls) > cfg["rules_lines"] or sum(map(len, ls)) > cfg["rules_chars"]:
            return "the %s list is over the budget of %d lines and %d characters (it has %d and %d)" % (
                scope, cfg["rules_lines"], cfg["rules_chars"], len(ls), sum(map(len, ls)))
    _, note = _migrate(cwd)
    if note:
        return note.removeprefix("sisi: ")
    had = {scope: scope_lines(scope, cwd) for scope in got}
    if not any(got.values()) and any(had.values()):
        return "the answer holds no rules at all"
    up, pp = path(USER), path(PROJECT, cwd)
    write_proj = bool(got[PROJECT]) or os.path.exists(pp)
    before_proj, after_proj = (store.read(pp) if os.path.exists(pp) else None), ("".join(l + "\n" for l in got[PROJECT]) if write_proj else None)
    if write_proj:
        try:
            _check_writable(pp)
            store.write(pp, after_proj)
        except OSError as e:
            return "could not write %s (%s)" % (pp, e)
    store.write(up, "".join(l + "\n" for l in got[USER]))
    seen = _organized()
    seen[_mark_key(USER)], seen[_mark_key(PROJECT, cwd)] = len(got[USER]), len(got[PROJECT])
    seen.pop("rules/projects/%s.md" % store.project_key(cwd), None)
    marks, backup = store.data("rules", "organized.json"), store.data("rules", "last-project.json")
    store.write(marks, json.dumps(seen))
    store.write(backup, json.dumps({"path": pp, "before": before_proj, "after": after_proj}))
    for scope in (USER, PROJECT):
        print("%s rules: %d lines (were %d)" % (scope, len(got[scope]), len(had[scope])))
    store.commit("rules organized", marks, backup, up)
    build_rulebook()
    return None


def revert():
    """Undo the last change to the learned rules. Returns why not, or None when it is done."""
    rc, out = store.git(["log", "-1", "--format=%H %s", "--", "rules"], store.DATA)
    if rc != 0 or not out.strip():
        return "there is no change to the learned rules to undo"
    commit, _, subject = out.strip().partition(" ")
    files = store.git(["diff-tree", "--no-commit-id", "--name-only", "-r", commit], store.DATA)[1].splitlines()
    snap, undo_revert = None, subject.startswith("Revert ")
    if "rules/last-project.json" in files:
        try:
            snap = json.loads(store.git(["show", "%s:rules/last-project.json" % (commit + "^" if undo_revert else commit)], store.DATA)[1])
        except ValueError:
            snap = None
    target = (snap["after"] if undo_revert else snap["before"]) if snap and snap.get("path") else None
    if snap and snap.get("path") and (target is not None or os.path.exists(snap["path"])):
        try:
            _check_writable(snap["path"])
        except OSError as e:
            return "could not restore %s (%s)" % (snap["path"], e)
    rc, _ = store.git(["-c", "user.name=sisi", "-c", "user.email=sisi@localhost", "revert", "--no-edit", commit], store.DATA)
    if rc != 0:
        store.git(["revert", "--abort"], store.DATA)
        return "could not undo `%s`" % subject
    if snap and snap.get("path"):
        os.remove(snap["path"]) if target is None and os.path.exists(snap["path"]) else (target is not None and store.write(snap["path"], target))
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


def learn(args, cwd=None):
    """`sisi learn [--project] TEXT`: the person's own words become a rule at once."""
    scope = PROJECT if "--project" in args else USER
    text = " ".join(a for a in args if a != "--project").strip()
    if len(text.split()) < 3:
        print('usage: sisi learn [--project] "<what the person said, in their words>"')
        return 1
    if scope == PROJECT:
        try:
            _check_writable(path(PROJECT, cwd))
        except OSError as e:
            print("sisi learn: could not write %s (%s). Nothing was changed." % (path(PROJECT, cwd), e))
            return 1
    log = store.data("rules", "owner.log")  # their exact words are kept, whatever organizing later does to the rule
    store.append(log, "%s %s %s" % (time.strftime("%Y-%m-%d"), scope, " ".join(text.split())))
    store.commit("the person's words", log)
    print("in force from the next session: %s" % add(text, scope, "owner", cwd))
    return 0
