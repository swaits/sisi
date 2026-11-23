"""One adapter per tool beyond Claude Code: detect, plan, wire, unwire, status.

Every edit goes through wiring's backup and atomic-write helpers. JSON configs are edited textually
(sisi/hookjson.py) so a user's other bytes — spellings, duplicate keys, formatting — are never
re-serialised away; a file that cannot be edited with certainty is skipped, never rewritten. A tool
whose config folder does not exist is skipped and reported, never an error. Only mechanisms confirmed
from the tool's own documentation, `--help`, installed files or a local spike are wired here (see
docs/harnesses.md); anything unconfirmed is reported in doctor, not guessed into a config.
"""
import difflib, hashlib, json, os

from . import hookjson, paths, store, wiring


# ---- shared helpers ---------------------------------------------------------
def _h(*a):
    return os.path.join(paths.home(), *a)


def _env_dir(var, *parts):
    """A tool's own documented home override (CODEX_HOME and friends): the tool looks there, so sisi must too."""
    return os.environ.get(var) or _h(*parts)


def _xdg(*parts):
    return os.path.join(wiring.xdg_config(), *parts)


def _cmd(sub, tool, subagent=False):
    return hookjson.fail_open_command(paths.launcher(), sub, tool, subagent)


def _gate_timeout():
    return int(store.config()["gate"].get("budget_s", 120)) + 30


def _ours_cmd(cmd, sub):
    return isinstance(cmd, str) and wiring._is_ours({"type": "command", "command": cmd}, sub)


def _launcher_ok(cmd):
    inv = hookjson.sisi_invocation(cmd)
    return bool(inv) and inv[0] == paths.launcher()


def _load_obj(p):
    data = wiring._read(p)
    if data is None:
        return None
    try:
        return wiring._parse_settings(data)[0]
    except (ValueError, UnicodeDecodeError):
        return None


def _link_ok(p):
    return os.path.islink(p) and os.readlink(p) == wiring.core()


def _link_detail(p):
    if _link_ok(p):
        return "%s -> the generated rulebook" % p
    if os.path.islink(p) and os.readlink(p) in wiring._old_cores():
        return "%s -> the product's canon/core.md (old wiring; run `sisi install`)" % p
    if os.path.lexists(p):
        return "%s exists and is not ours (left alone)" % p
    return "no %s" % p


def _write_new_or_through(p, data, new):
    if data is None:
        with open(p, "wb") as f:
            f.write(new)
    else:
        wiring._write(p, new)


# ---- nested hook groups (Codex hooks.json, Gemini/Qwen settings.json) -------
def add_nested(obj, spec):
    changed = False
    hooks = obj.get("hooks")
    if hooks is None:
        hooks = obj["hooks"] = {}
        changed = True
    if not isinstance(hooks, dict):
        raise ValueError("'hooks' is not an object")
    for ev, s in spec.items():
        groups = hooks.get(ev)
        if groups is None:
            groups = hooks[ev] = []
            changed = True
        if not isinstance(groups, list):
            raise ValueError("hooks.%s is not a list" % ev)
        found, kept = False, []
        for g in groups:
            hs = g.get("hooks") if isinstance(g, dict) else None
            if not isinstance(hs, list):
                kept.append(g)
                continue
            rest = []
            for hh in hs:
                if _ours_cmd(hh.get("command") if isinstance(hh, dict) else None, s["sub"]):
                    if found:
                        changed = True  # keep exactly one registration per event
                        continue
                    found = True
                    want = {"type": "command", "command": s["cmd"], "timeout": s["timeout"]}
                    if s.get("name"):
                        want["name"] = s["name"]
                    for k, v in want.items():
                        if hh.get(k) != v:
                            hh[k] = v
                            changed = True
                rest.append(hh)
            if rest or not hs:
                kept.append(dict(g, hooks=rest) if rest != hs else g)
            else:
                changed = True
        hooks[ev] = kept
        if not found:
            entry = {"type": "command", "command": s["cmd"], "timeout": s["timeout"]}
            if s.get("name"):
                entry["name"] = s["name"]
            group = {"matcher": s["matcher"], "hooks": [entry]} if s.get("matcher") else {"hooks": [entry]}
            kept.append(group)
            changed = True
    return changed


def remove_nested(obj, subs):
    changed = False
    hooks = obj.get("hooks")
    if not isinstance(hooks, dict):
        return False
    for ev, sub in subs.items():
        groups = hooks.get(ev)
        if not isinstance(groups, list):
            continue
        keep, ev_changed = [], False
        for g in groups:
            hs = g.get("hooks") if isinstance(g, dict) else None
            if isinstance(hs, list) and any(_ours_cmd(h.get("command") if isinstance(h, dict) else None, sub) for h in hs):
                changed = ev_changed = True
                rest = [h for h in hs if not _ours_cmd(h.get("command") if isinstance(h, dict) else None, sub)]
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


def nested_wired(obj, spec):
    hooks = obj.get("hooks") if isinstance(obj, dict) else None
    out = {}
    for ev, s in spec.items():
        ok = False
        groups = hooks.get(ev) if isinstance(hooks, dict) else None
        for g in groups if isinstance(groups, list) else []:
            for hh in g.get("hooks", []) if isinstance(g, dict) and isinstance(g.get("hooks"), list) else []:
                if isinstance(hh, dict) and _ours_cmd(hh.get("command"), s["sub"]) and _launcher_ok(hh["command"]):
                    ok = True
        out[ev] = ok
    return out


# ---- flat hook lists (Cursor hooks.json, Copilot hooks/*.json) ----------------
def _flat_cmd(entry):
    if not isinstance(entry, dict):
        return None
    return entry.get("bash") if isinstance(entry.get("bash"), str) else entry.get("command")


def add_flat(obj, spec, make_entry):
    changed = False
    hooks = obj.get("hooks")
    if hooks is None:
        hooks = obj["hooks"] = {}
        changed = True
    if not isinstance(hooks, dict):
        raise ValueError("'hooks' is not an object")
    for ev, s in spec.items():
        entries = hooks.get(ev)
        if entries is None:
            entries = hooks[ev] = []
            changed = True
        if not isinstance(entries, list):
            raise ValueError("hooks.%s is not a list" % ev)
        found, kept = False, []
        for e in entries:
            if _ours_cmd(_flat_cmd(e), s["sub"]):
                if found:
                    changed = True  # keep exactly one registration per event
                    continue
                found = True
                want = make_entry(s)
                for k, v in want.items():
                    if e.get(k) != v:
                        e[k] = v
                        changed = True
            kept.append(e)
        hooks[ev] = kept
        if not found:
            kept.append(make_entry(s))
            changed = True
    return changed


def remove_flat(obj, subs):
    changed = False
    hooks = obj.get("hooks")
    if not isinstance(hooks, dict):
        return False
    for ev, sub in subs.items():
        entries = hooks.get(ev)
        if not isinstance(entries, list):
            continue
        keep = [e for e in entries if not _ours_cmd(_flat_cmd(e), sub)]
        if len(keep) != len(entries):
            changed = True
            if keep:
                hooks[ev] = keep
            else:
                del hooks[ev]
    if changed and not hooks:
        del obj["hooks"]
    return changed


def flat_wired(obj, spec):
    hooks = obj.get("hooks") if isinstance(obj, dict) else None
    out = {}
    for ev, s in spec.items():
        entries = hooks.get(ev) if isinstance(hooks, dict) else None
        out[ev] = any(_ours_cmd(_flat_cmd(e), s["sub"]) and _launcher_ok(_flat_cmd(e))
                      for e in entries if isinstance(entries, list)) if isinstance(entries, list) else False
    return out


# ---- merging one JSON file, textually, with backup and exact restore ----------
def _flat_hookjson_spec(spec, make_entry):
    return {ev: {"sub": s["sub"], "entry": make_entry(s)} for ev, s in spec.items()}


