"""Before/after tool measurement: did this session's shell command actually change the project?

Registered as PreToolUse/PostToolUse (and each tool's confirmed equivalent) with a Bash/shell
matcher where the tool has one. Before an uncertain shell command, a stat-only tree snapshot
(gitutil.snapshot: sizes and mtimes, .gitignore honoured, .git never included, so `git commit`
changes nothing) is kept in the state dir; after it, the snapshot is taken again and the paths
that differ are attributed to this session in its session record. Provably read-only commands
(gate._shell_may_write is False: ls/cat/grep, read-only git/gh, and sisi's own commands other
than contract init/waive/trust, which write only personal data and state) skip the pair entirely.
Another agent changing the tree inside the command window is attributed to this session too —
that errs strict, which is the safe side. A pending before-record with no after (the command was
killed) is likewise treated as this session having edited, with no known paths (a sentinel).
Both hooks fail open: any error is logged and the tool call proceeds.
"""
import json, os, time

from . import gitutil, paths, store

BEFORE_EVENTS = {"PreToolUse", "BeforeTool", "preToolUse", "beforeShellExecution", "tool_call"}
AFTER_EVENTS = {"PostToolUse", "AfterTool", "postToolUse", "afterShellExecution",
                "postToolUseFailure", "tool_result"}
SHELL_TOOLS = ("bash", "shell", "command", "terminal", "exec")


def _s(d, *keys):
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def extract(d):
    """(tool_name, command, event, cwd, session_id) from any tool's tool-hook payload shape."""
    inp = None
    for k in ("tool_input", "toolInput", "input", "tool_input_dict"):
        if isinstance(d.get(k), dict):
            inp = d[k]
            break
    cmd = None
    if inp:
        for k in ("command", "cmd", "script"):
            if isinstance(inp.get(k), str):
                cmd = inp[k]
                break
    if cmd is None and isinstance(d.get("command"), str):
        cmd = d["command"]
    tool = _s(d, "tool_name", "toolName", "tool", "name") or ""
    cwd = _s(d, "cwd") or os.getcwd()
    return tool, cmd, _s(d, "hook_event_name", "hookEventName", "event_name", "event") or "", \
        cwd, _s(d, "session_id", "sessionId", "conversation_id") or ""


def is_shell(tool, cmd):
    t = (tool or "").lower()
    return bool(cmd) and (not t or any(w in t for w in SHELL_TOOLS))


def _may_write(cmd):
    from . import gate
    return gate._shell_may_write(cmd)


def snap_file(sid, kind):
    return os.path.join(paths.state(), "sessions", store.safe_id(sid) + "." + kind + ".json")


def _save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def note_edit(sess, changed_rel, root, sentinel=None):
    """Attribute paths (relative to root) to this session in its record."""
    sess["attr_gen"] = int(sess.get("attr_gen", 0) or 0) + 1
    sess["attr_writing"] = True
    have = sess.setdefault("attr_files", [])
    since = sess.setdefault("attr_since_pass", [])
    for rel in changed_rel:
        ap = os.path.join(root, rel) if root else rel
        if ap not in have:
            have.append(ap)
        if rel not in since:
            since.append(rel)
    if sentinel and sentinel not in since:
        since.append(sentinel)


def _session(sid, d, cwd):
    sess = store.load_session(sid)
    sess.setdefault("session_id", sid)
    sess["attr_measured"] = True
    if isinstance(d.get("transcript_path"), str):
        sess["transcript_path"] = d["transcript_path"]
    sess.setdefault("cwd", cwd)
    return sess


def note_shell(sess, cmd, payload):
    """Record, for the learning loop, who ran this shell command: whether it names a retro, and whether
    its hook payload came from a subagent (an agent id or a subagent transcript path). `sisi retro`
    reads this from the session record to quarantine what a subagent records; it never trusts the
    caller's environment. The command text itself is not kept."""
    from . import workers
    shells = sess.setdefault("shells", [])
    shells.append({"retro": "retro" in (cmd or ""), "subagent": bool(workers.is_subagent_payload(payload)),
                   "ts": time.time()})
    del shells[:-8]


def before(payload):
    tool, cmd, _ev, cwd, sid = extract(payload)
    if not is_shell(tool, cmd):
        return
    sid = sid or "cwd-" + cwd
    sess = _session(sid, payload, cwd)
    note_shell(sess, cmd, payload)
    store.save_session(sid, sess)
    if _may_write(cmd) is False:
        return  # provably read-only (incl. sisi's own and git commit): no measurement paid
    snap = gitutil.snapshot(cwd)
    _save(snap_file(sid, "watch"), {"root": snap["root"], "files": snap["files"],
                                    "command": (cmd or "")[:500], "ts": time.time()})


def after(payload):
    tool, cmd, _ev, cwd, sid = extract(payload)
    if not is_shell(tool, cmd):
        return
    sid = sid or "cwd-" + cwd
    sess = _session(sid, payload, cwd)
    pend = _load(snap_file(sid, "watch"))
    if pend is None:
        if _may_write(cmd) is not False:
            note_edit(sess, [], pend_root(sess, cwd), sentinel="*shell-unmeasured*")
        store.save_session(sid, sess)
        return
    try:
        os.unlink(snap_file(sid, "watch"))
    except OSError:
        pass
    root = pend.get("root") or gitutil.root(cwd) or cwd
    now = gitutil.snapshot(root)
    changed = gitutil.snapshot_diff(pend, now)
    if changed:
        note_edit(sess, changed, root)
    store.save_session(sid, sess)


def pend_root(sess, cwd):
    return gitutil.root(cwd) or sess.get("req_project") or cwd


def consume_pending(sess, sid, cwd):
    """A before-record with no after at gate time (command killed): strict. Returns True if one was."""
    p = snap_file(sid, "watch")
    pend = _load(p)
    if pend is None:
        return False
    try:
        os.unlink(p)
    except OSError:
        pass
    note_edit(sess, [], pend.get("root") or pend_root(sess, cwd), sentinel="*shell-unmeasured*")
    return True


def save_pass_snapshot(sid, cwd):
    snap = gitutil.snapshot(cwd)
    _save(snap_file(sid, "pass"), snap)
    return snap


def changed_since_pass(sid, cwd):
    """Paths differing from the last passing snapshot, or None when none was ever recorded."""
    pend = _load(snap_file(sid, "pass"))
    if pend is None:
        return None
    return gitutil.snapshot_diff(pend, gitutil.snapshot(cwd))


def main(args=()):
    try:
        from . import gate
        payload = gate._read_payload()
        _tool, _cmd, ev, _cwd, _sid = extract(payload)
        if "--before" in args or ev in BEFORE_EVENTS:
            before(payload)
        elif "--after" in args or ev in AFTER_EVENTS:
            after(payload)
    except Exception as e:  # fail open: a tool call must never be held up by measurement
        store.log_error("watch", e)
    return 0
