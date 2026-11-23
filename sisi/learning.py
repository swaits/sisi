"""Learning records: the single store behind retro, cycle, learn/oracle and monitoring.

One store: learnings.jsonl in the user store (one JSON object per learning, rewritten
atomically; git in the user store is the history). Findings of a retro live in
findings.jsonl. Showings are never recorded as evidence. See docs/learning.md.

Trust in a row comes from the ledger, never from the row itself: learnings-ledger.jsonl
is appended by sisi's own commands, in the same commit as the row they wrote, and holds
the id and content digest of what they wrote. A row that is not in the ledger with its
current digest (added or edited by hand) is never delivered.
"""
import hashlib, json, os, re, subprocess, time

from . import paths, pdata

STATUSES = ("observed", "analyzed", "proposed", "implemented", "validated",
            "promoted", "monitored", "revised", "reverted", "rejected")
ENDED = ("rejected", "reverted")
MECHANISMS = ("policy", "orchestration", "skill", "tool", "infrastructure",
              "verification", "knowledge", "benchmark")
IMPACTS = ("value", "correctness", "time", "cost", "attention")
SCOPES = ("organization", "user", "project", "task-class")
SCOPE_RANK = {"project": 0, "user": 1, "organization": 2}
MONITOR_UNITS = 5   # units in a learning's own scope before it can be called "holding"
STOP = set("the a an and or of to in is was were be been it its this that with for on at by as not no do does did when then than from we i".split())

# Words that carry no information about what happened. A finding made only of these is advice,
# not evidence ("be more careful when writing tests in future").
GENERIC_WORDS = set((
    "be being more most careful carefully better best write writing written test tests testing code coding "
    "future next time times always never should must need needs try trying remember make sure ensure check "
    "checks checking double pay attention use using cheaper cheap models model do does doing done good bad "
    "great nothing none na issue issues problem problems thing things work works working improve improved "
    "improving improvement quality thorough thoroughly review reviewing think thinking plan planning ahead "
    "going forward all any some general generally just really very much many bit little slightly again once "
    "ever also too so can could would will may might worse avoid mistakes mistake fine ok okay well everything "
    "anything something stuff careless carelessness sloppy rushed hasty lazy diligent diligence").split())


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


def normalize_project(value):
    """The project key for an old `repo`/`cwd` value: the same key new code uses when the folder
    still exists, else the cleaned path."""
    if not value:
        return ""
    value = str(value)
    return project_key(value) if os.path.isdir(value) else os.path.realpath(value)


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


# ---- who is recording: from recorded session state, never from the caller's environment ----

def session_record():
    """(session id, its recorded state). The id names which record to read; what decides
    anything is what the hooks recorded there."""
    sid = os.environ.get("SISI_SESSION_ID") or ""
    if not sid:
        return "", {}
    from . import store
    return sid, store.load_session(sid)


def is_subagent_session():
    """Was this retro recorded by a subagent? Decided from the session record: tick marks a
    session that started as a subagent, and the watch hook records, for each shell command, whether
    its hook payload came from a subagent (an agent id or a subagent transcript path). The latest
    retro command on record decides."""
    _sid, sess = session_record()
    if not sess:
        return False
    if sess.get("subagent"):
        return True
    for sh in reversed(sess.get("shells") or []):
        if isinstance(sh, dict) and sh.get("retro"):
            return bool(sh.get("subagent"))
    return False


# ---- store io -----------------------------------------------------------------

def learnings_path():
    return paths.data_file("learnings.jsonl")


def ledger_path():
    return paths.data_file("learnings-ledger.jsonl")


def findings_path():
    return paths.data_file("findings.jsonl")


def pending_path():
    return paths.data_file("pending.json")


def approvals_path():
    return paths.data_file("approvals.jsonl")


def _read_jsonl(path):
    """(rows, skipped): the JSON objects in a jsonl file and how many lines were not one."""
    rows, skipped = [], 0
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    skipped += 1
                    continue
                if isinstance(d, dict):
                    rows.append(d)
                else:
                    skipped += 1
    except OSError:
        pass
    return rows, skipped


