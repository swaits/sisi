"""install / uninstall / doctor. Wiring by reference (import line, symlink, hook entry); never copies canon text.
The tools load the generated rulebook in the personal data folder (base rules with the overlay applied), not the
product's canon/core.md. Every modified file is backed up into <personal>/install/ first; uninstall restores it exactly."""
import copy, hashlib, json, os, re, stat as _stat

from . import hookjson, paths, store

BEGIN, BEGIN_NONL, END = b"<!-- sisi:begin -->", b"<!-- sisi:begin nonl -->", b"<!-- sisi:end -->"
BLOCK_RE = re.compile(rb"^<!-- sisi:begin( nonl)? -->\n(@[^\n]*)\n<!-- sisi:end -->\n", re.M)


# ---- locations -------------------------------------------------------------
def xdg_config():
    """The XDG config base. A SISI_HOME test override wins, as it does for XDG_DATA_HOME in paths.data()."""
    if os.environ.get("SISI_HOME"):
        return os.path.join(paths.home(), ".config")
    x = os.environ.get("XDG_CONFIG_HOME")
    return x if x and os.path.isabs(x) else os.path.join(paths.home(), ".config")


def _opencode_dir():
    return os.environ.get("OPENCODE_CONFIG_DIR") or os.path.join(xdg_config(), "opencode")


