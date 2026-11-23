"""Rule 6 as a mechanism: the direct-work meter, the delegation guard and the delegation record.

The before-tool and after-tool hooks (sisi/watch.py) call in here for every tool. On a main thread:

 * every tool call that is not a delegation, a question dialog, a planning or to-do tool, a message or a
   `sisi` command counts as direct work, with the characters of its result; past the budget
   (`orchestrate.direct_calls` / `orchestrate.direct_chars`) the next counted call is refused with the
   router's recommendation and the two ways on (delegate with a brief, or `sisi unit direct "<reason>"`);
 * a delegation that names no model, or the session's own model, is refused the same way; one that is
   allowed is written to the ledger as a pending run, completed when it returns, and its brief is checked;
 * the fourth identical failing shell command with no file changed in between is refused once.

Only main threads are metered: a session the host marks as a subagent, one whose first prompt opens with the
brief template's line, one started by `sisi delegate` (SISI_WORKER_RUN) is a worker and never refused. Nothing
is refused when no usable worker other than the session's own model exists. Host tool names live in
canon/orchestration-tools.json. Per-session state is in <state>/sessions/<id>.meter.json under a file lock;
every counted event is also appended to <state>/orchestration.jsonl for the unit record. Every entry point
fails open (the caller wraps it): an error here must never hold up the user's tool.
"""
import fcntl, json, os, re, shlex, time, uuid

from . import paths, store

EVENTS = "orchestration.jsonl"
_HOSTS = {}


def cfg():
    c = store.config().get("orchestrate") or {}

    def num(key, default):
        try:
            return max(0, int(c.get(key, default)))
        except (TypeError, ValueError):
            return default
    return {"enabled": bool(c.get("enabled", True)), "direct_calls": max(1, num("direct_calls", 6)),
            "direct_chars": max(1, num("direct_chars", 30000)), "extension": max(1, num("extension", 10))}


def hosts():
    if not _HOSTS:
        try:
            with open(paths.canon("orchestration-tools.json"), encoding="utf-8") as f:
                d = json.load(f)
            _HOSTS.update({k: v for k, v in d.items() if isinstance(v, dict)})
        except (OSError, ValueError):
            _HOSTS["_none"] = {}
    return _HOSTS


def host_data(host):
    return hosts().get(host or "claude-code") or {}


def refuse_style(host):
    return host_data(host).get("refuse")


# ---------------------------------------------------------------- classifying a call

def _exempt_names(hd):
    out = set()
    for names in (hd.get("exempt") or {}).values():
        out.update(str(n).lower() for n in names or [])
    return out


def _dig(obj, dotted):
    for k in str(dotted or "").split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(k)
    return obj


def delegation_spec(hd, tool):
    for name, spec in (hd.get("delegation") or {}).items():
        if str(name).lower() == str(tool or "").lower():
            return spec if isinstance(spec, dict) else {}
    return None


def _segments(cmd):
    """The commands of a shell line, split at the operators outside quotes; None when it cannot be split."""
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:
        return None
    segs, cur = [], []
    for t in toks:
        if t and all(ch in "();&|<>" for ch in t) and not t.startswith(("<", ">")):
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        segs.append(cur)
    return segs


def runs_sisi(cmd):
    """True when every command in the shell line is an invocation of `sisi` itself."""
    segs = _segments(cmd or "")
    if not segs:
        return False
    for seg in segs:
        toks = [t for t in seg if not re.match(r"^[A-Za-z_]\w*=", t)]
        if not toks:
            return False
        first = toks[0]
        if re.match(r"^python[\d.]*$", os.path.basename(first)) and len(toks) > 1:
            first = toks[1]
        if os.path.basename(first) != "sisi":
            return False
    return True


def classify(host, tool, inp, cmd):
    """"delegation", "exempt" or "direct"."""
    hd = host_data(host)
    if delegation_spec(hd, tool) is not None:
        return "delegation"
    if str(tool or "").lower() in _exempt_names(hd):
        return "exempt"
    from . import watch
    if watch.is_shell(tool, cmd) and runs_sisi(cmd):
        return "exempt"
    return "direct"


# ---------------------------------------------------------------- the per-session meter

def meter_path(sid):
    return os.path.join(paths.state(), "sessions", store.safe_id(sid) + ".meter.json")


