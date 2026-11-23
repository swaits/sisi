"""Rule 6 when a worker is unavailable: detect it wherever it arrives, record it, hand over the fallback.

A worker's unavailability reaches a main session as the result of a delegation tool call (the after-tool
hook) or as a later notice that a background or delegated task failed (the prompt hook). Both run the same
failure classifier (workers.classify_failure). Unavailability is never a quality judgement: nothing here
reads a rejected result, and a result that merely mentions a limit in a long report is not a failure.

What the agent is told, in at most six lines: which worker is out and until when, the router's next pick for the
same kind of work with its mechanism line (a host-native worker when every other provider is down), to fall
back now with the same brief, neither asking the person nor reporting it to them (worker availability is
internal, SPEC 9.7 and 17), and to cancel the failed task so it cannot resume later on a stale branch. When
nothing else is usable it says so and when the earliest worker is due; the person hears of it only if the
outcome or its timing changes for them, in one plain sentence about that consequence.
"""
import re, time

from . import store, workers

NOTICE = "<task-notification>"
_FAIL_MARKERS = ("[failed]", "api error", "error:", "failed:", "traceback", "exit code")
_DEFAULT_KIND = ("implementation", 2)


def _tag(text, name):
    m = re.search(r"<%s>(.*?)</%s>" % (name, name), text or "", re.S)
    return m.group(1).strip() if m else None


def looks_failed(text, failure_event=False, status=None):
    """Is this a failed delegation rather than a finished report that happens to mention a limit?"""
    if failure_event or str(status or "").lower() in ("failed", "error", "killed", "cancelled", "stopped"):
        return True
    head = (text or "").strip()[:200].lower()
    return any(k in head for k in _FAIL_MARKERS)


def failure_notice(prompt):
    """{"text", "use_id", "task_id"} when a prompt is the host's notice that a task failed, else None."""
    t = (prompt or "").lstrip()
    if t.startswith(NOTICE):
        status = _tag(t, "status")
        body = " ".join(x for x in (_tag(t, "summary"), _tag(t, "result")) if x)
        if looks_failed(body, status=None if status in (None, "completed") else status):
            return {"text": body or t, "use_id": _tag(t, "tool-use-id"), "task_id": _tag(t, "task-id")}
        return None
    if "[failed]" in t[:300].lower():
        return {"text": t, "use_id": None, "task_id": None}
    return None


def shell_notice(output):
    """A `sisi delegate` run that already recorded a worker as unavailable: (worker, text) from its output."""
    m = re.search(r"(\S+) is unavailable \(([^)]*)\)", output or "")
    return (m.group(1), output) if m else None


def fmt_time(ts):
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts))


def fallback_text(info, cwd, own_model):
    """At most six lines: what is down, the next worker, the instruction, the cancel line."""
    kind, diff = info.get("kind") or _DEFAULT_KIND[0], info.get("difficulty") or _DEFAULT_KIND[1]
    who = info.get("worker") or "a delegated worker"
    until = info.get("until")
    head = "sisi: %s is unavailable (%s)%s; recorded, and not a judgement of its work." % (
        who, info.get("reason") or "failed", (" until %s" % fmt_time(until)) if until else "")
    worker, mech, _n = workers.recommend(kind, diff, cwd, own_model)
    cancel = ("Cancel or interrupt the failed task with this host's own means: it may resume when its limit resets "
              "and redo work on a stale branch.")
    if worker:
        return "\n".join([head,
                          "Next for the same kind of work (%s, difficulty %s): %s (%s)." % (kind, diff, worker, mech),
                          "Fall back now with the same brief. Do not ask the person, and do not report this to them: "
                          "which worker is out is internal.", cancel])
    due = workers.earliest_due()
    return "\n".join([head,
                      "No other worker is usable now%s." % ((" (earliest due: %s at %s)" % (due[0], fmt_time(due[1]))) if due else ""),
                      "Do the work yourself with this session's own tools meanwhile; do not ask the person. Tell them "
                      "only if what they receive, or when, changes in a way they must act on: one plain sentence about "
                      "that consequence, not about the workers.", cancel])


def handle(m, sid, cwd, text, own_model=None, worker=None, run_id=None, record=True):
    """A failure message arrived. Classify it; record the worker down (when it can be identified and `record`);
    mark its pending run superseded; remember it in the meter for the question-dialog check; return the fallback
    text, or None when the text is not an unavailability. Never raises past the caller's guard."""
    if workers.classify_failure(text) is None:
        return None
    from . import orchestration
    worker = worker or workers.identify_worker(text)
    info = {"worker": worker, "ts": time.time()}
    run = None
    if run_id:
        run = next((r for r in workers.merged_runs() if r.get("id") == run_id), None)
        if run:
            info["kind"], info["difficulty"] = run.get("type"), run.get("difficulty")
    if worker and record:
        marked = workers.mark_unavailable(worker, text)
        if marked:
            info.update(until=marked["until"], reason="%s: %s" % (marked["reason"], marked["note"][:60]))
    elif worker:  # `sisi delegate` already recorded it: read the time it stored
        due = workers.read_availability().get(str(worker).lower()) or {}
        info.update(until=due.get("retry_at"), reason=("%s: %s" % (due.get("reason"), (due.get("note") or "")[:60])) if due else None)
    if not info.get("reason"):
        reason, note, _ = workers.classify_failure(text)
        info["reason"] = "%s: %s" % (reason, note[:60])
    if run_id:
        workers.append_record({"kind": "run-end", "run_id": run_id, "ts": round(time.time()), "status": "superseded",
                               "ended": round(time.time())})
    m["unavail"] = {k: info.get(k) for k in ("worker", "kind", "difficulty", "until", "reason")}
    orchestration._event(m, sid, "unavailable", worker=worker, run=run_id)
    return fallback_text(info, cwd, own_model)
