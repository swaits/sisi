"""The models table: which workers this person can delegate to, what each is good at and what it costs.

A research worker writes it, the lead reads it to route, and `sisi judge` adds how each delegation went so the
next research knows. The table is plain text a person can read and correct."""
import json, os, time
from . import rules, store

RESEARCH = """You are a worker. Do this task yourself; do not delegate it further.

Find out which AI models this machine can delegate work to, what each is good at and what it costs, and write
the table an engineering lead will route by.

1. What is there. Look for AI coding command-line tools on PATH and run each one's own model listing. Add the
   models the host offers its own subagents. Do not log in, change a setting or run a paid task.
2. What each is good at. Use current public software-engineering benchmarks and the maker's own description
   (search the web), then our own record below, which outranks a benchmark.
3. What it costs here: free, a flat plan with an allowance, or paid per use, and anything that limits it.
4. Only the newest version of each model belongs in the table. A smaller or faster variant is a different model.
5. What the person has said, below, stands exactly: their limits and preferences are not yours to change.

Answer with exactly this and nothing else. First a markdown table of at most 40 rows, the cheapest capable
worker first within each level, with these columns:
| worker | how to call it | use for | cost | good at, bad at | notes |
"use for" is one or more of: routine, ordinary, hard. "how to call it" is exact: the host's subagent model
name, or the full command line with <brief> where the brief goes.
Then one line starting "Fallback order:" that says who takes over when a worker is out, level by level.

=== The table now ===
%(table)s

=== What the person has said ===
%(owner)s

=== How delegations went here, newest last ===
%(outcomes)s
"""
ASK = ("In the background, give the output of `sisi models research` to a research worker and record its "
       "answer with `sisi models research --record FILE`.")


def table():
    return store.data("models.md")


def age_days():
    try:
        return (time.time() - os.path.getmtime(table())) / 86400.0
    except OSError:
        return None


def stale():
    """One line when the table is missing or old, else ""."""
    age = age_days()
    if age is None:
        return "sisi: there is no models table yet. " + ASK
    if age > store.config()["research_days"]:
        return "sisi: the models table is %d days old. %s" % (age, ASK)
    return ""


def outcomes(n):
    out = []
    for line in store.read(store.data("outcomes.jsonl")).splitlines()[-n:]:
        try:
            o = json.loads(line)
            out.append("%s  %s  %s  %s" % (o["ts"][:10], o["worker"], o["verdict"], o["why"]))
        except (ValueError, KeyError):
            pass
    return out


def research_brief():
    owner = [l for l in rules.lines(rules.path(rules.USER)) if "[owner" in l]
    return RESEARCH % {"table": store.read(table()).rstrip() or "(none yet)",
                       "owner": "\n".join(owner) or "(nothing)", "outcomes": "\n".join(outcomes(60)) or "(none yet)"}


def research_record(answer_file):
    text = store.read(answer_file).strip()
    rows = [l for l in text.splitlines() if l.startswith("|")]
    if "| worker" not in text.lower() or "fallback order:" not in text.lower() or len(rows) < 3:
        return "the answer needs the table (a `| worker |` header and at least one row) and a `Fallback order:` line"
    if len(rows) > 42 or len(text) > 12000:
        return "the answer is too long (at most 40 rows and 12,000 characters)"
    store.write(table(), text + "\n")
    store.commit("models table researched", table())
    print("models table recorded: %d workers." % (len(rows) - 2))
    return None


def judge(args, cwd=None):
    """`sisi judge WORKER good|bad "<why>"`: how a delegation went."""
    if len(args) != 3 or args[1] not in ("good", "bad") or len(args[2].split()) < 3:
        print('usage: sisi judge WORKER good|bad "<what it did well or badly, in a sentence>"')
        return 1
    log = store.data("outcomes.jsonl")
    store.append(log, json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "worker": args[0], "verdict": args[1],
                                  "why": " ".join(args[2].split()),
                                  "project": os.path.basename(store.project_root(cwd))}, sort_keys=True))
    store.commit("delegation judged", log)
    print("recorded.")
    return 0


def run(args, cwd=None):
    if not args:
        text = store.read(table()).rstrip()
        print(text or stale())
        if text:
            print("\n(researched %d days ago)" % age_days())
            recent = outcomes(15)
            if recent:
                print("\nHow recent delegations went:\n" + "\n".join(recent))
            if stale():
                print("\n" + stale())
        return 0
    if args == ["research"]:
        print(research_brief())
        return 0
    if len(args) == 3 and args[:2] == ["research", "--record"]:
        why = research_record(args[2])
        if why:
            print("sisi models: %s. Nothing was changed." % why)
        return 1 if why else 0
    print("usage: sisi models | sisi models research [--record FILE]")
    return 1
