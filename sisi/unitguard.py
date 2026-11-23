"""The contract comes before the work: a unit is bound to the session that works on it, and the
before-tool hook refuses the first building step that has no valid unit behind it (rule 3).

What makes a unit valid for building, in this order:
 - it is open (not closed), and this session opened it (`sisi contract init`) or said it continues it
   (`sisi unit continue`): the binding lives in the session record, never in the contract file, so a
   unit left by another session is foreign until it is continued, parked or closed;
 - it is not stale: its last activity (a verification run, an allowed edit, a continue) is younger
   than `unit.stale_hours`;
 - `sisi contract check` passes, no check still carries the skeleton's placeholder, and the contract
   carries what the risk profile of the work requires BEFORE building (canon/risk.json: for
   integration and above the requirement list, the risk note and the approach; independent
   evidence and the retro are asked at the end, never here).

The profile is the risk floor of the target path together with the paths this session already
changed since its last valid unit (`risk.assess`). A trivial change is never refused. Writes under
.sisi/ and outside the project are never refused. Worker and subagent sessions are never refused:
their parent owns the unit. Every refusal says what is missing and names the command that resolves
it, and is stored (what, when) so the unit's record and `sisi status` can count them. Any error in
here lets the call through.

Entry points for sisi/watch.py: `before(payload)` (True when it refused and printed the host's
refusal) and `after(payload)`. For the gate and `sisi unit pause`: `bound_fresh`, `verdict`.
"""
import fnmatch, hashlib, json, os, re, shlex, sys, time

from . import assure, contract as C, paths as P, risk, store

CLAIM_RE = re.compile(r"\bsisi\b[^\n;&|]*?\b(?:contract\s+init|unit\s+(?:continue|resume|park))\b")
MAX_LINES = 12
_DATA = {}


def data():
    """canon/guard.json (word lists), read once per process."""
    if not _DATA:
        try:
            with open(P.canon("guard.json"), encoding="utf-8") as f:
                _DATA.update(json.load(f))
        except (OSError, ValueError):
            _DATA["_missing"] = True
    return _DATA


def _list(name):
    v = data().get(name)
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


# ---------------------------------------------------------------- who is asking

def _claim_file():
    return os.path.join(P.state(), "unitguard-claim.json")


def note_claim(sid, cwd):
    """The before-hook saw this session about to run `sisi contract init|unit continue|...`: remember which
    session it was, for a command line whose environment does not carry the session id."""
    try:
        os.makedirs(P.state(), exist_ok=True)
        tmp = _claim_file() + ".tmp%d" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"sid": sid, "cwd": cwd, "ts": time.time()}, f)
        os.replace(tmp, _claim_file())
    except OSError:
        pass


def cli_session():
    """The session a `sisi` command line belongs to: the id the session-start hook exported, else the
    session the before-hook saw start this command a moment ago. None when neither is known."""
    sid = os.environ.get("SISI_SESSION_ID")
    if sid:
        return sid
    try:
        with open(_claim_file(), encoding="utf-8") as f:
            d = json.load(f)
        if time.time() - float(d.get("ts", 0)) < 120 and isinstance(d.get("sid"), str):
            return d["sid"]
    except (OSError, ValueError, TypeError):
        pass
    return None


# ---------------------------------------------------------------- unit identity, binding, activity

def ident(c):
    """What makes a unit this unit: its start time (set once, by `contract init`), else its id. The id is not
    used when a start exists, because an agent may rename it while filling the contract in."""
    return c.get("started") or "id:%s" % c.get("id")


def unit_key(project, c):
    return "%s|%s" % (os.path.realpath(project), ident(c))


def _act_path(key):
    return os.path.join(P.state(), "unitguard", hashlib.sha1(key.encode()).hexdigest()[:16] + ".json")


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def touch(project, c, model=None, throttle=0.0):
    """This unit had activity just now. `throttle` skips the write when the last one is that recent."""
    key = unit_key(project, c)
    p = _act_path(key)
    d = _load(p)
    now = time.time()
    if throttle and now - float(d.get("last", 0) or 0) < throttle and not model:
        return
    d.update(project=os.path.realpath(project), id=c.get("id"), started=c.get("started"), last=now)
    if model:
        ms = d.setdefault("models", [])
        if model not in ms:
            ms.append(model)
    _save(p, d)