class Meter:
    """The session's meter under an exclusive lock; saved on a clean exit."""

    def __init__(self, sid):
        self.sid = sid
        self.m = None

    def __enter__(self):
        p = meter_path(self.sid)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        self.f = open(p, "a+", encoding="utf-8")
        end = time.time() + 2.0
        while True:
            try:
                fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() > end:
                    self.f.close()
                    raise
                time.sleep(0.005)
        self.f.seek(0)
        try:
            m = json.loads(self.f.read() or "{}")
        except ValueError:
            m = {}
        self.m = m if isinstance(m, dict) else {}
        self.m.setdefault("sid", self.sid)
        for k, v in (("turn", 0), ("calls", 0), ("chars", 0), ("ext", 0), ("refusals", 0), ("prompts", 0)):
            self.m.setdefault(k, v)
        for k in ("fails", "pending"):
            self.m.setdefault(k, {})
        for k in ("ext_log", "judge_asked"):
            self.m.setdefault(k, [])
        return self.m

    def __exit__(self, et, ev, tb):
        try:
            if et is None:
                self.m["last_ts"] = time.time()
                self.f.seek(0)
                self.f.truncate()
                self.f.write(json.dumps(self.m))
                self.f.flush()
        finally:
            try:
                fcntl.flock(self.f, fcntl.LOCK_UN)
            finally:
                self.f.close()
        return False


def _event(m, sid, ev, **kw):
    rec = {"ts": round(time.time(), 3), "session": sid, "project": m.get("project"), "ev": ev}
    rec.update(kw)
    store.append(EVENTS, rec)


def _project(m, cwd):
    if m.get("cwd") != cwd or not m.get("project"):
        from . import gitutil
        m["cwd"] = cwd
        m["project"] = gitutil.root(cwd) or cwd
    return m["project"]


def brief_line():
    from . import brief
    return brief.template().splitlines()[0].strip().lower()


def new_turn(sid, cwd=None, prompt=None):
    """A prompt reached the session: the meter for the turn starts again. The first prompt of a session
    that opens with the brief template's line makes it a worker for good."""
    with Meter(sid) as m:
        m["turn"] += 1
        m.update(calls=0, chars=0, ext=0, refusals=0, fails={}, ext_log=[], same_model_ok=False)
        m["prompts"] += 1
        if cwd:
            _project(m, cwd)
        if m["prompts"] == 1 and isinstance(prompt, str) \
                and prompt.lstrip()[:200].lower().startswith(brief_line()):
            m["worker"] = True
        return m


def end_turn(sid):
    """The turn ended (the gate let the agent finish): counts start again at the next call."""
    with Meter(sid) as m:
        m.update(calls=0, chars=0, ext=0, refusals=0, fails={}, ext_log=[], same_model_ok=False)


# ---------------------------------------------------------------- messages

def _fmt_pick(kind, difficulty, cwd, own_model):
    from . import workers
    try:
        worker, mech, _n = workers.recommend(kind, difficulty, cwd, own_model)
    except Exception as e:
        store.log_error("orchestration-route", e)
        worker, mech = None, None
    return worker, mech


def _picks(cwd, own_model):
    return (_fmt_pick("research", 1, cwd, own_model), _fmt_pick("implementation", 2, cwd, own_model))


def _pick_line(label, pick):
    worker, mech = pick
    return "  %s: %s (%s)" % (label, worker, mech) if worker else "  %s: no worker is usable now" % label


def refusal_text(m, c, picks, why="budget", detail=""):
    """At most 12 lines."""
    limit = c["direct_calls"] + m["ext"] * c["extension"]
    read, build = picks
    if why == "budget":
        head = ("sisi: %d direct tool calls this turn (limit %d, %d characters of results). Legwork belongs to a "
                "less expensive worker (rule 6)." % (m["calls"], limit, m["chars"]))
    else:
        head = "sisi: %s. Legwork belongs to a less expensive worker (rule 6)." % detail
    lines = [head, "Router for this project:", _pick_line("reading and searching", read),
             _pick_line("building", build), "Two ways on:",
             "  1. Delegate the rest: `sisi delegate brief` prints the brief to fill in; start the worker as above%s."
             % (", naming its model" if why != "budget" else ""),
             "  2. Record why doing it directly is cheaper: `sisi unit direct \"<reason>\"`%s."
             % (" (allows %d more calls this turn)" % c["extension"] if why == "budget"
                else " (also allows this same-model delegation)"),
             "This call was not run."]
    return "\n".join(lines)


