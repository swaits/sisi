"""Contract file: location, skeleton, validation."""
import json, os, re

from . import paths, gitutil

KINDS = ["general", "concurrency", "parsing", "money", "state-machine", "migration", "ui"]
REL = os.path.join(".sisi", "contract.json")


def find(cwd):
    """Nearest contract in cwd or an ancestor, stopping at the git root. Returns path or None."""
    cwd = os.path.abspath(cwd)
    top = gitutil.root(cwd)
    d = cwd
    while True:
        p = os.path.join(d, REL)
        if os.path.isfile(p):
            return p
        if d == top or os.path.dirname(d) == d or top is None:
            return None
        d = os.path.dirname(d)


def project_dir(contract_path):
    return os.path.dirname(os.path.dirname(contract_path))


PLACEHOLDER_CMD = "echo 'TODO: replace this command with a real check' >&2; false"


def is_unedited_skeleton(c):
    """True while every check still carries the placeholder command (nothing real has been written yet)."""
    try:
        return bool(c["checks"]) and not c.get("invariants") and all(x.get("cmd") == PLACEHOLDER_CMD for x in c["checks"])
    except (AttributeError, KeyError, TypeError):
        return False


REQ_KINDS = ("explicit", "implied", "contextual", "anticipated", "experiential")
REQ_DECISIONS = ("now", "architect", "defer", "ignore")
RISK_PROFILES = ("trivial", "isolated", "logic", "integration", "data", "critical", "release")
RISK_HINT = ("one of %s, your own judgement of the change; `sisi risk` shows the floor worked out from paths"
             % ", ".join(RISK_PROFILES))
UNIT_STATUSES = ("open", "paused", "closed")


def skeleton(goal=None, cwd=None):
    """A new contract. `risk.profile` starts at the floor of the current change; the agent judges it from there."""
    cwd = cwd or os.getcwd()
    name = re.sub(r"[^a-z0-9]+", "-", os.path.basename(os.path.abspath(cwd)).lower()).strip("-")
    from . import store as _store, risk as _risk
    floor = _risk.floor_for_working_tree(cwd)[0]
    return {
        "id": name or "work",
        "parent": None,
        "goal": goal or "TODO: one sentence describing the outcome",
        "scope": {"in": [], "out": []},
        "requirements": [],
        "risk": {"profile": floor},
        "checks": [{
            "id": "c1",
            "claim": "PLACEHOLDER (fast tier, runs at the end of every turn, 60 s at most): replace with what this check shows to be true",
            "kind": "general",
            "rung": 3,
            "cmd": PLACEHOLDER_CMD,
            "expect": {"exit": 0},
            "timeout_s": 60,
        }, {
            "id": "deep-example",
            "claim": "PLACEHOLDER (deep tier): replace or delete. For checks that take minutes or more: mutation testing, fuzzing, long proofs",
            "kind": "general",
            "rung": 2,
            "tier": "deep",
            "cmd": PLACEHOLDER_CMD,
            "expect": {"exit": 0},
            "timeout_s": 3600,
        }],
        "invariants": [],
        "assumptions": [],
        "questions": [],
        "deferred": [],
        "limitations": [],
        "plan": [],
        "approach": None,
        "status": "open",
        "started": _store.now(),
        "pauses": [],
        "deviations": [],
    }


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, c):
    tmp = path + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def deferred_checks(c):
    """{check_id: deferred entry} for deferred entries naming a check, by `check` or exactly by `what`."""
    out = {}
    for d in c.get("deferred", []) if isinstance(c, dict) else []:
        if isinstance(d, dict):
            cid = d.get("check") or d.get("what")
            if isinstance(cid, str) and cid:
                out[cid] = d
    return out


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _str(x):
    return isinstance(x, str) and x.strip() != ""


_PLACEHOLDER_WORDS = {"todo", "tbd", "tba", "fixme", "xxx", "wip", "none", "nothing", "no", "n/a", "na", "nil",
                      "null", "unknown", "placeholder", "later", "see above", "same", "as above", "not applicable",
                      "no risk", "no rollback", "none needed", "not needed", "nothing needed", "-", "--", "...",
                      "?", "yes", "ok", "fine", "tests", "all"}