def author_models(project, c):
    """The models of the sessions that bound themselves to this unit: who wrote the work."""
    return [m for m in _load(_act_path(unit_key(project, c))).get("models", []) if isinstance(m, str)]


def bind(sid, project, c, how):
    """This session now works on this unit: it opened it, continued it or resumed it."""
    sess = store.load_session(sid)
    sess.setdefault("session_id", sid)
    if not (sess.get("started") or sess.get("first_seen")):
        sess["first_seen"] = store.now()
    sess.setdefault("unit_bound", {})[os.path.realpath(project)] = {
        "id": c.get("id"), "ident": ident(c), "how": how, "ts": store.now()}
    store.save_session(sid, sess)
    touch(project, c, model=sess.get("model") if isinstance(sess.get("model"), str) else None)


def is_bound(sess, project, c):
    b = (sess.get("unit_bound") or {}).get(os.path.realpath(project))
    return isinstance(b, dict) and b.get("ident") == ident(c)


def stale_seconds():
    try:
        h = float(((store.config().get("unit") or {}).get("stale_hours", 12)))
    except (TypeError, ValueError):
        h = 12.0
    return max(0.0, h) * 3600.0


def _epoch(iso):
    try:
        return time.mktime(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
    except (TypeError, ValueError):
        return None


def _last_result_ts(project, uid):
    """Newest verification result recorded for this unit: only the tail of the results file is read."""
    try:
        p = store.file_path("results")
        with open(p, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 200000))
            tail = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    for line in reversed(tail):
        if '"%s"' % uid not in line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("contract") == uid and r.get("project") == project:
            return _epoch(r.get("ts"))
    return None


def last_activity(project, c):
    """Epoch of the unit's last activity: a continue or allowed edit, a verification run, or its start."""
    cands = [_epoch(c.get("started"))]
    cands.append(_load(_act_path(unit_key(project, c))).get("last"))
    cands.append(_last_result_ts(project, c.get("id")))
    cands = [x for x in cands if isinstance(x, (int, float))]
    return max(cands) if cands else None


def age_text(epoch):
    if not epoch:
        return "an unknown time"
    s = max(0, time.time() - epoch)
    if s < 90:
        return "just now"
    if s < 5400:
        return "%d minutes ago" % round(s / 60)
    if s < 36 * 3600:
        return "%d hours ago" % round(s / 3600)
    return "%d days ago" % round(s / 86400)


def git_top(cwd):
    """The repository root above cwd, found by looking for `.git` (no process started: this runs before every
    counted tool call). None outside a repository."""
    d = os.path.abspath(cwd)
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


def find_contract(cwd, top):
    """Nearest .sisi/contract.json from cwd up to the repository root (what C.find does, without asking git)."""
    d = os.path.abspath(cwd)
    while True:
        p = os.path.join(d, C.REL)
        if os.path.isfile(p):
            return p
        if d == top or os.path.dirname(d) == d:
            return None
        d = os.path.dirname(d)


def open_unit(cwd, top=None):
    """(contract, path, project) of the open unit (not closed) found from cwd, else (None, None, None)."""
    p = find_contract(cwd, top or git_top(cwd))
    if not p:
        return None, None, None
    try:
        c = C.load(p)
    except (OSError, ValueError):
        return None, None, None
    if not isinstance(c, dict) or c.get("status") == "closed":
        return None, None, None
    return c, p, C.project_dir(p)


def bound_fresh(sess, project, c):
    """('ok'|'foreign'|'stale', last activity epoch) for this session and the open unit."""
    last = last_activity(project, c)
    if not is_bound(sess, project, c):
        return "foreign", last
    if last is not None and time.time() - last > stale_seconds():
        return "stale", last
    return "ok", last


# ---------------------------------------------------------------- what the work is, how risky

def _ignored(rel):
    p = rel.replace(os.sep, "/").lower()
    return any(fnmatch.fnmatchcase(p, g.lower()) or (g.startswith("**/") and fnmatch.fnmatchcase(p, g[3:].lower()))
               or (g.endswith("/**") and p.startswith(g[:-2].lower())) for g in _list("ignore_changed"))


