"""Learned rules: what retros and the person add to the instructions.

A rule is one line. It is in force as soon as it is added: rules for all of the person's work become the last
section of the rulebook every session loads, and a project's rules are printed when a session starts there.
Now and then a cheap worker audits and organizes them. Every change is one commit and can be undone."""
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


def path(scope, cwd=None):
    if scope == USER:
        return store.data("rules", "user.md")
    return store.data("rules", "projects", store.project_key(cwd) + ".md")


def lines(p):
    return [l.rstrip() for l in store.read(p).splitlines() if l.startswith("- ")]


def add(text, scope, source, cwd=None):
    """Put one rule in force. `source` is "owner" for the person's own words, "retro" for a retro's finding."""
    p = path(scope, cwd)
    line = "- %s [%s %s]" % (" ".join(str(text).split()), source, time.strftime("%Y-%m-%d"))
    store.append(p, line)
    store.commit("rule added (%s, %s)" % (scope, source), p)
    if scope == USER:
        build_rulebook()
    return line


def delivered(p):
    """The newest rules that fit the budget, oldest first. The rest wait for organizing."""
    cfg, out, chars = store.config(), [], 0
    for line in reversed(lines(p)):
        if len(out) >= cfg["rules_lines"] or chars + len(line) > cfg["rules_chars"]:
            break
        out.append(line)
        chars += len(line)
    return out[::-1]


def build_rulebook():
    """Write the always-loaded instructions: the product's rulebook, then the person's learned rules."""
    text = store.read(os.path.join(store.ROOT, "canon", "core.md")).rstrip() + "\n"
    mine = delivered(path(USER))
    if mine:
        text += "\n" + HEAD_USER + "\n" + "\n".join(mine) + "\n"
    out = store.data("generated", "core.md")
    store.write(out, text)
    return out


def project_text(cwd):
    mine = delivered(path(PROJECT, cwd))
    return HEAD_PROJECT + "\n" + "\n".join(mine) if mine else ""


def objective():
    m = re.search(r"(?ms)^## The objective\s*\n(.*?)(?=^## )", store.read(os.path.join(store.ROOT, "canon", "core.md")))
    return " ".join(m.group(1).split()) if m else ""


def _organized():
    try:
        return json.loads(store.read(store.data("rules", "organized.json")) or "{}")
    except ValueError:
        return {}


def due(cwd):
    """One line when the learned rules need organizing, else ""."""
    cfg, seen, why = store.config(), _organized(), []
    for scope in (USER, PROJECT):
        p = path(scope, cwd)
        ls = lines(p)
        over = len(ls) > cfg["rules_lines"] or sum(map(len, ls)) > cfg["rules_chars"]
        added = len(ls) - int(seen.get(os.path.relpath(p, store.DATA), 0))
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
        "project": "\n".join(lines(path(PROJECT, cwd))) or "(none)",
        "retros": "\n".join(store.read(store.data("retro.jsonl")).splitlines()[-40:]) or "(none)"}


def organize_record(answer_file, cwd):
    """Replace both lists with the worker's answer. Returns why not, or None when it is done."""
    cfg = store.config()
    parts = re.split(r"(?m)^## (user|project)[ \t]*$", store.read(answer_file))
    got = {parts[i]: [l.rstrip() for l in parts[i + 1].splitlines() if l.startswith("- ")]
           for i in range(1, len(parts) - 1, 2)}
    if set(got) != {USER, PROJECT}:
        return "the answer needs a `## user` section and a `## project` section, each a list of `- ` lines"
    had = {scope: lines(path(scope, cwd)) for scope in got}
    if not any(got.values()) and any(had.values()):
        return "the answer holds no rules at all"
    for scope, ls in got.items():
        if len(ls) > cfg["rules_lines"] or sum(map(len, ls)) > cfg["rules_chars"]:
            return "the %s list is over the budget of %d lines and %d characters (it has %d and %d)" % (
                scope, cfg["rules_lines"], cfg["rules_chars"], len(ls), sum(map(len, ls)))
    seen, changed = _organized(), []
    for scope, ls in got.items():
        p = path(scope, cwd)
        store.write(p, "".join(l + "\n" for l in ls))
        seen[os.path.relpath(p, store.DATA)] = len(ls)
        changed.append(p)
        print("%s rules: %d lines (were %d)" % (scope, len(ls), len(had[scope])))
    marks = store.data("rules", "organized.json")
    store.write(marks, json.dumps(seen))
    store.commit("rules organized", marks, *changed)
    build_rulebook()
    return None


def revert():
    """Undo the last change to the learned rules. Returns why not, or None when it is done."""
    rc, out = store.git(["log", "-1", "--format=%H %s", "--", "rules"], store.DATA)
    if rc != 0 or not out.strip():
        return "there is no change to the learned rules to undo"
    commit, _, subject = out.strip().partition(" ")
    rc, _ = store.git(["-c", "user.name=sisi", "-c", "user.email=sisi@localhost", "revert", "--no-edit", commit], store.DATA)
    if rc != 0:
        store.git(["revert", "--abort"], store.DATA)
        return "could not undo `%s`" % subject
    build_rulebook()
    print("undone: %s" % subject)
    return None


def show(cwd):
    print("rulebook (loaded in every session): %s" % store.data("generated", "core.md"))
    for scope, title in ((USER, "Learned, all projects"), (PROJECT, "Learned, this project")):
        ls = lines(path(scope, cwd))
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
    log = store.data("rules", "owner.log")  # their exact words are kept, whatever organizing later does to the rule
    store.append(log, "%s %s %s" % (time.strftime("%Y-%m-%d"), scope, " ".join(text.split())))
    store.commit("the person's words", log)
    print("in force from the next session: %s" % add(text, scope, "owner", cwd))
    return 0
