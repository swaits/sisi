"""The hooks the agent tool calls: session start, each request, before each tool call, end of turn.

Session start loads what was learned. The tool hook counts what the lead does itself and stops it when it
should be delegating. The end-of-turn hook forces the retro when work was done."""
import json, os, re, sys, time
from . import models, rules, store

# A delegated session says so in the first lines of its first request (the brief).
WORKER = re.compile(r"(?im)^\W*(you are a (worker|subagent|sub-agent|delegate)\b|do this task yourself|do not delegate)")
DIRECT = ("shell", "read", "edit", "search", "web")  # the classes of tool call the meter counts

METER = ("sisi: %d direct tool calls this turn (the limit is %d). Delegate the rest: `sisi models` lists your "
         "workers; brief one and judge what comes back. If doing this yourself really costs less than briefing "
         "it, say why first: `sisi direct \"<reason>\"` allows %d more.\n")
GATE = ("sisi: this piece of work changed things and has no retro yet. Run `sisi retro`: it prints what happened. Set that against the objective and record the gap and the improvement, or that there was none. "
        "If the work is not finished and you are only pausing (for the person, for background work), say so instead: `sisi retro --later \"<what it waits for>\"`.")
NODONE = ("sisi: nothing starts before done is recorded. Work out what the person wants and what they will need "
          "next, then: sisi done --goal \"<their goal>\" --check \"<a check that can fail>\" [--check ...] "
          "--next \"<what comes next and what you do about it>\"\n")
NOPICK = ("sisi: this delegation goes to a worker the wheel did not give you. sisi pick routine|ordinary|hard gives you one for this task "
          "(--review-of WORKER for a review, --not WORKER if one is out); one pick, one delegation.\n")
UNKNOWN = "sisi: the worker you named is not in the models table, so the table is out of date. Rebuild it now with a research worker (`sisi models research` prints the brief; `sisi models research --record FILE` records the answer), then run `sisi pick`.\n"
NOSHELL = "sisi: do not shell out to a worker; start it with the host's delegation tool.\n"
FAILED = "sisi: check %s failed. A failed check is a gap: record it with `sisi retro --gap \"<where it fell short>\" --cause \"<the root cause>\" --improve \"<the rule that prevents it>\" --term <term>`."
OPEN = "sisi: these checks have no verdict yet: %s. Give each one: sisi done --pass N \"<evidence>\" or --fail N \"<why>\". If the work is only pausing: sisi retro --later \"<what it waits for>\"."
LATE = "%s was started %s and has not reported. Check it now: if it is dead or no longer wanted, cancel it with the host's tool and record `sisi judge WORKER bad \"<why>\"`; if it reported, judge it."

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
    """A shell command that runs sisi and nothing else: free on the meter."""
    import shlex
    try:
        lex = shlex.shlex(command, posix=False, punctuation_chars=True)
        lex.whitespace_split = True
        words = list(lex)
    except ValueError:
        return False
    return (bool(words) and os.path.basename(words[0]) == "sisi" and "`" not in command and "$(" not in command
            and "\n" not in command.strip() and not any(set(w) <= set("();<>|&") for w in words))


def say(text):
    """A denial's text, naming sisi by its full path when `sisi` is not on PATH."""
    import shutil
    return text if shutil.which("sisi") else re.sub(r"(?<![\w/-])sisi(?= [a-z-])", os.path.join(store.LIB, "current", "bin", "sisi"), text)


def _begin(state, cwd):
    if "started" not in state:
        state.update(started=time.time(), project=store.project_key(cwd), snapshot=store.snapshot(cwd))