def _rel_in_project(path, root, cwd):
    """The path relative to the project root, or None when it lies outside it."""
    ap = path if os.path.isabs(path) else os.path.join(cwd, path)
    ap = os.path.normpath(ap)
    real_root = os.path.realpath(root)
    d, b = os.path.split(ap)
    rp = os.path.join(os.path.realpath(d), b)
    if rp == real_root or not rp.startswith(real_root + os.sep):
        return None
    return os.path.relpath(rp, real_root)


def _is_sisi(rel):
    r = rel.replace(os.sep, "/")
    return r == ".sisi" or r.startswith(".sisi/")


def _floor_sig(project):
    """Which risk tables are in force: a change to any of them makes every remembered floor stale."""
    parts = []
    for f in (P.canon("risk.json"), P.data_file("risk.json"), P.overlay_dir("risk-adjustments.json"),
              os.path.join(project, ".sisi", "risk.json")):
        try:
            st = os.stat(f)
            parts.append("%s:%d:%d" % (f, st.st_mtime_ns, st.st_size))
        except OSError:
            parts.append(f + ":-")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def floor_of(rels, project):
    """(floor, reasons) of these paths by `risk.assess`. Matching a path against the whole table takes tens of
    milliseconds, so an answer is remembered (per table version) for the next call that asks about the same paths."""
    clean = sorted({r for r in rels if r})
    key, sig = "\n".join(clean), _floor_sig(project)
    cache_path = os.path.join(P.state(), "unitguard-floor.json")
    cache = _load(cache_path)
    if cache.get("sig") != sig:
        cache = {"sig": sig, "floors": {}}
    hit = cache["floors"].get(key)
    if hit:
        return hit[0], hit[1]
    prof, reasons = risk.assess(clean, patterns=risk.load_patterns(project))
    if len(cache["floors"]) > 300:
        cache["floors"] = {}
    cache["floors"][key] = [prof, reasons]
    try:
        _save(cache_path, cache)
    except OSError:
        pass
    return prof, reasons


def session_paths(sess):
    """Paths this session changed (and nothing covered yet) since its last valid unit."""
    return [p for p in (sess.get("ug_paths") or []) if isinstance(p, str)]


def _absorb(sess, root):
    """Fold the paths the after-tool snapshot attributed to this session into the guard's own list, once."""
    since = [p for p in (sess.get("attr_since_pass") or []) if isinstance(p, str) and not p.startswith("*")]
    covered = set(sess.get("ug_covered") or [])
    sess["ug_covered"] = [p for p in covered if p in since]  # settled stops empty attr_since_pass: forget
    have = sess.setdefault("ug_paths", [])
    new = False
    for p in since:
        rel = p
        if os.path.isabs(p):
            rel = _rel_in_project(p, root, root)
            if rel is None:
                continue
        if p in covered or rel in have or _is_sisi(rel) or _ignored(rel):
            continue
        have.append(rel)
        new = True
    return new


def _cover(sess):
    """A valid unit stands behind everything changed so far."""
    sess["ug_covered"] = [p for p in (sess.get("attr_since_pass") or []) if isinstance(p, str) and not p.startswith("*")]
    sess["ug_paths"] = []


# ---------------------------------------------------------------- the verdict

def _problems(profile, c, project, info):
    """[(what is missing, how to supply it)] before building at this profile."""
    errs = C.validate(c)
    out = []
    if C.is_unedited_skeleton(c) or any(isinstance(x, dict) and x.get("cmd") == C.PLACEHOLDER_CMD
                                        for x in (c.get("checks") or [])):
        out.append(("a check still carries the skeleton's placeholder command",
                    "replace it with a command that can fail, or delete the placeholder check (`sisi contract check`)"))
        errs = [e for e in errs if "placeholder" not in e.lower()]
    if C.is_placeholder(c.get("goal")):
        out.append(("the goal in the person's words", 'set "goal" to one sentence naming the outcome wanted'))
    if info.get("refused"):
        out.append(("risk.profile %r is below the floor %r and gives no reason" % (info.get("declared"), info.get("floor")),
                    'raise it, or add "risk": {"why": "<why the floor is too high>"}'))
    out += assure.missing(profile, c, project, None, errs, None, before_build=True)
    return out


