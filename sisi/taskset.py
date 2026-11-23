"""The task set: replayable human requests and brief tasks, graded honestly, split dev/holdout by id hash.

Kinds
  human  a genuine (not machine-written) main session in a rebuildable repo with a resolved start commit and at
         least one following commit. Grade:
           A  trusted for replay. Either the start commit is exact (sisi's own record) and no overlapping sibling
              session wrote anything, or there is no overlapping sibling at all and a test command exists. Both
              also need the session itself to have edited files or committed, so the following commits are
              plausibly its own.
           B  usable with some uncertainty: no overlapping writer sibling, or a test command exists, but the
              start commit is only estimated or siblings overlap.
           C  kept for analysis, not for replay: too many following commits to be one request, a first message too
              short to stand alone, a session that made no edits itself, overlapping writers with no test command, or
              a repeat of an earlier session's opening message in the same repo (a resume or fork).
         Every reason is stored with the task.
  brief  a subagent transcript: its brief, its parent session and, when a delegation-ledger record can be matched,
         the ledger outcome with a match confidence:
           high    one ledger record and one subagent fit each other uniquely (same project, worker class equals the
                   subagent model, ledger time within [start, end + 20 min], and minutes consistent when recorded)
           medium  the same unique pairing but the recorded minutes disagree with the transcript duration
           low     more than one candidate on either side: the outcome is NOT stored
           none    no candidate (or the worker is not a Claude subagent): no outcome
Split: sha256(task id) mod 100 < 70 is `dev`, else `holdout`. It depends on the id alone, so it never changes.
"""
import hashlib, json, os, time

from . import harvest, paths

DEV_PERCENT = 70
MATCH_SLACK_S = 1200
MAX_COMMITS_FOR_ONE_REQUEST = 40
MIN_REQUEST_CHARS = 15
WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def split_of(task_id):
    h = int(hashlib.sha256(str(task_id).encode()).hexdigest()[:8], 16)
    return "dev" if h % 100 < DEV_PERCENT else "holdout"


def grade_human(s, g):
    """(grade, [reasons]) for a session row `s` and its groundtruth row `g` (dict-likes)."""
    reasons = []
    exact = g["start_kind"] == "exact"
    has_test = bool(g["test_cmd"])
    tools = json.loads(s["tools"] or "{}")
    wrote = bool(s["ran_commit"]) or any(k in tools for k in WRITE_TOOLS)
    c = False
    reasons.append("start commit exact (sisi tick record)" if exact else "start commit estimated from commit dates")
    reasons.append("test command: %s" % g["test_cmd"] if has_test else "no test command detected")
    if g["overlap_any"]:
        reasons.append("%d overlapping sibling session(s), %d of them wrote" % (g["overlap_any"], g["overlap_writers"]))
    else:
        reasons.append("no overlapping sibling session")
    if g["n_commits"] > MAX_COMMITS_FOR_ONE_REQUEST:
        reasons.append("%d following commits: too many to be one request" % g["n_commits"]); c = True
    if len((s["first_message"] or "").strip()) < MIN_REQUEST_CHARS:
        reasons.append("request too short to stand alone"); c = True
    if not wrote:
        reasons.append("session itself made no edits or commits"); c = True
    if c:
        return "C", reasons
    if exact and g["overlap_writers"] == 0:
        return "A", reasons
    if g["overlap_any"] == 0 and has_test:
        return "A", reasons
    if g["overlap_writers"] == 0 or has_test:
        return "B", reasons
    reasons.append("overlapping writers and no test command")
    return "C", reasons


def _project_names(row, repo_root):
    names = set()
    for p in (row["cwd"], repo_root):
        if p:
            names.add(os.path.basename(p.rstrip("/")).lower())
    proj = (row["project"] or "").lower()
    for marker in ("-code-", "-work-"):
        if marker in proj:
            names.add(proj.split(marker, 1)[1])
    names.add(proj.rsplit("-", 1)[-1])
    return {n for n in names if n}


