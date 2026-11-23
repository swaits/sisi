"""Per-tool hook translation for `sisi tick --tool NAME` and `sisi gate --tool NAME`.

Claude Code's own shape stays in gate.py and tick.py, unchanged. Every other tool's documented hook JSON is
normalised here into the payload gate.decide() already understands, and the (action, message) result is
formatted back into that tool's documented output shape. Pi and OpenCode have no stdin hook process: their
sisi extension/plugin execs these commands, so they use a plain contract instead (tick prints lessons on
stdout; gate exits 2 and prints the send-back reason, exit 0 allows and may print a notice).

Everything fails open: garbage input or any internal error lets the agent finish.
"""
import io, json, sys

from . import store

TOOLS = ("codex", "gemini", "copilot", "qwen", "cursor", "pi", "opencode")


def known(tool):
    return tool in TOOLS


def _payload(raw):
    """The hook's JSON object, {} for empty input, or None for garbage (caller then fails open)."""
    s = (raw or "").strip()
    if not s:
        return {}
    try:
        d = json.loads(s)
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def _s(d, *keys):
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def normalize(tool, d):
    """One payload shape for gate.decide()/tick.main(), from any tool's documented input fields."""
    out = {}
    for key, val in (
        ("session_id", _s(d, "session_id", "sessionId", "conversation_id")),
        ("transcript_path", _s(d, "transcript_path", "transcriptPath")),
        ("agent_transcript_path", _s(d, "agent_transcript_path")),
        ("agent_id", _s(d, "agent_id", "agentId")),
        ("source", _s(d, "source")),
    ):
        if val:
            out[key] = val
    cwd = _s(d, "cwd")
    if not cwd and isinstance(d.get("workspace_roots"), list):
        roots = [r for r in d["workspace_roots"] if isinstance(r, str) and r]
        cwd = roots[0] if roots else None
    if cwd:
        out["cwd"] = cwd
    return out


def _text(msg):
    if isinstance(msg, dict):
        return msg.get("context") or msg.get("message") or ""
    return msg if isinstance(msg, str) else ""


def _notice(msg):
    if isinstance(msg, dict):
        return msg.get("message") or ""
    return msg if isinstance(msg, str) else ""


def _dump(obj):
    return json.dumps(obj) + "\n"


def _gate_out(tool, action, msg, subagent):
    """(stdout text or None, exit code) for one gate decision, in the tool's documented shape."""
    if tool in ("pi", "opencode"):
        if action == "block":
            return _text(msg) + "\n", 2
        note = _text(msg)
        return (note + "\n" if note else None), 0
    if action == "block":
        reason = _text(msg) or "sisi: the checks for this work do not pass; run `sisi verify` and fix before finishing."
        if tool == "cursor":
            return _dump({"followup_message": reason}), 0
        if tool == "gemini":
            return _dump({"decision": "deny", "reason": reason}), 0
        return _dump({"decision": "block", "reason": reason}), 0  # codex, copilot, qwen
    # allow: surface a notice only where the tool documents a channel for one on this event
    notice, context = _notice(msg), _text(msg)
    if tool == "codex":
        return (_dump({"systemMessage": notice}) if notice else None), 0
    if tool == "qwen":
        if context:
            ev = "SubagentStop" if subagent else "Stop"
            return _dump({"systemMessage": notice or context,
                          "hookSpecificOutput": {"hookEventName": ev, "additionalContext": context}}), 0
        return None, 0
    if tool == "gemini":
        return _dump({"systemMessage": notice} if notice else {}), 0
    if tool == "cursor":
        return _dump({}), 0
    return None, 0  # copilot: agentStop consumes only decision/reason; empty output allows


def gate_main(tool, args=()):
    sub = "--subagent" in args
    action, msg, norm = "allow", None, {}
    try:
        d = _payload(store.read_stdin())
        skip = d is not None and tool == "cursor" and d.get("status") not in (None, "completed")
        if d is not None and not skip:
            norm = normalize(tool, d)
            from . import gate
            action, msg = (gate.decide_subagent if sub else gate.decide)(norm)
    except Exception as e:  # fail open, exactly like gate.main
        store.log_error("gate-%s" % tool, e)
        action, msg = "allow", None
    if action == "allow" and not sub:
        try:
            from . import gate
            gate._record_delivery(norm)
        except Exception:
            pass
    text, rc = _gate_out(tool, action, msg, sub)
    if text:
        sys.stdout.write(text)
    return rc


def _tick_out(tool, text):
    text = (text or "").strip("\n")
    if tool in ("pi", "opencode"):
        return (text + "\n") if text else None
    if not text:
        return _dump({}) if tool in ("gemini", "qwen", "cursor") else None
    if tool == "copilot":
        return _dump({"additionalContext": text})
    if tool == "cursor":
        return _dump({"additional_context": text})
    return _dump({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}})


def tick_main(tool, args=()):
    try:
        d = _payload(store.read_stdin()) or {}
        from . import tick
        buf = io.StringIO()
        old_in, old_out = sys.stdin, sys.stdout
        try:
            sys.stdin = io.StringIO(json.dumps(normalize(tool, d)))
            sys.stdout = buf
            tick.main(())
        finally:
            sys.stdin, sys.stdout = old_in, old_out
        text = _tick_out(tool, buf.getvalue())
    except Exception as e:  # fail open: a session must never be held up by sisi
        store.log_error("tick-%s" % tool, e)
        return 0
    if text:
        sys.stdout.write(text)
    return 0
