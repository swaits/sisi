"""The hooks the agent tool calls: session start, each request, before each tool call, end of turn.

Session start loads what was learned. The tool hook counts what the lead does itself and reminds it when it
should be delegating. The end-of-turn hook forces the retro when work was done."""
import json, os, re, sys, time
from . import models, rules, store

# A delegated session says so in the first lines of its first request (the brief), or a host's bracketed line
# at the start of a line says an agent, not the user, sent it.
WORKER = re.compile(r"(?im)^\W*(you are a (worker|subagent|sub-agent|delegate)\b|do this task yourself|do not delegate)|\A\s*\[[^\]\n]{0,200}\bsent this message, not the user\.?\]")
DIRECT = ("shell", "read", "edit", "search", "web")  # the classes of tool call the meter counts

METER = ("sisi: %d direct tool calls this turn (the limit is %d). Delegate the rest: `sisi models` lists your workers and `sisi pick routine|ordinary|hard` "
         "chooses one; if doing this yourself costs less than briefing it, say why with `sisi direct \"<reason>\"` (%d more).")
GATE = ("sisi: this piece of work changed things and has no retro yet. Run `sisi retro` to see what happened, then record `sisi retro --gap \"<gap>\" --cause \"<cause>\" --improve \"<rule>\" --term <term>` "
        "or `sisi retro --no-gap \"<evidence>\" --term <term> --better \"<what would score better>\"` (or pause: `sisi retro --later \"<what it waits for>\"`).")
NODONE = "sisi: no done is recorded yet. Define what the person wants and what comes next now: `sisi done --goal \"<their goal>\" --check \"<a check that can fail>\" [--check ...] --next \"<what comes next and what you do about it>\"`."
NOPICK = ("sisi: this delegation went to a worker the wheel did not give you (recorded so `sisi judge` still works). Use `sisi pick routine|ordinary|hard` next time "
          "(--review-of WORKER for a review, --not WORKER if one is out); one pick, one delegation.")
UNKNOWN = "sisi: the worker you named is not in the models table (recorded so `sisi judge` still works), so the table is out of date. Rebuild it now with a research worker (`sisi models research` prints the brief; `sisi models research --record FILE` records the answer), and use `sisi pick` next time."
NOSHELL = "sisi: do not shell out to a worker; start it with the host's delegation tool next time."
FAILED = "sisi: check %s failed. A failed check is a gap: record `sisi retro --gap \"<where it fell short>\" --cause \"<the root cause>\" --improve \"<the rule that prevents it>\" --term <term>` (or pause: `sisi retro --later \"<what it waits for>\"`)."
OPEN = "sisi: these checks have no verdict yet: %s. Give each one: `sisi done --pass N \"<evidence>\"` or `sisi done --fail N \"<why>\"` (or pause: `sisi retro --later \"<what it waits for>\"`)."
LATE = "%s was started %s and has not reported. Check it: if still running, let it finish (this reminder is shown once); if dead or unwanted, cancel it and run `sisi judge WORKER bad \"<why>\"`; if it reported, run `sisi judge WORKER good|bad \"<why>\"`."

# The names each host gives a hook's fields; the first one present (and of the right type) wins.
FIELDS = (("session_id", str, ("session_id", "sessionId", "conversation_id", "conversationId")),
          ("tool_name", str, ("tool_name", "toolName", "tool", "toolCall.name")),
          ("tool_input", dict, ("tool_input", "toolInput", "input", "toolCall.args")),
          ("prompt", str, ("prompt", "lastUserInput")),
          ("hook_event_name", str, ("hook_event_name", "hookEventName")),
          ("cwd", str, ("cwd", "workspace_roots", "workspacePaths")))
SUBAGENT = ("agent_id", "agentId", "subagent_id", "subagentType", "agent_transcript_path")
_classes = None