def ledger_path():
    """An optional JSON-lines ledger of delegated attempts and their judged outcomes. None unless configured:
    the SISI_LEDGER environment variable, or "ledger" in the personal config.json."""
    p = os.environ.get("SISI_LEDGER")
    if not p:
        try:
            from . import store
            p = store.config().get("ledger")
        except Exception:
            p = None
    return os.path.expanduser(p) if isinstance(p, str) and p else None


def read_ledger(home=None):
    p = ledger_path()
    out = []
    if not p:
        return out
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict) and d.get("kind") == "attempt" and isinstance(d.get("ts"), (int, float)):
                    out.append(d)
    except OSError:
        pass
    return out


def worker_class(worker):
    w = (worker or "").lower()
    for c in ("haiku", "sonnet", "opus"):
        if w == c or w.startswith(c + "-"):
            return c
    return None


def sub_class(models, meta):
    found = set()
    for m in list(models) + [str((meta or {}).get("model") or "")]:
        for c in ("haiku", "sonnet", "opus"):
            if c in m.lower():
                found.add(c)
    return found


def match_ledger(subs, ledger):
    """subs: [{id, t0, t1, names, classes}]. Returns {sub_id: (ledger_rec|None, confidence, note)}."""
    cand_of_sub, cand_of_led = {}, {}
    for s in subs:
        cl = []
        for L in ledger:
            wc = worker_class(L.get("worker"))
            if not wc or wc not in s["classes"]:
                continue
            if (str(L.get("project") or "").lower() not in s["names"]) or s["t0"] is None:
                continue
            if s["t0"] - 120 <= L["ts"] <= (s["t1"] or s["t0"]) + MATCH_SLACK_S:
                cl.append(L)
        cand_of_sub[s["id"]] = cl
        for L in cl:
            cand_of_led.setdefault(L["id"], []).append(s["id"])
    out = {}
    for s in subs:
        cl = cand_of_sub[s["id"]]
        if not cl:
            out[s["id"]] = (None, "none", "no ledger record with matching project, worker class and time")
        elif len(cl) == 1 and len(cand_of_led[cl[0]["id"]]) == 1:
            L = cl[0]
            dur = ((s["t1"] or s["t0"]) - s["t0"]) / 60.0
            mins = L.get("minutes")
            if isinstance(mins, (int, float)) and abs(mins - dur) > max(2.0, 0.5 * max(mins, dur)):
                out[s["id"]] = (L, "medium", "unique pairing, but ledger minutes %.1f vs transcript %.1f" % (mins, dur))
            else:
                out[s["id"]] = (L, "high", "unique pairing on project, worker class and time")
        else:
            out[s["id"]] = (None, "low", "%d ledger candidate(s), and a candidate may fit other subagents too" % len(cl))
    return out


