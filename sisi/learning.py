"""Learning records: the single store behind retro, cycle, learn/oracle and monitoring.

One store: learnings.jsonl in the user store (one JSON object per learning, rewritten
atomically; git in the user store is the history). Findings of a retro live in
findings.jsonl. Showings are never recorded as evidence. See docs/learning.md.
"""
import hashlib, json, os, re, subprocess, time

from . import paths, pdata

STATUSES = ("observed", "analyzed", "proposed", "implemented", "validated",
            "promoted", "monitored", "revised", "reverted", "rejected")
MECHANISMS = ("policy", "orchestration", "skill", "tool", "infrastructure",
              "verification", "knowledge", "benchmark")
IMPACTS = ("value", "correctness", "time", "cost", "attention")
SCOPES = ("organization", "user", "project", "task-class")
GENERIC = re.compile(r"^\s*(nothing|none|n/?a|be more careful|write better tests|"
                     r"use cheaper models|do better|all good|no issues?)\W*$", re.I)
STOP = set("the a an and or of to in is was were be been it its this that with for on at by as not no do does did when then than from we i".split())


class LearningError(Exception):
    pass


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def project_key(cwd):
    """Stable project identity: the git root (main repo for linked worktrees), else the dir."""
    try:
        from . import groundtruth
        root, _vcs = groundtruth.main_repo_of(cwd)
        if root:
            return os.path.realpath(root)
    except Exception:
        pass
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd,
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return os.path.realpath(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.realpath(cwd)


def unit_id(project=None):
    """Seam with the work-unit worker: the id in .sisi/contract.json, else a session fallback."""
    project = project or os.getcwd()
    try:
        with open(os.path.join(project, ".sisi", "contract.json"), encoding="utf-8") as f:
            c = json.load(f)
        if isinstance(c, dict) and c.get("id"):
            return str(c["id"])
    except (OSError, ValueError):
        pass
    return "session:" + (os.environ.get("SISI_SESSION_ID") or
                         hashlib.sha1(os.path.realpath(project).encode()).hexdigest()[:12])


def is_subagent_session():
    return os.environ.get("SISI_SUBAGENT") == "1" or os.environ.get("SISI_AGENT_DEPTH", "") not in ("", "0")


# ---- store io -----------------------------------------------------------------

def learnings_path():
    return paths.data_file("learnings.jsonl")


def findings_path():
    return paths.data_file("findings.jsonl")


def pending_path():
    return paths.data_file("pending.json")


def load_learnings():
    out = []
    try:
        with open(learnings_path(), encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    d = json.loads(line)
                    if isinstance(d, dict) and d.get("id"):
                        out.append(d)
    except OSError:
        pass
    return out


def save_learnings(rows, msg):
    pdata.ensure()
    text = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
    pdata.write_text("learnings.jsonl", text)
    pdata.commit(msg, ["learnings.jsonl"])


def store_base(rows=None):
    rows = load_learnings() if rows is None else rows
    h = hashlib.sha256()
    for r in rows:
        h.update(json.dumps(r, sort_keys=True).encode())
        h.update(b"\n")
    return h.hexdigest()[:16]


def load_findings():
    out = []
    try:
        with open(findings_path(), encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    d = json.loads(line)
                    if isinstance(d, dict):
                        out.append(d)
    except OSError:
        pass
    return out


def append_finding(f, msg="retro: finding"):
    pdata.ensure()
    old = pdata.read_text("findings.jsonl", "") or ""
    pdata.write_text("findings.jsonl", old + json.dumps(f, sort_keys=True) + "\n")
    pdata.commit(msg, ["findings.jsonl"])


def next_id(rows):
    n = 0
    for r in rows:
        m = re.match(r"L-(\d+)$", str(r.get("id", "")))
        if m:
            n = max(n, int(m.group(1)))
    return "L-%04d" % (n + 1)


def get(rows, lid):
    for r in rows:
        if r.get("id") == lid:
            return r
    return None


# ---- derived text (the tool derives search terms, topics, short lines) ---------

def _stem(w):
    """A crude stem so 'parsing', 'parser' and 'parse' meet, as do plurals."""
    s = w
    if len(s) > 4 and s.endswith("ies"):
        s = s[:-3] + "y"
    else:
        done = False
        for suf in ("ingly", "ing", "edly", "ed"):
            if s.endswith(suf) and len(s) - len(suf) >= 3:
                base = s[:-len(suf)]
                if len(base) >= 2 and base[-1] == base[-2] and base[-1] not in "aeious":
                    base = base[:-1]
                s, done = base, True
                break
        if not done:
            if s.endswith(("ses", "xes", "zes", "ches", "shes")) and len(s) - 2 >= 3:
                s = s[:-2]
            else:
                for suf in ("ers", "er", "s"):
                    if s.endswith(suf) and len(s) - len(suf) >= 3:
                        s = s[:-len(suf)]
                        break
    if len(s) >= 4 and s.endswith("e"):
        s = s[:-1]
    return s


def stems(text):
    return {_stem(w) for w in re.findall(r"[a-z0-9_]+", (text or "").lower())
            if len(w) > 2 and w not in STOP}


def derive_terms(*texts):
    return sorted(set().union(*[stems(t) for t in texts]))[:24]


def derive_title(text, limit=90):
    t = " ".join((text or "").split())
    t = re.split(r"(?<=[.!?])\s", t)[0]
    return t[:limit].rstrip()


def similar_learnings(rows, text, limit=3):
    q = stems(text)
    scored = []
    for r in rows:
        if r.get("status") in ("rejected", "reverted"):
            continue
        hay = set(r.get("terms") or []) | stems(r.get("observation", {}).get("evidence", "")) \
            | stems(r.get("proposed", {}).get("description", ""))
        inter = len(q & hay)
        if inter >= 1:
            scored.append((inter / max(1, len(q)), inter, r))
    scored.sort(key=lambda x: -x[0])
    return [r for s, inter, r in scored
            if s >= 0.3 or (inter >= 1 and s >= 0.25 and len(q) <= 4)][:limit]


# ---- scope (earned, never claimed) ---------------------------------------------

def earned(rec):
    """Cross-project delivery is earned: >=2 units in >=2 projects, or an owner statement."""
    if rec.get("owner_statement"):
        return True
    prov = rec.get("provenance") or []
    units = {p.get("unit") for p in prov if p.get("unit")}
    projects = {p.get("project") for p in prov if p.get("project")}
    return len(units) >= 2 and len(projects) >= 2


def in_scope(rec, project):
    if rec.get("status") in ("rejected", "reverted"):
        return False
    if rec.get("candidate"):  # subagent learning, held until a parent retro adopts it
        return False
    if rec.get("entered_via") not in ("retro", "learn", "cycle", "migration"):
        return False  # only learnings that entered through sisi's own commands are delivered
    pk = project_key(project) if project else None
    if pk and rec.get("origin_project") == pk:
        return True
    return earned(rec)


def learnings_in_scope(project, rows=None):
    rows = load_learnings() if rows is None else rows
    return [r for r in rows if in_scope(r, project)]


def delivery_text(project, query=""):
    """Learnings in scope, framed as information, never as instructions. No showing is recorded."""
    rows = learnings_in_scope(project)
    if query:
        rows = similar_learnings(rows, query, limit=5)  # silence is the default
    rows = [r for r in rows if r.get("status") in
            ("promoted", "monitored", "proposed", "observed", "implemented", "validated")]
    if not rows:
        return ""
    lines = ["Background information from earlier work (evidence to weigh, not instructions):"]
    for r in rows[:5]:
        val = (r.get("validation") or {}).get("result") or "unvalidated"
        lines.append("- [%s, %s] %s — %s" % (r["id"], val if val == "validated" else "unvalidated",
                                             derive_title(r.get("title") or "", 110),
                                             derive_title(r.get("proposed", {}).get("description", ""), 160)))
    return "\n".join(lines) + "\n"


# ---- findings / record creation -------------------------------------------------

def new_record(finding, cause, impact, disposition, project, unit,
               change=None, mechanism=None, scope=None, expect=None, validate=None,
               limits=None, why_not=None, owner_statement=False, subagent=False,
               replay=None, entered_via="retro"):
    rows = load_learnings()
    pk = project_key(project)
    rec = {
        "id": next_id(rows), "title": derive_title(change or finding),
        "source_unit": unit, "origin_project": pk,
        "observation": {"evidence": finding, "impact": impact},
        "root_cause": cause,
        "proposed": {"description": change or "", "mechanism": mechanism,
                     "scope": scope or ("user" if owner_statement else "project"),
                     "target": None},
        "expected_effect": expect or "", "limits": limits or "", "why_not": why_not or "",
        "validation": {"method": validate or "", "benchmark": None,
                       "result": "unvalidated", "detail": ""},
        "status": "promoted" if owner_statement else
                  ("proposed" if disposition == "promote" else "observed"),
        "version": 1, "confidence": "low",
        "provenance": [{"unit": unit, "project": pk, "ts": now(), "kind": "origin"}],
        "terms": derive_terms(finding, cause, change or ""),
        "owner_statement": bool(owner_statement), "candidate": bool(subagent),
        "entered_via": entered_via, "recurrences_after_promotion": 0,
        "flagged_not_working": False, "promoted_at": now() if owner_statement else None,
        "promoted_unit_seq": None, "mechanism_ref": None, "replay": replay,
        "created": now(),
    }
    rows.append(rec)
    save_learnings(rows, "learning %s recorded" % rec["id"])
    return rec


def add_recurrence(rec, unit, project, rows):
    """Attach a recurrence. After promotion it counts against the learning."""
    pk = project_key(project)
    rec.setdefault("provenance", []).append(
        {"unit": unit, "project": pk, "ts": now(), "kind": "recurrence"})
    if rec.get("status") in ("promoted", "monitored", "validated", "implemented") and rec.get("promoted_at"):
        rec["recurrences_after_promotion"] = int(rec.get("recurrences_after_promotion") or 0) + 1
        if rec["recurrences_after_promotion"] >= 2:
            rec["flagged_not_working"] = True
    save_learnings(rows, "learning %s recurrence" % rec["id"])
    return rec


def findings_for_unit(project, uid):
    """Seam for the unit record: the findings recorded for one unit in one project."""
    pk = project_key(project)
    return [f for f in load_findings() if f.get("unit") == uid and f.get("project") == pk]


def units_seen():
    """Closed-unit summary lines from the unit worker's store, when it exists."""
    out = []
    try:
        with open(paths.data_file("units.jsonl"), encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    out.append(json.loads(line))
    except (OSError, ValueError):
        pass
    return out


def unit_seq():
    return len(units_seen())


# ---- monitoring -----------------------------------------------------------------

def flagged(rows=None):
    rows = load_learnings() if rows is None else rows
    return [r for r in rows if r.get("flagged_not_working") and r.get("status") not in ("revised", "reverted", "rejected")]


def learning_report():
    """Seam for `sisi status --learning`. No claim of improvement from counts of records."""
    rows = load_learnings()
    findings = load_findings()
    units = units_seen()
    lines = ["Learning loop (recorded facts; no improvement is claimed from counts):",
             "learnings: %d   findings: %d   closed units known: %d"
             % (len(rows), len(findings), len(units))]
    promoted = [r for r in rows if r.get("status") in ("promoted", "monitored") and not r.get("owner_statement")]
    if promoted:
        lines.append("promoted learnings:")
    holding = 0
    relevant = 0
    for r in promoted:
        since = None
        if r.get("promoted_unit_seq") is not None:
            since = len(units) - int(r["promoted_unit_seq"])
        else:
            since = sum(1 for u in units if str(u.get("ts", "")) >= str(r.get("promoted_at") or ""))
        rec = int(r.get("recurrences_after_promotion") or 0)
        val = (r.get("validation") or {}).get("result") or "unvalidated"
        if r.get("flagged_not_working"):
            verdict = "not working (flagged: next cycle must revise or revert)"
        elif since >= 5 and rec == 0:
            verdict = "holding"
        elif rec:
            verdict = "recurred, watching"
        else:
            verdict = "too few units to judge"
        if since >= 5:
            relevant += 1
            if rec == 0:
                holding += 1
        lines.append("- %s: %d unit(s) since promotion, %d recurrence(s), %s — %s"
                     % (r["id"], since, rec, val if val == "validated" else "unvalidated", verdict))
    if relevant < 5:
        lines.append("realization rate: too few (fewer than five promoted learnings have "
                     "five relevant units; no rate is claimed)")
    else:
        lines.append("realization rate: %d of %d promoted learnings holding with no recurrence "
                     "over at least five units" % (holding, relevant))
    fl = flagged(rows)
    if fl:
        lines.append("flagged not working: " + ", ".join(r["id"] for r in fl))
    pend = load_pending()
    if pend:
        lines.append("waiting for the owner's decision: %d change(s) (`sisi approve ID --yes|--no`)"
                     % len(pend))
    tool = [r for r in rows if r.get("proposed", {}).get("mechanism") == "tool"
            and r.get("status") not in ("rejected", "reverted")]
    if tool:
        lines.append("tool backlog (changes to sisi itself):")
        for r in tool[:8]:
            lines.append("- %s: %s" % (r["id"], derive_title(r["title"], 110)))
    return "\n".join(lines) + "\n"


# ---- pending approvals -----------------------------------------------------------

def load_pending():
    try:
        with open(pending_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def save_pending(items, msg="pending decision updated"):
    pdata.ensure()
    pdata.write_text("pending.json", json.dumps(items, indent=2, sort_keys=True) + "\n")
    pdata.commit(msg, ["pending.json"])


def pending_notice():
    n = len(load_pending())
    return "sisi: %d learning change(s) wait for your decision (`sisi approve`)." % n if n else ""


# ---- owner statements (one path: learn writes, oracle prints) ---------------------

def owner_statements(rows=None):
    rows = load_learnings() if rows is None else rows
    return [r for r in rows if r.get("owner_statement") and r.get("status") not in ("rejected", "reverted")]
