"""Check statistics and the scoreboard.

Check statistics (from results.jsonl): per check id, and per verifier when records carry a `verifier` field:
runs, failures, timeouts. A check with MANY_RUNS or more runs and no failure or timeout is flagged
"never seen failing" (it may be a check that cannot fail). The `gate` pseudo-check is skipped.

Scoreboard: ISO weeks (Monday start, UTC) and repo, from the harvested main sessions that a human started
(first typed message not machine-written). Trends matter, so every week uses the same definitions:
  sessions              human-started main sessions whose first message falls in the week
  turns_per_session     typed user turns per session
  corrections_per_100   correction-like typed messages per 100 typed turns (the first message never counts)
  questions_per_100     assistant turns that ended on a question with no tool call, plus AskUserQuestion calls,
                        per 100 typed turns
  contract_share        share of sessions that used `sisi contract`/`sisi verify`
  premature_done_share  among sessions with at least one completion claim, the share where a claim was
                        immediately followed by a correction-like message (a claim can only be "followed" by
                        a correction if the session went on, so this is not "sessions ending on a claim")
Only weeks and repos with at least one session appear. Completion claims, questions and corrections are
regex heuristics; compare week with week, not with an absolute truth.
"""
import datetime, json, time

from . import harvest, store, taskset

MANY_RUNS = 10


def check_stats(results):
    by, byv = {}, {}
    for r in results:
        if not isinstance(r, dict) or not r.get("check") or r.get("check") == "gate":
            continue
        keys = [("check", r["check"], by)]
        if r.get("verifier"):
            keys.append(("verifier", r["verifier"], byv))
        for _, k, d in keys:
            s = d.setdefault(k, {"runs": 0, "failures": 0, "timeouts": 0, "total_s": 0.0, "timed_runs": 0})
            s["runs"] += 1
            if isinstance(r.get("duration_s"), (int, float)) and not isinstance(r.get("duration_s"), bool):
                s["total_s"] += r["duration_s"]  # for `sisi time`: which checks cost the most
                s["timed_runs"] += 1
                s["tier"] = r.get("tier", "fast")
            if r.get("status") == "failed":
                s["failures"] += 1
            elif r.get("status") == "timeout":
                s["timeouts"] += 1
    def fin(d):
        out = []
        for k, s in sorted(d.items()):
            s = dict(s, id=k)
            s["never_seen_failing"] = s["runs"] >= MANY_RUNS and s["failures"] == 0 and s["timeouts"] == 0
            out.append(s)
        return out
    return {"checks": fin(by), "verifiers": fin(byv)}


def iso_week(t):
    d = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).date()
    y, w, _ = d.isocalendar()
    return "%04d-W%02d" % (y, w)


def _blank():
    return {"sessions": 0, "turns": 0, "corrections": 0, "questions": 0, "contract": 0, "claim_sessions": 0, "premature_sessions": 0}


def _finish(a):
    n, t = a["sessions"], a["turns"]
    return {"sessions": n, "turns_per_session": round(t / n, 2) if n else None,
            "corrections_per_100": round(100.0 * a["corrections"] / t, 1) if t else None,
            "questions_per_100": round(100.0 * a["questions"] / t, 1) if t else None,
            "contract_share": round(a["contract"] / n, 3) if n else None,
            "premature_done_share": round(a["premature_sessions"] / a["claim_sessions"], 3) if a["claim_sessions"] else None}


def _add(a, r):
    a["sessions"] += 1
    a["turns"] += r["user_turns"]
    a["corrections"] += r["n_corrections"]
    a["questions"] += r["n_question_turns"] + r["n_ask"]
    a["contract"] += 1 if (r["used_contract"] or r["used_verify"]) else 0
    if r["n_completion_claims"]:
        a["claim_sessions"] += 1
        a["premature_sessions"] += 1 if r["n_premature_done"] else 0


def scoreboard(con):
    weeks, repos, wr = {}, {}, {}
    q = ("SELECT s.t0, s.user_turns, s.n_corrections, s.n_question_turns, s.n_ask, s.used_contract, s.used_verify, "
         "s.n_completion_claims, s.n_premature_done, g.repo_root FROM sessions s LEFT JOIN groundtruth g ON g.session_id=s.id "
         "WHERE s.kind='main' AND s.machine=0 AND s.t0 IS NOT NULL")
    for r in con.execute(q):
        repo = (r["repo_root"] or "(no repo)").rstrip("/").rsplit("/", 1)[-1]
        week = iso_week(r["t0"])
        for table, key in ((weeks, week), (repos, repo), (wr, (week, repo))):
            _add(table.setdefault(key, _blank()), r)
    return {"weeks": {k: _finish(v) for k, v in sorted(weeks.items())},
            "repos": {k: _finish(v) for k, v in sorted(repos.items())},
            "week_repo": {"%s %s" % k: _finish(v) for k, v in sorted(wr.items())},
            "tasks": taskset.counts(con)}