def normalize(p):
    """Any host's hook input as one shape. A field of the wrong type is empty, never an error."""
    def get(name):
        v = p
        for part in name.split("."):
            v = v.get(part) if isinstance(v, dict) else None
        return v
    out = {}
    for key, kind, names in FIELDS:
        vals = [get(n) for n in names]
        if key == "cwd":
            vals = [v[0] if isinstance(v, list) and v else v for v in vals]  # workspace_roots is a list
        out[key] = next((v for v in vals if isinstance(v, kind) and v), kind())
    out["subagent"] = any(get(n) for n in SUBAGENT) or "/subagents/" in str(get("transcript_path") or "")
    return out


def payload():
    try:
        p = json.load(sys.stdin)
    except ValueError:
        p = None
    return normalize(p if isinstance(p, dict) else {})


def tool_class(tool):
    """shell, read, edit, search, web or delegate, by the table in canon/tools.json; "" for any other tool."""
    global _classes
    if _classes is None:
        try:
            raw = json.loads(store.read(os.path.join(store.ROOT, "canon", "tools.json")))
            _classes = {n: c for c, names in raw.items() for n in names}
        except (ValueError, AttributeError, TypeError):
            _classes = {}  # a missing or broken table meters nothing rather than breaking the session
    tool = tool.lower()
    return _classes.get(tool) or ("delegate" if tool.endswith("delegate_task") else "")


def own(command):
    """A shell command that runs only sisi (optionally chained with ; / && or piped to grep/tail/head): free."""
    tok_re = re.compile(r"[ \t]*(?:(?!\|\||\|&)(&&|[;|])|((?:'[^']*'|\"(?:\\.|(?!\$[({])[^\"\\`])*\"|\\[^\n]|(?!\$[({])[^\s'\";<>|&()`\\])+))")
    s, pos, op, ok = command.strip(), 0, ";", False
    while pos < len(s) and (m := tok_re.match(s, pos)):
        pos, tok, w = m.end(), m.group(1), (m.group(2) or "").strip("\"'")
        if (tok and not ok) or (not tok and op and not (os.path.basename(w) == "sisi" if op != "|" else w in ("grep", "tail", "head"))):
            return False
        op, ok = (tok, False) if tok else ("", True)
    return ok and pos == len(s)


def say(text):
    """A hook message, naming sisi by its full path when `sisi` is not on PATH."""
    import shutil
    return text if shutil.which("sisi") else re.sub(r"(?<![\w/-])sisi(?= [a-z-])", os.path.join(store.LIB, "current", "bin", "sisi"), text)


def _begin(state, cwd):
    if "started" not in state:
        state.update(started=time.time(), project=store.project_key(cwd), snapshot=store.snapshot(cwd))
        try:
            state["free_bytes"] = (st := os.statvfs(cwd)).f_bavail * st.f_frsize
        except OSError:
            pass


def _faults(cwd, gate=False, free=None, sid=""):
    if gate and not os.path.lexists(os.path.join(store.STATE, "core-faults", store.project_key(cwd) + ".json")):
        return ""
    from . import faults
    return faults.gate(cwd, sid) if gate else faults.check(cwd, free, sid)


def tick(p):
    """Session start: remember where the work began; print this project's learned rules and what is due."""
    sid, cwd, worker, free = p["session_id"], p["cwd"] or os.getcwd(), p["subagent"], None
    if sid:
        with store.session(sid) as s:
            _begin(s, cwd)
            worker, free = worker or bool(s.get("worker")), s.get("free_bytes")
        env = os.environ.get("CLAUDE_ENV_FILE")
        if env and re.fullmatch(r"[A-Za-z0-9_-]+", str(sid)):
            store.append(env, "export SISI_SESSION_ID=%s" % sid, once=True)  # so `sisi retro` knows its session
    if not os.path.exists(os.path.join(store.DATA, "generated", "core.md")):
        rules.build_rulebook()
    text = "\n".join(x for x in (rules.project_text(cwd), rules.due(cwd, claim=True), models.stale(), "" if worker else _faults(cwd, False, free, sid)) if x)
    if text:
        print(text)
    return 0


