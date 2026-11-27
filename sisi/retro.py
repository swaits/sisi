"""The retro: what happened, set against the objective; the gap, its cause, and the instruction that would have
prevented it. That instruction becomes a learned rule at once."""
import json, math, os, re, time
from . import rules, store

DONE_USAGE = """usage: sisi done --goal "<the goal in their words, 5+ words>" --check "<a check that can fail, 4+ words>" [--check ...] \\
                  --next "<what they will need next and what you do about it: now, room, follow-up or drop; 4+ words>"
       sisi done --pass N "<evidence>" | --fail N "<why>"      sisi done: show it"""
FLAGS = ("--gap", "--cause", "--improve", "--no-gap", "--later", "--scope", "--term", "--better", "--problem")
TERMS = {"value": "what the person wanted", "evidence": "verified by checks that fit the risk", "time": "elapsed time",
         "cost": "compute and tool cost", "attention": "the person's attention", "learning": "getting better at the next piece of work"}
TERM_HELP = "--term is one of: %s." % ", ".join(TERMS)
clean = store.clean
USAGE = """Record one of these:
  sisi retro --gap "<where the work fell short of the objective, with the evidence>" \\
             --cause "<the root cause>" \\
             --improve "<the instruction that would have prevented it, worded as a rule>" --term TERM --problem N|"..." [--scope user]
      Cite an existing problem number N from the list above, or give new words to open one. The improvement becomes a rule at once: in this project, or with --scope user in all your work.
  sisi retro --no-gap "<what shows the work met the objective>" --term TERM \\
             --better "<one concrete thing that would have scored better on that term, 5+ words>"
      TERM is where the work fell short, or could most have scored better: %s.
      A piece of work can always be done better; the better is recorded with the retro, and becomes a rule only if it recurs, when the rules are organized.
  sisi retro --later "<what the unfinished work is waiting for>\"""" % "; ".join("%s = %s" % kv for kv in TERMS.items())


def counts(state, cwd):
    since = state.get("retro_at") or state.get("started") or time.time()
    checks = (state.get("done") or {}).get("checks") or []
    return {"minutes": int((time.time() - since) / 60), "messages": state.get("prompts_since", 0),
            "direct": state.get("direct_since", 0), "delegations": state.get("delegations_since", 0),
            "commits": len(store.git(["log", "--oneline", "--since=@%d" % since], cwd)[1].splitlines()),
            "checks_pass": sum(c["verdict"] == "pass" for c in checks), "checks_fail": state.get("fails_since", 0)}


def facts(state, cwd):
    n, dirty = counts(state, cwd), store.git(["status", "--porcelain"], cwd)[1].splitlines()
    d = show(state["done"]) if state.get("done") else ["(no done recorded)"]
    named = fell(store.records("retro.jsonl")[-10:])
    out = ["time (measured): %d minutes since %s" % (n["minutes"], "the last retro" if state.get("retro_at") else "the session began"),
           "cost (measured): you made %d tool call(s) yourself and %d delegation(s); workers used: %s" % (
               n["direct"], n["delegations"], ", ".join(state.get("workers_since") or []) or "none")]
    out += ['  you extended your own direct work: "%s"' % r for r in state.get("reasons_since") or []]
    out += ["attention (measured): the person wrote %d message(s) in that time: read them again. Was any a correction, "
            "or something they had to say twice?" % n["messages"],
            "evidence (measured): %d check(s) passed, %d failed" % (n["checks_pass"], n["checks_fail"])] + d[1:-1]
    out += ["value (judged): did the person get what they wanted? changed: %d commit(s), %d file(s) uncommitted" % (n["commits"], len(dirty))]
    from . import faults
    fs = faults.lines(cwd, store.current_session(cwd))
    return out + d[:1] + d[1:][-1:] + (["open faults (%d):" % len(fs)] + ["  " + l for l in fs] if fs else []) + ["learning (measured): last 10 pieces of work named: %s" % (named or "none yet")]


def show(d):
    mark = lambda c: "[%s: %s]" % (c["verdict"], c["evidence"]) if c["verdict"] else "[no verdict yet]"
    return (["done: " + d["goal"]] + ["  %d. %s %s" % (i, c["text"], mark(c)) for i, c in enumerate(d["checks"], 1)]
            + ["next: " + d["next"]])


def fell(group):
    """How many of these records named each term, e.g. "time 4, attention 2" (old records carry none)."""
    return ", ".join("%s %d" % (k, n) for k in TERMS for n in [sum(r.get("term") == k for r in group)] if n)