def _merged_bytes(data, kind, spec, make_entry=None, created_version=None):
    """The bytes a merge would write. Existing files are edited textually (span surgery); only a
    missing or empty file is built structurally, since it holds no user formatting to preserve."""
    if data is None or not data.strip():
        obj = {}
        if kind == "nested":
            add_nested(obj, spec)
        else:
            add_flat(obj, spec, make_entry)
        if created_version is not None and "version" not in obj:
            obj = dict({"version": created_version}, **obj)
        return wiring._dump(obj, "  ", True)
    text = data.decode("utf-8")
    if kind == "nested":
        return hookjson.add_nested(text, spec, created_version).encode("utf-8")
    return hookjson.add_flat(text, _flat_hookjson_spec(spec, make_entry), created_version).encode("utf-8")


def _removed_bytes(data, kind, subs, created_version, drop_version, drop_empty_hooks):
    text = data.decode("utf-8")
    fn = hookjson.remove_nested if kind == "nested" else hookjson.remove_flat
    return fn(text, subs, created_version, drop_version, drop_empty_hooks).encode("utf-8")


def merge_json(m, p, kind, spec, notes, label, created_version=None, make_entry=None):
    data, err = wiring._read_file(p)
    if err:
        raise ValueError(err)
    new = _merged_bytes(data, kind, spec, make_entry, created_version)
    if new != data:
        wiring._backup(m, p, data)
        wiring._mkdirs(m, os.path.dirname(p))
        _write_new_or_through(p, data, new)
        notes.append("%s: hooks registered in %s" % (label, p))


def unmerge_json(m, p, kind, subs, spec, notes, label, created_version=None, make_entry=None):
    data, err = wiring._read_file(p)
    if err:
        notes.append("%s: %s not touched (%s)" % (label, p, err))
        return
    if data is None:
        return
    ent = m["files"].get(p)
    orig = wiring._read(os.path.join(wiring._idir(), "backups", ent["backup"])) if ent and ent["backup"] else None
    try:
        if orig is not None:
            drop_hooks, drop_version = hookjson.backup_drop_flags(
                orig.decode("utf-8") if orig.strip() else None, created_version)
        else:
            drop_hooks, drop_version = True, created_version is not None
        removed = _removed_bytes(data, kind, subs, created_version, drop_version, drop_hooks)
    except ValueError as e:
        notes.append("%s: %s not touched (%s)" % (label, p, e))
        return
    if removed == data:
        return
    empty_root = False
    try:
        root = hookjson.parse(removed.decode("utf-8")) if removed.strip() else None
        empty_root = root is not None and root.kind == "obj" and not root.members
    except ValueError:
        pass
    if ent is not None and ent["backup"] is None and empty_root and not os.path.islink(p):
        os.unlink(p)
    else:
        restored = False
        if orig is not None:
            try:
                restored = _merged_bytes(orig, kind, spec, make_entry, created_version) == data
            except ValueError:
                restored = False
        # unedited since install: restore exact bytes; edited: only sisi's spans were removed above
        wiring._write(p, orig if restored else removed)
    notes.append("%s: hooks removed from %s" % (label, p))


def plan_merge_ops(p, kind, spec, make_entry=None, created_version=None):
    data, err = wiring._read_file(p)
    if err:
        return [{"kind": "skip", "reason": err, "fatal": True}]
    try:
        new = _merged_bytes(data, kind, spec, make_entry, created_version)
    except ValueError as e:
        return [{"kind": "skip", "reason": "%s cannot be merged (%s); it would be skipped" % (p, e), "fatal": True}]
    if new == data:
        return []
    return [{"kind": "create" if data is None else "edit", "path": p, "old": data, "new": new}]


def _diff_text(path, old, new):
    old_lines = (old or b"").decode("utf-8", "replace").splitlines(True)
    new_lines = (new or b"").decode("utf-8", "replace").splitlines(True)
    return "".join(difflib.unified_diff(old_lines, new_lines, path + " (current)", path + " (after install)"))


def format_ops(label, ops):
    lines = []
    for op in ops:
        k = op["kind"]
        if k in ("create", "edit"):
            lines.append("%s: %s %s" % (label, k, op["path"]))
            diff = _diff_text(op["path"], op["old"], op["new"])
            lines.extend("  " + ln for ln in diff.splitlines())
        elif k == "link":
            lines.append("%s: link %s -> %s" % (label, op["path"], op["target"]))
        elif k == "skip":
            lines.append("%s: skip (%s)" % (label, op["reason"]))
        elif k == "note":
            lines.append("%s: %s" % (label, op["text"]))
    return lines or ["%s: no changes" % label]


# ---- generated code/text files (Pi extension, OpenCode plugin, pointers) ------
def _header_of(content):
    return content.split(b"\n", 1)[0].rstrip(b"\r")


GENERATED_MARKER = b"sisi:generated"


def _is_generated(data, content, p=None):
    """Ours when the first line is exactly the current header, or carries the stable
    `sisi:generated` marker in its first line (what earlier sisi versions wrote; their
    header wording differed), or the recorded install manifest's sha for this path
    matches the file's bytes. A marker anywhere else in the file proves nothing."""
    if data is None:
        return False
    if _header_of(data) == _header_of(content) or GENERATED_MARKER in _header_of(data):
        return True
    if p is not None:
        try:
            ent = wiring._mload().get("files", {}).get(p) or {}
            sha = ent.get("sha256")
            return bool(sha) and hashlib.sha256(data).hexdigest() == sha
        except Exception:
            return False
    return False


def generated_state(p, content):
    """current | stale | foreign | absent, for doctor: compared with what install would write now."""
    data, err = wiring._read_file(p)
    if err or data is None:
        return "absent"
    if not _is_generated(data, content, p):
        return "foreign"
    return "current" if data == content else "stale"


def _record_sha(m, p, content):
    ent = m["files"].get(p)
    if ent is not None:
        ent["sha256"] = hashlib.sha256(content).hexdigest()


def write_generated(m, p, content, notes, label):
    data, err = wiring._read_file(p)
    if err:
        notes.append("%s: %s; not touched" % (label, err))
        return False
    if data is not None and not _is_generated(data, content, p):
        notes.append("%s: %s exists and is not ours; not touched" % (label, p))
        return False
    if data == content:
        _record_sha(m, p, content)
        return True
    wiring._backup(m, p, data)
    _record_sha(m, p, content)
    wiring._mkdirs(m, os.path.dirname(p))
    _write_new_or_through(p, data, content)
    notes.append("%s: wrote %s" % (label, p))
    return True


def remove_generated(m, p, notes, label, content):
    data, err = wiring._read_file(p)
    if err:
        notes.append("%s: %s not touched (%s)" % (label, p, err))
        return
    if data is None or not _is_generated(data, content, p):
        return
    ent = m["files"].get(p)
    known = (ent.get("sha256") if ent else None) or hashlib.sha256(content).hexdigest()
    if hashlib.sha256(data).hexdigest() != known:
        notes.append("%s: %s was edited since install; left alone" % (label, p))
        return
    if ent is not None and ent["backup"]:
        orig = wiring._read(os.path.join(wiring._idir(), "backups", ent["backup"]))
        if orig is not None and not _is_generated(orig, content, p):
            wiring._write(p, orig)
            notes.append("%s: restored %s" % (label, p))
            return
        # a backup that is itself a sisi-generated file (an older version) is not restored:
        # uninstall removes the generated file rather than resurrecting the old one
    if os.path.islink(p):
        notes.append("%s: %s is a symlink; left alone" % (label, p))
        return
    os.unlink(p)
    notes.append("%s: removed %s" % (label, p))


def plan_generated_ops(p, content):
    data, err = wiring._read_file(p)
    if err:
        return [{"kind": "skip", "reason": err + "; not touched", "fatal": False}]
    if data is not None and not _is_generated(data, content, p):
        return [{"kind": "skip", "reason": "%s exists and is not ours; not touched" % p, "fatal": False}]
    if data == content:
        return []
    return [{"kind": "create" if data is None else "edit", "path": p, "old": data, "new": content}]