def repeat_text(key, n):
    return ("sisi: `%s` has failed %d times in a row and no file has changed since, so running it again will not "
            "produce new information (rule 5). Diagnose why it fails, or change the approach; this one repeat is "
            "refused once." % (key[:80], n))


# ---------------------------------------------------------------- hook entry points

_RESP_KEYS = ("tool_response", "toolResponse", "tool_result", "toolResult", "tool_output", "result", "output", "error")


def _chars(payload):
    n = 0
    for k in _RESP_KEYS:
        if k in payload and payload[k] is not None:
            stack = [payload[k]]
            while stack:
                x = stack.pop()
                if isinstance(x, str):
                    n += len(x)
                elif isinstance(x, dict):
                    stack.extend(x.values())
                elif isinstance(x, list):
                    stack.extend(x)
            break
    return n


def _failed(payload, ev):
    if "failure" in str(ev or "").lower():
        return True
    resp = None
    for k in _RESP_KEYS:
        if isinstance(payload.get(k), dict):
            resp = payload[k]
            break
    if resp:
        for k in ("exit_code", "exitCode", "returncode", "returnCode", "code"):
            v = resp.get(k)
            if isinstance(v, int) and not isinstance(v, bool):
                return v != 0
    return False


def _norm(cmd):
    return " ".join((cmd or "").split())


def _is_worker(payload, sess, m):
    from . import workers
    return bool(m.get("worker") or sess.get("subagent") or workers.is_subagent_payload(payload))


def _own_model(payload, sess):
    v = payload.get("model")
    return v if isinstance(v, str) and v else sess.get("model")


def before(payload, host=None):
    """{"deny": text} to refuse the call, {"context": text} for advice, {} otherwise."""
    c = cfg()
    if not c["enabled"]:
        return {}
    from . import watch, workers
    tool, cmd, _ev, cwd, sid = watch.extract(payload)
    host = host or store.tool() or "claude-code"
    hd = host_data(host)
    if not hd or workers.is_subagent_payload(payload):
        return {}
    sid = sid or "cwd-" + cwd
    inp = next((payload[k] for k in ("tool_input", "toolInput", "input") if isinstance(payload.get(k), dict)), {})
    kind = classify(host, tool, inp, cmd)
    shell = watch.is_shell(tool, cmd)
    if kind == "exempt" and not shell:
        return {}
    sess = store.load_session(sid)
    with Meter(sid) as m:
        if _is_worker(payload, sess, m):
            return {}
        project = _project(m, cwd)
        m["last_tool"] = tool
        if shell:
            key = _norm(cmd)
            e = m["fails"].get(key)
            if e and e.get("n", 0) >= 3 and not e.get("refused"):
                from . import gitutil
                try:
                    fp = gitutil.fingerprint(cwd)
                except Exception:
                    fp = None
                if fp == e.get("fp"):
                    e["refused"] = True
                    m["refusals"] += 1
                    _event(m, sid, "refusal", why="repeat", tool=tool)
                    return {"deny": repeat_text(key, e["n"])}
                m["fails"].pop(key, None)
        if kind == "exempt":
            return {}
        if kind == "delegation":
            return _before_delegation(payload, hd, tool, inp, host, sid, sess, m, c, cwd)
        limit = c["direct_calls"] + m["ext"] * c["extension"]
        chars_limit = c["direct_chars"] * limit / float(c["direct_calls"])
        if m["calls"] >= limit or m["chars"] >= chars_limit:
            own = _own_model(payload, sess)
            picks = _picks(project, own)
            if not any(p[0] for p in picks):
                m["calls"] += 1
                _event(m, sid, "unrefused", why="no usable worker", tool=tool)
                _event(m, sid, "call", tool=tool)
                return {}
            m["refusals"] += 1
            _event(m, sid, "refusal", why="budget", tool=tool, calls=m["calls"], chars=m["chars"])
            return {"deny": refusal_text(m, c, picks)}
        m["calls"] += 1
        _event(m, sid, "call", tool=tool)
    return {}