def _late_lines(late1, cwd):
    now, cfg_m = time.time(), store.config()["worker_minutes"]
    def prog(branch, ext):
        rc, out = store.git(["log", "-1", "--format=%ct", branch], cwd, timeout=2) if branch else (1, "")
        return "commit %dm ago on %s" % (max(0, int((now - int(out.strip())) / 60)), branch) if rc == 0 and out.strip().isdigit() else "extended %dm ago" % max(0, int((now - ext) / 60)) if ext is not None else "no report since it started"
    return ["sisi: worker %s has run %dm (limit %gm); last progress: %s" % (w, int((now - t) / 60), lim if lim is not None else cfg_m, prog(b, e)) for w, t, lim, b, e in late1]


def prompt(p):
    """Each request: a new turn begins. The first request tells a delegated worker from a lead."""
    sid, cwd, worker, free, late1 = p["session_id"], p["cwd"] or os.getcwd(), p["subagent"], None, []
    if sid:
        with store.session(sid) as s:
            _begin(s, cwd)
            if not s.get("prompts") and WORKER.search(p["prompt"][:2000]):
                s["worker"] = True
            worker, free = worker or bool(s.get("worker")), s.get("free_bytes")
            worker or not p["prompt"].strip() or WORKER.search(p["prompt"][:2000]) or s.update(said=((s["said"] if isinstance(s.get("said"), list) else []) + [" ".join(p["prompt"].split())[:8000]])[-20:])  # the person's own words
            s["prompts"] = s.get("prompts", 0) + 1
            s.get("prompts_since") or s.update(began=time.time())  # the first request of a piece of work
            s["prompts_since"] = s.get("prompts_since", 0) + 1
            s["direct"], s["extra"], s["blocks"] = 0, 0, 0
            not worker and (models.sync_late(s, cwd, sid), late1 := models.late(s, 1))
    not worker and (text := "\n".join(x for x in [_faults(cwd, False, free, sid)] + _late_lines(late1, cwd) if x)) and print(text)
    return 0


def watch(p):
    """Before a tool call by the lead: count it, record delegations, and remind when off-course (never blocking)."""
    sid, tool, ti = p["session_id"], p["tool_name"].lower(), p["tool_input"]
    if p["hook_event_name"] not in ("", "PreToolUse") or not sid or p["subagent"]:
        return 0
    kind, cfg = tool_class(tool), store.config()
    command = next((v for k in ("command", "cmd", "CommandLine") if isinstance(v := ti.get(k), str) and v), "")
    notes = []
    with store.session(sid) as s:
        _begin(s, p["cwd"] or os.getcwd())
        if s.get("worker") or (kind == "shell" and own(command)):
            return 0
        shell = kind == "shell" and models.is_call(command)
        shell and not cfg["shell_workers"] and notes.append(NOSHELL)
        (kind in ("delegate", "edit") or shell) and not s.get("done") and notes.append(NODONE)
        if kind == "delegate" or shell:
            target = ti.get("target") if isinstance(ti.get("target"), dict) else {}
            names = (ti.get("model"),) if tool == "agent" else (ti.get("model"), target.get("model"), ti.get("agent"))
            text = command if shell else next((n for n in names if n and isinstance(n, str)), "")
            table_text = store.read(models.table())
            if tool != "workflow" and not models.claim(s, text, not shell and bool(names[0])):
                probe = {"picked": [models.short(r[0]) for r in models.rows(table_text)]}
                known = models.claim(probe, text, True)
                if models.usable(table_text):
                    not shell and text.strip() and not known and models.stale(text)
                    notes.append(UNKNOWN if not shell and text.strip() and not known else NOPICK)
                w = (probe.get("workers_since") or [models.short(text) if not shell else ""])[0]
                if re.fullmatch(r"[a-z0-9._/:+-]{1,80}", w):
                    d = {"picked": [w], "starts": s.get("starts"), "workers_since": s.get("workers_since") if isinstance(s.get("workers_since"), list) else []}
                    models.claim(d, w) and s.update(starts=d["starts"], workers_since=d["workers_since"])
            s["delegations_since"] = s.get("delegations_since", 0) + 1
            s.pop("paused", None)
        elif kind in DIRECT:
            limit = cfg["direct_calls"] + s.get("extra", 0)
            cfg["meter"] and s.get("direct", 0) >= limit and notes.append(METER % (s.get("direct", 0), limit, cfg["direct_extension"]))
            if kind == "edit":
                s["changed"] = True
                s.pop("paused", None)
            s["direct"], s["direct_since"] = s.get("direct", 0) + 1, s.get("direct_since", 0) + 1
    if notes:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": say("\n".join(notes))}}))
    return 0


