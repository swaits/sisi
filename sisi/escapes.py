"""Escape candidates: work declared verified (or finished) that then turned out wrong. Evidence pointers only.

Kinds
  contract-then-correction   a contract run passed (every check passed or awaits a human) in a session, and a
                             correction-like user message came later in that session.
  contract-then-fix-session  a contract run passed in a session; within 7 days a later main session in the same
                             repo touched at least one of the same files (by following commits) and opened with a
                             fix-like request.
  premature-done             independent of sisi records: an assistant turn ended on a completion claim and the
                             very next typed user message was correction-like.
Results join to sessions by the `session` field when present, otherwise by time and project: a session whose
window contains the run and whose cwd or repo is inside the run's project. If more than one session fits, the
candidate is marked `ambiguous`. These are candidates for a human or a model to look at, not conclusions.
"""
import json, re

from . import harvest, store

WEEK_S = 7 * 86400
_FIXLIKE = re.compile(r"\b(fix|bug|broken|wrong|regress|revert|fails?|failing|doesn'?t work|not working|error|crash)", re.I)


def passed_runs(results):
    """[{ts, t, project, contract, session, run}] for runs whose checks all passed."""
    groups = {}
    for r in results:
        if not isinstance(r, dict) or r.get("check") == "gate":
            continue
        key = r.get("run") or "%s|%s|%s" % (r.get("ts"), r.get("contract"), r.get("project"))
        groups.setdefault(key, []).append(r)
    out = []
    for key, rs in groups.items():
        if all(x.get("status") in ("passed", "awaiting-human") for x in rs) and any(x.get("status") == "passed" for x in rs):
            t = harvest.epoch(rs[0].get("ts") or "")
            if t is not None:
                out.append({"ts": rs[0]["ts"], "t": t, "project": rs[0].get("project"), "contract": rs[0].get("contract"),
                            "session": rs[0].get("session"), "run": key})
    return sorted(out, key=lambda x: x["t"])


def _inside(path, parent):
    if not path or not parent:
        return False
    p, q = path.rstrip("/"), parent.rstrip("/")
    return p == q or p.startswith(q + "/") or q.startswith(p + "/")


def attribute(run, sessions):
    """Sessions (rows) the run can be attributed to: by session id when it names one, else by time and project."""
    if run["session"]:
        hit = [s for s in sessions if s["id"] == run["session"]]
        if hit:
            return hit, False
    hit = [s for s in sessions if s["t0"] is not None and s["t0"] <= run["t"] <= (s["t1"] or s["t0"]) + 60
           and (_inside(s["cwd"], run["project"]) or _inside(s["repo_root"], run["project"]))]
    return hit, len(hit) > 1


def find(con, results=None):
    results = store.read("results") if results is None else results
    sessions = [dict(r) for r in con.execute(
        "SELECT s.id, s.cwd, s.t0, s.t1, s.first_message, s.machine, g.repo_root, g.files, g.start_kind "
        "FROM sessions s LEFT JOIN groundtruth g ON g.session_id=s.id WHERE s.kind='main'")]
    out = []
    for run in passed_runs(results):
        hit, ambiguous = attribute(run, sessions)
        for s in hit:
            later = con.execute("SELECT idx, ts, t FROM user_msgs WHERE session_id=? AND correction=1 AND t>? ORDER BY t",
                                (s["id"], run["t"])).fetchall()
            for m in later[:3]:
                out.append({"kind": "contract-then-correction", "session": s["id"], "run": run["run"], "contract": run["contract"],
                            "passed_at": run["ts"], "evidence": {"user_msg_idx": m["idx"], "at": m["ts"]}, "ambiguous": ambiguous})
            files = set(json.loads(s["files"] or "[]"))
            if files and s["repo_root"]:
                for o in sessions:
                    if o["id"] == s["id"] or o["repo_root"] != s["repo_root"] or o["machine"] or o["t0"] is None:
                        continue
                    if not (run["t"] < o["t0"] <= run["t"] + WEEK_S):
                        continue
                    common = files & set(json.loads(o["files"] or "[]"))
                    if common and _FIXLIKE.search((o["first_message"] or "")[:1500]):
                        out.append({"kind": "contract-then-fix-session", "session": s["id"], "run": run["run"],
                                    "contract": run["contract"], "passed_at": run["ts"],
                                    "evidence": {"later_session": o["id"], "common_files": sorted(common)[:10]},
                                    "ambiguous": ambiguous})
    for r in con.execute("SELECT m.session_id, m.idx, m.ts FROM user_msgs m WHERE m.correction=1 AND m.after_completion=1 ORDER BY m.t"):
        out.append({"kind": "premature-done", "session": r["session_id"], "evidence": {"user_msg_idx": r["idx"], "at": r["ts"]},
                    "ambiguous": False})
    return out