def _before_delegation(payload, hd, tool, inp, host, sid, sess, m, c, cwd):
    spec = delegation_spec(hd, tool) or {}
    model = _dig(inp, spec.get("model", "model"))
    model = model.strip() if isinstance(model, str) else ""
    text = _dig(inp, spec.get("brief", "prompt"))
    own = _own_model(payload, sess)
    problem = None
    if not model:
        problem = "this delegation names no model, so the subagent would run on this session's own model%s" \
                  % (" (%s)" % own if own else "")
    elif own and workers_same(model, own):
        problem = "this delegation names this session's own model (%s)" % own
    if problem and not m.get("same_model_ok"):
        picks = _picks(m.get("project") or cwd, own)
        if any(p[0] for p in picks):
            m["refusals"] += 1
            _event(m, sid, "refusal", why="delegation-model", tool=tool)
            return {"deny": refusal_text(m, c, picks, why="delegation", detail=problem)}
    from . import brief, workers
    run_id = uuid.uuid4().hex[:8]
    now = time.time()
    worker = model or own or "(inherited)"
    try:
        workers.append_record({"kind": "run", "id": run_id, "ts": round(now), "type": None, "difficulty": None,
                               "worker": worker, "model": model or own, "tool": workers.host_tool(), "cwd": m.get("project") or cwd,
                               "session": sid, "started": round(now), "ended": None, "minutes": None,
                               "status": "pending", "origin": "hook", "tokens": None, "tokens_class": "unavailable"})
    except OSError as e:
        store.log_error("orchestration-run", e)
    key = payload.get("tool_use_id") if isinstance(payload.get("tool_use_id"), str) else "last"
    m["pending"][key] = {"run": run_id, "t0": now}
    _event(m, sid, "delegation", run=run_id, worker=worker)
    lines = ["sisi: delegation recorded as run %s. When it returns, judge it: `sisi delegate judge %s --outcome "
             "accepted|rejected --check read|tests|diffstat|review|none --type KIND --difficulty 1|2|3`."
             % (run_id, run_id)]
    if isinstance(text, str):
        lines += ["sisi brief advice: " + a for a in brief.check(text)]
    return {"context": "\n".join(lines)}


def workers_same(a, b):
    from . import workers
    return workers.same_model(a, b)


def after(payload, host=None):
    """Record what a call returned: result characters, a delegation's end, a failing shell command.
    {"context": text} may carry a line for the agent."""
    c = cfg()
    if not c["enabled"]:
        return {}
    from . import watch, workers
    tool, cmd, ev, cwd, sid = watch.extract(payload)
    host = host or store.tool() or "claude-code"
    hd = host_data(host)
    if not hd or workers.is_subagent_payload(payload):
        return {}
    sid = sid or "cwd-" + cwd
    inp = next((payload[k] for k in ("tool_input", "toolInput", "input") if isinstance(payload.get(k), dict)), {})
    kind = classify(host, tool, inp, cmd)
    shell = watch.is_shell(tool, cmd)
    if kind == "exempt" and not shell:
        return {}
    sess = store.load_session(sid)
    out = {}
    with Meter(sid) as m:
        if _is_worker(payload, sess, m):
            return {}
        _project(m, cwd)
        if kind == "delegation":
            return _after_delegation(payload, ev, sid, m)
        if shell:
            key = _norm(cmd)
            if _failed(payload, ev):
                from . import gitutil
                try:
                    fp = gitutil.fingerprint(cwd)
                except Exception:
                    fp = None
                e = m["fails"].get(key)
                if e and e.get("fp") == fp:
                    e["n"] = e.get("n", 0) + 1
                else:
                    m["fails"][key] = {"n": 1, "fp": fp, "refused": False}
            else:
                m["fails"].pop(key, None)
        if kind == "direct":
            n = _chars(payload)
            m["chars"] += n
            _event(m, sid, "chars", tool=tool, chars=n)
    return out


