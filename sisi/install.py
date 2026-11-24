"""Wiring sisi into the agent tool, and putting a checked copy of the product in place."""
import json, os, shutil, subprocess, sys, time
from . import models, rules, store

# event, the sisi command it runs, the tool matcher it needs
EVENTS = (("SessionStart", "tick", None), ("UserPromptSubmit", "prompt", None),
          ("PreToolUse", "watch", "*"), ("Stop", "gate", None))


def _claude():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(store.HOME, ".claude")


def _current():
    return os.path.join(store.LIB, "current")


def _wired(settings, sub):
    entries = (settings.get("hooks") or {}).get({s: e for e, s, _ in EVENTS}[sub]) or []
    return any("bin/sisi %s" % sub in str(h.get("command")) for e in entries for h in e.get("hooks") or [])


def install():
    """Add the four hooks to the tool's settings and the rulebook to its instructions. Safe to repeat."""
    spath = os.path.join(_claude(), "settings.json")
    raw = store.read(spath)
    try:
        settings = json.loads(raw) if raw.strip() else {}
        assert isinstance(settings, dict) and isinstance(settings.get("hooks", {}), dict)
    except (ValueError, AssertionError):
        print("sisi install: %s is not something sisi can edit safely. Fix it first. Nothing was changed." % spath)
        return 1
    exe, added = os.path.join(_current(), "bin", "sisi"), []
    for event, sub, matcher in EVENTS:
        if not _wired(settings, sub):
            entry = {"hooks": [{"type": "command", "command": "test -x %s || exit 0 ; %s %s" % (exe, exe, sub)}]}
            if matcher:
                entry["matcher"] = matcher
            settings.setdefault("hooks", {}).setdefault(event, []).append(entry)
            added.append(event)
    if added:
        if raw:
            store.write(spath + ".before-sisi", raw)
        store.write(spath, json.dumps(settings, indent=2) + "\n")
    book = rules.build_rulebook()
    mpath = os.path.join(_claude(), "CLAUDE.md")
    md = store.read(mpath)
    if "@" + book not in md:
        store.write(mpath, (md.rstrip() + "\n\n" if md.strip() else "") + "<!-- sisi:begin -->\n@%s\n<!-- sisi:end -->\n" % book)
    print("hooks added: %s" % (", ".join(added) or "none, all four were there"))
    print("rulebook: %s (loaded through %s)" % (book, mpath))
    return 0


def _switch(dest):
    tmp = _current() + ".new"
    if os.path.lexists(tmp):
        os.remove(tmp)
    os.symlink(dest, tmp)
    os.replace(tmp, _current())


def release():
    """Run the tests, then make this copy the one the hooks run. The four newest releases are kept."""
    if subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=store.ROOT).returncode:
        print("sisi release: the tests fail. Nothing was released.")
        return 1
    folder = os.path.join(store.LIB, "releases")
    name = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    dest = os.path.join(folder, name)
    shutil.copytree(store.ROOT, dest, ignore=shutil.ignore_patterns(".git", ".agent-work", ".sisi", "__pycache__"))
    _switch(dest)
    subprocess.run([os.path.join(dest, "bin", "sisi"), "rulebook"])
    for old in sorted(os.listdir(folder))[:-4]:
        shutil.rmtree(os.path.join(folder, old), ignore_errors=True)
    print("released %s" % name)
    return 0


def rollback():
    """Go back to the release before the one in use."""
    folder = os.path.join(store.LIB, "releases")
    now = os.path.basename(os.path.realpath(_current()))
    older = [n for n in sorted(os.listdir(folder)) if n < now] if os.path.isdir(folder) else []
    if not older:
        print("sisi rollback: there is no earlier release.")
        return 1
    _switch(os.path.join(folder, older[-1]))
    exe = os.path.join(_current(), "bin", "sisi")  # the copy now in use rebuilds the rulebook its own way
    if subprocess.run([exe, "rulebook"], capture_output=True).returncode:
        subprocess.run([exe, "install"], capture_output=True)
    print("now running release %s (was %s)" % (older[-1], now))
    return 0


def doctor(cwd=None):
    try:
        settings = json.loads(store.read(os.path.join(_claude(), "settings.json")) or "{}")
    except ValueError:
        settings = {}
    book = store.read(os.path.join(store.DATA, "generated", "core.md"))
    age = models.age_days()
    print("this copy:       %s" % store.ROOT)
    print("release in use:  %s" % (os.path.realpath(_current()) if os.path.lexists(_current()) else "none: run `sisi release`"))
    print("your store:      %s" % store.DATA)
    print("hooks:           %s" % ", ".join("%s %s" % (e, "wired" if _wired(settings, s) else "MISSING (run `sisi install`)")
                                             for e, s, _ in EVENTS))
    print("rulebook:        %d lines, %d characters" % (len(book.splitlines()), len(book)))
    print("learned rules:   %d for all projects, %d for this one" % (
        len(rules.lines(rules.path(rules.USER))), len(rules.lines(rules.path(rules.PROJECT, cwd)))))
    print("models table:    %s" % ("none yet" if age is None else "%d days old" % age))
    return 0