def plan_link_ops(p, target):
    if os.path.islink(p) and os.readlink(p) == target:
        return []
    if os.path.lexists(p) and not (os.path.islink(p) and wiring._ours(p)):
        return [{"kind": "skip", "reason": "%s exists and is not ours; not touched" % p, "fatal": False}]
    return [{"kind": "link", "path": p, "target": target}]


def unlink_ours(p, notes):
    if wiring._ours(p):
        os.unlink(p)
        notes.append("removed link %s" % p)


# ---- adapters -----------------------------------------------------------------
class Adapter:
    name = "?"
    enforcement = "none"  # blocks | sends a follow-up | none | unknown
    via = ""

    def detect(self):
        return False

    def skip_note(self):
        return "%s: not found; skipped" % self.name

    def plan_ops(self):
        return []

    def plan(self):
        out = []
        for op in self.plan_ops():
            if op["kind"] in ("create", "edit"):
                out.append("%s %s" % (op["kind"], op["path"]))
            elif op["kind"] == "link":
                out.append("link %s to %s" % (op["path"], op["target"]))
            elif op["kind"] == "skip":
                out.append("skip (%s)" % op["reason"])
            elif op["kind"] == "note":
                out.append(op["text"])
        return out

    def wire(self, m, notes):
        pass

    def unwire(self, m, notes):
        pass

    def status(self):
        return {"tool": self.name, "detected": self.detect(), "rulebook": False, "tick": False,
                "enforcement": self.enforcement, "via": self.via, "wired": False,
                "detail": "not wired", "action": None}



class Codex(Adapter):
    name, enforcement, via = "codex", "blocks", "Stop"
    TRUST = "open Codex, run /hooks, and trust the sisi hooks (Codex skips untrusted hooks; repeat after the hook commands change)"

    def dir(self):
        return wiring.loc()["codex_dir"]

    def hooks_file(self):
        return os.path.join(self.dir(), "hooks.json")

    def spec(self):
        return {
            "SessionStart": {"cmd": _cmd("tick", "codex"), "timeout": 10, "sub": "tick", "matcher": "startup|resume"},
            "UserPromptSubmit": {"cmd": _cmd("prompt", "codex"), "timeout": 10, "sub": "prompt"},
            "Stop": {"cmd": _cmd("gate", "codex"), "timeout": _gate_timeout(), "sub": "gate"},
            "SubagentStop": {"cmd": _cmd("gate", "codex", True), "timeout": 30, "sub": "gate"},
            "PreToolUse": {"cmd": _cmd("watch", "codex"), "timeout": 60, "sub": "watch"},
            "PostToolUse": {"cmd": _cmd("watch", "codex"), "timeout": 60, "sub": "watch"},
        }

    def detect(self):
        return os.path.isdir(self.dir())

    def skip_note(self):
        return "codex: %s not found; skipped" % self.dir()

    def plan_ops(self):
        return plan_merge_ops(self.hooks_file(), "nested", self.spec()) + (
            [{"kind": "note", "text": "then: " + self.TRUST}])

    def wire(self, m, notes):
        merge_json(m, self.hooks_file(), "nested", self.spec(), notes, "codex")
        notes.append("codex: one more step — %s" % self.TRUST)
        if self.shadowed():
            notes.append("codex: %s shadows AGENTS.md there, so the rulebook will not load until it is removed or merged"
                         % os.path.join(self.dir(), "AGENTS.override.md"))

    def unwire(self, m, notes):
        subs = {"SessionStart": "tick", "UserPromptSubmit": "prompt", "Stop": "gate", "SubagentStop": "gate",
                "PreToolUse": "watch", "PostToolUse": "watch"}
        unmerge_json(m, self.hooks_file(), "nested", subs, self.spec(), notes, "codex")

    def shadowed(self):
        return os.path.lexists(os.path.join(self.dir(), "AGENTS.override.md"))

    def status(self):
        st = Adapter.status(self)
        link = wiring.loc()["codex"]
        hw = nested_wired(_load_obj(self.hooks_file()) or {}, self.spec())
        rb = _link_ok(link)
        missing = [n for n, ok in (("rulebook link", rb), ("tick hook", hw["SessionStart"]),
                                   ("prompt hook", hw.get("UserPromptSubmit", False)),
                                   ("gate hook", hw["Stop"]), ("subagent hook", hw["SubagentStop"]),
                                   ("watch-before hook", hw.get("PreToolUse", False)), ("watch-after hook", hw.get("PostToolUse", False))) if not ok]
        if self.shadowed():
            st.update(rulebook=False, tick=hw["SessionStart"], wired=False,
                      detail="AGENTS.override.md in %s shadows the AGENTS.md link, so the rulebook will not load; "
                             "hooks %s" % (self.dir(), "registered" if all(hw.values()) else "incomplete"),
                      action="remove or merge %s" % os.path.join(self.dir(), "AGENTS.override.md"))
            return st
        st.update(rulebook=rb, tick=hw["SessionStart"], wired=not missing,
                  detail=("missing: " + ", ".join(missing) + "; " + _link_detail(link)) if missing
                         else "rulebook link + tick + gate hooks in %s (hook trust cannot be verified from here)" % self.hooks_file(),
                  action=self.TRUST if any(hw.values()) else None)
        return st


class Gemini(Adapter):
    name, enforcement, via = "gemini", "blocks", "AfterAgent"

    def dir(self):
        return _h(".gemini")

    def settings(self):
        return os.path.join(self.dir(), "settings.json")

    def spec(self):
        return {
            "SessionStart": {"cmd": _cmd("tick", "gemini"), "timeout": 10000, "sub": "tick", "name": "sisi-tick"},
            "BeforeAgent": {"cmd": _cmd("prompt", "gemini"), "timeout": 10000, "sub": "prompt", "name": "sisi-prompt"},
            "AfterAgent": {"cmd": _cmd("gate", "gemini"), "timeout": _gate_timeout() * 1000, "sub": "gate", "name": "sisi-gate"},
            "BeforeTool": {"cmd": _cmd("watch", "gemini"), "timeout": 60000, "sub": "watch", "name": "sisi-watch-before"},
            "AfterTool": {"cmd": _cmd("watch", "gemini"), "timeout": 60000, "sub": "watch", "name": "sisi-watch-after"},
        }

    def detect(self):
        return os.path.isdir(self.dir())

    def skip_note(self):
        return "gemini: %s not found; skipped" % self.dir()

    def plan_ops(self):
        return (plan_merge_ops(self.settings(), "nested", self.spec())
                + plan_link_ops(os.path.join(self.dir(), "GEMINI.md"), wiring.core()))

    def wire(self, m, notes):
        merge_json(m, self.settings(), "nested", self.spec(), notes, "gemini")
        wiring._link(m, os.path.join(self.dir(), "GEMINI.md"), wiring.core(), notes, "gemini")

    def unwire(self, m, notes):
        unmerge_json(m, self.settings(), "nested", {"SessionStart": "tick", "BeforeAgent": "prompt", "AfterAgent": "gate",
                                                    "BeforeTool": "watch", "AfterTool": "watch"},
                     self.spec(), notes, "gemini")
        unlink_ours(os.path.join(self.dir(), "GEMINI.md"), notes)

    def status(self):
        st = Adapter.status(self)
        link = os.path.join(self.dir(), "GEMINI.md")
        hw = nested_wired(_load_obj(self.settings()) or {}, self.spec())
        rb = _link_ok(link)
        missing = [n for n, ok in (("rulebook link", rb), ("tick hook", hw["SessionStart"]),
                                   ("prompt hook", hw.get("BeforeAgent", False)), ("gate hook", hw["AfterAgent"]),
                                   ("watch-before hook", hw.get("BeforeTool", False)), ("watch-after hook", hw.get("AfterTool", False))) if not ok]
        st.update(rulebook=rb, tick=hw["SessionStart"], wired=not missing,
                  detail=("missing: " + ", ".join(missing)) if missing else "rulebook link + tick + gate hooks (shared ~/.gemini file also serves Antigravity)")
        return st