def _after_delegation(payload, ev, sid, m):
    from . import workers
    key = payload.get("tool_use_id") if isinstance(payload.get("tool_use_id"), str) else "last"
    ent = m["pending"].pop(key, None)
    if ent is None and m["pending"]:
        ent = m["pending"].pop(sorted(m["pending"], key=lambda k: m["pending"][k]["t0"])[-1])
    if ent is None:
        return {}
    now = time.time()
    resp = next((payload[k] for k in _RESP_KEYS if payload.get(k) is not None), None)
    tokens, _cost = workers.extract_usage(json.dumps(resp) if resp is not None else "")
    minutes = round((now - ent["t0"]) / 60.0, 2)
    if isinstance(resp, dict):
        ms = resp.get("totalDurationMs", resp.get("total_duration_ms"))
        if isinstance(ms, (int, float)) and not isinstance(ms, bool):
            minutes = round(ms / 60000.0, 2)
    failed = "failure" in str(ev or "").lower()
    try:
        workers.append_record({"kind": "run-end", "run_id": ent["run"], "ts": round(now), "ended": round(now),
                               "minutes": minutes, "tokens": tokens,
                               "tokens_class": "measured" if tokens is not None else "unavailable",
                               "status": "failed" if failed else "waiting"})
    except OSError as e:
        store.log_error("orchestration-run-end", e)
    return {"context": "sisi: delegation run %s finished (%s min). Judge it: `sisi delegate judge %s --outcome "
                       "accepted|rejected --check read|tests|diffstat|review|none --type KIND --difficulty 1|2|3`."
                       % (ent["run"], minutes, ent["run"])}


# ---------------------------------------------------------------- `sisi unit direct`

_FILLER = set("easier easy quick quicker quickly faster fast simpler simple convenient convenience myself directly "
              "direct itself rather instead because just efficient efficiently less effort overhead trivial small "
              "short like want prefer simply".split())


def reason_is_generic(text):
    """The existing generic-text check, plus the filler a lazy reason is made of: it must name something
    specific (a number, a file, a particular fact), not only that direct work is easier or faster."""
    from . import learning as L
    if L.is_generic(text):
        return True
    toks = re.findall(r"[a-z0-9_]+", (text or "").lower())
    if any(any(ch.isdigit() for ch in t) for t in toks):
        return False
    rest = [t for t in toks if len(t) >= 2 and t not in L.STOP and t not in L.GENERIC_WORDS and t not in _FILLER]
    return len(rest) < 2


def find_session(cwd):
    """The session a `sisi unit direct` belongs to: SISI_SESSION_ID, else the most recently active meter
    in this project, else the most recent one of all (within the last ten minutes)."""
    sid = os.environ.get("SISI_SESSION_ID")
    if sid:
        return sid
    d = os.path.join(paths.state(), "sessions")
    best, any_best = None, None
    from . import gitutil
    project = gitutil.root(cwd) or cwd
    try:
        names = [n for n in os.listdir(d) if n.endswith(".meter.json")]
    except OSError:
        return None
    for n in names:
        try:
            with open(os.path.join(d, n), encoding="utf-8") as f:
                mm = json.load(f)
        except (OSError, ValueError):
            continue
        ts = float(mm.get("last_ts") or 0)
        sid = mm.get("sid") or n[:-len(".meter.json")]
        if mm.get("project") == project and (best is None or ts > best[0]):
            best = (ts, sid)
        if time.time() - ts < 600 and (any_best is None or ts > any_best[0]):
            any_best = (ts, sid)
    return (best or any_best or (0, None))[1]


def cmd_direct(args, cwd=None):
    """`sisi unit direct "<reason>"`: record why doing this directly is cheaper; grants an extension."""
    reason = " ".join(args).strip()
    if not reason:
        print('usage: sisi unit direct "<why doing this directly is cheaper than delegating it>"')
        return 1
    if reason_is_generic(reason):
        print("sisi: that reason is generic: say what makes direct work cheaper here (which file, how many lines, "
              "what a brief would have to carry), not only that it is easier or faster.")
        return 1
    cwd = cwd or os.getcwd()
    sid = find_session(cwd)
    if not sid:
        print("sisi: no session is being metered here; nothing to extend (no limit applies).")
        return 0
    c = cfg()
    with Meter(sid) as m:
        if any(e.get("reason") == reason for e in m["ext_log"]):
            print("sisi: that same reason was already recorded this turn; say what is different now, or delegate.")
            return 1
        m["ext"] += 1
        m["same_model_ok"] = True
        m["ext_log"].append({"reason": reason, "ts": store.now(), "calls": c["extension"]})
        _event(m, sid, "extension", reason=reason[:300], calls=c["extension"])
        limit = c["direct_calls"] + m["ext"] * c["extension"]
    print("recorded: %d more direct calls allowed this turn (limit now %d, extension %d); the reason is kept with "
          "the unit record." % (c["extension"], limit, m["ext"]))
    return 0