def is_placeholder(x):
    """True for text that fills a field without saying anything: empty, `TODO`, `n/a`, `none`,
    `tbd`, a bare punctuation mark, or anything that begins with TODO/TBD/FIXME. The gate asks for
    a requirement list, a risk note, an approach and a reason; these words do not provide one."""
    if not isinstance(x, str):
        return True
    t = " ".join(x.lower().split()).strip(" .,:;!-_*")
    if len(re.findall(r"[a-z0-9]", t)) < 3 and t not in ("ui",):
        return True
    return t in _PLACEHOLDER_WORDS or bool(re.match(r"^(todo|tbd|fixme|placeholder|xxx)\b", t))


TIERS = ("fast", "deep")


def _tier(x, where, errs):
    t = x.get("tier", "fast")
    if t not in TIERS:
        errs.append("%s: tier must be fast or deep" % where)
        return
    if t == "fast" and x.get("rung") not in (5, 6):
        from . import store
        cfg = store.config()["verify"]
        limit = cfg["fast_limit_s"]
        to = x.get("timeout_s", cfg["default_timeout_s"])
        if _num(to) and to > limit:
            errs.append('%s: timeout_s %g is over the fast limit of %g s; mark it "tier": "deep" '
                        "(deep checks run with `sisi verify --deep`, never in the end-of-turn gate)" % (where, to, limit))


def warnings(c):
    """Non-fatal findings."""
    from . import store
    cfg = store.config()
    tot = 0.0
    for x in list(c.get("checks", [])) + list(c.get("invariants", [])):
        if isinstance(x, dict) and x.get("tier", "fast") == "fast" and x.get("cmd") and x.get("rung") not in (5, 6):
            to = x.get("timeout_s", cfg["verify"]["default_timeout_s"])
            tot += to if _num(to) else 0
    budget = cfg["gate"]["budget_s"]
    return ["the fast timeouts add up to %g s, more than the gate budget of %g s: some checks may be reported as "
            "timed out at the end of a turn" % (tot, budget)] if tot > budget else []


def _expect(e, where, errs):
    if not isinstance(e, dict):
        errs.append("%s: expect must be an object" % where)
        return
    if not (isinstance(e.get("exit"), int) and not isinstance(e.get("exit"), bool)):
        errs.append("%s: expect.exit must be an integer" % where)
    sc = e.get("stdout_contains")
    if sc is not None and not isinstance(sc, str):
        errs.append("%s: expect.stdout_contains must be a string" % where)
    for k in e:
        if k not in ("exit", "stdout_contains"):
            errs.append("%s: unknown expect key %r" % (where, k))


_TRUE_WORDS = {"true", ":", "/bin/true", "/usr/bin/true"}
_PRINT_WORDS = {"echo", "printf"}
_SHELLS = {"sh", "bash", "dash", "zsh", "/bin/sh", "/bin/bash", "/usr/bin/env"}
_WRAPPERS = {"env", "command", "exec", "time", "nohup", "builtin"}
_TESTERS = {"test", "["}
_OPS = {"&&", "||", ";", "|", "&"}