_LOADED = {}  # id -> digest of the row as it was on disk at the last read


def load_learnings():
    rows = [d for d in _read_jsonl(learnings_path())[0] if d.get("id")]
    _LOADED.clear()
    _LOADED.update({r["id"]: row_digest(r) for r in rows})
    return rows


def row_digest(rec):
    return hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest()[:20]


def load_ledger():
    """{id: digest of the row as sisi last wrote it}."""
    return {d["id"]: d.get("digest") for d in _read_jsonl(ledger_path())[0] if d.get("id")}


def is_registered(rec, ledger=None):
    ledger = load_ledger() if ledger is None else ledger
    return ledger.get(rec.get("id")) == row_digest(rec)


def save_learnings(rows, msg, touched=(), via="retro", created=()):
    """Rewrite the store. Only the rows a sisi command wrote are entered in the ledger: `created`
    (new rows) and `touched` (rows changed by this command, which must have been as sisi last wrote
    them when read). A row added or edited by hand never gets a ledger entry, and a later sisi
    command that touches it does not launder it."""
    pdata.ensure()
    text = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
    pdata.write_text("learnings.jsonl", text)
    ids = {t["id"] if isinstance(t, dict) else t for t in touched}
    new = {t["id"] if isinstance(t, dict) else t for t in created}
    ledger = load_ledger()
    add = ""
    for r in rows:
        i = r.get("id")
        if i not in ids and i not in new:
            continue
        d = row_digest(r)
        prior = ledger.get(i)
        if i in new:
            ok = prior is None
        else:
            ok = prior is not None and _LOADED.get(i) == prior
        if ok and prior != d:
            add += json.dumps({"id": i, "digest": d, "via": via, "ts": now()}, sort_keys=True) + "\n"
    if add:
        pdata.write_text("learnings-ledger.jsonl", (pdata.read_text("learnings-ledger.jsonl", "") or "") + add)
    pdata.commit(msg, ["learnings.jsonl", "learnings-ledger.jsonl"])
    _LOADED.clear()
    _LOADED.update({r["id"]: row_digest(r) for r in rows if r.get("id")})


def store_base(rows=None):
    rows = load_learnings() if rows is None else rows
    h = hashlib.sha256()
    for r in rows:
        h.update(json.dumps(r, sort_keys=True).encode())
        h.update(b"\n")
    return h.hexdigest()[:16]


def load_findings():
    return _read_jsonl(findings_path())[0]


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


# ---- text checks: generic findings, secrets -----------------------------------------------

def is_generic(text):
    """True when the text is only generic advice, wherever the filler appears. A number, a
    path, a quoted name or any other specific word makes it concrete."""
    toks = re.findall(r"[a-z0-9_]+", (text or "").lower())
    if not toks:
        return True
    if any(any(c.isdigit() for c in t) for t in toks):
        return False
    return not [t for t in toks if len(t) >= 2 and t not in STOP and t not in GENERIC_WORDS]