class Copilot(Adapter):
    name, enforcement, via = "copilot", "blocks", "agentStop"

    def dir(self):
        return _env_dir("COPILOT_HOME", ".copilot")

    def hooks_file(self):
        return os.path.join(self.dir(), "hooks", "sisi.json")

    def spec(self):
        return {
            "sessionStart": {"cmd": _cmd("tick", "copilot"), "timeout": 10, "sub": "tick"},
            "userPromptSubmitted": {"cmd": _cmd("prompt", "copilot"), "timeout": 10, "sub": "prompt"},
            "agentStop": {"cmd": _cmd("gate", "copilot"), "timeout": _gate_timeout(), "sub": "gate"},
            "subagentStop": {"cmd": _cmd("gate", "copilot", True), "timeout": 30, "sub": "gate"},
            "preToolUse": {"cmd": _cmd("watch", "copilot"), "timeout": 60, "sub": "watch"},
            "postToolUse": {"cmd": _cmd("watch", "copilot"), "timeout": 60, "sub": "watch"},
        }

    def detect(self):
        return os.path.isdir(self.dir())

    def skip_note(self):
        return "copilot: %s not found; skipped" % self.dir()

    def plan_ops(self):
        return (plan_merge_ops(self.hooks_file(), "flat", self.spec(), self._entry, created_version=1)
                + plan_link_ops(os.path.join(self.dir(), "copilot-instructions.md"), wiring.core()))

    @staticmethod
    def _entry(s):
        return {"type": "command", "bash": s["cmd"], "timeoutSec": s["timeout"]}

    def wire(self, m, notes):
        merge_json(m, self.hooks_file(), "flat", self.spec(), notes, "copilot", created_version=1, make_entry=self._entry)
        wiring._link(m, os.path.join(self.dir(), "copilot-instructions.md"), wiring.core(), notes, "copilot")

    def unwire(self, m, notes):
        subs = {"sessionStart": "tick", "userPromptSubmitted": "prompt", "agentStop": "gate", "subagentStop": "gate",
                "preToolUse": "watch", "postToolUse": "watch"}
        unmerge_json(m, self.hooks_file(), "flat", subs, self.spec(), notes, "copilot",
                     created_version=1, make_entry=self._entry)
        unlink_ours(os.path.join(self.dir(), "copilot-instructions.md"), notes)

    def status(self):
        st = Adapter.status(self)
        link = os.path.join(self.dir(), "copilot-instructions.md")
        hw = flat_wired(_load_obj(self.hooks_file()) or {}, self.spec())
        rb = _link_ok(link)
        missing = [n for n, ok in (("rulebook link", rb), ("tick hook", hw["sessionStart"]),
                                   ("prompt hook", hw.get("userPromptSubmitted", False)),
                                   ("gate hook", hw["agentStop"]), ("subagent hook", hw["subagentStop"]),
                                   ("watch-before hook", hw.get("preToolUse", False)), ("watch-after hook", hw.get("postToolUse", False))) if not ok]
        st.update(rulebook=rb, tick=hw["sessionStart"], wired=not missing,
                  detail=("missing: " + ", ".join(missing)) if missing else "rulebook link + tick + gate hooks in %s (CLI; cloud needs a committed .github/hooks file, not written by sisi)" % self.hooks_file())
        return st


class Qwen(Adapter):
    name, enforcement, via = "qwen", "blocks", "Stop"

    def dir(self):
        return _h(".qwen")

    def settings(self):
        return os.path.join(self.dir(), "settings.json")

    def spec(self):
        return {
            "SessionStart": {"cmd": _cmd("tick", "qwen"), "timeout": 10, "sub": "tick", "name": "sisi-tick"},
            "Stop": {"cmd": _cmd("gate", "qwen"), "timeout": _gate_timeout(), "sub": "gate", "name": "sisi-gate"},
            "SubagentStop": {"cmd": _cmd("gate", "qwen", True), "timeout": 30, "sub": "gate", "name": "sisi-gate-subagent"},
        }

    def detect(self):
        return os.path.isdir(self.dir())

    def skip_note(self):
        return "qwen: %s not found; skipped (run Qwen Code once, then `sisi install`)" % self.dir()

    def plan_ops(self):
        return (plan_merge_ops(self.settings(), "nested", self.spec())
                + plan_link_ops(os.path.join(self.dir(), "QWEN.md"), wiring.core()))

    def wire(self, m, notes):
        merge_json(m, self.settings(), "nested", self.spec(), notes, "qwen")
        wiring._link(m, os.path.join(self.dir(), "QWEN.md"), wiring.core(), notes, "qwen")

    def unwire(self, m, notes):
        subs = {"SessionStart": "tick", "Stop": "gate", "SubagentStop": "gate"}
        unmerge_json(m, self.settings(), "nested", subs, self.spec(), notes, "qwen")
        unlink_ours(os.path.join(self.dir(), "QWEN.md"), notes)

    def status(self):
        st = Adapter.status(self)
        link = os.path.join(self.dir(), "QWEN.md")
        hw = nested_wired(_load_obj(self.settings()) or {}, self.spec())
        rb = _link_ok(link)
        missing = [n for n, ok in (("rulebook link", rb), ("tick hook", hw["SessionStart"]),
                                   ("gate hook", hw["Stop"]), ("subagent hook", hw["SubagentStop"])) if not ok]
        st.update(rulebook=rb, tick=hw["SessionStart"], wired=not missing,
                  detail=("missing: " + ", ".join(missing)) if missing else "rulebook link + tick + gate hooks (no confirmed before/after tool events, so shell edits there are still judged from the command text)")
        return st


class Cursor(Adapter):
    name, enforcement, via = "cursor", "sends a follow-up", "stop"

    def dir(self):
        return _h(".cursor")

    def hooks_file(self):
        return os.path.join(self.dir(), "hooks.json")

    def spec(self):
        return {
            "sessionStart": {"cmd": _cmd("tick", "cursor"), "timeout": 10, "sub": "tick"},
            "stop": {"cmd": _cmd("gate", "cursor"), "timeout": _gate_timeout(), "sub": "gate"},
            "subagentStop": {"cmd": _cmd("gate", "cursor", True), "timeout": 30, "sub": "gate"},
            "preToolUse": {"cmd": _cmd("watch", "cursor"), "timeout": 60, "sub": "watch"},
            "postToolUse": {"cmd": _cmd("watch", "cursor"), "timeout": 60, "sub": "watch"},
        }

    @staticmethod
    def _entry(s):
        return {"command": s["cmd"], "timeout": s["timeout"]}

    def detect(self):
        return os.path.isdir(self.dir())

    def skip_note(self):
        return "cursor: %s not found; skipped" % self.dir()

    def plan_ops(self):
        return plan_merge_ops(self.hooks_file(), "flat", self.spec(), self._entry, created_version=1)

    def wire(self, m, notes):
        merge_json(m, self.hooks_file(), "flat", self.spec(), notes, "cursor", created_version=1, make_entry=self._entry)

    def unwire(self, m, notes):
        subs = {"sessionStart": "tick", "stop": "gate", "subagentStop": "gate",
                "preToolUse": "watch", "postToolUse": "watch"}
        unmerge_json(m, self.hooks_file(), "flat", subs, self.spec(), notes, "cursor",
                     created_version=1, make_entry=self._entry)

    def status(self):
        st = Adapter.status(self)
        hw = flat_wired(_load_obj(self.hooks_file()) or {}, self.spec())
        missing = [n for n, ok in (("tick hook", hw["sessionStart"]), ("gate hook", hw["stop"]), ("subagent hook", hw["subagentStop"]),
                                   ("watch-before hook", hw.get("preToolUse", False)), ("watch-after hook", hw.get("postToolUse", False))) if not ok]
        st.update(rulebook=False, tick=hw["sessionStart"], wired=not missing,
                  detail=("missing: " + ", ".join(missing) + "; " if missing else "tick + gate hooks in %s; " % self.hooks_file())
                         + "no global rulebook file is confirmed for Cursor (project AGENTS.md files still load)")
        return st