def loc():
    h = paths.home()
    codex_dir = os.environ.get("CODEX_HOME") or os.path.join(h, ".codex")
    opencode_dir = _opencode_dir()
    return {
        "claude_dir": os.path.join(h, ".claude"),
        "claude_md": os.path.join(h, ".claude", "CLAUDE.md"),
        "settings": os.path.join(h, ".claude", "settings.json"),
        "codex_dir": codex_dir,
        "codex": os.path.join(codex_dir, "AGENTS.md"),
        "opencode_dir": opencode_dir,
        "opencode": os.path.join(opencode_dir, "AGENTS.md"),
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


def _dangling(p):
    return os.path.islink(p) and not os.path.exists(p)


def _read_file(p):
    """(bytes, None) on success, (None, None) when missing, (None, reason) when present but untouchable.

    Telling these apart matters: a dangling symlink or an unreadable file must be refused and left
    alone, never treated as an absent file that install may create through."""
    if _dangling(p):
        return None, "%s is a dangling symlink (to %s)" % (p, os.readlink(p))
    if not os.path.lexists(p):
        return None, None
    if os.path.isdir(p):
        return None, "%s is a directory" % p
    try:
        with open(p, "rb") as f:
            return f.read(), None
    except OSError as e:
        return None, "%s cannot be read (%s)" % (p, e.strerror or e)


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


def _source_mode(p):
    try:
        return _stat.S_IMODE(os.stat(p).st_mode) & 0o777 or 0o600
    except OSError:
        return 0o600


def _backups_dir():
    """Backup folder, owner-only: backups of settings files may hold API keys."""
    d = os.path.join(_idir(), "backups")
    os.makedirs(d, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def _harden_backup(name, p):
    bp = os.path.join(_idir(), "backups", name)
    try:
        os.chmod(bp, _source_mode(p))
    except OSError:
        pass


def _backup(m, p, data):
    """Remember the original state of p before first modification in this install round.

    Backup names are content-addressed, so a later round whose original changed gets a fresh backup
    instead of silently reusing a stale one; within a round the first backup wins. A backup file gets
    the source file's mode (never wider), in a 0700 folder."""
    existing = m["files"].get(p)
    if existing is not None:
        if existing.get("backup"):
            _harden_backup(existing["backup"], p)
        return
    name = None
    if data is not None:
        name = "%s-%s-%s.orig" % (_sha(p.encode())[:8], _sha(data)[:12], os.path.basename(p))
        bp = os.path.join(_backups_dir(), name)
        mode = _source_mode(p)
        try:
            fd = os.open(bp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        except FileExistsError:
            try:
                os.chmod(bp, mode)
            except OSError:
                pass
        else:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            try:
                os.chmod(bp, mode)
            except OSError:
                pass
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
HOOK_MATCHERS = {}  # no matcher: the tool hooks run for every tool (the orchestration meter counts all of them)


def hook_cmds():
    gate_to = int(store.config()["gate"].get("budget_s", 120)) + 30
    watch = hookjson.fail_open_command(paths.launcher(), "watch", "claude-code")
    return {"SessionStart": (hookjson.fail_open_command(paths.launcher(), "tick", "claude-code"), 10),
            "UserPromptSubmit": (hookjson.fail_open_command(paths.launcher(), "prompt", "claude-code"), 10),
            "Stop": (hookjson.fail_open_command(paths.launcher(), "gate", "claude-code"), gate_to),
            "SubagentStop": (hookjson.fail_open_command(paths.launcher(), "gate", "claude-code", True), 30),
            "PreToolUse": (watch, 60),
            "PostToolUse": (watch, 60),
            "PostToolUseFailure": (watch, 60)}


def _claude_spec():
    return {ev: dict({"cmd": cmd, "timeout": to, "sub": hookjson.sisi_invocation(cmd)[1]},
                     **({"matcher": HOOK_MATCHERS[ev]} if ev in HOOK_MATCHERS else {}))
            for ev, (cmd, to) in hook_cmds().items()}


def _is_ours(h, sub):
    return (isinstance(h, dict) and h.get("type") == "command"
            and hookjson.is_ours_command(h.get("command"), sub))


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
        sub = hookjson.sisi_invocation(cmd)[1]
        groups = hooks.get(ev)
        if groups is None:
            groups = hooks[ev] = []
            changed = True
        if not isinstance(groups, list):
            raise ValueError("settings.json hooks.%s is not a list" % ev)
        found, kept = False, []
        for g in groups:
            hs = g.get("hooks") if isinstance(g, dict) else None
            if not isinstance(hs, list):
                kept.append(g)
                continue
            rest = []
            for h in hs:
                if _is_ours(h, sub):
                    if found:
                        changed = True  # a second registration would run the hook twice; keep exactly one
                        continue
                    found = True
                    if h.get("command") != cmd:
                        h["command"] = cmd
                        changed = True
                    if h.get("timeout") != to:
                        h["timeout"] = to
                        changed = True
                rest.append(h)
            if rest or not hs:
                kept.append(dict(g, hooks=rest) if rest != hs else g)
            else:
                changed = True
        hooks[ev] = kept
        if not found:
            group = {"hooks": [{"type": "command", "command": cmd, "timeout": to}]}
            if ev in HOOK_MATCHERS:
                group = {"matcher": HOOK_MATCHERS[ev], "hooks": group["hooks"]}
            kept.append(group)
            changed = True
    return changed


def _hooks_wired(obj):
    hooks = obj.get("hooks") if isinstance(obj, dict) else None
    out = {}
    for ev, sub, name in (("SessionStart", "tick", "tick"), ("UserPromptSubmit", "prompt", "prompt"),
                          ("Stop", "gate", "gate"), ("SubagentStop", "gate", "subagent"),
                          ("PreToolUse", "watch", "pre"), ("PostToolUse", "watch", "post"),
                          ("PostToolUseFailure", "watch", "postfail")):
        groups = hooks.get(ev) if isinstance(hooks, dict) else None
        sub, key = sub, name
        out[key] = False
        for g in groups if isinstance(groups, list) else []:
            if ev in ("PreToolUse", "PostToolUse", "PostToolUseFailure") and isinstance(g, dict) \
                    and g.get("matcher") not in (None, "", "*"):
                continue  # a hook limited to some tools (the shell only, in an older install) does not meter the rest
            for h in g.get("hooks", []) if isinstance(g, dict) and isinstance(g.get("hooks"), list) else []:
                inv = hookjson.sisi_invocation(h.get("command")) if isinstance(h, dict) else None
                if _is_ours(h, sub) and inv and inv[0] == paths.launcher():
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
    return False


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
    """Can we read and create-or-replace the file p (following symlinks)? Returns an error string or None.

    An existing file must itself be writable, not just its folder: an atomic replace would otherwise
    silently overwrite a file the user made read-only."""
    if _dangling(p):
        return "%s is a dangling symlink (to %s)" % (p, os.readlink(p))
    if os.path.isdir(p):
        return "%s is a directory" % p
    real = os.path.realpath(p)
    if os.path.exists(real):
        if not os.access(real, os.R_OK):
            return "%s cannot be read" % p
        ok = os.access(real, os.W_OK) and os.access(os.path.dirname(real), os.W_OK)
    else:
        d = os.path.dirname(real)
        while d and not os.path.isdir(d):
            d = os.path.dirname(d)
        ok = os.access(d, os.W_OK)
    return None if ok else "%s is not writable" % p


def _link_writable(p, target):
    """Would creating or replacing the symlink p be possible? None when no write is needed or possible."""
    if os.path.islink(p) and os.readlink(p) == target:
        return None
    if os.path.lexists(p) and not (os.path.islink(p) and _ours(p)):
        return None  # a user file or foreign symlink: _link leaves it alone
    d = os.path.dirname(p)
    while d and not os.path.isdir(d):
        d = os.path.dirname(d)
    return None if os.access(d, os.W_OK) else "%s is not writable" % d


def _link_plan_lines(p, target, label):
    if os.path.islink(p):
        cur = os.readlink(p)
        if cur == target:
            return []
        if not _ours(p):
            return ["%s: skip %s (symlink to %s; not touched)" % (label, p, cur)]
        return ["%s: replace link %s -> %s" % (label, p, target)]
    if os.path.lexists(p):
        return ["%s: skip %s (exists and is not a symlink; not touched)" % (label, p)]
    return ["%s: create link %s -> %s" % (label, p, target)]


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
            if data is None or not data.strip():
                obj, ind, nl = _parse_settings(data if data is not None else b"")
                if add_hooks(obj):
                    steps.append((p, data, _dump(obj, ind, nl if data is not None else True),
                                  "claude-code: hooks registered in %s" % p))
            else:
                new = hookjson.add_nested(data.decode("utf-8"), _claude_spec()).encode("utf-8")
                if new != data:
                    steps.append((p, data, new, "claude-code: hooks registered in %s" % p))
        except ValueError as ex:
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
    from . import adapters
    prefailed = adapters.preflight_all()  # every adapter target checked before the first one is touched
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
            if os.path.isdir(L[key + "_dir"]) and key not in prefailed:
                _link(m, L[key], core(), notes, key)
            # absence (and any preflight refusal) is reported once, by the tool's adapter below
        adapters.wire_all(m, notes, prefailed)
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


def install_dry_run():
    """Exactly what install would create, edit (with diffs) or skip — changing nothing at all.
    Nothing is prepared either: no personal folder, no generated rulebook, no manifest."""
    from . import adapters
    L = loc()
    notes = ["dry-run: nothing will be changed"]
    rc = 0
    if os.path.isdir(L["claude_dir"]):
        steps, errs = _plan_claude(L)
        if errs:
            rc = 1
            notes += ["claude-code: install would be refused: " + e for e in errs]
        else:
            ops = [{"kind": "create" if old is None else "edit", "path": p, "old": old, "new": new}
                   for p, old, new, _note in steps]
            notes += adapters.format_ops("claude-code", ops)
    else:
        notes.append("claude-code: %s not found; skipped" % L["claude_dir"])
    prefailed = adapters.preflight_all()
    for key in ("codex", "opencode"):
        if os.path.isdir(L[key + "_dir"]) and key not in prefailed:
            notes += _link_plan_lines(L[key], core(), key)
    notes += adapters.dry_run_lines()
    sk = os.path.join(paths.product_root(), "canon", "skills")
    for name in sorted(os.listdir(sk)) if os.path.isdir(sk) else []:
        if os.path.isdir(os.path.join(sk, name)):
            notes += _link_plan_lines(os.path.join(L["skills"], name), os.path.join(sk, name), "skills")
    notes += _link_plan_lines(L["bin"], paths.launcher(), "cli")
    notes.append("dry-run: no files were changed")
    return rc, notes


def uninstall():
    L, notes = loc(), []
    m = _mload()
    # CLAUDE.md
    p = L["claude_md"]
    data = _read(p)
    if _dangling(p):
        notes.append("claude-code: %s is a dangling symlink; not touched" % p)
        data = None
    if data is not None and BLOCK_RE.search(data):
        new = remove_import(data)
        if not new and m["files"].get(p, {}).get("backup") is None and p in m["files"] and not os.path.islink(p):
            os.unlink(p)
        else:
            _write(p, new)
        notes.append("claude-code: import line removed")
    # settings.json
    p = L["settings"]
    data, read_err = _read_file(p)
    ent = m["files"].get(p)
    if read_err:
        notes.append("claude-code: settings.json not touched (%s)" % read_err)
    elif data is not None:
        try:
            text = data.decode("utf-8")
            subs = {"SessionStart": "tick", "UserPromptSubmit": "prompt", "Stop": "gate", "SubagentStop": "gate",
                    "PreToolUse": "watch", "PostToolUse": "watch", "PostToolUseFailure": "watch"}
            orig = _read(os.path.join(_idir(), "backups", ent["backup"])) if ent and ent["backup"] else None
            drop_hooks, _dv = hookjson.backup_drop_flags(
                orig.decode("utf-8") if orig is not None else None, None) if orig is not None else (True, False)
            removed = hookjson.remove_nested(text, subs, drop_empty_hooks=drop_hooks)
            if removed != text:
                root = hookjson.parse(removed) if removed.strip() else None
                empty_root = root is not None and root.kind == "obj" and not root.members
                if ent is not None and ent["backup"] is None and empty_root and not os.path.islink(p):
                    os.unlink(p)
                else:
                    restored = False
                    if orig is not None:
                        try:
                            restored = hookjson.add_nested(orig.decode("utf-8"), _claude_spec()) == text
                        except ValueError:
                            restored = False
                    # unedited since install: restore exact bytes; edited: only our spans were removed above
                    _write(p, orig if restored else removed.encode("utf-8"))
                notes.append("claude-code: hooks removed")
        except ValueError as e:
            notes.append("claude-code: settings.json not touched (%s)" % e)
    from . import adapters
    adapters.unwire_all(m, notes)
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
        hw = _hooks_wired(_parse_settings(st)[0]) if st is not None else {"tick": False, "gate": False, "subagent": False, "pre": False, "post": False}
    except (ValueError, UnicodeDecodeError):
        hw = {"tick": False, "gate": False, "subagent": False, "pre": False, "post": False}
    missing = [n for n, ok in (("import line", _claude_md_wired(cm)), ("tick hook", hw["tick"]),
                               ("prompt hook", hw.get("prompt", False)),
                               ("gate hook", hw["gate"]), ("subagent hook", hw["subagent"]),
                               ("watch-before hook (all tools)", hw["pre"]), ("watch-after hook (all tools)", hw["post"]),
                               ("watch-failure hook", hw.get("postfail", False))) if not ok]
    rows.append({"tool": "claude-code", "status": "not wired" if missing else "wired",
                 "detail": ("missing: " + ", ".join(missing)) if missing else "import + tick + prompt + gate registered",
                 "blocking_hook": "yes (Stop)" if hw["gate"] else "no",
                 "rulebook": not missing and _claude_md_wired(cm), "tick": hw["tick"],
                 "enforcement": "blocks", "action": None})
    from . import adapters
    tool_rows = []
    for a in adapters.ADAPTERS:
        st = a.status()
        if a.name not in ("codex", "opencode", "muse") and not st["detected"]:
            continue  # a tool this user does not have gets no row; codex/opencode keep their historic rows
        enf = st["enforcement"]
        blocking = ("blocks (%s)" % st["via"] if enf == "blocks" else
                    "sends a follow-up (%s)" % st["via"] if enf == "sends a follow-up" else enf)
        tool_rows.append({"tool": st["tool"], "status": "wired" if st["wired"] else "not wired",
                          "detail": st["detail"], "blocking_hook": blocking, "rulebook": st["rulebook"],
                          "tick": st["tick"], "enforcement": enf, "action": st["action"]})
    rows += tool_rows
    anti = adapters.antigravity_status()
    if anti["detected"]:
        rows.append({"tool": "antigravity", "status": "not wired", "detail": anti["detail"],
                     "blocking_hook": "unknown", "rulebook": anti["rulebook"], "tick": False,
                     "enforcement": "unknown", "action": None})
    _providers = {"claude-code", "codex", "opencode", "cursor", "pi", "muse", "gemini", "copilot", "qwen", "grok"}
    wired_names = [n for n in ([r["tool"] for r in tool_rows if r["status"] == "wired"]
                   + (["claude-code"] if rows[0]["status"] == "wired" else [])) if n in _providers]
    providers = ", ".join(sorted(set(wired_names))) or "none wired yet"
    for host in ("t3-code", "orca"):
        rows.append({"tool": host, "status": "ok",
                     "detail": "host app with no instructions or hooks of its own; covered through the providers it runs (wired: %s)" % providers,
                     "blocking_hook": "via provider", "rulebook": bool(wired_names), "tick": False,
                     "enforcement": "via provider", "action": None})
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
                                                  "; run `sisi update`: still to move: " + ", ".join(todo) if todo else ""),
                 "blocking_hook": "-"})
    gen = paths.generated()
    cur = os.path.isfile(gen) and not overlay.is_stale()
    rows.append({"tool": "rulebook", "status": "current" if cur else ("stale" if os.path.isfile(gen) else "missing"),
                 "detail": gen + ("" if cur else "; run `sisi update` to rebuild"), "blocking_hook": "-"})
    return rows