def verdict(sid, sess, cwd, floor, c=None, path=None, project=None, literal=False):
    """What stands between this session and building a change of this floor (`literal`: a trivial floor asks
    for nothing beyond a bound, fresh, well-formed unit; otherwise it is read as `isolated`).
    {"state": none|foreign|stale|invalid|ok, "problems": [(what, how)], "unit": contract|None, "profile": ...}"""
    if c is None:
        c, path, project = open_unit(cwd)
    if literal and floor == "trivial":
        floor = "trivial-literal"
    if c is None:
        prof = floor if floor not in ("trivial", "trivial-literal") else "isolated"
        return {"state": "none", "problems": [], "unit": None, "profile": prof, "last": None, "project": project}
    state, last = bound_fresh(sess, project, c)
    profile, info = assure.effective_profile("trivial" if floor == "trivial-literal" else
                                             (floor if floor != "trivial" else "isolated"), c)
    v = {"state": state, "problems": [], "unit": c, "profile": profile, "last": last, "project": project, "info": info}
    if state != "ok":
        return v
    v["problems"] = _problems(profile, c, project, info)
    if v["problems"]:
        v["state"] = "invalid"
    return v


# ---------------------------------------------------------------- the message

def how_on(c, state, last):
    uid = c.get("id") or "?"
    goal = " ".join(str(c.get("goal") or "").split())[:90]
    when = age_text(last)
    if state == "stale":
        head = 'Unit %s ("%s") has had no activity since %s, so this session must say it continues it.' % (uid, goal, when)
    else:
        head = 'Unit %s ("%s", last active %s) was not opened or continued by this session.' % (uid, goal, when)
    return [head,
            "Three ways on: `sisi unit continue` (it is this work), `sisi unit park \"<why>\"` (set it aside, kept),",
            "or `sisi unit close --abandon \"<why>\"`; for new work then run `sisi contract init`, replace its placeholder",
            "check with one that can fail, and fill what the profile needs."]


def _profile_needs(profile):
    req = assure.requirements(profile)
    names = [n for k, n in (("covers", "what each check covers"), ("invariants", "invariants"),
                            ("requirement_model", "the requirement list"), ("risk_note", "the risk note"),
                            ("approach", "the approach")) if req.get(k)]
    return ", ".join(names)


def refusal_text(v, what, floor_reasons=None):
    profile = v["profile"]
    lines = ["sisi refused: %s. The risk profile is `%s` and there is no valid unit for this work (rule 3: the contract comes first)."
             % (what, profile)]
    c = v.get("unit")
    if v["state"] == "none":
        lines += ["Missing: a unit for this work -> `sisi contract init`, then write at least one check that can fail,",
                  "replacing the placeholder, and set the goal in the person's words."]
        need = _profile_needs(profile)
        if need:
            lines.append("At %s the contract also needs: %s (`sisi contract check` lists what is missing)." % (profile, need))
    elif v["state"] in ("foreign", "stale"):
        lines += how_on(c, v["state"], v.get("last"))
    else:
        lines.append("Unit %s is yours but not ready to build on. Missing:" % c.get("id"))
        lines += ["- %s -> %s" % (a, b) for a, b in v["problems"]]
    lines.append("Then retry the call.")
    return assure.fit(lines, MAX_LINES)


def unit_line(v):
    """One phrase for the refusal record: what state the unit was in."""
    return v["state"] + ((": " + "; ".join(a for a, _ in v["problems"][:3])) if v.get("problems") else "")


# ---------------------------------------------------------------- the record of refusals

REFUSALS = "refusals.jsonl"


def record_refusal(sid, project, what, v, sess=None, tool=None):
    """Store one refusal: what was refused and when. `unit` is the unit this session is bound to (None when
    none); `open_unit` is whatever unit was open."""
    c = v.get("unit")
    bound = None
    if isinstance(c, dict) and is_bound(sess or {}, project, c):
        bound = c.get("id")
    try:
        store.append(REFUSALS, {"ts": store.now(), "session": sid, "project": os.path.realpath(project), "what": what,
                                "tool": tool, "state": v["state"], "unit": bound,
                                "unit_started": c.get("started") if bound else None,
                                "open_unit": c.get("id") if isinstance(c, dict) else None,
                                "why": unit_line(v)[:300]})
    except Exception as e:
        store.log_error("unitguard-record", e)