def _pi_extension():
    body = '''// sisi:generated by `sisi install` -- runs `sisi tick` at session start, `sisi prompt` on each request and `sisi gate` before the session settles. Remove with `sisi uninstall`.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { execFile } from "node:child_process";

const SISI = __SISI__;
const GATE_TIMEOUT_MS = __GATE_MS__;
const SID = "pi-" + process.pid + "-" + Math.random().toString(36).slice(2, 10);
let tickText = "";
let blocks = 0;

function runSisi(args, timeout, payload) {
  return new Promise((resolve) => {
    const child = execFile(SISI, args, { timeout, maxBuffer: 1024 * 1024 }, (err, stdout, stderr) => {
      const code = err && typeof err.code === "number" ? err.code : err ? -1 : 0;
      resolve({ code, out: String(stdout ?? "") + String(stderr ?? "") });
    });
    if (child.stdin) child.stdin.end(JSON.stringify({ session_id: SID, cwd: process.cwd(), ...(payload || {}) }));
  });
}

export default function (pi: ExtensionAPI) {
  pi.on("session_start", async () => {
    try {
      tickText = (await runSisi(["tick", "--tool", "pi"], 10000)).out.trim();
    } catch {
      tickText = "";
    }
  });
  pi.on("before_agent_start", async (event) => {
    let promptText = "";
    try {
      const userText = event && typeof event.prompt === "string" ? event.prompt : "";
      if (userText) promptText = (await runSisi(["prompt", "--tool", "pi"], 10000, { prompt: userText })).out.trim();
    } catch {
      promptText = "";
    }
    const content = [tickText, promptText].filter(Boolean).join("\\n\\n");
    tickText = "";
    if (!content) return;
    return { message: { customType: "sisi-tick", content, display: false } };
  });
  pi.on("agent_before_settle", async (event) => {
    let r;
    try {
      r = await runSisi(["gate", "--tool", "pi"], GATE_TIMEOUT_MS);
    } catch {
      return;
    }
    if (r.code !== 2) {
      blocks = 0;
      const note = r.code === 0 ? r.out.trim() : "";
      if (note) return { entries: [...event.entries, { type: "custom_message", customType: "sisi-gate", content: note, display: false }] };
      return;
    }
    if (blocks++ >= 3) return;
    const content = r.out.trim() || "sisi gate failed; run `sisi verify` and fix before finishing.";
    return { entries: [...event.entries, { type: "custom_message", customType: "sisi-gate", content, display: false }], continue: true };
  });
}
'''
    return body.replace("__SISI__", json.dumps(paths.launcher())).replace(
        "__GATE_MS__", str(_gate_timeout() * 1000)).encode("utf-8")


class Pi(Adapter):
    name, enforcement, via = "pi", "blocks", "agent_before_settle"

    def dir(self):
        return _env_dir("PI_CODING_AGENT_DIR", ".pi", "agent")

    def ext_file(self):
        return os.path.join(self.dir(), "extensions", "sisi.ts")

    def detect(self):
        return os.path.isdir(self.dir())

    def skip_note(self):
        return "pi: %s not found; skipped" % self.dir()

    def plan_ops(self):
        return (plan_generated_ops(self.ext_file(), _pi_extension())
                + plan_link_ops(os.path.join(self.dir(), "AGENTS.md"), wiring.core()))

    def wire(self, m, notes):
        write_generated(m, self.ext_file(), _pi_extension(), notes, "pi")
        wiring._link(m, os.path.join(self.dir(), "AGENTS.md"), wiring.core(), notes, "pi")
        if self.shadowed():
            notes.append("pi: %s shadows AGENTS.md there, so the rulebook will not load until it is removed or merged"
                         % os.path.join(self.dir(), "AGENTS.override.md"))

    def unwire(self, m, notes):
        remove_generated(m, self.ext_file(), notes, "pi", _pi_extension())
        unlink_ours(os.path.join(self.dir(), "AGENTS.md"), notes)

    def shadowed(self):
        return os.path.lexists(os.path.join(self.dir(), "AGENTS.override.md"))

    def status(self):
        st = Adapter.status(self)
        link = os.path.join(self.dir(), "AGENTS.md")
        state = generated_state(self.ext_file(), _pi_extension())
        ext = state == "current" and os.path.isfile(paths.launcher())
        rb = _link_ok(link)
        if self.shadowed():
            st.update(rulebook=False, tick=ext, wired=False,
                      detail="AGENTS.override.md in %s shadows the AGENTS.md link, so the rulebook will not load; extension %s"
                             % (self.dir(), state),
                      action="remove or merge %s" % os.path.join(self.dir(), "AGENTS.override.md"))
            return st
        missing = [n for n, ok in (("rulebook link", rb), ("extension", ext)) if not ok]
        detail = ("missing: " + ", ".join(missing)) if missing else "rulebook link + extension (tick at session start, blocking gate before settle)"
        if state == "stale":
            detail += "; the extension differs from what install would write now (stale or edited; run `sisi install`)"
        elif state == "current" and not os.path.isfile(paths.launcher()):
            detail += "; the extension points at a missing launcher (%s)" % paths.launcher()
        st.update(rulebook=rb, tick=ext, wired=not missing, detail=detail)
        return st


def _opencode_plugin():
    body = '''// sisi:generated by `sisi install` -- runs `sisi tick` when a session is created and `sisi gate` when it goes idle. Remove with `sisi uninstall`.
import { execFile } from "node:child_process";

const SISI = __SISI__;
const GATE_TIMEOUT_MS = __GATE_MS__;
const children = new Set();
const running = new Set();
const blocks = new Map();

function runSisi(args, payload, timeout) {
  return new Promise((resolve) => {
    const child = execFile(SISI, args, { timeout, maxBuffer: 1024 * 1024 }, (err, stdout, stderr) => {
      const code = err && typeof err.code === "number" ? err.code : err ? -1 : 0;
      resolve({ code, out: String(stdout ?? "") + String(stderr ?? "") });
    });
    if (child.stdin) child.stdin.end(JSON.stringify(payload));
  });
}

function makeGate(directory, sendPrompt) {
  return async function gate(sessionID) {
    if (!sessionID || children.has(sessionID) || running.has(sessionID)) return;
    running.add(sessionID);
    try {
      const r = await runSisi(["gate", "--tool", "opencode"], { session_id: sessionID, cwd: directory }, GATE_TIMEOUT_MS);
      if (r.code !== 2) {
        blocks.set(sessionID, 0);
        return;
      }
      const n = (blocks.get(sessionID) || 0) + 1;
      blocks.set(sessionID, n);
      if (n > 3) return;
      const text = r.out.trim() || "sisi gate failed; run `sisi verify` and fix before finishing.";
      if (sendPrompt) await sendPrompt(sessionID, text);
    } catch {
      // fail open: a gate problem must never trap the session
    } finally {
      running.delete(sessionID);
    }
  };
}

function eventParts(e) {
  const d = (e && e.details) || e || {};
  const p = d.properties || {};
  const data = d.data || p || {};
  const info = data.info || p.info || {};
  return {
    type: d.type || e?.type,
    sid: data.sessionID || p.sessionID || info.id || e?.sessionID,
    info,
  };
}

function makeOnEvent(directory, sendPrompt) {
  const gate = makeGate(directory, sendPrompt);
  return async (e) => {
    try {
      const { type, sid, info } = eventParts(e);
      if (info && info.id && info.parentID) children.add(info.id);
      if (type === "session.created" && sid && !children.has(sid)) {
        await runSisi(["tick", "--tool", "opencode"], { session_id: sid, cwd: directory }, 10000);
      } else if (type === "session.idle") {
        await gate(sid);
      }
    } catch {
      // fail open
    }
  };
}

// OpenCode 1.x entry: server() receives { client, directory } and returns hook callbacks.
export const SisiPlugin = async (ctx) => {
  const directory = ctx && typeof ctx.directory === "string" ? ctx.directory : process.cwd();
  const client = ctx && ctx.client;
  const sendPrompt = client?.session?.prompt
    ? async (id, text) => { await client.session.prompt({ path: { id }, body: { parts: [{ type: "text", text }] } }); }
    : undefined;
  const onEvent = makeOnEvent(directory, sendPrompt);
  return { event: async ({ event }) => onEvent(event) };
};

// OpenCode 2.x entry: setup(ctx) receives service objects (ctx.event, ctx.session, ctx.location).
// Registration surfaces differ by version; every attempt is optional and any failure leaves the plugin inert.
function setup(ctx) {
  try {
    if (!ctx) return;
    const directory = (ctx.location && ctx.location.directory) || process.cwd();
    const promptFn = ctx.session && ctx.session.prompt;
    const sendPrompt = typeof promptFn === "function"
      ? async (id, text) => { await promptFn({ sessionID: id, parts: [{ type: "text", text }] }); }
      : undefined;
    const onEvent = makeOnEvent(directory, sendPrompt);
    try { if (ctx.event?.subscribe) ctx.event.subscribe(onEvent); } catch {}
    try { if (ctx.session?.hook) ctx.session.hook({}, onEvent); } catch {}
  } catch {
    // fail open
  }
}

export default { id: "sisi", server: SisiPlugin, setup };
'''
    return body.replace("__SISI__", json.dumps(paths.launcher())).replace(
        "__GATE_MS__", str(_gate_timeout() * 1000)).encode("utf-8")


