"""The retro: what happened, set against the objective; the gap, its cause, and the instruction that would have
prevented it. That instruction becomes a learned rule at once."""
import json, os, re, time
from . import rules, store

DONE_USAGE = """usage: sisi done --goal "<the goal in their words, 5+ words>" --check "<a check that can fail, 4+ words>" [--check ...] \\
                  --next "<what they will need next and what you do about it: now, room, follow-up or drop; 4+ words>"
       sisi done --pass N "<evidence>" | --fail N "<why>"      sisi done: show it"""
FLAGS = ("--gap", "--cause", "--improve", "--no-gap", "--later", "--scope")
SECRET = re.compile(r"\b(sk-[a-z0-9_-]{16,}|gh[pousr]_[a-z0-9]{20,}|xox[abp]-[a-z0-9-]{10,}|akia[0-9a-z]{16}|[a-f0-9]{40,})|\b(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*\S+", re.I)
USAGE = """Record one of these:
  sisi retro --gap "<where the work fell short of the objective, with the evidence>" \\
             --cause "<the root cause>" \\
             --improve "<the instruction that would have prevented it, worded as a rule>" [--scope user]
      The improvement becomes a rule at once: in this project, or with --scope user in all your work.
  sisi retro --no-gap "<what shows the work met the objective>"
  sisi retro --later "<what the unfinished work is waiting for>\""""


def clean(text):
    return SECRET.sub("<redacted>", " ".join(str(text or "").split()))


def counts(state, cwd):
    since = state.get("retro_at") or state.get("started") or time.time()
    checks = (state.get("done") or {}).get("checks") or []
    return {"minutes": int((time.time() - since) / 60), "messages": state.get("prompts_since", 0),
            "direct": state.get("direct_since", 0), "delegations": state.get("delegations_since", 0),
            "commits": len(store.git(["log", "--oneline", "--since=@%d" % since], cwd)[1].splitlines()),
            "checks_pass": sum(c["verdict"] == "pass" for c in checks), "checks_fail": state.get("fails_since", 0)}


def facts(state, cwd):
    n, dirty = counts(state, cwd), store.git(["status", "--porcelain"], cwd)[1].splitlines()
    out = ["  time: %d minutes since %s" % (n["minutes"], "the last retro" if state.get("retro_at") else "the session began"),
           "  the person wrote %d message(s) in that time: read them again. Was any a correction, or something "
           "they had to say twice?" % n["messages"],
           "  changed: %d commit(s), %d file(s) uncommitted" % (n["commits"], len(dirty)),
           "  you made %d tool call(s) yourself and %d delegation(s)" % (n["direct"], n["delegations"])]
    out += ['  you extended your own direct work: "%s"' % r for r in state.get("reasons_since") or []]
    return out


def show(d):
    mark = lambda c: "[%s: %s]" % (c["verdict"], c["evidence"]) if c["verdict"] else "[no verdict yet]"
    return (["done: " + d["goal"]] + ["  %d. %s %s" % (i, c["text"], mark(c)) for i, c in enumerate(d["checks"], 1)]
            + ["next: " + d["next"]])