def build(con, home=None):
    """Create or refresh tasks from harvested data. Existing tasks keep their split. Returns counts."""
    now = time.time()
    existing = {r["id"]: r["split"] for r in con.execute("SELECT id,split FROM tasks")}
    keep = set()
    n_human = 0
    q = ("SELECT s.*, g.repo_root, g.start_commit, g.start_kind, g.test_cmd, g.n_commits, g.overlap_any, g.overlap_writers "
         "FROM sessions s JOIN groundtruth g ON g.session_id=s.id WHERE s.kind='main' AND s.machine=0 "
         "AND g.repo_root IS NOT NULL AND g.start_commit IS NOT NULL AND g.n_commits>0 ORDER BY s.t0")
    first_seen = {}
    for s in con.execute(q):
        tid = "h-" + s["id"][:12]
        grade, reasons = grade_human(s, s)
        key = (s["repo_root"], (s["first_message"] or "").strip())
        if key in first_seen:  # a resumed or forked session repeats the opening message: not a second task
            reasons.append("same opening message as earlier session %s in this repo" % first_seen[key][:8])
            grade = "C"
        else:
            first_seen[key] = s["id"]
        keep.add(tid)
        _upsert(con, existing, now, id=tid, kind="human", session_id=s["id"], parent_id=None, grade=grade,
                reasons=json.dumps(reasons), repo_root=s["repo_root"], start_commit=s["start_commit"],
                start_kind=s["start_kind"], test_cmd=s["test_cmd"], request=s["first_message"], ledger_id=None,
                ledger_outcome=None, match_confidence=None, match_note=None)
        n_human += 1
    ledger = read_ledger(home)
    subs, rows = [], {}
    repo_of = {r["session_id"]: r["repo_root"] for r in con.execute("SELECT session_id,repo_root FROM groundtruth")}
    cwd_of = {r["id"]: dict(r) for r in con.execute("SELECT id,cwd,project FROM sessions WHERE kind='main'")}
    for s in con.execute("SELECT * FROM sessions WHERE kind='subagent' AND first_message IS NOT NULL"):
        parent = cwd_of.get(s["parent_id"]) or {"cwd": s["cwd"], "project": s["project"]}
        names = _project_names(parent, repo_of.get(s["parent_id"]))
        names |= _project_names({"cwd": s["cwd"], "project": s["project"]}, None)
        subs.append({"id": s["id"], "t0": s["t0"], "t1": s["t1"], "names": names,
                     "classes": sub_class(json.loads(s["models"] or "{}"), json.loads(s["meta"] or "{}"))})
        rows[s["id"]] = s
    matches = match_ledger(subs, ledger)
    for sid, s in rows.items():
        L, conf, note = matches[sid]
        tid = "b-" + sid
        keep.add(tid)
        reasons = ["subagent transcript with a brief", "ledger match: %s (%s)" % (conf, note)]
        _upsert(con, existing, now, id=tid, kind="brief", session_id=sid, parent_id=s["parent_id"],
                grade=None, reasons=json.dumps(reasons), repo_root=None, start_commit=None, start_kind=None,
                test_cmd=None, request=s["first_message"], ledger_id=L["id"] if L else None,
                ledger_outcome=L.get("outcome") if L else None, match_confidence=conf, match_note=note)
    stale = [t for t in existing if t not in keep]
    for t in stale:
        con.execute("DELETE FROM tasks WHERE id=?", (t,))
    con.commit()
    return {"human": n_human, "brief": len(rows), "removed": len(stale), "ledger_records": len(ledger)}


def _upsert(con, existing, now, **t):
    split = existing.get(t["id"]) or split_of(t["id"])  # an existing task never changes split
    cols = ["id", "kind", "session_id", "parent_id", "grade", "reasons", "split", "repo_root", "start_commit",
            "start_kind", "test_cmd", "request", "ledger_id", "ledger_outcome", "match_confidence", "match_note",
            "updated_at"]
    vals = [t[c] if c in t else None for c in cols]
    vals[cols.index("split")] = split
    vals[cols.index("updated_at")] = now
    if t["id"] in existing:
        con.execute("UPDATE tasks SET %s WHERE id=?" % ",".join(c + "=?" for c in cols[1:]), vals[1:] + [t["id"]])
    else:
        con.execute("INSERT INTO tasks(%s,created_at) VALUES(%s,?)" % (",".join(cols), ",".join("?" * len(cols))), vals + [now])


def list_tasks(con, kind=None, grade=None, split=None):
    q, a = "SELECT * FROM tasks WHERE 1=1", []
    for col, v in (("kind", kind), ("grade", grade), ("split", split)):
        if v:
            q += " AND %s=?" % col
            a.append(v)
    return [dict(r) for r in con.execute(q + " ORDER BY kind, COALESCE(grade,'~'), id", a)]


def get_task(con, tid):
    rows = list(con.execute("SELECT * FROM tasks WHERE id=? OR id LIKE ?", (tid, tid + "%")))
    return dict(rows[0]) if len(rows) == 1 else None


def counts(con):
    """{kind: {grade: {split: n}}} for the scoreboard."""
    out = {}
    for r in con.execute("SELECT kind, COALESCE(grade,'-') g, split, COUNT(*) n FROM tasks GROUP BY 1,2,3"):
        out.setdefault(r["kind"], {}).setdefault(r["g"], {})[r["split"]] = r["n"]
    return out
