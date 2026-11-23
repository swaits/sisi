"""install / uninstall / doctor. Wiring by reference (import line, symlink, hook entry); never copies canon text.
The tools load the generated rulebook in the personal data folder (base rules with the overlay applied), not the
product's canon/core.md. Every modified file is backed up into <personal>/install/ first; uninstall restores it exactly."""
import copy, hashlib, json, os, re, shlex, shutil

from . import paths, store

BEGIN, BEGIN_NONL, END = b"<!-- sisi:begin -->", b"<!-- sisi:begin nonl -->", b"<!-- sisi:end -->"
BLOCK_RE = re.compile(rb"^<!-- sisi:begin( nonl)? -->\n(@[^\n]*)\n<!-- sisi:end -->\n", re.M)


# ---- locations -------------------------------------------------------------
def loc():
    h = paths.home()
    return {
        "claude_dir": os.path.join(h, ".claude"),
        "claude_md": os.path.join(h, ".claude", "CLAUDE.md"),
        "settings": os.path.join(h, ".claude", "settings.json"),
        "codex_dir": os.path.join(h, ".codex"),
        "codex": os.path.join(h, ".codex", "AGENTS.md"),
        "opencode_dir": os.path.join(h, ".config", "opencode"),
        "opencode": os.path.join(h, ".config", "opencode", "AGENTS.md"),
        "skills": os.path.join(h, ".agents", "skills"),
        "bin": os.path.join(h, ".local", "bin", "sisi"),
    }


def core():
    """What the tools import: the generated rulebook."""
    return paths.generated()


def _old_cores():
    """Places earlier installs pointed at (the product's own rulebook)."""
    return (paths.canon("core.md"),)


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _read(p):
    try:
        with open(p, "rb") as f:
            return f.read()
    except OSError:
        return None


def _write(p, data):
    """Atomic write. A symlink at p is written through to its real file, never replaced."""
    real = os.path.realpath(p)
    tmp = real + ".sisi-tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    try:
        os.chmod(tmp, os.stat(real).st_mode & 0o7777)
    except OSError:
        pass
    os.replace(tmp, real)


# ---- manifest --------------------------------------------------------------
def _idir():
    """The install records: <personal>/install/, or the state dir for an installation not migrated yet."""
    new = paths.data_file("install")
    if os.path.exists(os.path.join(new, "manifest.json")) or not os.path.exists(paths.state_file("manifest.json")):
        return new
    return paths.state()


def _mpath():
    return os.path.join(_idir(), "manifest.json")


def _mload():
    try:
        with open(_mpath(), encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError):
        m = {}
    m.setdefault("files", {})
    m.setdefault("dirs", [])
    return m


def _msave(m):
    new = json.dumps(m, indent=1, sort_keys=True) + "\n"
    old = _read(_mpath())
    if old is not None and old.decode() == new:
        return
    os.makedirs(os.path.dirname(_mpath()), exist_ok=True)
    with open(_mpath(), "w", encoding="utf-8") as f:
        f.write(new)


def _backup(m, p, data):
    """Remember the original state of p before first modification."""
    if p in m["files"]:
        return
    name = None
    if data is not None:
        name = "%s-%s.orig" % (_sha(p.encode())[:8], os.path.basename(p))
        bp = os.path.join(_idir(), "backups", name)
        os.makedirs(os.path.dirname(bp), exist_ok=True)
        if not os.path.exists(bp):
            with open(bp, "wb") as f:
                f.write(data)
    m["files"][p] = {"backup": name}


def _mkdirs(m, d):
    missing = []
    while d and not os.path.isdir(d):
        missing.append(d)
        d = os.path.dirname(d)
    for x in reversed(missing):
        os.mkdir(x)
        m["dirs"].append(x)


# ---- CLAUDE.md -------------------------------------------------------------
def _block(nonl):
    return (BEGIN_NONL if nonl else BEGIN) + b"\n@" + core().encode() + b"\n" + END + b"\n"


def add_import(data):
    m = BLOCK_RE.search(data)
    if m:
        want = _block(bool(m.group(1)))
        return data[:m.start()] + want + data[m.end():]
    nonl = bool(data) and not data.endswith(b"\n")
    return data + (b"\n" if nonl else b"") + _block(nonl)