def refusals_for(project, uid=None, started=None):
    """The stored refusals of one unit (its id and start), or, with uid None, of no unit at all."""
    rp = os.path.realpath(project)
    out = []
    for r in store.read(REFUSALS):
        if not isinstance(r, dict) or r.get("project") != rp:
            continue
        if uid is None:
            if r.get("unit") is None:
                out.append(r)
        elif r.get("unit") == uid and (started is None or r.get("unit_started") in (None, started)):
            out.append(r)
    return out


# ---------------------------------------------------------------- what a tool call would change

def _norm_lines(cmd):
    """The command without heredoc bodies (their text is data, not commands)."""
    out, skip = [], None
    for line in str(cmd).split("\n"):
        if skip is not None:
            if line.strip() == skip:
                skip = None
            continue
        out.append(line)
        m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", line)
        if m:
            skip = m.group(1)
    return "\n".join(out)


def shell_targets(cmd, cwd):
    """Best-effort paths a shell command writes: redirects, tee, sed/perl -i, cp/mv/install/ln, rm/touch/mkdir, dd of=.
    What cannot be told from the text (an interpreter, a script) is left to the after-tool snapshot."""
    try:
        lex = shlex.shlex(_norm_lines(cmd), posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:
        return []
    segs, cur = [], []
    for t in toks:
        if t in (";", "&", "|", "&&", "||"):
            segs.append(cur)
            cur = []
        else:
            cur.append(t)
    segs.append(cur)
    out = []

    def add(x):
        if x and not x.startswith(("&", "-", "/dev/")) and x not in out:
            out.append(x)
    for seg in segs:
        i = 0
        while i < len(seg):
            t = seg[i]
            if re.fullmatch(r"\d*>>?", t) or t in (">>", ">", ">|") or re.fullmatch(r"&>>?", t):
                if i + 1 < len(seg):
                    add(seg[i + 1])
                i += 2
                continue
            i += 1
        words = [w for w in seg if w and not re.fullmatch(r"\d*(>>?|<<?|>\||&>>?)", w)]
        k = 0
        while k < len(words) and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[k]) or words[k] in ("sudo", "command", "exec", "time", "nice")):
            k += 1
        if k >= len(words):
            continue
        prog, rest = os.path.basename(words[k]), words[k + 1:]
        args = [a for a in rest if not a.startswith("-")]
        if prog == "tee":
            for a in args:
                add(a)
        elif prog in ("sed", "perl") and any(re.match(r"^-[a-zA-Z]*i", a) for a in rest if a.startswith("-")):
            for a in (args[1:] if prog == "sed" and not any(a in ("-e", "-f") for a in rest) else args):
                add(a)
        elif prog in ("cp", "install", "ln", "mv", "rm", "touch", "mkdir", "rmdir"):
            for a in (args if prog in ("mv", "rm", "touch", "mkdir", "rmdir") else args[-1:]):
                add(a)
        elif prog == "dd":
            for a in rest:
                if a.startswith("of="):
                    add(a[3:])
    return out