def tick(p):
    """Session start: remember where the work began; print this project's learned rules and what is due."""
    sid, cwd = p["session_id"], p["cwd"] or os.getcwd()
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
    sid = p["session_id"]
    if sid:
        with store.session(sid) as s:
            _begin(s, p["cwd"] or os.getcwd())
            if not s.get("prompts") and WORKER.search(p["prompt"][:2000]):
                s["worker"] = True
            s["prompts"] = s.get("prompts", 0) + 1
            s["prompts_since"] = s.get("prompts_since", 0) + 1
            s["direct"], s["extra"], s["blocks"] = 0, 0, 0
    return 0


def watch(p):
    """Before a tool call by the lead: count it, and refuse it when the lead should be delegating."""
    sid, tool, ti = p["session_id"], p["tool_name"].lower(), p["tool_input"]
    if p["hook_event_name"] not in ("", "PreToolUse") or not sid or p["subagent"]:
        return 0
    kind, command, cfg = tool_class(tool), str(ti.get("command") or ""), store.config()
    with store.session(sid) as s:
        _begin(s, p["cwd"] or os.getcwd())
        if s.get("worker"):
            return 0
        if kind == "shell" and own(command):
            return 0
        shell = kind == "shell" and models.is_call(command)
        if shell and not cfg["shell_workers"]:
            sys.stderr.write(say(NOSHELL))
            return 2
        if (kind in ("delegate", "edit") or shell) and not s.get("done"):
            sys.stderr.write(say(NODONE))
            return 2
        if kind == "delegate" or shell:
            target = ti.get("target") if isinstance(ti.get("target"), dict) else {}
            names = (ti.get("model"),) if tool == "agent" else (ti.get("model"), target.get("model"), ti.get("agent"))
            text = command if shell else next((n for n in names if n and isinstance(n, str)), "")  # tool_input.model may be a short name: a segment
            table_text = store.read(models.table())
            if tool != "workflow" and models.usable(table_text) and not models.claim(s, text, not shell and bool(names[0])):
                unknown = not shell and text.strip() and not models.known(table_text, text)
                unknown and models.stale(text)
                sys.stderr.write(say(UNKNOWN if unknown else NOPICK))
                return 2
            s["delegations_since"] = s.get("delegations_since", 0) + 1
            s.pop("paused", None)
            return 0
        if kind not in DIRECT:
            return 0
        limit = cfg["direct_calls"] + s.get("extra", 0)
        if cfg["meter"] and s.get("direct", 0) >= limit:
            sys.stderr.write(say(METER % (s["direct"], limit, cfg["direct_extension"])))
            return 2  # the tool call is refused and the agent reads the reason
        if kind == "edit":
            s["changed"] = True
            s.pop("paused", None)
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
    sid, cwd = p["session_id"], p["cwd"] or os.getcwd()
    if for_subagent or not sid or p["subagent"] or not store.config()["gate"]:
        return 0
    with store.session(sid) as s:
        _begin(s, cwd)
        if s.get("worker"):
            return 0
        reason, demand = " ".join("sisi: " + LATE % (w, time.strftime("%H:%M", time.localtime(t))) for w, t in models.overdue(s)), False
        if not reason and not s.get("paused"):
            checks = (s.get("done") or {}).get("checks") or []
            unsaid = ["%d. %s" % (i, c["text"]) for i, c in enumerate(checks, 1) if not c["verdict"]]
            failed = [str(i) for i, c in enumerate(checks, 1) if c["verdict"] == "fail"]
            worked = s.get("changed") or store.snapshot(cwd) != s.get("snapshot")
            if checks and not unsaid and not failed and not worked:
                from . import retro
                retro.record(s, cwd, {}, sid)  # every check passed and nothing changed: the work closes itself
                return 0
            reason = OPEN % "; ".join(unsaid) if unsaid else GATE if worked else FAILED % ", ".join(failed) if failed else ""
            demand = bool(reason and not unsaid)
        if not reason or s.get("blocks", 0) >= 2:
            return 0
        s["blocks"] = s.get("blocks", 0) + 1
        demand and s.setdefault("retro_demanded", time.time())
    print(json.dumps({"decision": "block", "reason": say(reason)}))
    return 0