def remove_import(data):
    m = BLOCK_RE.search(data)
    if not m:
        return data
    start = m.start()
    if m.group(1) and data[start - 1:start] == b"\n":
        start -= 1
    return data[:start] + data[m.end():]


def _claude_md_wired(data):
    m = BLOCK_RE.search(data or b"")
    return bool(m) and m.group(2) == b"@" + core().encode()


# ---- settings.json ---------------------------------------------------------
def hook_cmds():
    b = shlex.quote(paths.launcher())
    gate_to = int(store.config()["gate"].get("budget_s", 120)) + 30
    return {"SessionStart": (b + " tick --tool claude-code", 10), "Stop": (b + " gate --tool claude-code", gate_to),
            "SubagentStop": (b + " gate --subagent --tool claude-code", 30)}


def _is_ours(h, sub):
    if not (isinstance(h, dict) and h.get("type") == "command" and isinstance(h.get("command"), str)):
        return False
    try:
        parts = shlex.split(h["command"])
    except ValueError:
        return False
    return len(parts) >= 2 and os.path.basename(parts[0]) == "sisi" and parts[1] == sub


def _parse_settings(text):
    s = text.decode("utf-8")
    if not s.strip():
        return {}, "  ", True
    obj = json.loads(s)
    if not isinstance(obj, dict):
        raise ValueError("settings.json is not a JSON object")
    m = re.search(r'\n([ \t]+)"', s)
    ind = m.group(1) if m else None
    return obj, ind, s.endswith("\n")


def _dump(obj, ind, nl):
    return (json.dumps(obj, indent=ind, ensure_ascii=False) + ("\n" if nl else "")).encode("utf-8")


def add_hooks(obj):
    """Mutate obj; return True if anything changed."""
    changed = False
    hooks = obj.get("hooks")
    if hooks is None:
        hooks = obj["hooks"] = {}
        changed = True
    if not isinstance(hooks, dict):
        raise ValueError("settings.json 'hooks' is not an object")
    for ev, (cmd, to) in hook_cmds().items():
        sub = shlex.split(cmd)[1]
        groups = hooks.get(ev)
        if groups is None:
            groups = hooks[ev] = []
            changed = True
        if not isinstance(groups, list):
            raise ValueError("settings.json hooks.%s is not a list" % ev)
        found = False
        for g in groups:
            for h in (g.get("hooks", []) if isinstance(g, dict) and isinstance(g.get("hooks"), list) else []):
                if _is_ours(h, sub):
                    found = True
                    if h.get("command") != cmd:
                        h["command"] = cmd
                        changed = True
        if not found:
            groups.append({"hooks": [{"type": "command", "command": cmd, "timeout": to}]})
            changed = True
    return changed


def remove_hooks(obj):
    changed = False
    hooks = obj.get("hooks")
    if not isinstance(hooks, dict):
        return False
    for ev, sub in (("SessionStart", "tick"), ("Stop", "gate"), ("SubagentStop", "gate")):
        groups = hooks.get(ev)
        if not isinstance(groups, list):
            continue
        keep, ev_changed = [], False
        for g in groups:
            hs = g.get("hooks") if isinstance(g, dict) else None
            if isinstance(hs, list) and any(_is_ours(h, sub) for h in hs):
                changed = ev_changed = True
                rest = [h for h in hs if not _is_ours(h, sub)]
                if rest:
                    g = dict(g, hooks=rest)
                else:
                    continue
            keep.append(g)
        if keep:
            hooks[ev] = keep
        elif ev_changed:
            del hooks[ev]
    if changed and not hooks:
        del obj["hooks"]
    return changed


def _hooks_wired(obj):
    hooks = obj.get("hooks") if isinstance(obj, dict) else None
    out = {}
    for ev, sub, name in (("SessionStart", "tick", "tick"), ("Stop", "gate", "gate"), ("SubagentStop", "gate", "subagent")):
        groups = hooks.get(ev) if isinstance(hooks, dict) else None
        sub, key = sub, name
        out[key] = False
        for g in groups if isinstance(groups, list) else []:
            for h in g.get("hooks", []) if isinstance(g, dict) and isinstance(g.get("hooks"), list) else []:
                if _is_ours(h, sub) and shlex.split(h["command"])[0] == paths.launcher():
                    out[key] = True
    return out