def _is_sisi_command(cmd):
    """Every command of the line is sisi itself: it writes only personal data and the unit's own files."""
    try:
        lex = shlex.shlex(_norm_lines(cmd), posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:
        return False
    segs, cur = [], []
    for t in toks:
        if t in (";", "&", "|", "&&", "||"):
            segs.append(cur)
            cur = []
        else:
            cur.append(t)
    segs.append(cur)
    segs = [s for s in segs if s]
    return bool(segs) and all(os.path.basename(s[0]) == "sisi" for s in segs)


def classify(tool, payload, cmd):
    """'edit' (a file-editing tool), 'shell', 'delegate' (spawns a worker) or None."""
    from . import watch
    t = tool or ""
    if t in _list("edit_tools") or any(w in t.lower() for w in _list("edit_name_words")):
        return "edit"
    if t in _list("delegation_tools"):
        return "delegate"
    if watch.is_shell(t, cmd):
        return "shell"
    return None


def _brief_text(payload):
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    return " ".join(str(inp.get(k) or "") for k in ("description", "prompt", "task", "message")).lower()


def routed_kind(sess, payload):
    """The kind of work a delegation was routed as (impl, review, search, ...), or None when no routing
    decision is recorded for it. The one place that reads the routing record."""
    r = sess.get("route") if isinstance(sess.get("route"), dict) else None
    k = r.get("kind") if r else None
    return k if isinstance(k, str) and k else None


def is_building_delegation(sess, payload):
    kind = routed_kind(sess, payload)
    if kind:
        return kind in _list("build_kinds")
    text = _brief_text(payload)
    if any(ph in text for ph in _list("read_only_phrases")):
        return False
    return any(re.search(r"\b(?:" + re.escape(w) + r"(?:s|es|ed|d|ing)?|" + re.escape(w[:-1] if w.endswith("e") else w) + r"ing)\b", text)
               for w in _list("build_words"))


# ---------------------------------------------------------------- pause, and the gate

def pause_refusal(c, path, project):
    """The refusal for `sisi unit pause`, or None when the pause is allowed. A pause defers checks that wait
    on something and the retro; it never defers the contract, so it needs a unit this session holds that is
    valid for what has changed so far."""
    from . import unit as U
    sid = cli_session()
    sess = store.load_session(sid) if sid else {}
    fl, _ = U.risk_floor(c, project)
    floor = fl.get("value") if isinstance(fl, dict) else fl
    if floor not in risk.PROFILES:
        floor = "isolated"
    mine = session_paths(sess)
    if mine:
        own = floor_of(mine, project)[0]
        floor = max(floor, own, key=lambda x: risk.PROFILES.index(x))
    v = verdict(sid, sess, project, floor, c, path, project, literal=True)
    if v["state"] == "ok":
        return None
    lines = ["sisi refused the pause: a pause defers checks that are waiting on something (a review, a decision, a deploy)",
             "and the retro. It never defers the contract: the unit must exist, be this session's, and be valid first."]
    if v["state"] in ("foreign", "stale"):
        lines += how_on(c, v["state"], v.get("last"))
    else:
        lines.append("Unit %s is not ready. Missing:" % c.get("id"))
        lines += ["- %s -> %s" % (a, b) for a, b in v["problems"]]
    record_refusal(sid or "?", project, "a pause of unit %s" % c.get("id"), v, sess, "pause")
    return assure.fit(lines, MAX_LINES)


def pause_without_unit(cwd):
    """The refusal for `sisi unit pause` when no unit is open at all (recorded like any other)."""
    sid = cli_session()
    try:
        from . import gitutil
        record_refusal(sid or "?", gitutil.root(cwd) or os.path.abspath(cwd), "a pause with no unit open",
                       {"state": "none", "problems": [], "unit": None}, store.load_session(sid) if sid else {}, "pause")
    except Exception as e:
        store.log_error("unitguard-pause", e)
    return ("sisi refused the pause: a pause defers checks that are waiting on something and the retro, never the "
            "contract, and there is no open unit to pause. Start one with `sisi contract init`.")


def holds_valid(sess, project, c, floor="trivial"):
    """True when this session holds the unit (bound, not stale) and nothing is missing before building at this
    floor: what lets a paused unit stay quiet at the end of a turn."""
    return verdict(None, sess, project, floor, c, None, project, literal=True)["state"] == "ok"


def gate_sendback_lines(c, state, last, own_path, profile):
    """The end-of-turn message when this session changed work the open unit is not its own."""
    head = "sisi: this %s change is not ready to hand over (send-back {n}): this session changed `%s` and does not hold a unit for it." \
        % (profile, own_path)
    return [head] + how_on(c, state, last) + ["The unit's checks are not run against this work. Do not report it as done."]


# ---------------------------------------------------------------- the hooks

def _deny(msg):
    sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                         "permissionDecisionReason": msg}}) + "\n")


def _is_contract_target(rel):
    return rel.replace(os.sep, "/") == ".sisi/contract.json"


def before(payload):
    """True when this call was refused (the refusal is printed in the host's shape and the call must not run)."""
    try:
        return _before(payload)
    except Exception as e:  # fail open: a tool call is never held up by an error in here
        store.log_error("unitguard-before", e)
        return False