def _lex(s):
    import shlex
    lx = shlex.shlex(s.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lx.whitespace_split = True
    lx.commenters = "#"
    return list(lx)


def _literal(w):
    return not any(ch in w for ch in "$`*?[~{}")


def _constant_true_simple(words, expect, depth=0):
    """True when this one simple command is a constant that exits 0 whatever the project holds."""
    while words and (words[0] in _WRAPPERS or (words[0] == "timeout" and len(words) > 2)):
        words = words[2:] if words[0] == "timeout" else words[1:]
    if not words:
        return False
    w0, rest = words[0], words[1:]
    if w0 in _TRUE_WORDS:
        return True
    if w0 == "exit":
        return not rest or rest == ["0"]
    if w0 in _PRINT_WORDS:
        out = " ".join(rest)
        want = expect.get("stdout_contains")
        return want is None or str(want) in out
    if w0 in _TESTERS:
        ops = rest[:-1] if w0 == "[" and rest[-1:] == ["]"] else rest
        if len(ops) == 3 and ops[1] in ("=", "==", "-eq") and all(_literal(x) for x in (ops[0], ops[2])):
            return ops[0] == ops[2]
        return False
    if w0.rsplit("/", 1)[-1] in _SHELLS and depth < 4:
        for i, x in enumerate(rest):
            if x.startswith("-") and "c" in x[1:] and not x.startswith("--") and i + 1 < len(rest):
                return _constant_true(rest[i + 1], expect, depth + 1)
    return False


def _split(words, seps):
    out, cur = [], []
    for w in words:
        if w in seps:
            out.append(cur)
            cur = []
        else:
            cur.append(w)
    out.append(cur)
    return out


def _constant_true(cmd, expect, depth=0):
    try:
        words = _lex(cmd)
    except ValueError:
        return False
    if not words or any(w.startswith(("<", ">")) or w in ("<<", ">>") for w in words):
        return False  # a redirection reads or writes something: it can fail
    alts = _split(words, {"||"})

    def chain(ws):
        seqs = [q for q in _split(ws, {";", "&&", "&"}) if q]
        for seq in seqs:
            stages = _split(seq, {"|"})
            if not stages[-1] or not _constant_true_simple(stages[-1], expect, depth):
                return False
        return bool(seqs)
    return chain(alts[0]) or (len(alts) > 1 and chain(alts[-1]))


def vacuous_reason(ch):
    """Why this check cannot fail, or None. The commands that exit 0 whatever the project
    holds: `true`, `:`, `exit 0`, `echo`/`printf` that already prints what is expected,
    `test 1 = 1`, any of them inside `sh -c`, joined with `;` or `&&`, or after `||` (so
    `anything || true`). A floor, not a proof: no analysis can catch every constant."""
    cmd = ch.get("cmd")
    if not isinstance(cmd, str):
        return None
    expect = ch.get("expect") if isinstance(ch.get("expect"), dict) else {}
    if expect.get("exit", 0) != 0:
        return None
    if not _constant_true(cmd.strip(), expect):
        return None
    return "vacuous check: %r cannot fail; write a command that can" % cmd.strip()


def _check_new_fields(ch, w, errs):
    if "covers" in ch and not _str(ch["covers"]):
        errs.append(w + ": covers must be a non-empty string")
    if "when_changed" in ch:
        wc = ch["when_changed"]
        if not isinstance(wc, list) or not wc or not all(_str(x) for x in wc):
            errs.append(w + ": when_changed must be a non-empty list of path patterns")
    for k in ("mandatory", "independent"):
        if k in ch and not isinstance(ch[k], bool):
            errs.append("%s: %s must be true or false" % (w, k))
    if "by" in ch and not _str(ch["by"]):
        errs.append(w + ": by must name who or what produced the independent evidence")


def _validate_new_top(c, ids, errs):
    if "parent" in c and c["parent"] is not None and not _str(c["parent"]):
        errs.append("parent must be a non-empty string or null")
    if "status" in c and c["status"] not in UNIT_STATUSES:
        errs.append("status must be one of %s" % ", ".join(UNIT_STATUSES))
    if "started" in c and not _str(c["started"]):
        errs.append("started must be a non-empty string")
    if "scope" in c:
        sc = c["scope"]
        if not isinstance(sc, dict):
            errs.append("scope must be an object with in/out lists")
        else:
            for k in sc:
                if k not in ("in", "out"):
                    errs.append("scope: unknown key %r" % k)
            for k in ("in", "out"):
                if k in sc and (not isinstance(sc[k], list) or not all(isinstance(x, str) for x in sc[k])):
                    errs.append("scope.%s must be a list of strings" % k)
    if "requirements" in c:
        rq = c["requirements"]
        if not isinstance(rq, list):
            errs.append("requirements must be a list")
        else:
            seen = set()
            for i, r in enumerate(rq):
                w = "requirements[%d]" % i
                if not isinstance(r, dict):
                    errs.append(w + " must be an object"); continue
                if not _str(r.get("id")):
                    errs.append(w + ".id must be a non-empty string")
                elif r["id"] in seen:
                    errs.append("duplicate requirement id %r" % r["id"])
                else:
                    seen.add(r["id"]); w = "requirement %r" % r["id"]
                if r.get("kind") not in REQ_KINDS:
                    errs.append("%s: kind must be one of %s" % (w, ", ".join(REQ_KINDS)))
                if not _str(r.get("text")):
                    errs.append(w + ": text must be a non-empty string")
                if r.get("decision") not in REQ_DECISIONS:
                    errs.append("%s: decision must be one of %s" % (w, ", ".join(REQ_DECISIONS)))
                if "why" in r and not _str(r["why"]):
                    errs.append(w + ": why must be a non-empty string")
                if "check" in r and r["check"] is not None:
                    if not _str(r["check"]):
                        errs.append(w + ": check must be a check id or null")
                    elif ids and r["check"] not in ids:
                        errs.append("%s: check %r is not a check or invariant id" % (w, r["check"]))
                if "added" in r and not _str(r["added"]):
                    errs.append(w + ": added must be a non-empty string")
    rk = c.get("risk")
    if not isinstance(rk, dict):
        errs.append("risk must be an object that states its profile: " + RISK_HINT)
    else:
        if rk.get("profile") not in RISK_PROFILES:
            errs.append("risk.profile is required: " + RISK_HINT)
        for k in ("why", "blast_radius", "rollback"):
            if k in rk and not _str(rk[k]):
                errs.append("risk.%s must be a non-empty string" % k)
    if "deferred" in c:
        df = c["deferred"]
        if not isinstance(df, list):
            errs.append("deferred must be a list")
        else:
            for i, d in enumerate(df):
                w = "deferred[%d]" % i
                if not isinstance(d, dict):
                    errs.append(w + " must be an object"); continue
                for k in ("what", "why", "safe_because"):
                    if not _str(d.get(k)):
                        errs.append("%s.%s must be a non-empty string" % (w, k))
                if "check" in d and d["check"] is not None and not _str(d["check"]):
                    errs.append(w + ": check must be a check id or null")
    if "approach" in c and c["approach"] is not None:
        ap = c["approach"]
        if not isinstance(ap, dict):
            errs.append("approach must be an object")
        else:
            for k in ap:
                if k not in ("chosen", "why", "alternatives", "reuses"):
                    errs.append("approach: unknown key %r" % k)
            for k in ("chosen", "why"):
                if k in ap and not _str(ap[k]):
                    errs.append("approach.%s must be a non-empty string" % k)
            for k in ("alternatives", "reuses"):
                if k in ap and (not isinstance(ap[k], list) or not all(_str(x) for x in ap[k])):
                    errs.append("approach.%s must be a list of non-empty strings" % k)
    if "limitations" in c:
        if not isinstance(c["limitations"], list) or not all(isinstance(x, str) for x in c["limitations"]):
            errs.append("limitations must be a list of strings")
    if "plan" in c:
        if not isinstance(c["plan"], list) or not all(isinstance(x, (str, dict)) for x in c["plan"]):
            errs.append("plan must be a list of steps (strings or objects)")
    if "pauses" in c and not isinstance(c["pauses"], list):
        errs.append("pauses must be a list")
    if "deviations" in c and not isinstance(c["deviations"], list):
        errs.append("deviations must be a list")


def validate(c):
    """Return a list of error strings; empty means valid."""
    errs = []
    if not isinstance(c, dict):
        return ["contract must be a JSON object"]
    for k in ("id", "goal"):
        if not _str(c.get(k)):
            errs.append("%s must be a non-empty string" % k)
    if "parallel" in c and not isinstance(c["parallel"], bool):
        errs.append("parallel must be true or false")
    ids = set()
    checks = c.get("checks")
    if not isinstance(checks, list) or not checks:
        errs.append("checks must be a non-empty list with at least one runnable check "
                    "(rung 1-4 with a cmd); to say a change needs no checks run `sisi contract waive \"<reason>\"`")
        checks = []
    for i, ch in enumerate(checks):
        w = "checks[%d]" % i
        if not isinstance(ch, dict):
            errs.append(w + " must be an object")
            continue
        if not _str(ch.get("id")):
            errs.append(w + ".id must be a non-empty string")
        else:
            w = "check %r" % ch["id"]
            if ch["id"] in ids:
                errs.append("duplicate id %r" % ch["id"])
            ids.add(ch["id"])
        if not _str(ch.get("claim")):
            errs.append(w + ": claim must be a non-empty string")
        if ch.get("kind") not in KINDS:
            errs.append("%s: kind must be one of %s" % (w, ", ".join(KINDS)))
        r = ch.get("rung")
        if not (isinstance(r, int) and not isinstance(r, bool) and 1 <= r <= 6):
            errs.append(w + ": rung must be an integer 1-6")
        elif r >= 5:
            if ch.get("cmd"):
                errs.append(w + ": rung 5 and 6 checks must not have a cmd")
        else:
            if not _str(ch.get("cmd")):
                errs.append(w + ": rung 1-4 checks need a cmd")
            _expect(ch.get("expect"), w, errs)
        if "timeout_s" in ch and not (_num(ch["timeout_s"]) and ch["timeout_s"] > 0):
            errs.append(w + ": timeout_s must be a positive number")
        _tier(ch, w, errs)
        if "serial" in ch and not isinstance(ch["serial"], bool):
            errs.append(w + ": serial must be true or false")
        _check_new_fields(ch, w, errs)
        vr = vacuous_reason(ch)
        if vr:
            errs.append("%s: %s" % (w, vr))
    inv = c.get("invariants", [])
    if not isinstance(inv, list):
        errs.append("invariants must be a list")
        inv = []
    for i, iv in enumerate(inv):
        w = "invariants[%d]" % i
        if not isinstance(iv, dict):
            errs.append(w + " must be an object")
            continue
        if not _str(iv.get("id")):
            errs.append(w + ".id must be a non-empty string")
        else:
            w = "invariant %r" % iv["id"]
            if iv["id"] in ids:
                errs.append("duplicate id %r" % iv["id"])
            ids.add(iv["id"])
        if not _str(iv.get("claim")):
            errs.append(w + ": claim must be a non-empty string")
        if not _str(iv.get("cmd")):
            errs.append(w + ": cmd must be a non-empty string")
        _expect(iv.get("expect"), w, errs)
        if "timeout_s" in iv and not (_num(iv["timeout_s"]) and iv["timeout_s"] > 0):
            errs.append(w + ": timeout_s must be a positive number")
        _tier(iv, w, errs)
        if "serial" in iv and not isinstance(iv["serial"], bool):
            errs.append(w + ": serial must be true or false")
        _check_new_fields(iv, w, errs)
        vr = vacuous_reason(iv)
        if vr:
            errs.append("%s: %s" % (w, vr))
    runnable = any(isinstance(x, dict) and x.get("rung") in (1, 2, 3, 4) and x.get("cmd") for x in checks) or \
        any(isinstance(x, dict) and x.get("cmd") for x in inv)
    if checks and not runnable:
        errs.append("no runnable check or invariant: rung 5 and 6 items never run, so add at least one check at "
                    "rung 1-4 with a cmd (or run `sisi contract waive \"<reason>\"` if no checks are needed)")
    a = c.get("assumptions", [])
    if not isinstance(a, list) or not all(isinstance(x, str) for x in a):
        errs.append("assumptions must be a list of strings")
    q = c.get("questions", [])
    if not isinstance(q, list):
        errs.append("questions must be a list")
    else:
        for i, x in enumerate(q):
            if not (isinstance(x, dict) and _str(x.get("q")) and "default" in x):
                errs.append("questions[%d] needs q and default" % i)
    _validate_new_top(c, ids, errs)
    return errs