# ---- symlinks --------------------------------------------------------------
def _ours(p):
    """A symlink sisi made: it points into the product or at the generated rulebook."""
    if not os.path.islink(p):
        return False
    t = os.readlink(p)
    if t.startswith(paths.REPO + os.sep) or t == core() or t.startswith(paths.data() + os.sep):
        return True
    if t.startswith(os.path.join(paths.lib(), "")):
        return True  # the stable copy
    from . import release  # a link made when the tools ran from the source folder
    src = release.dev_source()
    return bool(src) and t.startswith(os.path.join(src, ""))


def _link(m, p, target, notes, label):
    if os.path.islink(p):
        cur = os.readlink(p)
        if cur == target:
            return
        if not _ours(p):
            notes.append("%s: %s is a symlink to %s; not touched" % (label, p, cur))
            return
    elif os.path.lexists(p):
        notes.append("%s: %s exists and is not a symlink; not touched" % (label, p))
        return
    _mkdirs(m, os.path.dirname(p))
    tmp = "%s.sisi-new-%d" % (p, os.getpid())
    try:
        os.unlink(tmp)
    except OSError:
        pass
    os.symlink(target, tmp)
    os.replace(tmp, p)  # a running hook sees the old link or the new one, never none
    notes.append("%s: linked %s" % (label, p))


# ---- install / uninstall ---------------------------------------------------
def _writable(p):
    """Can we create or replace the file p (following symlinks)? Returns an error string or None."""
    if os.path.islink(p) and not os.path.exists(p):
        return "%s is a dangling symlink" % p
    real = os.path.realpath(p)
    if os.path.exists(real):
        ok = os.access(real, os.W_OK) and os.access(os.path.dirname(real), os.W_OK)
    else:
        d = os.path.dirname(real)
        while d and not os.path.isdir(d):
            d = os.path.dirname(d)
        ok = os.access(d, os.W_OK)
    return None if ok else "%s is not writable" % p


def _plan_claude(L):
    """Compute every change to Claude Code's files without touching anything. Returns (steps, errors)."""
    steps, errs = [], []
    p = L["claude_md"]
    e = _writable(p)
    if e:
        errs.append(e)
    else:
        data = _read(p)
        new = add_import(data or b"")
        if data is None or new != data:
            steps.append((p, data, new, "claude-code: import line added to %s" % p))
    p = L["settings"]
    e = _writable(p)
    if e:
        errs.append(e)
    else:
        data = _read(p)
        try:
            obj, ind, nl = _parse_settings(data if data is not None else b"")
            if add_hooks(obj):
                steps.append((p, data, _dump(obj, ind, nl if data is not None else True),
                              "claude-code: hooks registered in %s" % p))
        except (ValueError, UnicodeDecodeError) as ex:
            errs.append("settings.json is not valid (%s); %s left untouched" % (ex, p))
    return steps, errs


def install():
    """Validate everything first; if anything would fail, change nothing."""
    L, notes = loc(), []
    steps, errs = [], []
    if os.path.isdir(L["claude_dir"]):
        steps, errs = _plan_claude(L)
    else:
        notes.append("claude-code: %s not found; skipped" % L["claude_dir"])
    if errs:
        return 1, ["install refused, nothing was changed:"] + ["  " + e for e in errs]
    # The personal folder and the generated rulebook come first: nothing may point at a file that is not there yet.
    try:
        from . import lifecycle, overlay
        notes += lifecycle.run()
        b = overlay.build_canon()
        if b["over_budget"]:
            notes.append("warning: the rulebook is %d lines, over the %d-line budget" % (b["lines"], overlay.MAX_LINES))
    except Exception as e:
        return 1, ["install refused, the personal data could not be prepared (%r); nothing was wired" % e]
    m = _mload()
    try:
        for p, old, new, note in steps:
            _backup(m, p, old)
            if old is None:
                with open(p, "wb") as f:
                    f.write(new)
            else:
                _write(p, new)
            notes.append(note)
        for key in ("codex", "opencode"):
            if os.path.isdir(L[key + "_dir"]):
                _link(m, L[key], core(), notes, key)
            else:
                notes.append("%s: %s not found; skipped" % (key, L[key + "_dir"]))
        notes.append("muse: not wired (global instruction path unconfirmed)")
        sk = os.path.join(paths.product_root(), "canon", "skills")
        for name in sorted(os.listdir(sk)) if os.path.isdir(sk) else []:
            if os.path.isdir(os.path.join(sk, name)):
                _link(m, os.path.join(L["skills"], name), os.path.join(sk, name), notes, "skills")
        _link(m, L["bin"], paths.launcher(), notes, "cli")
        _msave(m)
    except Exception as e:  # undo what was done so far
        _msave(m)
        uninstall()
        return 1, notes + ["install failed (%r) and was rolled back" % e]
    return 0, notes