class OpenCode(Adapter):
    name, enforcement, via = "opencode", "unknown", "session.idle"

    def dir(self):
        return wiring.loc()["opencode_dir"]

    def plugin_file(self):
        return os.path.join(self.dir(), "plugins", "sisi.js")

    def detect(self):
        return os.path.isdir(self.dir())

    def skip_note(self):
        return "opencode: %s not found; skipped" % self.dir()

    def plan_ops(self):
        return plan_generated_ops(self.plugin_file(), _opencode_plugin())

    def wire(self, m, notes):
        write_generated(m, self.plugin_file(), _opencode_plugin(), notes, "opencode")

    def unwire(self, m, notes):
        remove_generated(m, self.plugin_file(), notes, "opencode", _opencode_plugin())

    def status(self):
        st = Adapter.status(self)
        link = wiring.loc()["opencode"]
        state = generated_state(self.plugin_file(), _opencode_plugin())
        pl = state == "current" and os.path.isfile(paths.launcher())
        rb = _link_ok(link)
        missing = [n for n, ok in (("rulebook link", rb), ("plugin", pl)) if not ok]
        detail = (("missing: " + ", ".join(missing) + "; ") if missing else "rulebook link + plugin; ")
        if state == "stale":
            detail += "the plugin differs from what install would write now (stale or edited; run `sisi install`); "
        st.update(rulebook=rb, tick=False, wired=not missing,
                  detail=detail
                         + "the plugin is loaded by OpenCode (verified) and runs tick at session start and the gate when idle where events are delivered, "
                         + "but on OpenCode v2.3.2 no event delivery or lesson injection could be confirmed in headless runs, and session.idle cannot veto a stop; continuations are best-effort and unproven")
        return st


class RulebookOnly(Adapter):
    """A single symlink to the generated rulebook; the tool has no usable hooks."""
    enforcement = "none"

    def __init__(self, name, detect_parts, link_parts, why, base="home"):
        # Paths are stored as relative parts and resolved per call: SISI_HOME can change between calls.
        # base "xdg" resolves under the XDG config folder instead of the home folder.
        self.name, self._detect_parts, self._link_parts, self.why, self._base = name, detect_parts, link_parts, why, base

    def _resolve(self, parts):
        return _xdg(*parts) if self._base == "xdg" else _h(*parts)

    @property
    def _detect_dir(self):
        return self._resolve(self._detect_parts)

    @property
    def _link(self):
        return self._resolve(self._link_parts)

    def detect(self):
        return os.path.isdir(self._detect_dir)

    def skip_note(self):
        return "%s: %s not found; skipped" % (self.name, self._detect_dir)

    def plan_ops(self):
        return plan_link_ops(self._link, wiring.core())

    def wire(self, m, notes):
        wiring._link(m, self._link, wiring.core(), notes, self.name)

    def unwire(self, m, notes):
        unlink_ours(self._link, notes)

    def status(self):
        st = Adapter.status(self)
        rb = _link_ok(self._link)
        st.update(rulebook=rb, wired=rb,
                  detail=(_link_detail(self._link) + "; " + self.why) if not rb else "rulebook only; " + self.why)
        return st


class Cline(Adapter):
    name, enforcement = "cline", "none"

    def rules_dir(self):
        if os.path.isdir(_h("Documents", "Cline")):
            return _h("Documents", "Cline", "Rules")
        if os.path.isdir(_h(".cline")):
            return _h(".cline", "rules")
        return None

    def link(self):
        d = self.rules_dir()
        return os.path.join(d, "sisi.md") if d else _h("Documents", "Cline", "Rules", "sisi.md")

    def detect(self):
        return self.rules_dir() is not None

    def skip_note(self):
        return "cline: neither %s nor %s found; skipped" % (_h("Documents", "Cline"), _h(".cline"))

    def plan_ops(self):
        return plan_link_ops(self.link(), wiring.core())

    def wire(self, m, notes):
        wiring._link(m, self.link(), wiring.core(), notes, "cline")

    def unwire(self, m, notes):
        unlink_ours(self.link(), notes)

    def status(self):
        st = Adapter.status(self)
        rb = _link_ok(self.link())
        st.update(rulebook=rb, wired=rb,
                  detail=(_link_detail(self.link()) + "; " if not rb else "rulebook only; ")
                         + "Cline hooks exist but no send-the-agent-back contract is confirmed, so sisi wires no gate")
        return st


def _windsurf_pointer():
    text = ("<!-- sisi:generated by `sisi install` -- remove with `sisi uninstall` -->\n"
            "# sisi shared rulebook\n\n"
            "Read and follow the shared rulebook at `%s` in full before working. It is the same rulebook every "
            "AI coding tool on this machine uses. In short: draft `.sisi/contract.json` for the work, run "
            "`sisi verify` until it passes before you report done, and record a `sisi retro` at the end. "
            "Windsurf has no sisi gate hook, so run the checks yourself.\n" % wiring.core())
    return text.encode("utf-8")


class Windsurf(Adapter):
    name, enforcement = "windsurf", "none"

    def dir(self):
        return _h(".codeium", "windsurf")

    def file(self):
        return os.path.join(self.dir(), "memories", "global_rules.md")

    def detect(self):
        return os.path.isdir(self.dir())

    def skip_note(self):
        return "windsurf: %s not found; skipped" % self.dir()

    def plan_ops(self):
        return plan_generated_ops(self.file(), _windsurf_pointer())

    def wire(self, m, notes):
        write_generated(m, self.file(), _windsurf_pointer(), notes, "windsurf")

    def unwire(self, m, notes):
        remove_generated(m, self.file(), notes, "windsurf", _windsurf_pointer())

    def status(self):
        st = Adapter.status(self)
        state = generated_state(self.file(), _windsurf_pointer())
        ours = state == "current"
        st.update(rulebook=ours, wired=ours,
                  detail=("pointer file at %s (global rules are size-capped, so the rulebook itself is linked by reference in the text; "
                          "whether Cascade follows the pointer is unconfirmed); no gate hook is confirmed" % self.file())
                         if ours else "no current sisi pointer at %s (state: %s; an existing non-sisi file there is left alone); no gate hook is confirmed" % (self.file(), state))
        return st


