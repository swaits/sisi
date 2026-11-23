"""Time to delivery: how long from the human's request to a verified stop, recorded by the gate
and read back as unit telemetry when a unit closes (see sisi.unit; `sisi status` is the one report).

Delivery row (deliveries.jsonl in the state dir): session, project, start, end (ISO UTC), seconds, send_backs (times the
gate sent the agent back during this request), check_s (seconds spent running checks during this request), contract
(whether a contract existed), tool. The start is the timestamp of the last message the human typed, found by reading
only the tail of the transcript and applying harvest.typed_text, the one definition of "typed by the human".
Everything here fails quiet: a missing or corrupt transcript records nothing and never touches the gate's answer."""
import json, os, time

from . import store

CHUNK = 128 * 1024
MAX_READ = 4 * 1024 * 1024  # a turn longer than this (in transcript bytes) is not measured


def _line_start(raw):
    """(epoch seconds, None) of the human message in one transcript line, else None. Cheap prefilters come first."""
    from . import harvest
    is_att = b'"type":"attachment"' in raw and b"queued_command" in raw  # compact JSON, as Claude Code writes it
    if b'"type":"user"' not in raw and not is_att:
        return None
    if b"toolUseResult" in raw and not is_att:
        return None  # a tool result: never a human message, and often huge
    d = json.loads(raw)
    if not isinstance(d, dict) or not isinstance(d.get("timestamp"), str):
        return None
    if d.get("type") == "user":
        text = harvest.typed_text(d)[0]
    elif d.get("type") == "attachment":
        a = d.get("attachment") or {}
        if not (a.get("type") == "queued_command" and a.get("commandMode") == "prompt" and not a.get("isMeta")):
            return None
        text = harvest.typed_text(a, queued_prompt=a.get("prompt"))[0]
    else:
        return None
    return harvest.epoch(d["timestamp"]) if text is not None else None


def find_start(path, max_bytes=MAX_READ, chunk=CHUNK):
    """Epoch seconds of the last message the human typed in the transcript at `path`, or None when it cannot be found
    within the last `max_bytes`. Reads backwards in chunks, so a long file costs only its tail."""
    try:
        with open(os.path.expanduser(path), "rb") as f:
            pos = f.seek(0, 2)
            buf, read = b"", 0
            while pos > 0 and read < max_bytes:
                n = min(chunk, pos)
                pos -= n
                f.seek(pos)
                buf = f.read(n) + buf
                read += n
                lines = buf.split(b"\n")
                buf = lines[0] if pos > 0 else b""  # the first piece may be cut in half: keep it for the next round
                for raw in reversed(lines[1:] if pos > 0 else lines):
                    if not raw.strip():
                        continue
                    try:
                        t = _line_start(raw)
                    except Exception:
                        continue
                    if t is not None:
                        return t
            return None
    except Exception:
        return None


def _iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + "Z"


def record(payload, sess, sid, cwd, now=None):
    """Append one delivery row for a stop the gate has allowed, then reset the per-request counters in `sess`.
    Never raises. Returns the row, or None when nothing was recorded."""
    try:
        tp = payload.get("transcript_path")
        if not isinstance(tp, str) or not tp:
            return None
        start = find_start(tp)
        if start is None:
            return None
        end = time.time() if now is None else now
        if end < start or sess.get("delivery_start") == start:
            return None  # a clock oddity, or this request was already recorded (the stop hook ran again)
        row = {"ts": _iso(end), "session": sid, "project": sess.get("req_project") or cwd, "start": _iso(start),
               "end": _iso(end), "seconds": round(end - start, 1), "send_backs": int(sess.get("req_blocks", 0)),
               "check_s": round(float(sess.get("req_check_s", 0.0)), 1), "contract": bool(sess.get("req_contract")),
               "tool": store.tool()}
        store.append("deliveries", row)
        sess.update(delivery_start=start, req_blocks=0, req_check_s=0.0)
        store.save_session(sid, sess)
        return row
    except Exception as e:
        store.log_error("delivery", e)
        return None