def uninstall():
    L, notes = loc(), []
    m = _mload()
    # CLAUDE.md
    p = L["claude_md"]
    data = _read(p)
    if data is not None and BLOCK_RE.search(data):
        new = remove_import(data)
        if not new and m["files"].get(p, {}).get("backup") is None and p in m["files"]:
            os.unlink(p)
        else:
            _write(p, new)
        notes.append("claude-code: import line removed")
    # settings.json
    p = L["settings"]
    data = _read(p)
    ent = m["files"].get(p)
    if data is not None:
        try:
            obj, ind, nl = _parse_settings(data)
            before = copy.deepcopy(obj)
            if remove_hooks(obj):
                if ent is not None and ent["backup"] is None and not obj:
                    os.unlink(p)
                else:
                    orig = _read(os.path.join(_idir(), "backups", ent["backup"])) if ent and ent["backup"] else None
                    try:
                        back = _parse_settings(orig)[0] if orig is not None else None
                    except ValueError:
                        back = None
                    if back is not None:
                        t = copy.deepcopy(back)
                        add_hooks(t)
                    if back is not None and t == before:
                        _write(p, orig)  # current file is original + our entries: restore exact bytes
                    else:
                        _write(p, _dump(obj, ind, nl))
                notes.append("claude-code: hooks removed")
        except (ValueError, UnicodeDecodeError) as e:
            notes.append("claude-code: settings.json not touched (%s)" % e)
    # symlinks
    cand = [L["codex"], L["opencode"], L["bin"]]
    if os.path.isdir(L["skills"]):
        cand += [os.path.join(L["skills"], n) for n in sorted(os.listdir(L["skills"]))]
    for p in cand:
        if _ours(p):
            os.unlink(p)
            notes.append("removed link %s" % p)
    for d in reversed(m["dirs"]):
        try:
            os.rmdir(d)
        except OSError:
            pass
    try:
        os.unlink(_mpath())
    except OSError:
        pass
    return 0, notes