# ---------------------------------------------------------------- the gate asks for judgements

def judgement_sendback(payload, sid):
    """Text asking for the judgements of this session's finished, unjudged delegations, once per set of
    runs; None when there is nothing to ask."""
    from . import workers
    runs = [r for r in workers.unjudged_runs() if r.get("session") == sid]
    if not runs:
        return None
    ids = sorted(r["id"] for r in runs)
    with Meter(sid) as m:
        if m["judge_asked"] == ids:
            return None
        m["judge_asked"] = ids
    lines = ["sisi: %d delegation(s) from this session finished and are not judged yet (rule 6: the record is the "
             "routing policy):" % len(runs)]
    for r in runs[:6]:
        lines.append("- %s: %s%s" % (r["id"], r.get("worker"), (", %s min" % r["minutes"]) if r.get("minutes") is not None else ""))
    lines.append("Judge each: `sisi delegate judge ID --outcome accepted|rejected --check read|tests|diffstat|review|none "
                 "--type KIND --difficulty 1|2|3`, then finish. (Asked once for this set.)")
    return "\n".join(lines)


# ---------------------------------------------------------------- the unit record

def _inside(project, root):
    root = str(root or "").rstrip(os.sep)
    return bool(project) and (project == root or str(project).startswith(root + os.sep))


def summary(project, t0, t1):
    """Facts about orchestration for one project between two epochs, or None when nothing was metered."""
    from . import workers
    evs = [e for e in store.read(EVENTS) if isinstance(e, dict) and _inside(e.get("project"), project)
           and isinstance(e.get("ts"), (int, float)) and (t0 is None or e["ts"] >= t0) and e["ts"] <= t1]
    if not evs:
        return None
    calls = sum(1 for e in evs if e["ev"] == "call")
    chars = sum(int(e.get("chars") or 0) for e in evs if e["ev"] == "chars")
    refusals = [e for e in evs if e["ev"] == "refusal"]
    exts = [e for e in evs if e["ev"] == "extension"]
    runs = [e["run"] for e in evs if e["ev"] == "delegation"]
    records = workers.read_records()
    judged = {r.get("run_id") for r in records if r.get("kind") == "attempt"}
    done = sum(1 for r in runs if r in judged)
    total = calls + len(runs)
    return {"direct_calls": calls, "direct_chars": chars, "refusals": len(refusals),
            "extensions": len(exts), "extension_reasons": [e.get("reason") for e in exts],
            "unrefused": sum(1 for e in evs if e["ev"] == "unrefused"),
            "delegations_started": len(runs), "delegations_judged": done,
            "delegations_unjudged": len(runs) - done,
            "delegated_share": round(len(runs) / float(total), 3) if total else None}


def telemetry(project, t0, t1):
    """The orchestration part of a unit's telemetry, each value with its class."""
    from .scorecard import val, unavailable
    s = summary(project, t0, t1)
    keys = ("direct_calls", "direct_chars", "refusals", "extensions", "extension_reasons", "delegations_started",
            "delegations_judged", "delegations_unjudged", "delegated_share")
    if s is None:
        return {k: unavailable() for k in keys}
    return {k: (val(s[k], "measured") if s[k] is not None else unavailable()) for k in keys}


def status_line(project, t0, t1):
    s = summary(project, t0, t1)
    if s is None:
        return None
    share = ("%d%%" % round(s["delegated_share"] * 100)) if s["delegated_share"] is not None else "n/a"
    line = ("orchestration (measured): %d direct calls, %d characters read, %d refusals, %d extension(s), "
            "%d delegation(s) started (%d judged, %d unjudged), %s of tool calls delegated"
            % (s["direct_calls"], s["direct_chars"], s["refusals"], s["extensions"], s["delegations_started"],
               s["delegations_judged"], s["delegations_unjudged"], share))
    if s["extension_reasons"]:
        line += "; extension reasons: " + " | ".join(str(r) for r in s["extension_reasons"])
    return line
