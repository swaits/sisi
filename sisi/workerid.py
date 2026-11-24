"""Who is a worker: the one decision, used by the contract guard, the meter, the delegation guard, the fallback
logic and the gate (R-7.1-1, R-7.2-2, R-16-1). A session is a worker when the host marks it as a subagent,
`sisi delegate` started it, or its FIRST user message opens like a brief (canon/worker-openings.json). A session
a person started is a main thread. Fails open: an error is "main thread" (the safe default), never stored."""
import json, os

from . import paths, store

_DATA = {}


def _data():
    if not _DATA:
        try:
            with open(paths.canon("worker-openings.json"), encoding="utf-8") as f:
                _DATA.update(json.load(f))
        except (OSError, ValueError):
            return {}
    return _DATA


def _squash(text):
    return " ".join(str(text or "").split()).lower()


def opens_as_brief(text):
    """Does this first user message open like a brief: a listed phrase (or the template's first line) within the
    first `window` characters?"""
    d = _data()
    try:
        window = int(d.get("window") or 400)
    except (TypeError, ValueError):
        window = 400
    head = _squash(str(text or "")[:window * 3])[:window]
    phrases = [_squash(p) for p in d.get("openings") or [] if isinstance(p, str) and p.strip()]
    try:
        from . import brief
        phrases.append(_squash(brief.template().splitlines()[0]))
    except Exception:
        pass
    return any(p and p in head for p in phrases)


def _read_head(path, nbytes):
    """(bytes, whole) from the start of the file: `whole` says the file ended inside the bound."""
    with open(os.path.expanduser(path), "rb") as f:
        raw = f.read(nbytes + 1)
    return raw[:nbytes], len(raw) <= nbytes


def first_user_text(path):
    """(found, text): the first message the person typed, from only the head of the transcript. `found` is False
    when the transcript cannot be read or holds no such message yet."""
    from . import harvest
    try:
        nbytes = int(_data().get("head_bytes") or 1048576)
        raw, whole = _read_head(path, nbytes)
    except (OSError, TypeError, ValueError):
        return False, ""
    lines = raw.split(b"\n")
    if not whole:
        lines = lines[:-1]  # the last line is cut by the bound
    for line in lines:
        if b'"user"' not in line or b"toolUseResult" in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("type") == "user":
            text = harvest.typed_text(d)[0]
            if text is not None:
                return True, text
    return False, ""


def is_worker_session(payload, session_record, meter_record):
    """True for a worker or subagent session. A decision made from the transcript is written into
    `meter_record` (key "worker"); the caller saves it. Without a readable first message nothing is stored."""
    payload = payload if isinstance(payload, dict) else {}
    sess = session_record if isinstance(session_record, dict) else {}
    if store.is_subagent_payload(payload) or sess.get("subagent"):
        return True
    if not isinstance(meter_record, dict):
        return False
    if "worker" in meter_record:
        return bool(meter_record["worker"])
    tp = payload.get("transcript_path") or sess.get("transcript_path")
    if not isinstance(tp, str) or not tp:
        return False
    found, text = first_user_text(tp)
    if not found:
        return False
    meter_record["worker"] = opens_as_brief(text)
    meter_record["worker_from"] = "transcript"
    return bool(meter_record["worker"])


def session_is_worker(payload, sid, cwd=None):
    """The same decision for a caller holding no records: reads them, and keeps a new decision in the session's
    meter record so the transcript is read once."""
    try:
        from . import orchestration
        sid = sid or "cwd-" + (cwd or os.getcwd())
        sess = store.load_session(sid)
        m = orchestration._peek(sid)
        had = "worker" in m
        found = is_worker_session(payload, sess, m)
        if not had and "worker" in m:
            with orchestration.Meter(sid) as real:
                real.setdefault("worker", m["worker"])
                real.setdefault("worker_from", m.get("worker_from"))
                found = bool(real["worker"])
        return found
    except Exception as e:
        store.log_error("workerid", e)
        return False