# ---- Aider: `read:` in ~/.aider.conf.yml (the only YAML sisi touches) ----------
import re as _re

_READ_RE = _re.compile(r"^read\s*:\s*(.*?)\s*$")
_ITEM_RE = _re.compile(r"^(\s+)-\s+(.*?)\s*$")


_DQ_ESCAPES = {"\\": "\\", '"': '"', "/": "/", "n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "0": "\0"}


def _parse_quoted(s, i):
    """(value, end_index) for the quoted scalar starting at s[i]. Raises ValueError when uncertain."""
    q = s[i]
    out, j = [], i + 1
    while j < len(s):
        c = s[j]
        if q == "'":
            if c == "'":
                if j + 1 < len(s) and s[j + 1] == "'":
                    out.append("'")
                    j += 2
                    continue
                return "".join(out), j + 1
            out.append(c)
            j += 1
            continue
        if c == '"':
            return "".join(out), j + 1
        if c == "\\":
            if j + 1 >= len(s):
                break
            e = s[j + 1]
            if e in _DQ_ESCAPES:
                out.append(_DQ_ESCAPES[e])
                j += 2
                continue
            if e == "u" and j + 5 < len(s) + 1 and len(s) >= j + 6:
                try:
                    out.append(chr(int(s[j + 2:j + 6], 16)))
                except ValueError:
                    raise ValueError("unrecognised escape in quoted scalar")
                j += 6
                continue
            raise ValueError("unrecognised escape in quoted scalar")
        out.append(c)
        j += 1
    raise ValueError("unterminated quoted scalar")


def _yaml_scalar(v):
    v = v.strip()
    if v[:1] in "\"'":
        val, end = _parse_quoted(v, 0)
        if v[end:].strip():
            raise ValueError("trailing characters after quoted scalar")
        return val
    return v


def _split_flow(inner):
    """Quote-aware split of a flow list's inside: [(raw_token, value)]. Raises ValueError when the
    list cannot be split with certainty, in which case the caller must not rewrite it at all."""
    toks, i, n = [], 0, len(inner)
    while True:
        while i < n and inner[i] in " \t":
            i += 1
        if i >= n:
            return toks
        if inner[i] in "\"'":
            val, end = _parse_quoted(inner, i)
            raw = inner[i:end]
            i = end
        else:
            start = i
            while i < n and inner[i] != ",":
                if inner[i] in "[]{}":
                    raise ValueError("nested flow collection in `read:` list is not merged")
                i += 1
            raw = inner[start:i].strip()
            if not raw:
                raise ValueError("empty entry in `read:` list")
            val = raw
        toks.append((raw, val))
        while i < n and inner[i] in " \t":
            i += 1
        if i >= n:
            return toks
        if inner[i] != ",":
            raise ValueError("unexpected characters in `read:` list")
        i += 1


def _block_value(rest):
    if rest[:1] in "\"'":
        val, end = _parse_quoted(rest, 0)
        tail = rest[end:].strip()
        if tail and not tail.startswith("#"):
            raise ValueError("trailing characters after quoted `read:` item")
        return val
    if rest[:1] in "[{":
        raise ValueError("flow collection as a `read:` item is not merged")
    return rest.split(" #", 1)[0].strip()


def _yaml_emit(v):
    if _re.search(r"[\s#:\[\]{},&*?|<>=!%@`\"']", v) or v == "":
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return v


def _aider_read_span(lines):
    """Locate a top-level `read:` entry. Returns (index, kind, values, raw_tokens), kind in
    block/flow/scalar, or None. Raises ValueError for any shape that cannot be rewritten with certainty."""
    for i, line in enumerate(lines):
        m = _READ_RE.match(line)
        if not m:
            continue
        val = m.group(1)
        if val == "":
            vals, raws, j = [], [], i + 1
            while j < len(lines):
                im = _ITEM_RE.match(lines[j])
                if not im:
                    break
                vals.append(_block_value(im.group(2)))
                raws.append(im.group(2))
                j += 1
            return i, "block", vals, raws
        if val.startswith("["):
            if not val.rstrip().endswith("]"):
                raise ValueError("multi-line flow `read:` list is not merged")
            toks = _split_flow(val.strip()[1:-1])
            return i, "flow", [v for _r, v in toks], [r for r, _v in toks]
        if " #" in val or val[:1] in "&*|>{":
            raise ValueError("unrecognised `read:` shape")
        return i, "scalar", [_yaml_scalar(val)], [val]
    return None


def aider_add(data):
    if isinstance(data, bytes):
        data = data.decode("utf-8")  # may raise UnicodeDecodeError (a ValueError): caller skips the tool
    core = wiring.core()
    lines = data.split("\n")
    span = _aider_read_span(lines)
    if span is None:
        out = data
        if out and not out.endswith("\n"):
            out += "\n"
        return out + "read:\n  - %s\n" % _yaml_emit(core)
    i, kind, vals = span[0], span[1], span[2]
    if core in vals:
        return data
    if kind == "block":
        j = i + 1
        indent = "  "
        while j < len(lines) and _ITEM_RE.match(lines[j]):
            indent = _ITEM_RE.match(lines[j]).group(1)
            j += 1
        lines.insert(j, "%s- %s" % (indent, _yaml_emit(core)))
    elif kind == "flow":
        line = lines[i]
        idx = line.rfind("]")
        before = line[:idx].rstrip()
        sep = "" if before.endswith("[") else ", "
        lines[i] = before + sep + _yaml_emit(core) + line[idx:]
    else:
        lines[i] = "read: [%s, %s]" % (_READ_RE.match(lines[i]).group(1), _yaml_emit(core))
    return "\n".join(lines)


def aider_remove(data):
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    core = wiring.core()
    lines = data.split("\n")
    span = _aider_read_span(lines)
    if span is None:
        return data
    i, kind, vals, raws = span
    if core not in vals:
        return data
    rest_raw = [r for r, v in zip(raws, vals) if v != core]
    if kind == "block":
        j = i + 1
        while j < len(lines) and _ITEM_RE.match(lines[j]):
            if _block_value(_ITEM_RE.match(lines[j]).group(2)) == core:
                del lines[j]
            else:
                j += 1
        if not rest_raw:
            del lines[i]
    elif not rest_raw:
        del lines[i]
    elif kind == "scalar" and len(rest_raw) == 1:
        lines[i] = "read: %s" % rest_raw[0]
    else:
        lines[i] = "read: [%s]" % ", ".join(rest_raw)  # raw tokens kept verbatim, quoting included
    return "\n".join(lines)


class Aider(Adapter):
    name, enforcement = "aider", "none"

    def file(self):
        return _h(".aider.conf.yml")

    def detect(self):
        return os.path.isfile(self.file())

    def skip_note(self):
        return "aider: %s not found; skipped (create it, even empty, then re-run `sisi install`)" % self.file()

    def plan_ops(self):
        data, err = wiring._read_file(self.file())
        if err:
            return [{"kind": "skip", "reason": err, "fatal": True}]
        try:
            new = aider_add(data or b"").encode("utf-8")
        except ValueError as e:
            return [{"kind": "skip", "reason": "%s would be skipped (%s)" % (self.file(), e), "fatal": True}]
        if new == data:
            return []
        return [{"kind": "edit", "path": self.file(), "old": data, "new": new}]

    def wire(self, m, notes):
        data, err = wiring._read_file(self.file())
        if err:
            raise ValueError(err)
        new = aider_add(data or b"").encode("utf-8")
        if new != data:
            wiring._backup(m, self.file(), data)
            wiring._write(self.file(), new)
            notes.append("aider: rulebook added to `read:` in %s" % self.file())

    def unwire(self, m, notes):
        data, err = wiring._read_file(self.file())
        if err:
            notes.append("aider: %s not touched (%s)" % (self.file(), err))
            return
        if data is None:
            return
        ent = m["files"].get(self.file())
        try:
            removed = aider_remove(data).encode("utf-8")
        except ValueError as e:
            notes.append("aider: %s not touched (%s)" % (self.file(), e))
            return
        if removed == data:
            return
        orig = wiring._read(os.path.join(wiring._idir(), "backups", ent["backup"])) if ent and ent["backup"] else None
        restored = False
        if orig is not None:
            try:
                restored = aider_add(orig).encode("utf-8") == data
            except ValueError:
                restored = False
        wiring._write(self.file(), orig if restored else removed)
        notes.append("aider: rulebook removed from `read:` in %s" % self.file())

    def status(self):
        st = Adapter.status(self)
        rb = False
        try:
            span = _aider_read_span((wiring._read(self.file()) or b"").decode("utf-8").split("\n"))
            rb = bool(span) and wiring.core() in span[2]
        except ValueError:
            pass
        st.update(rulebook=rb, wired=rb,
                  detail=("rulebook in `read:` of %s; Aider has no hooks, so nothing enforces it" % self.file()) if rb
                         else "rulebook not in `read:` of %s; Aider has no hooks" % self.file())
        return st


class Muse(Adapter):
    """No muse-specific wiring exists to make: the binary documents no global instruction path and its hook
    event list has no end-of-turn Stop. The rulebook still arrives through the Claude/Codex files Muse loads
    as foreign personal context, which is what doctor reports."""
    name, enforcement = "muse", "unknown"

    def dir(self):
        return _h(".config", "muse")

    def detect(self):
        return os.path.isdir(self.dir())

    def skip_note(self):
        return "muse: %s not found; skipped" % self.dir()

    NOTE = ("nothing to wire directly (no documented global instruction path, no end-of-turn Stop hook); "
            "it loads the rulebook through foreign context (~/.claude/CLAUDE.md, ~/.codex/AGENTS.md) when those are wired")

    def plan_ops(self):
        return [{"kind": "note", "text": self.NOTE}]

    def wire(self, m, notes):
        notes.append("muse: " + self.NOTE)

    def status(self):
        st = Adapter.status(self)
        L = wiring.loc()
        foreign = wiring._claude_md_wired(wiring._read(L["claude_md"])) or _link_ok(L["codex"])
        st.update(rulebook=foreign,
                  detail=("rulebook loaded via foreign personal context (~/.claude/CLAUDE.md, ~/.codex/AGENTS.md); native global path undocumented; "
                          "no hooks wired (the binary's hook events have no end-of-turn Stop, and the global hook shape is unconfirmed)")
                         if foreign else
                         "rulebook not loaded: Muse reads ~/.claude/CLAUDE.md and ~/.codex/AGENTS.md as foreign context, and neither is wired; "
                         "no hooks wired (no end-of-turn Stop hook event in the binary; global hook shape unconfirmed)")
        return st


def antigravity_status():
    detected = os.path.isdir(_h(".gemini", "antigravity")) or os.path.exists(_h(".gemini", "config", "hooks.json"))
    rb = _link_ok(_h(".gemini", "GEMINI.md"))
    return {"tool": "antigravity", "detected": detected, "rulebook": rb, "tick": False,
            "enforcement": "unknown", "via": "", "wired": False, "action": None,
            "detail": ("shares ~/.gemini/GEMINI.md with Gemini CLI%s; hooks not wired (whether the CLI fires hooks and the always-on size budget are unconfirmed)"
                       % (" (linked to the rulebook)" if rb else " (not linked)"))}


class Grok(RulebookOnly):
    """Rulebook-only, but under $GROK_HOME when set (confirmed live with `grok inspect`)."""

    def __init__(self):
        super().__init__("grok", (".grok",), (".grok", "AGENTS.md"),
                         "Grok hooks exist but session-start output is reportedly discarded and no blocking stop is confirmed, so sisi wires no gate")

    def _resolve(self, parts):
        base = _env_dir("GROK_HOME", ".grok")
        return os.path.join(base, *parts[1:]) if len(parts) > 1 else base


def _rulebook_only(name, detect_parts, link_parts, why, base="home"):
    return RulebookOnly(name, detect_parts, link_parts, why, base)


ADAPTERS = [
    Codex(), Gemini(), Copilot(), Qwen(), Pi(), Cursor(), OpenCode(),
    Windsurf(), Cline(),
    _rulebook_only("kiro", (".kiro",), (".kiro", "steering", "AGENTS.md"),
                   "Kiro hooks are trigger automations with no confirmed turn-end veto, so sisi wires no gate"),
    _rulebook_only("zed", (".config", "zed"), (".config", "zed", "AGENTS.md"),
                   "Zed's built-in agent has no hooks (external ACP agents bring their own)"),
    _rulebook_only("goose", (".config", "goose"), (".config", "goose", ".goosehints"),
                   "Goose plugin hooks cannot inject context or force a continuation on any confirmed contract, so sisi wires no gate"),
    _rulebook_only("amp", (".config", "amp"), (".config", "amp", "AGENTS.md"),
                   "no blocking end-of-turn hook is confirmed for Amp, so sisi wires no gate"),
    Grok(),
    _rulebook_only("crush", ("crush",), ("crush", "CRUSH.md"),
                   "Crush hooks support only PreToolUse today, so sisi wires no gate", base="xdg"),
    Aider(), Muse(),
]

BY_NAME = {a.name: a for a in ADAPTERS}


def preflight_all():
    """{tool: reason} for detected tools that must not be touched at all: a fatal plan refusal
    (dangling/unreadable/unmergeable config) or a planned write to a read-only target. Checked for
    every tool before install touches the first one, so no tool ends up half-wired."""
    failed = {}
    for a in ADAPTERS:
        if not a.detect():
            continue
        try:
            ops = a.plan_ops()
        except (ValueError, OSError) as e:
            failed[a.name] = str(e)
            continue
        for op in ops:
            err = None
            if op["kind"] == "skip" and op.get("fatal"):
                err = op["reason"]
            elif op["kind"] in ("create", "edit"):
                err = wiring._writable(op["path"])
            elif op["kind"] == "link":
                err = wiring._link_writable(op["path"], op["target"])
            if err:
                failed[a.name] = err
                break
    return failed


def wire_all(m, notes, prefailed=None):
    if prefailed is None:
        prefailed = preflight_all()
    for a in ADAPTERS:
        if not a.detect():
            notes.append(a.skip_note())
            continue
        if a.name in prefailed:
            notes.append("%s: skipped, its config was left untouched (%s)" % (a.name, prefailed[a.name]))
            continue
        try:
            a.wire(m, notes)
        except (ValueError, OSError) as e:
            notes.append("%s: skipped, its config was left untouched (%s)" % (a.name, e))


def dry_run_lines():
    failed = preflight_all()
    lines = []
    for a in ADAPTERS:
        if not a.detect():
            lines.append(a.skip_note())
            continue
        if a.name in failed:
            lines.append("%s: skip (would be refused: %s)" % (a.name, failed[a.name]))
            continue
        try:
            ops = a.plan_ops()
        except (ValueError, OSError) as e:
            ops = [{"kind": "skip", "reason": str(e), "fatal": True}]
        lines += format_ops(a.name, ops)
    return lines


def unwire_all(m, notes):
    for a in ADAPTERS:
        try:
            a.unwire(m, notes)
        except (ValueError, OSError) as e:
            notes.append("%s: could not fully unwire (%s)" % (a.name, e))


def rulebook_links():
    """(tool, path) for every symlink that should point at the generated rulebook."""
    out = []
    for a in ADAPTERS:
        if isinstance(a, RulebookOnly):
            out.append((a.name, a._link))
    out += [("gemini", _h(".gemini", "GEMINI.md")), ("qwen", _h(".qwen", "QWEN.md")),
            ("copilot", os.path.join(BY_NAME["copilot"].dir(), "copilot-instructions.md")),
            ("pi", os.path.join(BY_NAME["pi"].dir(), "AGENTS.md")),
            ("cline", BY_NAME["cline"].link())]
    return out