def quick_problem():
    """Cheap check for tick. Returns a short string or None."""
    L = loc()
    from . import adapters
    links = [(k, L[k]) for k in ("codex", "opencode")] + adapters.rulebook_links()
    refs = any(os.path.islink(p) and os.readlink(p) == core() for _, p in links)
    refs = refs or _claude_md_wired(_read(L["claude_md"]))  # only complain about a rulebook something points at
    if refs and not os.path.isfile(core()):
        return "the generated rulebook is missing at %s (run `sisi update` to rebuild)" % core()
    if refs:
        from . import overlay
        if overlay.is_stale():
            return "the generated rulebook is out of date (run `sisi update` to rebuild)"
    for k, p in links:
        if os.path.islink(p) and os.readlink(p).startswith((paths.REPO, paths.data())) and not os.path.exists(p):
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
        hw = _hooks_wired(_parse_settings(st)[0]) if st is not None else {"tick": False, "gate": False, "subagent": False, "pre": False, "post": False}
    except (ValueError, UnicodeDecodeError):
        hw = {"tick": False, "gate": False, "subagent": False, "pre": False, "post": False}
    missing = [n for n, ok in (("import line", _claude_md_wired(cm)), ("tick hook", hw["tick"]),
                               ("prompt hook", hw.get("prompt", False)),
                               ("gate hook", hw["gate"]), ("subagent hook", hw["subagent"]),
                               ("watch-before hook (all tools)", hw["pre"]), ("watch-after hook (all tools)", hw["post"]),
                               ("watch-failure hook", hw.get("postfail", False))) if not ok]
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
