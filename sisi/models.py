"""The models table: which workers this person can delegate to, what each is good at and what it costs.

A research worker writes it, the lead reads it to route, and `sisi judge` adds how each delegation went so the
next research knows. The table is plain text a person can read and correct."""
import json, math, os, re, time
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

List only workers the host's delegation tool can actually start: check the host's own list of enabled providers.
Answer with exactly this and nothing else. First a markdown table of at most 40 rows, the cheapest capable
worker first within each level, with these columns:
| worker | maker | how to call it | use for | cost | good at, bad at | notes |
"maker" is the company or lab that trained the model, lower case, one word. "use for" is exactly one of: routine,
ordinary, hard. It is the model's capability class, not a list of tasks it could do. Routine is the small, fast,
cheap tier (the level of a maker's smallest current model); ordinary is the mid tier (a maker's main everyday
model); hard is the top tier (a maker's strongest model). Place each model by comparing it with its peers from
other makers (benchmarks and the maker's own positioning), so that every class holds models of like strength from
several makers. A model that seems to fit two classes goes in the lower one only if it truly performs at that
level, never in both. "how to call it" is exact: the host delegation tool's provider and model id (T3 Code's
delegate_task); the host's subagent model name where it has subagents; the full command line with <brief> where
the brief goes only for a worker the host's tool cannot reach. A worker that is unavailable carries exactly
`out until YYYY-MM-DD` in its notes.
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


def table(): return store.data("models.md")


def age_days():
    try:
        return (time.time() - os.path.getmtime(table())) / 86400.0
    except OSError:
        return None


def stale(mark=None):
    """One line when the table is missing, old, or missed a worker, else ""."""
    who = re.sub(r"[^\w./:+-]", "", str(store.read(store.data("models.stale")) if mark is None else mark), flags=re.A)[:80]
    if mark is not None and who:
        try:
            store.write(store.data("models.stale"), who + "\n")
        except Exception:  # best effort: a refusal never depends on it
            pass
    age = age_days()
    if age is None or age > store.config()["research_days"]:
        return "sisi: " + ("there is no models table yet. " if age is None else "the models table is %d days old. " % age) + ASK
    return ("sisi: a delegation named `%s`, which the models table does not list. " % who + ASK) if who and not known(store.read(table()), who) else ""


KEYS = ("worker", "how", "use", "cost", "good", "notes", "maker")  # a column is known by its header's first word
LAUNCHERS = {"python", "python3", "bash", "sh", "zsh", "cd", "env", "npx", "npm", "node", "uv", "uvx", "make", "ssh",
             "git", "docker", "sudo"}


def rows(text):
    """The table's worker rows, each a list of cells in the order of KEYS, found by header name."""
    out, cols = [], KEYS[:6]
    for line in text.splitlines():
        c = [x.strip() for x in line.strip().strip("|").split("|")] if line.startswith("|") else []
        if c and c[0].lower() == "worker":
            cols = [(x.split() or [""])[0].lower() for x in c]
        elif len(c) >= 5 and not set(c[0]) <= set("-: "):
            out.append([dict(zip(cols, c)).get(k, "") for k in KEYS])
    return out


def usable(text): return any(re.search(r"routine|ordinary|hard", r[2].lower()) for r in rows(text))


def short(cell): return (str(cell).split() or [""])[0].lower()


def maker(r):
    """Who made a worker: its maker cell; else the leading letters of the last path segment of its name; else
    its call text without its own name (the same way of calling, the same maker)."""
    name, m = short(r[0]), re.match(r"[a-z]+", short(r[0]).rsplit("/", 1)[-1])
    return r[6].lower() or (m.group() if "/" in name and m else r[1].lower().replace(name, "") or name)


def command(row): return "<brief>" in row[1] and "host subagent" not in row[1].lower()


def is_call(command_line):
    """Does any segment of this shell command start a worker in the table (after nohup, exec, time, env, VAR=)?"""
    starts = {(r[1].replace("`", "").split() or [""])[0] for r in rows(store.read(table())) if command(r)} - LAUNCHERS
    for seg in re.split(r"&&|\|\||[;|&\n]", command_line):
        words = [w for w in seg.split()]
        while words and (words[0] in ("nohup", "exec", "time", "env") or re.match(r"[A-Za-z_]\w*=", words[0])):
            words.pop(0)
        if words and os.path.basename(words[0]) in starts:
            return True
    return False


def known(table_text, text): return claim({"picked": [short(r[0]) for r in rows(table_text)]}, text, True)


def claim(s, text, segment=False):
    """Spend the pick that this delegation's model text names; False when none of the picks fits. With `segment` (the
    host names its models shortly: `fast` for `maker-fast-2`) one whole `-` segment of a picked id's last `/` part that has a letter fits."""
    for name in s.get("picked") or []:
        if any(re.search(r"(?<![a-z0-9.-])%s(?![a-z0-9.-])" % re.escape(n), text.lower()) for n in (name, name.rsplit("/", 1)[-1])) or (
                segment and re.search("[a-z]", text.lower()) and text.lower() in name.rsplit("/", 1)[-1].split("-")):
            s["picked"].remove(name)
            starts = s["starts"] if isinstance(s.get("starts"), dict) else {}
            starts[name] = (starts[name] if isinstance(starts.get(name), list) else []) + [time.time()]
            s["starts"] = starts  # `sisi judge` times the job from here
            s.setdefault("workers_since", []).append(name)
            return True
    return False


def overdue(s):
    """Open delegations older than `worker_minutes`: [(worker, its oldest such start)]. A bad or future start is none."""
    mins, starts = store.config()["worker_minutes"], s.get("starts")
    old = lambda v: [t for t in v if type(t) in (int, float) and math.isfinite(t) and t <= time.time() - 60 * mins] if isinstance(v, list) else []
    return [(w, min(old(v))) for w, v in (starts.items() if isinstance(starts, dict) and type(mins) in (int, float) else []) if old(v)]


def out(r, skip, bad, today):
    """Why this worker is off the wheel, "" when it is on."""
    until = [d for d in re.findall(r"out until (\d{4}-\d{2}-\d{2})", " ".join(r).lower()) if d > today]
    return ("excluded" if short(r[0]) in skip else "same maker as the work under review" if maker(r) == bad
            else "out until " + until[0] if until else "")


def median(v):
    v = sorted(v)
    return (v[len(v) // 2] + v[(len(v) - 1) // 2]) / 2


def speeds():
    """Each worker's last 10 timed minutes from its good outcomes, oldest first."""
    out = {}
    for o in store.records("outcomes.jsonl"):
        if o.get("verdict") == "good" and type(o.get("minutes")) is int and 0 < o["minutes"] <= 10000 and isinstance(o.get("worker"), str):
            out.setdefault(short(o["model"] if isinstance(o.get("model"), str) and o["model"] else o["worker"]), []).append(o["minutes"])
    return {w: v[-10:] for w, v in out.items()}


def choose(text, cls, skip=(), review=None, rand=None, today=None, speed=None):
    """One worker of this class, by a wheel weighted by table order (the first of n has weight n, the last 1)
    times its speed: the fastest candidate's median minutes over its own, cubed, at least 0.02 (1 with no timed jobs)."""
    table_rows, today = rows(text), today or time.strftime("%Y-%m-%d")
    bad = next((maker(r) for r in table_rows if short(r[0]) == short(review)), None) if review else None
    left = [r for r in table_rows if r[2].strip().lower() == cls and not out(r, skip, bad, today)]
    if not left:
        return None
    if rand is None:
        import random
        rand = random.random
    med = {short(r[0]): median(speed[short(r[0])]) for r in left if (speed or {}).get(short(r[0]))}
    fast = min(med.values(), default=1)
    weights = [w * max(0.02, (fast / med[short(r[0])]) ** 3) if short(r[0]) in med else w for w, r in zip(range(len(left), 0, -1), left)]
    x = rand() * sum(weights)
    for weight, r in zip(weights, left):
        x -= weight
        if x < 0:
            return r
    return left[-1]


def pick(args, cwd=None, rand=None):
    """`sisi pick routine|ordinary|hard [--review-of WORKER] [--not WORKER ...]`: the wheel gives one worker."""
    cls, skip, review, i = (args[0] if args and args[0] in ("routine", "ordinary", "hard") else None), set(), None, 1
    while cls and i < len(args):
        if args[i] == "--not" and i + 1 < len(args):
            skip.add(short(args[i + 1]))
        elif args[i] == "--review-of" and i + 1 < len(args):
            review = args[i + 1]
        else:
            cls = None
        i += 2
    if not cls:
        print("usage: sisi pick routine|ordinary|hard [--review-of WORKER] [--not WORKER ...]")
        return 1
    text = store.read(table())
    mine = [r for r in rows(text) if r[2].strip().lower() == cls]
    for r in rows(text):
        if len(re.findall(r"routine|ordinary|hard", r[2].lower())) > 1:
            print("%s is in more than one class and is on no wheel: rebuild the table" % short(r[0]))
    if review is not None and not any(short(r[0]) == short(review) for r in rows(text)):
        print("sisi pick: %r is not a worker in the models table; --review-of names the worker whose work is reviewed." % review)
        return 1
    speed = speeds()
    r = choose(text, cls, skip, review, rand, speed=speed)
    if not r:
        bad = next((maker(x) for x in rows(text) if short(x[0]) == short(review)), None)
        again = {"routine": " Choose again from ordinary.", "ordinary": " Choose again from hard."}.get(cls, "")
        print(("sisi pick: every worker of class %s is out or excluded: %s." % (cls, "; ".join(
            "%s (%s)" % (x[0], out(x, skip, bad, time.strftime("%Y-%m-%d"))) for x in mine)) if mine
              else "sisi pick: the models table has no worker of class %s." % cls) + again)
        return 1
    sid = store.current_session(cwd)
    if sid:
        with store.session(sid) as s:
            s.setdefault("picked", []).append(short(r[0]))
    print("worker: %s (model id: %s)\nstart it with the host's delegation tool; one pick buys one delegation" % (r[0], short(r[0])))
    if store.config()["shell_workers"] or not command(r):
        print("how to call it: " + r[1])
    print("good at, bad at: %s\nnotes: %s" % (r[4], r[5]))
    t = speed.get(short(r[0]))
    print("speed: median %g min over %d timed jobs" % (median(t), len(t)) if t else "speed: no timed jobs yet")
    return 0


def outcomes(n):
    out = []
    for o in store.records("outcomes.jsonl")[-n:]:
        if all(type(o.get(k)) is str for k in ("ts", "worker", "verdict", "why")):
            out.append("%s  %s  %s  %s%s" % (o["ts"][:10], o["worker"], o["verdict"],
                       "(%d min)  " % o["minutes"] if type(o.get("minutes")) is int else "", o["why"]))
    return out


def research_brief():
    owner = [l for l in rules.lines(rules.path(rules.USER)) if "[owner" in l]
    return RESEARCH % {"table": store.read(table()).rstrip() or "(none yet)",
                       "owner": "\n".join(owner) or "(nothing)", "outcomes": "\n".join(outcomes(60)) or "(none yet)"}


def research_record(answer_file):
    text = store.read(answer_file).strip()
    lines = [l for l in text.splitlines() if l.startswith("|")]
    if "| worker" not in text.lower() or "fallback order:" not in text.lower() or len(lines) < 3:
        return "the answer needs the table (a `| worker |` header and at least one row) and a `Fallback order:` line"
    for r in rows(text):
        if len(re.findall(r"routine|ordinary|hard", r[2].lower())) != 1:
            return "each row's \"use for\" must name exactly one of routine, ordinary or hard: | %s |" % " | ".join(r[:6])
        if re.search(r"out (?!until \d{4}-\d{2}-\d{2}(?!\d))(until|till)\b", r[5].lower()):
            return "a worker that is out needs exactly `out until YYYY-MM-DD` in its notes: | %s |" % " | ".join(r[:6])
    if len(lines) > 42 or len(text) > 12000:
        return "the answer is too long (at most 40 rows and 12,000 characters)"
    store.write(table(), text + "\n")
    os.path.isfile(store.data("models.stale")) and os.remove(store.data("models.stale"))
    store.commit("models table researched", table())
    print("models table recorded: %d workers." % (len(lines) - 2))
    return None


def judge(args, cwd=None):
    """`sisi judge WORKER good|bad "<why>" [--minutes N] [--newest]`: how a delegation went, and how long the job took:
    from the oldest start of this worker's open jobs (the newest with --newest) unless --minutes says."""
    from . import retro  # not at the top: hooks import this module and must stay quick
    args, newest, minutes, note = [a for a in args if a != "--newest"], "--newest" in args, None, ""
    if "--minutes" in args:
        i = args.index("--minutes")
        v, args = (args[i + 1:i + 2] or [""])[0], args[:i] + args[i + 2:]
        minutes = int(v) if re.fullmatch(r"[1-9]\d{0,3}|10000", v) else 0
    if len(args) != 3 or not args[0].strip() or args[1] not in ("good", "bad") or len(args[2].split()) < 3 or minutes == 0:
        print('usage: sisi judge WORKER good|bad "<what it did well or badly, in a sentence>" [--minutes N] [--newest]')
        return 1
    trows = rows(store.read(table()))
    hits = [r for r in trows if short(r[0]) == short(args[0])] or [r for r in trows if claim({"picked": [short(r[0])]}, args[0], True)]
    model = (hits[0][0].split() or [""])[0] if len(hits) == 1 else args[0]
    sid, now, began = store.current_session(cwd), time.time(), None
    if sid:
        with store.session(sid) as s:
            starts = s["starts"].get(short(model)) if isinstance(s.get("starts"), dict) else None
            if isinstance(starts, list) and starts:
                cand = starts.pop(-1 if newest else 0)  # one start per open job, oldest first
                if type(cand) in (int, float) and math.isfinite(cand) and cand <= now:  # else dropped, times nothing
                    began = cand
                    minutes = minutes or max(1, int((now - began) / 60))
                    note = " (job started %s, %d more open for this worker)" % (time.strftime("%H:%M", time.localtime(began)), len(starts))
    iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))
    rec = {"ts": iso(now), "ended": iso(now), "worker": args[0], "model": model, "verdict": args[1],
           "why": retro.clean(args[2]), "project": os.path.basename(store.project_root(cwd)),
           "project_key": store.project_key(cwd)}
    if sid:
        rec["session_id"] = sid
    if began is not None:
        rec["started"] = iso(began)
    if minutes:
        rec["minutes"] = minutes
    log = store.data("outcomes.jsonl")
    store.append(log, json.dumps(rec, sort_keys=True))
    store.commit("delegation judged", log)
    print("recorded: %d min%s." % (minutes, note) if minutes else "recorded, not timed.")
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
        return print(research_brief()) or 0
    if len(args) == 3 and args[:2] == ["research", "--record"]:
        why = research_record(args[2])
        return (print("sisi models: %s. Nothing was changed." % why) or 1) if why else 0
    print("usage: sisi models | sisi models research [--record FILE]")
    return 1