def trend():
    """The measured trend, by term, over the records that carry numbers: the last 10 pieces of work and the 10 before."""
    records = store.records("retro.jsonl")
    units = [r for r in records if isinstance(r.get("unit"), dict)]
    num = lambda x, k: x[k] if type(x.get(k)) in (int, float) else 0
    median = lambda v: (lambda s: (s[(len(s) - 1) // 2] + s[len(s) // 2]) / 2.0)(sorted(v))
    out = []
    for label, group in (("last", units[-10:]), ("before", units[-20:-10])):
        if group:
            u = [r["unit"] for r in group]
            out.append("  %s %d: time median %g min; cost median %g calls; attention median %g messages; evidence %d checks failed" % (
                label, len(group), median([num(x, "minutes") for x in u]),
                median([num(x, "direct") + num(x, "delegations") for x in u]), median([num(x, "messages") for x in u]),
                sum(num(x, "checks_fail") for x in u)))
    out.append("  fell short or could do better on: %s" % (fell(records[-10:]) or "nothing named yet"))
    return ["measured (pieces of work with numbers):"] + out if len(units) >= 2 else []


def _problems(recs=None):
    """Known problems derived from retro.jsonl in order of first appearance (1-based number)."""
    by_key, out = {}, []
    for idx, r in enumerate(store.records("retro.jsonl", 64000000) if recs is None else recs):
        if not (isinstance(r.get("problem"), str) and (name := clean(r["problem"]))):
            continue
        date, key = str(r.get("ts") or "")[:10] or "?", name.lower()
        p = by_key.get(key) or by_key.setdefault(key, {"num": len(out) + 1, "name": name, "opened": date, "attempts": []})
        p not in out and out.append(p)
        p["attempts"].append({"date": date, "cause": str(r.get("cause") or ""), "improve": str(r.get("improve") or "")})
        p["last"], p["last_idx"] = date, idx
    return out


def _problem_lines(probs):
    recent = sorted(probs, key=lambda p: (-p["last_idx"], -p["num"]))[:15]
    return ["  #%d: %s (%d attempt%s, last %s)" % (p["num"], p["name"], n := len(p["attempts"]), "" if n == 1 else "s", p["last"]) for p in recent]


def _resolve_problem(problem, probs):
    if not problem or not (norm := " ".join(problem.split())):
        return None, 'sisi retro: every --gap retro names a problem (--problem N to cite, or --problem "<name>" to open one).'
    if clean(problem) != norm:
        return None, "sisi retro: name the problem in plain words (no secrets, tokens, or long hex/digit strings)."
    if len(norm) > 400:
        return None, "sisi retro: problem name is at most 400 characters."
    if re.fullmatch(r"[+-]?\d+", norm):
        n = int(norm)
        return (probs[n - 1], "") if 1 <= n <= len(probs) else (None, "sisi retro: problem #%s does not exist." % norm)
    return next((p for p in probs if p["name"].lower() == norm.lower()), {"num": len(probs) + 1, "name": norm, "attempts": []}), ""


def report(sid, cwd):
    state = {}
    if sid:
        with store.session(sid) as s:
            state = dict(s)
    print("sisi retro: what happened in this piece of work, by term of the objective.")
    print("\n".join(facts(state, cwd)))
    print("\nThe objective: %s" % rules.objective())
    if (plines := _problem_lines(_problems())):
        print("\nknown problems (most recent first):\n" + "\n".join(plines))
    print("\nSet what happened against the objective, term by term. Where did the work fall short, why, and what "
          "instruction would have prevented it? Name the root cause; general advice is not an improvement.\n")
    print(USAGE)
    if trend():
        print("\n" + "\n".join(trend()))


def record(s, cwd, opt, sid=None):
    """Append one record for the piece of work in this session state, and begin the next one."""
    d, now, dem = s.get("done") or {}, time.time(), s.get("retro_demanded")
    entry = dict(opt, ts=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
                 project=os.path.basename(store.project_root(cwd)), unit=counts(s, cwd),
                 goal=d.get("goal", ""), workers=s.get("workers_since", []))
    if d:
        entry["done"] = d
    if sid:
        entry["session_id"] = sid
    if type(dem) in (int, float) and math.isfinite(dem) and dem <= now:
        entry["retro_seconds"] = max(0, int(round(now - dem)))
    log = store.data("retro.jsonl")
    store.append(log, json.dumps(entry, sort_keys=True))
    if not store.commit("retro recorded", log):
        print("sisi: retro saved, but store git commit failed.")
    s["snapshot"], s["changed"], s["retro_at"] = store.snapshot(cwd), False, now
    for key in ("prompts_since", "direct_since", "delegations_since", "reasons_since", "workers_since", "done", "paused",
                "fails_since", "picked", "starts", "pending", "meta", "reminded", "retro_demanded", "began"):
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
        if args[i] in FLAGS and i + 1 < len(args) and args[i][2:] not in opt:
            opt[args[i][2:]] = args[i + 1] if args[i] == "--problem" else clean(args[i + 1])
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
        return report(sid, cwd) or 0
    opt = _options(args)
    scope, term, better, problem = [(opt or {}).pop(k, None) for k in ("scope", "term", "better", "problem")]
    scope = scope or rules.PROJECT
    kind = (None if not opt or scope not in (rules.USER, rules.PROJECT)
            else "later" if set(opt) == {"later"} and _words(opt, "later", 3)
            else "no-gap" if set(opt) == {"no-gap"} and _words(opt, "no-gap", 5)
            else "gap" if set(opt) == {"gap", "cause", "improve"} and all(_words(opt, k, 4) for k in opt) else None)
    if (kind is None or len(opt.get("improve", "")) > 400 or len(better or "") > 400 or (kind == "later" and (term or better))
            or (kind != "no-gap" and better)):
        print("sisi retro: that is not a retro yet (each part needs a real sentence; an improvement is at most "
              "400 characters).\n" + USAGE)
        return 1
    if kind != "gap" and problem is not None:
        print("sisi retro: --problem goes only with --gap.")
        return 1
    if kind != "later" and term not in TERMS:
        print("sisi retro: name the term of the objective where the work fell short, or could most have scored better. " + TERM_HELP)
        return 1
    if kind == "no-gap" and len((better or "").split()) < 5:
        print("sisi retro: a piece of work can always be done better. Add --better \"<one concrete thing that would have "
              "scored better on %s, 5+ words>\"; it is recorded, and becomes a rule only if it recurs." % term)
        return 1
    prob = None
    if kind == "gap":
        probs = _problems()
        prob, why = _resolve_problem(problem, probs)
        if not prob:
            plines = _problem_lines(probs)
            print(why + ("\nknown problems (most recent first):\n" + "\n".join(plines) + "\nRe-run with --problem N (one of the numbers above) or --problem \"<new problem name>\"."
                         if plines else "\nknown problems: none yet.\nRe-run with --problem \"<new problem name>\"."))
            return 1
    opt.update({"term": term, "problem": prob["name"]} if kind == "gap" else {"term": term, "better": clean(better)} if kind == "no-gap" else {})
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
                record(s, cwd, opt, sid)
    elif kind != "later":
        record({}, cwd, dict(opt, scope=scope) if kind == "gap" else opt)
    if kind == "gap":
        found = next((p for p in _problems() if p["name"].lower() == opt["problem"].lower()), None)
        prior = found["attempts"][:-1] if found else prob["attempts"]
        prob, misses = found or prob, len(prior)
        if misses:
            print("problem %d '%s' has come back: %d miss%s" % (prob["num"], prob["name"], misses, "" if misses == 1 else "es"))
            for a in prior:
                print("  - [%s] %s" % (a["date"], a["improve"] or a["cause"] or "(no improvement recorded)"))
            for d in rules.drops_for(prob["num"]):
                print("  - dropped [%s] %s (%s)" % (str(d.get("ts") or "")[:10] or "?", d.get("rule", ""), d.get("reason", "")))
        else:
            print("opened problem %d '%s'." % (prob["num"], prob["name"]))
        try:
            added, warn = rules.add(opt["improve"], scope, "retro", cwd)
            print(warn or "recorded. In force from the next session%s: %s" % (
                " in every project" if scope == rules.USER else " in this project", added))
        except OSError as e:
            print("recorded, but could not write %s (%s)." % (rules.path(scope, cwd) or cwd, e))
        if misses >= 2:
            from . import faults
            msg = "Problem '%s' came back: written rules failed %d times. Fix it with a hook or an automatic check, not another sentence." % (prob["name"][:170], misses)
            try:
                if (hit := faults.add(cwd, msg, kind="problem:%d" % prob["num"])):
                    print("sisi: opened fault #%d: %s" % (hit["id"], hit["text"]))
            except OSError as e:
                print("sisi: could not open fault for problem %d (%s)." % (prob["num"], e))
        if rules.due(cwd):
            print(rules.due(cwd))
    else:
        print("recorded." if kind == "no-gap" else "noted: the retro waits until this work ends.")
    return 0
