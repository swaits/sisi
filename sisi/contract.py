"""Contract file: location, skeleton, validation, floors."""
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


def skeleton(goal=None, cwd=None):
    name = re.sub(r"[^a-z0-9]+", "-", os.path.basename(os.path.abspath(cwd or os.getcwd())).lower()).strip("-")
    return {
        "id": name or "work",
        "goal": goal or "TODO: one sentence describing the outcome",
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
    }


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def floors():
    try:
        with open(paths.canon("floors.json"), encoding="utf-8") as f:
            return {k: int(v) for k, v in json.load(f).items()}
    except (OSError, ValueError):
        return {}


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _str(x):
    return isinstance(x, str) and x.strip() != ""


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
    return errs


def floor_failures(c, floor_map=None):
    """Kinds with a floor where every check of that kind is weaker than the floor."""
    fm = floors() if floor_map is None else floor_map
    out = []
    for kind, fl in sorted(fm.items()):
        of_kind = [ch for ch in c.get("checks", []) if ch.get("kind") == kind]
        if of_kind and not any(ch["rung"] <= fl for ch in of_kind):
            out.append({"kind": kind, "floor": fl,
                        "message": "floor: %s claims need a check at rung %d or stronger; best is rung %d"
                                   % (kind, fl, min(ch["rung"] for ch in of_kind))})
    return out