def _before(payload):
    from . import attribution, watch, workers
    tool, cmd, _ev, cwd, sid = watch.extract(payload)
    kind = classify(tool, payload, cmd)
    if kind is None:
        return False
    if not store.config()["gate"].get("enabled", True) or workers.is_subagent_payload(payload):
        return False
    sid = sid or "cwd-" + cwd
    if kind == "shell":
        if CLAIM_RE.search(cmd or ""):
            note_claim(sid, cwd)
        if watch._may_write(cmd) is False or _is_sisi_command(cmd):
            return False
    sess = store.load_session(sid)
    if sess.get("subagent"):
        return False
    top = git_top(cwd)
    if top is None:
        return False  # nothing to measure outside a repository
    rels, outside = [], False
    if kind == "edit":
        files = attribution._input_files(payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {})
        if not files:
            return False
        targets = files
    elif kind == "shell":
        targets = shell_targets(cmd, cwd)
    else:
        targets = []
    for f in targets:
        r = _rel_in_project(f, top, cwd)
        if r is None:
            outside = True
        else:
            rels.append(r)
    if kind == "delegate" and not is_building_delegation(sess, payload):
        return False
    if kind == "edit" and not rels:
        return False  # only outside the project
    c, cpath, project = open_unit(cwd, top)
    project = project or top
    if any(_is_contract_target(r) for r in rels):
        return _guard_contract_write(sid, sess, c, project, cwd, kind)
    rels = [r for r in rels if not _is_sisi(r) and not _ignored(r)]
    changed = _absorb(sess, top)
    paths_all = list(dict.fromkeys(rels + session_paths(sess)))
    if kind != "delegate" and not paths_all:
        if changed:
            store.save_session(sid, sess)
        return False
    floor, _reasons = floor_of(paths_all, project) if paths_all else ("trivial", [])
    if kind != "delegate" and floor == "trivial":
        have = sess.setdefault("ug_paths", [])
        for r in rels:
            if r not in have:
                have.append(r)
        store.save_session(sid, sess)
        return False
    v = verdict(sid, sess, cwd, floor, c, cpath, project)
    v.setdefault("project", project)
    if v["state"] == "ok":
        _cover(sess)
        store.save_session(sid, sess)
        touch(project, c, throttle=60.0)
        return False
    if kind == "delegate":
        what = "delegating this work to a worker"
    else:
        focus = next((x for x in paths_all if floor_of([x], project)[0] != "trivial"), paths_all[0])
        what = ("this call would change `%s`" % focus) if focus in rels else \
            ("this session already changed `%s` with no unit behind it" % focus)
    msg = refusal_text(v, what)
    if kind == "delegate":
        msg = msg.replace("Then retry the call.", "The contract is where the worker's brief takes its acceptance from. Then retry.")
    record_refusal(sid, project, what, v, sess, tool)
    store.save_session(sid, sess)
    _deny(msg)
    return True


def _guard_contract_write(sid, sess, c, project, cwd, kind):
    """A write to the contract file itself. With a unit open that this session does not hold, that would
    overwrite another piece of work's record: refused, with the three ways on. With no unit open it is how a
    new contract is written, and the session is bound to it afterwards."""
    if c is None:
        sess["ug_will_bind"] = os.path.realpath(project)
        store.save_session(sid, sess)
        return False
    state, last = bound_fresh(sess, project, c)
    if state == "ok":
        return False
    v = {"state": state, "problems": [], "unit": c, "profile": "isolated", "last": last, "project": project}
    what = "this call would rewrite the contract of unit %s" % c.get("id")
    msg = assure.fit(["sisi refused: %s, which this session has not opened or continued." % what] + how_on(c, state, last)
                     + ["Then retry the call."], MAX_LINES)
    record_refusal(sid, project, what, v, sess, "contract-write")
    _deny(msg)
    return True


def after(payload):
    try:
        _after(payload)
    except Exception as e:
        store.log_error("unitguard-after", e)


def _after(payload):
    from . import watch
    tool, cmd, _ev, cwd, sid = watch.extract(payload)
    sid = sid or "cwd-" + cwd
    sess = store.load_session(sid)
    if not sess:
        return
    dirty = False
    top = git_top(cwd)
    if sess.get("ug_will_bind"):
        project = sess.pop("ug_will_bind")
        dirty = True
        c, _p, proj = open_unit(project, project)
        if c is not None:
            bind(sid, proj, c, "wrote")
            sess = store.load_session(sid)
    if top and classify(tool, payload, cmd) == "shell" and not sess.get("subagent"):
        dirty = _absorb(sess, top) or dirty  # a change the before-hook could not see: the next counted call answers for it
    if dirty:
        store.save_session(sid, sess)
