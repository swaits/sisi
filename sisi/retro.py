"""The retro: what happened, set against the objective; the gap, its cause, and the instruction that would have
prevented it. That instruction becomes a learned rule at once."""
import json, os, re, time
from . import rules, store

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


def facts(state, cwd):
    since = state.get("retro_at") or state.get("started") or time.time()
    commits = store.git(["log", "--oneline", "--since=@%d" % since], cwd)[1].splitlines()
    dirty = store.git(["status", "--porcelain"], cwd)[1].splitlines()
    out = ["  time: %d minutes since %s" % ((time.time() - since) / 60,
                                           "the last retro" if state.get("retro_at") else "the session began"),
           "  the person wrote %d message(s) in that time: read them again. Was any a correction, or something "
           "they had to say twice?" % state.get("prompts_since", 0),
           "  changed: %d commit(s), %d file(s) uncommitted" % (len(commits), len(dirty)),
           "  you made %d tool call(s) yourself and %d delegation(s)" % (state.get("direct_since", 0),
                                                                        state.get("delegations_since", 0))]
    out += ['  you extended your own direct work: "%s"' % r for r in state.get("reasons_since") or []]
    return out


def report(sid, cwd):
    state = {}
    if sid:
        with store.session(sid) as s:
            state = dict(s)
    print("sisi retro: what happened in this piece of work.")
    print("\n".join(facts(state, cwd)))
    print("\nThe objective: %s" % rules.objective())
    print("\nSet what happened against the objective, term by term. Where did the work fall short, why, and what "
          "instruction would have prevented it? Name the root cause; general advice is not an improvement.\n")
    print(USAGE)


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
    if kind != "later":
        entry = dict(opt, ts=time.strftime("%Y-%m-%dT%H:%M:%S"), project=os.path.basename(store.project_root(cwd)))
        if kind == "gap":
            entry["scope"] = scope
        log = store.data("retro.jsonl")
        store.append(log, json.dumps(entry, sort_keys=True))
        store.commit("retro recorded", log)
    if sid:
        with store.session(sid) as s:
            s["snapshot"], s["changed"], s["blocks"] = store.snapshot(cwd), False, 0
            if kind != "later":
                s["retro_at"] = time.time()
                for counter in ("prompts_since", "direct_since", "delegations_since", "reasons_since"):
                    s.pop(counter, None)
    if kind == "gap":
        print("recorded. In force from the next session%s: %s" % (
            " in every project" if scope == rules.USER else " in this project", rules.add(opt["improve"], scope, "retro", cwd)))
        if rules.due(cwd):
            print(rules.due(cwd))
    else:
        print("recorded." if kind == "no-gap" else "noted: the retro waits until this work ends.")
    return 0
