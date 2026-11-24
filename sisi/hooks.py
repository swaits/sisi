"""The hooks the agent tool calls: session start, each request, before each tool call, end of turn.

Session start loads what was learned. The tool hook counts what the lead does itself and stops it when it
should be delegating. The end-of-turn hook forces the retro when work was done."""
import json, os, re, sys, time
from . import models, rules, store

# A delegated session says so in the first lines of its first request (the brief).
WORKER = re.compile(r"(?im)^\W*(you are a (worker|subagent|sub-agent|delegate)\b|do this task yourself|do not delegate)")
DIRECT = {"Bash", "Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "Grep", "Glob", "WebFetch", "WebSearch"}
EDITS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
OWN = re.compile(r"\s*(\S*/)?sisi\s[^;&|<>`$]*")  # a shell command that runs sisi and nothing else

METER = ("sisi: %d direct tool calls this turn (the limit is %d). Delegate the rest: `sisi models` lists your "
         "workers; brief one and judge what comes back. If doing this yourself really costs less than briefing "
         "it, say why first: `sisi direct \"<reason>\"` allows %d more.\n")
GATE = ("sisi: this piece of work changed things and has no retro yet. Run `sisi retro`: it prints what "
        "happened. Set that against the objective and record the gap and the improvement, or that there was "
        "none. If the work is not finished and you are only pausing (for the person, for background work), say "
        "so instead: `sisi retro --later \"<what it waits for>\"`.")
NODONE = ("sisi: nothing starts before done is recorded. Work out what the person wants and what they will need "
          "next, then: sisi done --goal \"<their goal>\" --check \"<a check that can fail>\" [--check ...] "
          "--next \"<what comes next and what you do about it>\"\n")
NOPICK = ("sisi: this delegation goes to a worker the wheel did not give you. sisi pick routine|ordinary|hard gives "
          "you one for this task (--review-of WORKER for a review, --not WORKER if one is out); one pick, one "
          "delegation.\n")
NOSHELL = "sisi: do not shell out to a worker; start it with the host's delegation tool.\n"
OPEN = ("sisi: these checks have no verdict yet: %s. Give each one: sisi done --pass N \"<evidence>\" or --fail N "
        "\"<why>\". If the work is only pausing: sisi retro --later \"<what it waits for>\".")


def payload():
    try:
        p = json.load(sys.stdin)
        return p if isinstance(p, dict) else {}
    except ValueError:
        return {}


def subagent(p):
    """The host's own subagents share their parent's session: the hook's input is what tells them apart."""
    return bool(p.get("agent_id") or p.get("agentId") or p.get("agent_transcript_path")
                or "/subagents/" in str(p.get("transcript_path") or ""))


def delegation(tool):
    return tool in ("Agent", "Task", "Workflow") or tool.endswith("delegate_task")


def _begin(state, cwd):
    if "started" not in state:
        state.update(started=time.time(), project=store.project_key(cwd), snapshot=store.snapshot(cwd))


def tick(p):
    """Session start: remember where the work began; print this project's learned rules and what is due."""
    sid, cwd = p.get("session_id"), p.get("cwd") or os.getcwd()
    if sid:
        with store.session(sid) as s:
            _begin(s, cwd)
        env = os.environ.get("CLAUDE_ENV_FILE")
        if env and re.fullmatch(r"[A-Za-z0-9_-]+", str(sid)):
            store.append(env, "export SISI_SESSION_ID=%s" % sid)  # so `sisi retro` knows its session
    if not os.path.exists(os.path.join(store.DATA, "generated", "core.md")):
        rules.build_rulebook()
    text = "\n".join(x for x in (rules.project_text(cwd), rules.due(cwd), models.stale()) if x)
    if text:
        print(text)
    return 0


def prompt(p):
    """Each request: a new turn begins. The first request tells a delegated worker from a lead."""
    sid = p.get("session_id")
    if sid:
        with store.session(sid) as s:
            _begin(s, p.get("cwd") or os.getcwd())
            if not s.get("prompts") and WORKER.search(str(p.get("prompt") or "")[:2000]):
                s["worker"] = True
            s["prompts"] = s.get("prompts", 0) + 1
            s["prompts_since"] = s.get("prompts_since", 0) + 1
            s["direct"], s["extra"], s["blocks"] = 0, 0, 0
    return 0


def watch(p):
    """Before a tool call by the lead: count it, and refuse it when the lead should be delegating."""
    sid, tool = p.get("session_id"), str(p.get("tool_name") or "")
    if p.get("hook_event_name") not in (None, "PreToolUse") or not sid or subagent(p):
        return 0
    ti = p.get("tool_input") if isinstance(p.get("tool_input"), dict) else {}
    command, cfg = str(ti.get("command") or ""), store.config()
    with store.session(sid) as s:
        _begin(s, p.get("cwd") or os.getcwd())
        if s.get("worker"):
            return 0
        if tool == "Bash" and OWN.fullmatch(command):
            return 0
        shell = tool == "Bash" and models.is_call(command)
        if shell and not cfg["shell_workers"]:
            sys.stderr.write(NOSHELL)
            return 2
        if (delegation(tool) or shell or tool in EDITS) and not s.get("done"):
            sys.stderr.write(NODONE)
            return 2
        if delegation(tool) or shell:
            target = ti.get("target") if isinstance(ti.get("target"), dict) else {}
            text = command if shell else str((target if tool.endswith("delegate_task") else ti).get("model") or "")
            if tool != "Workflow" and store.read(models.table()) and not models.claim(s, text):
                sys.stderr.write(NOPICK)
                return 2
            s["delegations_since"] = s.get("delegations_since", 0) + 1
            return 0
        if tool not in DIRECT:
            return 0
        limit = cfg["direct_calls"] + s.get("extra", 0)
        if cfg["meter"] and s.get("direct", 0) >= limit:
            sys.stderr.write(METER % (s["direct"], limit, cfg["direct_extension"]))
            return 2  # the tool call is refused and the agent reads the reason
        if tool in EDITS:
            s["changed"] = True
        s["direct"] = s.get("direct", 0) + 1
        s["direct_since"] = s.get("direct_since", 0) + 1
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
    sid, cwd = p.get("session_id"), p.get("cwd") or os.getcwd()
    if for_subagent or not sid or subagent(p) or not store.config()["gate"]:
        return 0
    with store.session(sid) as s:
        _begin(s, cwd)
        if s.get("worker"):
            return 0
        checks = (s.get("done") or {}).get("checks") or []
        unsaid = ["%d. %s" % (i, c["text"]) for i, c in enumerate(checks, 1) if not c["verdict"]]
        failed = any(c["verdict"] == "fail" for c in checks)
        worked = s.get("changed") or store.snapshot(cwd) != s.get("snapshot")
        if checks and not unsaid and not failed and not worked:
            from . import retro
            retro.record(s, cwd, {})  # every check passed and nothing changed: the work closes itself
            return 0
        reason = OPEN % "; ".join(unsaid) if unsaid and not s.get("later") else GATE if worked or failed else ""
        if not reason or s.get("blocks", 0) >= 2:
            return 0
        s["blocks"] = s.get("blocks", 0) + 1
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0