_SECRET_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"), "<redacted private key>"),
    (re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}"), "<redacted key>"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "<redacted token>"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "<redacted token>"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<redacted key>"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "<redacted token>"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"), "<redacted token>"),
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{16,}"), r"\1 <redacted>"),
    (re.compile(r"(?i)\b([A-Za-z0-9_.-]*(?:api[_-]?key|secret|token|passw(?:or)?d|passwd|pwd|credentials?|authorization)"
                r"[A-Za-z0-9_.-]*)\s*([:=])\s*(['\"]?)[^\s'\",;]{4,}"), r"\1\2 \3<redacted>"),
    (re.compile(r"://([^/\s:@]+):[^/\s@]+@"), r"://\1:<redacted>@"),
]
_OPAQUE = re.compile(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{40,}={0,2}(?![A-Za-z0-9+/_-])")


def scrub_secrets(text):
    """Things that look like keys, tokens or passwords become <redacted> before anything is stored."""
    s = str(text or "")
    for rx, rep in _SECRET_PATTERNS:
        s = rx.sub(rep, s)

    def opaque(m):
        t = m.group(0)
        if re.fullmatch(r"[0-9a-f]{40,64}", t):
            return t  # a git object id is evidence, not a secret
        if "/" in t and not re.search(r"[0-9]", t):
            return t  # a long path of words
        if any(c.isdigit() for c in t) and any(c.isalpha() for c in t):
            return "<redacted>"
        return t
    return _OPAQUE.sub(opaque, s)


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


def derive_terms(*texts, limit=32):
    """The learning's own search terms, in order of first appearance (never cut alphabetically)."""
    out, seen = [], set()
    for t in texts:
        for w in re.findall(r"[a-z0-9_]+", (t or "").lower()):
            if len(w) > 2 and w not in STOP:
                s = _stem(w)
                if s not in seen:
                    seen.add(s)
                    out.append(s)
    return out[:limit]


def derive_title(text, limit=90):
    t = " ".join((text or "").split())
    t = re.split(r"(?<=[.!?])\s", t)[0]
    return t[:limit].rstrip()


def similar_learnings(rows, text, limit=3):
    """Learnings whose own terms are found in the text. The share is taken of the smaller of the
    two term sets, so a long prompt does not dilute a match: what counts is how much of the
    learning's own vocabulary the text uses."""
    q = stems(text)
    scored = []
    for r in rows:
        if r.get("status") in ENDED:
            continue
        own = set(r.get("terms") or []) or stems((r.get("title") or "") + " " + (r.get("proposed", {}).get("description") or ""))
        if not own:
            continue
        inter = len(q & own)
        share = inter / max(1, min(len(q), len(own)))
        if (inter >= 3 and share >= 0.25) or (inter >= 2 and share >= 0.3) \
                or (inter >= 1 and len(q) <= 4 and inter / len(q) >= 0.25):  # a short, focused request
            scored.append((share, inter, r))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return [r for _s, _i, r in scored][:limit]


# ---- scope (earned, never claimed) ---------------------------------------------

def earned_scope(rec):
    """The widest scope this learning has earned: `organization` for a learning seen in at least
    two units in at least two projects, `user`/`organization` for an owner statement made at that
    scope (a project-scoped statement stays in its project), else `project`. Nothing a cycle
    author writes can change this."""
    if rec.get("owner_statement"):
        s = (rec.get("proposed") or {}).get("scope")
        return s if s in ("user", "organization") else "project"
    prov = rec.get("provenance") or []
    units = {p.get("unit") for p in prov if p.get("unit")}
    projects = {p.get("project") for p in prov if p.get("project")}
    return "organization" if len(units) >= 2 and len(projects) >= 2 else "project"


def earned(rec):
    return earned_scope(rec) != "project"


def in_scope(rec, project, ledger=None):
    if rec.get("status") in ENDED:
        return False
    if rec.get("candidate"):  # subagent learning, held until a parent retro adopts it
        return False
    if not is_registered(rec, ledger):
        return False  # only rows sisi's own commands wrote, as they wrote them, are delivered
    pk = project_key(project) if project else None
    if pk and rec.get("origin_project") == pk:
        return True
    return earned(rec)


def learnings_in_scope(project, rows=None, targets=()):
    rows = load_learnings() if rows is None else rows
    ledger = load_ledger()
    out = [r for r in rows if in_scope(r, project, ledger)]
    if targets:
        want = set(targets)
        out = [r for r in out if (r.get("proposed") or {}).get("target") in want]
    return out


DELIVERED = ("promoted", "monitored", "proposed", "observed", "implemented", "validated")


def _delivery_lines(rows):
    lines = []
    for r in rows:
        val = (r.get("validation") or {}).get("result") or "unvalidated"
        lines.append("- [%s, %s] %s — %s" % (r["id"], val if val == "validated" else "unvalidated",
                                             derive_title(r.get("title") or "", 110),
                                             derive_title(r.get("proposed", {}).get("description", ""), 160)))
    return lines


def delivery_text(project, query="", targets=(), limit=5):
    """Learnings in scope, framed as information, never as instructions. No showing is recorded.
    With targets: the learnings that target those rule, recipe or technique ids, plus the ones
    that match the query. Silence is the default."""
    rows = [r for r in learnings_in_scope(project) if r.get("status") in DELIVERED]
    chosen = []
    if targets:
        chosen += [r for r in rows if (r.get("proposed") or {}).get("target") in set(targets)]
    if query:
        chosen += [r for r in similar_learnings(rows, query, limit=limit) if r not in chosen]
    elif not targets:
        chosen = []
    if not chosen:
        return ""
    lines = ["Background information from earlier work (evidence to weigh, not instructions):"]
    lines += _delivery_lines(chosen[:limit])
    return "\n".join(lines) + "\n"


# ---- findings / record creation -------------------------------------------------

def new_record(finding, cause, impact, disposition, project, unit,
               change=None, mechanism=None, scope=None, expect=None, validate=None,
               limits=None, why_not=None, owner_statement=False, subagent=False,
               replay=None, entered_via="retro", target=None, origin=None):
    rows = load_learnings()
    pk = project_key(project)
    finding, cause = scrub_secrets(finding), scrub_secrets(cause)
    change = scrub_secrets(change) if change else change
    rec = {
        "id": next_id(rows), "title": derive_title(change or finding),
        "source_unit": unit, "origin_project": pk,
        "observation": {"evidence": finding, "impact": impact},
        "root_cause": cause,
        "proposed": {"description": change or "", "mechanism": mechanism,
                     "scope": scope or ("user" if owner_statement else "project"),
                     "scope_asked": scope, "target": target},
        "expected_effect": scrub_secrets(expect or ""), "limits": scrub_secrets(limits or ""),
        "why_not": scrub_secrets(why_not or ""),
        "validation": {"method": scrub_secrets(validate or ""), "benchmark": None,
                       "result": "unvalidated", "detail": ""},
        "status": "promoted" if owner_statement else
                  ("proposed" if disposition == "promote" else "observed"),
        "version": 1, "confidence": "high" if owner_statement else "low",
        "provenance": [{"unit": unit, "project": pk, "ts": now(), "kind": "origin"}],
        "terms": derive_terms(finding, cause, change or ""),
        "owner_statement": bool(owner_statement), "candidate": bool(subagent),
        "recurrences_after_promotion": 0,
        "flagged_not_working": False, "promoted_at": now() if owner_statement else None,
        "mechanism_ref": None, "replay": replay, "created": now(),
    }
    if origin:
        rec["statement_origin"] = origin
    rows.append(rec)
    save_learnings(rows, "learning %s recorded" % rec["id"], created=[rec], via=entered_via)
    return rec


def add_recurrence(rec, unit, project, rows, finding=None):
    """Attach a recurrence, once per unit. The finding (a recorded finding of this unit in this
    project) is the evidence; a unit already in the provenance is not counted again. After
    promotion a new recurrence counts against the learning. Returns True when one was added."""
    pk = project_key(project)
    prov = rec.setdefault("provenance", [])
    if any(p.get("unit") == unit and p.get("project") == pk for p in prov):
        return False
    prov.append({"unit": unit, "project": pk, "ts": now(), "kind": "recurrence", "finding": finding})
    if rec.get("status") in ("promoted", "monitored", "validated", "implemented") and rec.get("promoted_at"):
        rec["recurrences_after_promotion"] = int(rec.get("recurrences_after_promotion") or 0) + 1
        if rec["recurrences_after_promotion"] >= 2:
            rec["flagged_not_working"] = True
        if rec["status"] == "promoted":
            rec["status"] = "monitored"
    save_learnings(rows, "learning %s recurrence" % rec["id"], touched=[rec])
    return True


def adopt(lid, unit, project):
    """A parent adopts a subagent's candidate, by id and in its own project only."""
    rows = load_learnings()
    rec = get(rows, lid)
    if rec is None:
        raise LearningError("no learning %r" % lid)
    if not rec.get("candidate"):
        raise LearningError("learning %s is not a candidate" % lid)
    if rec.get("origin_project") != project_key(project):
        raise LearningError("learning %s was recorded in another project; adopt it there" % lid)
    rec["candidate"] = False
    rec.setdefault("history", []).append({"ts": now(), "action": "adopt", "unit": unit})
    save_learnings(rows, "learning %s adopted" % lid, touched=[rec])
    return rec


def withdraw(lid, why):
    """Withdraw an owner statement recorded by mistake: kept in history, never delivered again."""
    rows = load_learnings()
    rec = get(rows, lid)
    if rec is None or not rec.get("owner_statement"):
        raise LearningError("no owner statement %r" % lid)
    if rec.get("status") in ENDED:
        raise LearningError("%s is already withdrawn" % lid)
    rec["status"] = "rejected"
    rec.setdefault("history", []).append({"ts": now(), "action": "withdraw", "why": scrub_secrets(why)})
    save_learnings(rows, "learning %s withdrawn" % lid, touched=[rec], via="learn")
    return rec


def findings_for_unit(project, uid):
    """Seam for the unit record: the findings recorded for one unit in one project."""
    pk = project_key(project)
    return [f for f in load_findings() if f.get("unit") == uid and f.get("project") == pk]


# ---- owner statements: who said it ------------------------------------------------------

def _norm_words(t):
    return " ".join(str(t or "").lower().split())


def statement_origin(statement):
    """`typed by the owner` when the quoted words appear in a human-typed message of this
    session's transcript (read with harvest.typed_text, the one definition of "typed by the
    human"); `relayed by an agent` when they do not, or when no transcript is available."""
    _sid, sess = session_record()
    tp = sess.get("transcript_path") if isinstance(sess, dict) else None
    if not isinstance(tp, str) or not tp:
        return "relayed by an agent"
    want = _norm_words(statement)
    try:
        from . import harvest
        path = os.path.expanduser(tp)
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            start = max(0, size - 8 * 1024 * 1024)
            f.seek(start)
            data = f.read()
        lines = data.split(b"\n")
        if start:
            lines = lines[1:]
        for raw in lines:
            if b'"user"' not in raw:
                continue
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            text = harvest.typed_text(d)[0]
            if text and want in _norm_words(text):
                return "typed by the owner"
    except (OSError, ImportError):
        pass
    return "relayed by an agent"


# ---- units and monitoring --------------------------------------------------------------

def units_seen():
    """Closed units from the unit record's summary file in the user store (one JSON object per
    line: id, project, closed_at, risk). The file may not exist yet: then there are none."""
    return _read_jsonl(paths.data_file("units.jsonl"))[0]


def units_since_promotion(rec, units=None):
    """Closed units that count for this learning: after its promotion, and in its own scope (its
    origin project when the scope is project, any project when it has earned more)."""
    units = units_seen() if units is None else units
    since = str(rec.get("promoted_at") or "")
    if not since:
        return []
    wide = earned_scope(rec) != "project"
    out, cache = [], {}
    for u in units:
        closed = str(u.get("closed_at") or "")
        if not closed or closed < since:
            continue
        if not wide:
            p = u.get("project")
            if p not in cache:
                cache[p] = normalize_project(p)
            if cache[p] != rec.get("origin_project"):
                continue
        out.append(u)
    return out


def monitor(rows=None, units=None):
    """Move promoted learnings to `monitored` once monitoring has something to say (a unit in
    scope has closed since promotion, or one recurred). Returns the changed records."""
    rows = load_learnings() if rows is None else rows
    units = units_seen() if units is None else units
    changed = []
    for r in rows:
        if r.get("status") == "promoted" and not r.get("owner_statement") and r.get("promoted_at") \
                and (units_since_promotion(r, units) or int(r.get("recurrences_after_promotion") or 0)):
            r["status"] = "monitored"
            changed.append(r)
    return changed


def flagged(rows=None):
    rows = load_learnings() if rows is None else rows
    return [r for r in rows if r.get("flagged_not_working") and r.get("status") not in ("revised", "reverted", "rejected")]


def learning_report():
    """Seam for `sisi status --learning`. No claim of improvement from counts of records."""
    rows = load_learnings()
    findings = load_findings()
    units = units_seen()
    ledger = load_ledger()
    lines = ["Learning loop (recorded facts; no improvement is claimed from counts):",
             "learnings: %d   findings: %d   closed units known: %d"
             % (len(rows), len(findings), len(units))]
    odd = [r["id"] for r in rows if not is_registered(r, ledger)]
    if odd:
        lines.append("not delivered (not written by sisi's own commands, or edited by hand): " + ", ".join(odd))
    promoted = [r for r in rows if r.get("status") in ("promoted", "monitored") and not r.get("owner_statement")]
    if promoted:
        lines.append("promoted learnings:")
    holding = 0
    relevant = 0
    for r in promoted:
        since = len(units_since_promotion(r, units))
        rec = int(r.get("recurrences_after_promotion") or 0)
        val = (r.get("validation") or {}).get("result") or "unvalidated"
        if r.get("flagged_not_working"):
            verdict = "not working (flagged: next cycle must revise or revert)"
        elif since >= MONITOR_UNITS and rec == 0:
            verdict = "holding"
        elif rec:
            verdict = "recurred, watching"
        else:
            verdict = "too few units to judge"
        if since >= MONITOR_UNITS:
            relevant += 1
            if rec == 0:
                holding += 1
        lines.append("- %s: %d unit(s) in scope since promotion, %d recurrence(s), %s — %s"
                     % (r["id"], since, rec, val if val == "validated" else "unvalidated", verdict))
    if relevant < 5:
        lines.append("realization rate: too few (fewer than five promoted learnings have "
                     "five relevant units; no rate is claimed)")
    else:
        lines.append("realization rate: %d of %d promoted learnings holding with no recurrence "
                     "over at least five units in their scope" % (holding, relevant))
    fl = flagged(rows)
    if fl:
        lines.append("flagged not working: " + ", ".join(r["id"] for r in fl))
    pend = load_pending()
    if pend:
        lines.append("waiting for the owner's decision: %d change(s) (`sisi approve` lists them in full)"
                     % len(pend))
    tool = [r for r in rows if r.get("proposed", {}).get("mechanism") == "tool"
            and r.get("status") not in ENDED]
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


def next_pending_id(items):
    n = 0
    for i in items:
        m = re.match(r"P-(\d+)$", str(i.get("id", "")))
        if m:
            n = max(n, int(m.group(1)))
    try:
        n = max(n, max(int(re.sub(r"\D", "", str(a.get("id"))) or 0) for a in load_approvals()))
    except ValueError:
        pass
    return "P-%04d" % (n + 1)


def load_approvals():
    return _read_jsonl(approvals_path())[0]


def record_approval(row):
    """Append-only record of an owner decision; committed with the change it decided."""
    pdata.ensure()
    pdata.write_text("approvals.jsonl", (pdata.read_text("approvals.jsonl", "") or "")
                     + json.dumps(row, sort_keys=True) + "\n")
    pdata.commit("approval %s recorded" % row.get("id"), ["approvals.jsonl"])


def approved_ids():
    return {a["id"] for a in load_approvals() if a.get("decision") == "yes" and a.get("id")}


def pending_notice():
    n = len(load_pending())
    if not n:
        return ""
    return ("sisi: %d learning change(s) wait for the owner's decision. Ask the owner through the host's "
            "question dialog (`sisi approve` lists each change in full; show the owner what it would do) and give "
            "the owner the command to run in a terminal: `sisi approve ID --yes` or `--no`. "
            "Do not run it for the owner." % n)


# ---- owner statements (one path: learn writes, oracle prints) ---------------------

def owner_statements(rows=None):
    rows = load_learnings() if rows is None else rows
    ledger = load_ledger()
    return [r for r in rows if r.get("owner_statement") and r.get("status") not in ENDED
            and is_registered(r, ledger)]
