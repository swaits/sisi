"""Wiring sisi into every agent tool on the machine, and putting a checked copy of the product in place.

The tools are plain data in canon/harnesses.json: where each keeps its always-on instructions (the rulebook goes
there) and, for the ones whose hooks have the same shape, its hooks file. Nothing is written for a tool that is
not installed, and nothing is touched that sisi cannot edit safely: it is left alone and reported."""
import json, os, re, shutil, subprocess, sys, tempfile, time
from . import models, rules, store

SISI = re.compile(r"bin/sisi (tick|prompt|watch|gate)\b")  # what marks a hook entry as sisi's, old or new
SUBS = ("tick", "prompt", "watch", "gate")


def _current():
    return os.path.join(store.LIB, "current")


def _book():
    return os.path.join(store.DATA, "generated", "core.md")


def _table():
    try:
        return json.loads(store.read(os.path.join(store.ROOT, "canon", "harnesses.json")))
    except ValueError:
        return []


def _dir(h):
    """The tool's folder when it is installed, else None."""
    d = os.environ.get(h.get("env", "")) or os.path.expanduser(h["detect"])
    return d if os.path.isdir(d) else None


def _read(path):
    """The file's text, "" when there is none. A file that cannot be read as text raises, so it is never overwritten."""
    return open(path, encoding="utf-8").read() if os.path.lexists(path) else ""


def _save(path, text):
    real = os.path.realpath(path)  # a link to the real file (a dotfiles repository) stays a link
    if os.path.exists(real) and not os.stat(real).st_mode & 0o200:
        raise OSError("it is read-only")
    store.write(real, text)


def _ours(entry):
    return isinstance(entry, dict) and bool(SISI.search(str(entry.get("command"))))


def _load(path):
    """The hooks file's JSON object and its hooks. ValueError when sisi cannot edit it safely."""
    raw = _read(path)
    try:
        doc = json.loads(raw) if raw.strip() else {}
    except ValueError:
        raise ValueError("it is not plain JSON (a comment or a trailing comma?)")
    hooks = doc.get("hooks", {}) if isinstance(doc, dict) else None
    if not isinstance(hooks, dict) or not all(isinstance(v, list) for v in hooks.values()):
        raise ValueError("its hooks are not in a shape sisi can edit")
    return raw, doc, hooks


def _entries(h):
    """The hook entries this tool gets, in order: (event, entry)."""
    exe, spec = os.path.join(_current(), "bin", "sisi"), h["hooks"]
    return [(spec[sub], dict({"matcher": "*"} if sub == "watch" else {}, hooks=[
        {"type": "command", "command": "test -x %s || exit 0 ; %s %s" % (exe, exe, sub)}])) for sub in SUBS]


