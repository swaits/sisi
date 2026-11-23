"""Time to delivery: how long from the human's request to a verified stop, recorded by the gate
and read back as unit telemetry (`sisi status` reports it; the old `sisi time` command is gone).

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


# ---------------------------------------------------------------- reading (telemetry helpers)

DAY = 86400.0


def median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def percentile(xs, p):
    """Linear-interpolation percentile (p in 0..100) of a list of numbers; None when empty."""
    s = sorted(xs)
    if not s:
        return None
    k = (len(s) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _epoch(ts):
    from . import harvest
    return harvest.epoch(ts) if isinstance(ts, str) else None


def summarize(rows):
    secs = [r["seconds"] for r in rows]
    tot = sum(secs)
    chk = sum(min(r.get("check_s", 0.0), r["seconds"]) for r in rows)
    return {"n": len(rows), "median_s": median(secs), "p90_s": percentile(secs, 90),
            "check_share": (chk / tot) if tot > 0 else None,
            "send_back_deliveries": sum(1 for r in rows if r.get("send_backs", 0) > 0)}


def windows(rows, now):
    """(last 7 days, the 7 days before) of delivery rows, by their end time."""
    cur, prev = [], []
    for r in rows:
        if not (isinstance(r, dict) and isinstance(r.get("seconds"), (int, float))):
            continue
        t = _epoch(r.get("end") or r.get("ts"))
        if t is None:
            continue
        if now - 7 * DAY <= t <= now:
            cur.append(r)
        elif now - 14 * DAY <= t < now - 7 * DAY:
            prev.append(r)
    return cur, prev


def slow_checks(results, now, top=5):
    """The slowest checks by mean duration over the last 7 days, each with a suggestion."""
    from . import scorecard
    recent = [r for r in results if isinstance(r, dict) and (_epoch(r.get("ts")) or 0) >= now - 7 * DAY]
    out = []
    for s in scorecard.check_stats(recent)["checks"]:
        if s.get("timed_runs"):
            out.append({"id": s["id"], "mean_s": s["total_s"] / s["timed_runs"], "runs": s["runs"], "tier": s.get("tier", "fast")})
    out.sort(key=lambda x: -x["mean_s"])
    out = out[:top]
    for x in out:
        if x["mean_s"] < 5:
            x["suggestion"] = "quick enough: leave it in the fast tier"
        elif x["tier"] == "deep":
            x["suggestion"] = "already deep; split it so a quick part can run in the gate"
        else:
            x["suggestion"] = 'mark as "tier": "deep" if it can wait, or split it into a quick part and a slow part'
    return out


def report(now=None):
    now = time.time() if now is None else now
    rows = store.read("deliveries")
    cur, prev = windows(rows, now)
    by_project = {}
    for label, group in (("cur", cur), ("prev", prev)):
        for r in group:
            by_project.setdefault(r.get("project") or "(unknown)", {"cur": [], "prev": []})[label].append(r)
    return {"now": _iso(now), "all": {"last7": summarize(cur), "prev7": summarize(prev)},
            "projects": {p: {"last7": summarize(v["cur"]), "prev7": summarize(v["prev"])} for p, v in sorted(by_project.items())},
            "slowest_checks": slow_checks(store.read("results"), now)}


def fmt_s(s):
    if s is None:
        return "-"
    s = int(round(s))
    if s < 60:
        return "%ds" % s
    if s < 3600:
        return "%dm%02ds" % (s // 60, s % 60)
    return "%dh%02dm" % (s // 3600, (s % 3600) // 60)