# ---- doctor ----------------------------------------------------------------
def doctor():
    L = loc()
    rows = []
    cm, st = _read(L["claude_md"]), _read(L["settings"])
    try:
        hw = _hooks_wired(_parse_settings(st)[0]) if st is not None else {"tick": False, "gate": False, "subagent": False}
    except (ValueError, UnicodeDecodeError):
        hw = {"tick": False, "gate": False, "subagent": False}
    missing = [n for n, ok in (("import line", _claude_md_wired(cm)), ("tick hook", hw["tick"]),
                               ("gate hook", hw["gate"]), ("subagent hook", hw["subagent"])) if not ok]
    rows.append({"tool": "claude-code", "status": "not wired" if missing else "wired",
                 "detail": ("missing: " + ", ".join(missing)) if missing else "import + tick + gate registered",
                 "blocking_hook": "yes (Stop)" if hw["gate"] else "no"})
    for key, name, hook in (("codex", "codex", "no (documented, not built)"),
                            ("opencode", "opencode", "no (none verified)")):
        p = L[key]
        if os.path.islink(p) and os.readlink(p) == core():
            st_, det = "wired", "%s -> the generated rulebook" % p
        elif os.path.islink(p) and os.readlink(p) in _old_cores():
            st_, det = "not wired", "%s -> the product's canon/core.md (old wiring; run `sisi install`)" % p
        elif os.path.lexists(p):
            st_, det = "not wired", "%s exists and is not ours (left alone)" % p
        else:
            st_, det = "not wired", "no %s" % p
        rows.append({"tool": name, "status": st_, "detail": det, "blocking_hook": hook})
    rows.append({"tool": "muse", "status": "not wired",
                 "detail": "global instruction path unconfirmed (binary mentions ~/.claude/CLAUDE.md and ~/.codex/AGENTS.md as foreign context; unverified)",
                 "blocking_hook": "unknown"})
    sk = paths.canon("skills")
    names = [n for n in sorted(os.listdir(sk)) if os.path.isdir(os.path.join(sk, n))] if os.path.isdir(sk) else []
    bad = [n for n in names if not (_ours(os.path.join(L["skills"], n)))]
    rows.append({"tool": "skills", "status": "not wired" if bad else "wired",
                 "detail": ("not linked: " + ", ".join(bad)) if bad else "%d skill(s) linked" % len(names), "blocking_hook": "-"})
    ok = os.path.islink(L["bin"]) and os.readlink(L["bin"]) == paths.launcher()
    rows.append({"tool": "cli", "status": "wired" if ok else "not wired", "detail": L["bin"], "blocking_hook": "-"})
    from . import lifecycle, overlay, pdata
    from . import release
    live = release.live_text()
    rows.append({"tool": "product", "status": "ok" if os.path.isfile(os.path.join(paths.product_root(), "canon", "core.md")) else "broken",
                 "detail": "live copy: " + live + (" (read-only at run time)" if not release.current_name() else ""),
                 "blocking_hook": "-"})
    todo = lifecycle.pending()
    rows.append({"tool": "personal", "status": "ok" if pdata.exists() and not todo else "not ready",
                 "detail": "%s (format %d)%s" % (paths.data(), pdata.version(),
                                                  "; run `sisi migrate`: still to move: " + ", ".join(todo) if todo else ""),
                 "blocking_hook": "-"})
    gen = paths.generated()
    cur = os.path.isfile(gen) and not overlay.is_stale()
    rows.append({"tool": "rulebook", "status": "current" if cur else ("stale" if os.path.isfile(gen) else "missing"),
                 "detail": gen + ("" if cur else "; run `sisi build-canon`"), "blocking_hook": "-"})
    return rows


def quick_problem():
    """Cheap check for tick. Returns a short string or None."""
    L = loc()
    refs = any(os.path.islink(L[k]) and os.readlink(L[k]) == core() for k in ("codex", "opencode"))
    refs = refs or _claude_md_wired(_read(L["claude_md"]))  # only complain about a rulebook something points at
    if refs and not os.path.isfile(core()):
        return "the generated rulebook is missing at %s (run `sisi build-canon`)" % core()
    if refs:
        from . import overlay
        if overlay.is_stale():
            return "the generated rulebook is out of date (run `sisi build-canon`)"
    for k in ("codex", "opencode"):
        if os.path.islink(L[k]) and os.readlink(L[k]).startswith((paths.REPO, paths.data())) and not os.path.exists(L[k]):
            return "%s link is dangling" % k
    if os.path.isdir(L["claude_dir"]):
        r = doctor_claude()
        if r:
            return "claude-code wiring is incomplete (%s)" % r
    return None


def doctor_claude():
    L = loc()
    cm, st = _read(L["claude_md"]), _read(L["settings"])
    try:
        hw = _hooks_wired(_parse_settings(st)[0]) if st is not None else {"tick": False, "gate": False, "subagent": False}
    except (ValueError, UnicodeDecodeError):
        hw = {"tick": False, "gate": False, "subagent": False}
    missing = [n for n, ok in (("import line", _claude_md_wired(cm)), ("tick hook", hw["tick"]),
                               ("gate hook", hw["gate"]), ("subagent hook", hw["subagent"])) if not ok]
    return ", ".join(missing)


def live_wired():
    """Are the CLI link and the Claude Code hooks pointing at the launcher the tools should use now?"""
    L = loc()
    if not (os.path.islink(L["bin"]) and os.readlink(L["bin"]) == paths.launcher()):
        return False
    st = _read(L["settings"])
    try:
        hw = _hooks_wired(_parse_settings(st)[0]) if st is not None else None
    except (ValueError, UnicodeDecodeError):
        return False
    return hw is None or all(hw.values())