def _sync(path, wanted):
    """Take every sisi entry out of a hooks file (under any event), then add `wanted`. Everything else stays."""
    raw, doc, hooks = _load(path)
    new = {}
    for event, groups in hooks.items():
        kept = []
        for g in groups:
            inner = g.get("hooks") if isinstance(g, dict) else None
            mine = [x for x in inner if _ours(x)] if isinstance(inner, list) else []
            if not mine:
                kept.append(g)
            elif len(mine) < len(inner):
                kept.append(dict(g, hooks=[x for x in inner if not _ours(x)]))
        if kept or not groups:
            new[event] = kept
    for event, entry in wanted:
        new.setdefault(event, []).append(entry)
    out = dict(doc, hooks=new) if new or "hooks" in doc else doc
    if out == doc:
        return "unchanged"
    if raw and wanted and not os.path.exists(os.path.realpath(path) + ".before-sisi"):
        store.write(os.path.realpath(path) + ".before-sisi", raw)
    if not wanted and out in ({}, {"hooks": {}}):
        os.remove(os.path.realpath(path))  # nothing but sisi's entries was there
        return "file removed"
    _save(path, json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    return "wired" if wanted else "removed"


def _hooks(h, d, mode):
    return _sync(os.path.join(d, h["hooks"]["file"]), _entries(h) if mode == "add" else []) if h.get("hooks") else ""


def _clean(h, d):
    """Take out what an older sisi left in this tool: its hook entries in a json file, or a file it generated."""
    done = []
    for rel in h.get("clean", []):
        path = os.path.join(d, rel)
        if rel.endswith(".json"):
            how = _sync(path, [])
            done += ["sisi's entries from " + rel] if how == "removed" else [rel] if how == "file removed" else []
        elif os.path.isfile(path) and not os.path.islink(path) and "sisi:generated" in _read(path)[:300]:
            os.remove(path)
            done.append(rel)
    return "removed " + ", ".join(done) if done else ""


def _rulebook(h, d, book, mode):
    """Deliver the rulebook to the tool's instructions file. mode: add (create it), refresh (only what sisi put
    there), remove, or check. Returns how it stands; a file sisi cannot own is left alone and reported."""
    target = os.path.join(d, h["rules"])
    if os.path.islink(target):
        if os.path.realpath(target) != os.path.realpath(book):
            return "left alone: it is a link to %s, not to the rulebook" % os.path.realpath(target)
        if mode == "remove":
            os.remove(target)
            return "link removed"
        return "linked"
    text = _read(target)
    body = "@%s\n" % book if h.get("import") else store.read(book)
    found = store.BLOCK.search(text)
    if mode == "remove":
        if found:
            rest = store.BLOCK.sub("", text, count=1)
            os.remove(target) if not rest else _save(target, rest)
        return "removed" if found else ""
    if not found and mode == "add" and not os.path.exists(target) and not h.get("import"):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        os.symlink(book, target)
        return "linked"
    if mode != "check" and (found or mode == "add"):
        new = store.put_block(text, body)
        new != text and _save(target, new)
        found = True
    if not found:
        return "MISSING (run `sisi install`)"
    return "imported" if h.get("import") else "in a marked block"


def refresh(book):
    """The rulebook was rebuilt: bring the copy that sisi put into a tool's real instructions file up to date."""
    for h in _table():
        try:
            if h.get("rules") and _dir(h):
                _rulebook(h, _dir(h), book, "refresh")
        except (OSError, ValueError):
            pass


def _apply(mode):
    book, bad = rules.build_rulebook() if mode == "add" else _book(), 0
    for h in _table():
        d = _dir(h)
        steps = [("hooks", lambda: _hooks(h, d, mode)), ("old files", lambda: _clean(h, d))]
        if h.get("rules"):
            steps.insert(0, ("rulebook", lambda: _rulebook(h, d, book, mode)))
        for label, step in steps if d else ():
            try:
                msg = step()
            except (OSError, ValueError) as e:
                msg, bad = "left alone (%s)" % e, 1
            if msg:
                print("%s %s: %s" % (h["name"], label, msg))
    return bad


def _command(mode):
    """`sisi` on PATH: ~/.local/bin/sisi, a link to the launcher. Anything else already there is left alone."""
    link, exe = os.path.join(store.HOME, ".local", "bin", "sisi"), os.path.join(_current(), "bin", "sisi")
    mine = os.path.islink(link) and os.readlink(link) == exe
    if mode == "remove" and mine:
        os.remove(link)
        try:
            os.removedirs(os.path.dirname(link))  # the folders install made, while they are empty
        except OSError:
            pass
    elif mode == "add" and not os.path.lexists(link):
        os.makedirs(os.path.dirname(link), exist_ok=True)
        os.symlink(exe, link)
        print("sisi command: linked %s" % link)
    elif mode == "add" and not mine:
        print("sisi command: left alone: %s is already there and is not sisi's link to %s" % (link, exe))


def install():
    """Rulebook and hooks into every tool that is installed, and `sisi` on PATH. Safe to repeat."""
    _command("add")
    return _apply("add")


def uninstall():
    """Take out exactly what install put in."""
    _command("remove")
    return _apply("remove")


def _source():
    """The URL this checkout came from: its github or origin remote, else its first. "" when it has none."""
    names = store.git(["remote"], store.ROOT)[1].split()
    for name in [n for n in ("github", "origin") if n in names] + names:
        rc, url = store.git(["remote", "get-url", name], store.ROOT)
        return url.strip() if rc == 0 else ""
    return ""


def _switch(dest):
    tmp = _current() + ".new"
    if os.path.lexists(tmp):
        os.remove(tmp)
    os.symlink(dest, tmp)
    os.replace(tmp, _current())


def release():
    """Run the tests, then make this copy the one the hooks run. The four newest releases are kept. Run through the
    installed command (a copy in the releases folder) it releases the checkout that copy came from, if there is one."""
    folder, src = os.path.join(store.LIB, "releases"), (store.read(os.path.join(store.ROOT, "SOURCE")).split("\n") + ["", ""])[1].strip()
    if store.ROOT.startswith(os.path.realpath(folder) + os.sep):  # the installed command: a copy of it ships nothing new
        if src and os.path.isfile(os.path.join(src, "bin", "sisi")):  # SOURCE: the remote's url, then the checkout's path
            print("sisi release: this is the installed copy; releasing from %s instead." % src)
            return subprocess.run([sys.executable, os.path.join(src, "bin", "sisi"), "release"]).returncode
        print("sisi release: run it from the source checkout.")
        return 1
    if subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=store.ROOT).returncode:
        print("sisi release: the tests fail. Nothing was released.")
        return 1
    name = time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + "%03dZ" % (time.time() % 1 * 1000)  # two in one second differ
    dest = os.path.join(folder, name)
    shutil.copytree(store.ROOT, dest, ignore=shutil.ignore_patterns(".git", ".agent-work", ".sisi", "__pycache__"))
    store.write(os.path.join(dest, "SOURCE"), "%s\n%s\n" % (_source(), os.path.abspath(store.ROOT)))
    _switch(dest)
    subprocess.run([os.path.join(dest, "bin", "sisi"), "rulebook"])
    for old in [o for o in sorted(os.listdir(folder)) if o != name][:-3]:  # never the one just put in use, even when the clock is behind
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