def trend():
    """The measured trend over the records that carry numbers: the last 10 pieces of work and the 10 before."""
    units = []
    for line in store.read(store.data("retro.jsonl")).splitlines():
        try:
            if isinstance(json.loads(line).get("unit"), dict):
                units.append(json.loads(line))
        except (ValueError, AttributeError):
            pass
    median = lambda v: (lambda s: (s[(len(s) - 1) // 2] + s[len(s) // 2]) / 2.0)(sorted(v))
    out = []
    for label, group in (("last", units[-10:]), ("before", units[-20:-10])):
        if group:
            u = [r["unit"] for r in group]
            out.append("  %s %d: median %g min, median %g messages, %d checks failed, %d with a gap" % (
                label, len(group), median([x.get("minutes", 0) for x in u]), median([x.get("messages", 0) for x in u]),
                sum(x.get("checks_fail", 0) for x in u), sum("gap" in r for r in group)))
    return ["measured (pieces of work with numbers):"] + out if len(units) >= 2 else []


def report(sid, cwd):
    state = {}
    if sid:
        with store.session(sid) as s:
            state = dict(s)
    print("sisi retro: what happened in this piece of work.")
    print("\n".join(facts(state, cwd)))
    if state.get("done"):
        print("\n" + "\n".join(show(state["done"])))
    print("\nThe objective: %s" % rules.objective())
    print("\nSet what happened against the objective, term by term. Where did the work fall short, why, and what "
          "instruction would have prevented it? Name the root cause; general advice is not an improvement.\n")
    print(USAGE)
    if trend():
        print("\n" + "\n".join(trend()))


def record(s, cwd, opt):
    """Append one record for the piece of work in this session state, and begin the next one."""
    d, now = s.get("done") or {}, time.time()
    entry = dict(opt, ts=time.strftime("%Y-%m-%dT%H:%M:%S"), project=os.path.basename(store.project_root(cwd)),
                 unit=counts(s, cwd), goal=d.get("goal", ""), workers=s.get("workers_since", []))
    if d:
        entry["done"] = d
    log = store.data("retro.jsonl")
    store.append(log, json.dumps(entry, sort_keys=True))
    store.commit("retro recorded", log)
    s["snapshot"], s["changed"], s["retro_at"] = store.snapshot(cwd), False, now
    for key in ("prompts_since", "direct_since", "delegations_since", "reasons_since", "workers_since", "done", "paused",
                "fails_since", "picked"):
        s.pop(key, None)


def done(args, cwd=None):
    """`sisi done`: define done before the work (goal, checks, what comes next), then give every check a verdict."""
    sid, opt, verdict, i = store.current_session(cwd or os.getcwd()), {}, None, 0
    while i < len(args):
        if args[i] in ("--goal", "--next", "--check") and i + 1 < len(args):
            opt.setdefault(args[i][2:], []).append(clean(args[i + 1]))
            i += 2
        elif args[i] in ("--pass", "--fail") and i + 2 < len(args) and not verdict:
            verdict, i = (args[i][2:], args[i + 1], clean(args[i + 2])), i + 3
        else:
            i = len(args) + 1
    words = lambda key, least: all(len(x.split()) >= least for x in opt[key])
    new = bool(opt) and not verdict and set(opt) == {"goal", "next", "check"} and len(opt["goal"]) == len(opt["next"]) == 1 \
        and words("goal", 5) and words("next", 4) and words("check", 4)
    if i != len(args) or not sid or not (new or (verdict and not opt) or not (opt or verdict)):
        print(DONE_USAGE)
        return 1
    with store.session(sid) as s:
        if new:
            s["done"] = {"goal": opt["goal"][0], "next": opt["next"][0],
                         "checks": [{"text": c, "verdict": None, "evidence": ""} for c in opt["check"]]}
        elif verdict:
            kind, n, why = verdict
            if not (s.get("done") and n.isdecimal() and 1 <= int(n) <= len(s["done"]["checks"]) and len(why.split()) >= 3):
                print(DONE_USAGE)
                return 1
            s["done"]["checks"][int(n) - 1].update(verdict=kind, evidence=why)
            s["fails_since"] = s.get("fails_since", 0) + (kind == "fail")
        s.pop("paused", None) if new or verdict else None
        print("\n".join(show(s["done"])) if s.get("done") else "no done recorded yet.\n" + DONE_USAGE)
    return 0


def _options(args):
    opt, i = {}, 0
    while i < len(args):
        if args[i] in FLAGS and i + 1 < len(args):
            opt[args[i][2:]] = clean(args[i + 1])
            i += 2
        else:
            return None
    return opt


def _words(opt, key, least):
    return len((opt.get(key) or "").split()) >= least


def run(args, cwd=None):
    cwd = cwd or os.getcwd()
    sid = store.current_session(cwd)
    if not args:
        report(sid, cwd)
        return 0
    opt = _options(args)
    scope = (opt or {}).pop("scope", rules.PROJECT)
    kind = (None if not opt or scope not in (rules.USER, rules.PROJECT)
            else "later" if set(opt) == {"later"} and _words(opt, "later", 3)
            else "no-gap" if set(opt) == {"no-gap"} and _words(opt, "no-gap", 5)
            else "gap" if set(opt) == {"gap", "cause", "improve"} and all(_words(opt, k, 4) for k in opt) else None)
    if kind is None or len(opt.get("improve", "")) > 400:
        print("sisi retro: that is not a retro yet (each part needs a real sentence; an improvement is at most "
              "400 characters).\n" + USAGE)
        return 1
    if sid:
        with store.session(sid) as s:
            if kind == "no-gap" and any(c["verdict"] == "fail" for c in (s.get("done") or {}).get("checks", [])):
                print("sisi retro: a failed check is a gap; record it with --gap.")
                return 1
            if kind == "gap":
                opt["scope"] = scope
            if kind == "later":
                s["paused"] = True
            else:
                record(s, cwd, opt)
    elif kind != "later":
        record({}, cwd, dict(opt, scope=scope) if kind == "gap" else opt)
    if kind == "gap":
        print("recorded. In force from the next session%s: %s" % (
            " in every project" if scope == rules.USER else " in this project", rules.add(opt["improve"], scope, "retro", cwd)))
        if rules.due(cwd):
            print(rules.due(cwd))
    else:
        print("recorded." if kind == "no-gap" else "noted: the retro waits until this work ends.")
    return 0