def direct(args, cwd=None):
    """`sisi direct "<reason>"`: the lead says why doing more itself costs less than delegating it."""
    reason, sid, cfg = " ".join(" ".join(args).split()), store.current_session(cwd), store.config()
    if len(reason.split()) < 4 or not sid:
        print('usage: sisi direct "<why doing this yourself costs less than briefing a worker>"')
        return 1
    with store.session(sid) as s:
        s["extra"] = s.get("extra", 0) + cfg["direct_extension"]
        s.setdefault("reasons_since", []).append(reason[:200])
    print("%d more direct calls this turn. The reason goes into the retro." % cfg["direct_extension"])
    return 0


def gate(p, for_subagent=False):
    """End of turn: when the lead changed things and has not held the retro, send it back to hold it."""
    sid, cwd = p["session_id"], p["cwd"] or os.getcwd()
    if for_subagent or not sid or p["subagent"] or not store.config()["gate"]:
        return 0
    with store.session(sid) as s:
        _begin(s, cwd)
        if s.get("worker"):
            return 0
        models.sync_late(s, cwd, sid)
        open_f, starts = _faults(cwd, True, None, sid), s["starts"] if isinstance(s.get("starts"), dict) else {}
        seen = [x for x in (s["reminded"] if isinstance(s.get("reminded"), list) else [])
                if isinstance(x, list) and len(x) == 2 and x[1] in (starts.get(x[0]) if isinstance(starts.get(x[0]), list) else ())]
        late = models.overdue({"starts": {w: [t for t in v if [w, t] not in seen] for w, v in starts.items() if isinstance(v, list)}, "meta": s.get("meta")})
        reason, demand = " ".join("sisi: " + LATE % (w, time.strftime("%H:%M", time.localtime(t))) for w, t in late), False
        if not reason and not s.get("paused"):
            checks = (s.get("done") or {}).get("checks") or []
            unsaid = ["%d. %s" % (i, c["text"]) for i, c in enumerate(checks, 1) if not c["verdict"]]
            failed = [str(i) for i, c in enumerate(checks, 1) if c["verdict"] == "fail"]
            worked = s.get("changed") or store.snapshot(cwd) != s.get("snapshot")
            quick = 0 <= time.time() - s.get("began", 0) < 60 * store.config()["retro_minutes"] and not s.get("delegations_since") and not s.get("fails_since")
            if checks and not unsaid and not failed and (not worked or quick):
                from . import retro
                retro.record(s, cwd, {}, sid)  # every check passed and nothing changed, or it was quick and alone: the work closes itself
            else:
                reason = "" if unsaid and models.waiting(s) else OPEN % "; ".join(unsaid) if unsaid else GATE if worked else FAILED % ", ".join(failed) if failed else ""
                demand = bool(reason and not unsaid)
        reason = " ".join(x for x in (open_f, reason) if x)
        if reason and s.get("blocks", 0) < 2:
            seen += [[w, t] for w, t in late]
        s.pop("reminded", None) if not seen else s.update(reminded=seen)
        if not reason or s.get("blocks", 0) >= 2:
            return 0
        s["blocks"] = s.get("blocks", 0) + 1
        demand and s.setdefault("retro_demanded", time.time())
    print(json.dumps({"decision": "block", "reason": say(reason)}))
    return 0