def update():
    """Fetch the newest sisi from where the release in use came from, and release it. No checkout needed."""
    url = store.read(os.path.join(_current(), "SOURCE")).split("\n")[0].strip()
    if not url:
        print("sisi update: the release in use does not record where it came from. Run `sisi release` from a checkout that has a remote.")
        return 1
    with tempfile.TemporaryDirectory(prefix="sisi-update-") as tmp:
        src = os.path.join(tmp, "sisi")
        if subprocess.run(["git", "clone", "-q", "--depth", "1", url, src]).returncode:
            print("sisi update: could not fetch %s. Nothing was changed." % url)
            return 1
        return subprocess.run([sys.executable, os.path.join(src, "bin", "sisi"), "release"]).returncode


def _wired(h, d):
    """Does the tool's hooks file hold every current sisi entry?"""
    hooks = _load(os.path.join(d, h["hooks"]["file"]))[2]
    have = {(event, SISI.search(x["command"]).group(1)) for event, groups in hooks.items() for g in groups
            if isinstance(g, dict) and isinstance(g.get("hooks"), list) for x in g["hooks"] if _ours(x)}
    return {(h["hooks"][sub], sub) for sub in SUBS} <= have


def _state(h, d):
    if not d:
        return "not installed"
    if not h.get("rules"):
        return "not covered"
    try:
        state = "rulebook " + _rulebook(h, d, _book(), "check")
        if h.get("hooks"):
            state += "; hooks " + ("wired" if _wired(h, d) else "MISSING (run `sisi install`)")
        return state if h.get("hooks") else state + "; rulebook only"
    except (OSError, ValueError, TypeError) as e:
        return "unreadable (%s)" % e


def doctor(cwd=None):
    book = store.read(_book())
    age = models.age_days()
    print("this copy:       %s" % store.ROOT)
    print("release in use:  %s" % (os.path.realpath(_current()) if os.path.lexists(_current()) else "none: run `sisi release`"))
    print("your store:      %s" % store.DATA)
    print("rulebook:        %d lines, %d characters" % (len(book.splitlines()), len(book)))
    proj_n = len(rules.scope_lines(rules.PROJECT, cwd))
    print("learned rules:   %d for all projects, %d for this one" % (len(rules.lines(rules.path(rules.USER))), proj_n))
    proj_n and print("project note:    %s" % rules.note(cwd, write=False))
    print("models table:    %s" % ("none yet" if age is None else "%d days old" % age))
    print("sisi on PATH:    %s" % (shutil.which("sisi") or "no: add ~/.local/bin to PATH (`sisi install` links it there)"))
    for h in _table():
        print("%-13s %s%s" % (h["name"] + ":", _state(h, _dir(h)), ". " + h.get("limits", "") if _dir(h) else ""))
    return 0
