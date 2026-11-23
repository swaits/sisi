"""Choosing the approach as a checked step: the contract's `design` section and `sisi design`.

The design section records, before building: what the goal and the owner's standing principles
(`sisi oracle`) imply that the request did not spell out; what the environment, host tool or
existing system already provides that should be used instead of built; at least two
alternatives with cost and risk; the chosen one and why it is what the owner would pick; for
every standing principle, the objection the owner would raise and how the design answers it
(or why it does not apply); and an independent challenge, by a different model or a subagent
playing the owner, with what changed in response.

Validation is structural only, but it is aimed at filler: entries must be non-trivial,
`provided` must name at least one thing that verifiably exists (a `command:NAME` on PATH or a
`file:PATH` in the repository, given as evidence), alternatives must differ from each other
and from the chosen approach, and the challenge must contain an objection plus a change (or a
stated reason for no change) from someone who is not the author.

One thing is honestly not checkable: that the challenge was recorded before the first code
edit. The edit-attribution data in sisi/watch.py records which paths a session changed, but no
first-edit timestamp survives (the only timestamp is on a pending before-snapshot, consumed
when the command finishes), so validation requires a parseable `recorded_at` that is not in
the future and no more.
"""
import json, os, re, shutil
from datetime import datetime, timezone

QUESTIONS = """Before building, answer these in the contract's design section:
  implies      what the goal and the owner's standing principles imply that the request did
               not spell out (consequences of what the owner already said)
  provided     what the environment, the host tool or the existing system already provides
               that should be used instead of built; give evidence for each item as
               "command:NAME" (on PATH) or "file:PATH" (in the repository)
  alternatives at least two approaches, one line each on cost and on risk
  chosen       which approach, and why it is the one the owner would pick
  objections   one entry per standing principle: when it applies, the objection the owner
               would raise and how the design answers it; when it does not, why not
  challenge    an independent attack on the design by a different model or a subagent,
               playing the owner (what will he say is missing or wrong), who did it, when it
               was recorded, and what was changed in response (or why nothing changed)"""

_FILLER = {"tbd", "todo", "n/a", "na", "none", "nothing", "as requested", "best", "low",
           "high", "medium", "x", "y", "-", "stuff", "things", "various", "etc", "placeholder",
           "as above", "see above", "obvious", "standard", "normal", "usual"}


def _norm(s):
    return " ".join(str(s or "").split()).lower().strip(" .!?:;\"'")


def _trivial(s, min_chars, min_words):
    t = " ".join(str(s or "").split())
    n = _norm(t)
    if not t or n in _FILLER or "todo" in n or "placeholder" in n:
        return True
    return len(t) < min_chars or len(t.split()) < min_words


def skeleton(principle_recs=None):
    if principle_recs is None:
        try:
            from . import principles
            principle_recs = principles.statements()
        except Exception:
            principle_recs = []
    from . import principles as P
    return {
        "implies": ["TODO: what the goal and the owner's principles imply that the request did not spell out"],
        "provided": [{"what": "TODO: what already exists that this should use instead of building",
                      "evidence": "command:TODO or file:TODO"}],
        "alternatives": [
            {"name": "TODO first approach", "cost": "TODO cost in one line", "risk": "TODO risk in one line"},
            {"name": "TODO second approach", "cost": "TODO cost in one line", "risk": "TODO risk in one line"}],
        "chosen": {"name": "TODO chosen approach",
                   "why": "TODO why this is the one the owner would pick"},
        "objections": [{"principle": P.plain_of(r), "applicable": True,
                        "objection": "TODO the objection the owner would raise",
                        "answer": "TODO how the design answers it"} for r in principle_recs],
        "challenge": {"by": "TODO who attacked it (a different model or a subagent)",
                      "recorded_at": "TODO ISO timestamp, recorded before building",
                      "objections": ["TODO what the owner would say is missing or wrong"],
                      "changes": ["TODO what was changed in response"]},
    }


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _text_of(v, keys=()):
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        for k in keys:
            if isinstance(v.get(k), str) and v[k].strip():
                return v[k]
    return ""


def _evidence_ok(item, cwd):
    """True when a `provided` item verifiably names something that exists."""
    evidences = []
    if isinstance(item, dict):
        for k in ("evidence", "exists", "check"):
            if isinstance(item.get(k), str):
                evidences.append(item[k])
        text = _text_of(item, ("what", "name", "use", "text"))
    else:
        text = str(item or "")
    for ev in evidences + [text]:
        for m in re.finditer(r"command:([A-Za-z0-9_./-]+)", ev or ""):
            if shutil.which(m.group(1)):
                return True
        for m in re.finditer(r"(?:file|path):([^\s\"']+)", ev or ""):
            p = m.group(1).rstrip(".,;)")
            if os.path.exists(p if os.path.isabs(p) else os.path.join(cwd, p)):
                return True
    for tok in re.findall(r"[A-Za-z0-9_./~-]+", text):
        if "/" in tok and os.path.exists(os.path.join(cwd, tok.rstrip(".,;)"))):
            return True
    return False


def _match_principle(field, principle_recs):
    from . import principles as P
    if isinstance(field, int) and 1 <= field <= len(principle_recs):
        return field - 1
    f = _norm(field)
    m = re.fullmatch(r"p(\d+)", f)
    if m and 1 <= int(m.group(1)) <= len(principle_recs):
        return int(m.group(1)) - 1
    for i, rec in enumerate(principle_recs):
        for cand in (rec["text"], P.plain_of(rec)):
            c = _norm(cand)
            if f == c or (f and c and (f in c or c in f)):
                return i
    return None


def validate_design(contract, cwd=None, principle_recs=None):
    """Structural refusal reasons for a contract's design section; empty means acceptable."""
    cwd = cwd or os.getcwd()
    if principle_recs is None:
        try:
            from . import principles
            principle_recs = principles.statements()
        except Exception:
            principle_recs = []
    if not isinstance(contract, dict) or not isinstance(contract.get("design"), dict):
        return ["design section is missing: sizeable work needs a `design` section in the "
                "contract (`sisi design` prints the owner's principles and the questions)"]
    d = contract["design"]
    errs = []
    goal = _norm(contract.get("goal"))
    implies = _as_list(d.get("implies"))
    if not implies or all(_trivial(_text_of(x, ("text", "implies")), 40, 7) for x in implies):
        errs.append("design.implies: name at least one consequence of the goal and the owner's "
                    "principles that the request did not spell out (a real sentence, not filler)")
    elif any(_norm(_text_of(x, ("text", "implies"))) == goal for x in implies):
        errs.append("design.implies: restating the goal is not an implication")
    provided = _as_list(d.get("provided"))
    if not provided:
        errs.append("design.provided: name what the environment, host tool or existing system "
                    "already provides that should be used instead of built")
    else:
        if all(_trivial(_text_of(x, ("what", "name", "use", "text")), 25, 5) for x in provided):
            errs.append("design.provided: each item must say concretely what already exists")
        elif not any(_evidence_ok(x, cwd) for x in provided):
            errs.append("design.provided: at least one item must name something that verifiably "
                        "exists, with evidence as \"command:NAME\" (on PATH) or \"file:PATH\" "
                        "(in the repository)")
    chosen_name = _text_of(d.get("chosen"), ("name", "approach", "chosen"))
    alts = _as_list(d.get("alternatives"))
    alt_names = [_norm(_text_of(a, ("name", "approach"))) for a in alts]
    if len(alts) < 2:
        errs.append("design.alternatives: at least two approaches are required")
    else:
        if any(not n or _trivial(n, 4, 1) for n in alt_names) or len(set(alt_names)) != len(alt_names):
            errs.append("design.alternatives: the approaches must be distinct and named")
        if _norm(chosen_name) and _norm(chosen_name) in alt_names:
            errs.append("design.alternatives: alternatives must differ from the chosen approach "
                        "(they are the approaches not taken, with their cost and risk)")
        for a in alts:
            if not isinstance(a, dict) or _trivial(a.get("cost"), 12, 3) or _trivial(a.get("risk"), 12, 3):
                errs.append("design.alternatives: each approach needs one real line on cost and one on risk")
                break
    why = _text_of(d.get("chosen"), ("why", "reason")) if isinstance(d.get("chosen"), dict) else ""
    if _trivial(chosen_name, 4, 1):
        errs.append("design.chosen: name the chosen approach")
    if _trivial(why, 40, 7):
        errs.append("design.chosen.why: say why this is the approach the owner would pick "
                    "(a real sentence, not filler)")
    objections = _as_list(d.get("objections"))
    covered = {}
    for o in objections:
        if isinstance(o, dict):
            i = _match_principle(o.get("principle"), principle_recs)
            if i is not None:
                covered[i] = o
    for i, rec in enumerate(principle_recs):
        from . import principles as P
        o = covered.get(i)
        if o is None:
            errs.append("design.objections: no entry for the standing principle %r - state the "
                        "owner's objection and its answer, or why it does not apply"
                        % P.plain_of(rec)[:80])
            continue
        if o.get("applicable") is False:
            if _trivial(o.get("reason"), 20, 4):
                errs.append("design.objections: principle %r is marked not applicable without a reason"
                            % P.plain_of(rec)[:80])
        elif _trivial(o.get("objection"), 20, 4) or _trivial(o.get("answer"), 20, 4):
            errs.append("design.objections: principle %r needs the objection the owner would "
                        "raise and how the design answers it" % P.plain_of(rec)[:80])
    ch = d.get("challenge") if isinstance(d.get("challenge"), dict) else {}
    by = _text_of(ch, ("by", "who", "challenger"))
    if _trivial(by, 3, 1) or _norm(by) in ("self", "me", "myself", "the agent", "author"):
        errs.append("design.challenge.by: name who attacked the design (a different model or a "
                    "subagent playing the owner, not the author)")
    cobjs = _as_list(ch.get("objections"))
    if not cobjs or all(_trivial(_text_of(x, ("text", "objection")), 25, 5) for x in cobjs):
        errs.append("design.challenge: at least one real objection from the challenger is required")
    changes = _as_list(ch.get("changes"))
    if (not changes or all(_trivial(_text_of(x, ("text", "change")), 25, 5) for x in changes)) \
            and _trivial(ch.get("no_change_reason"), 25, 5):
        errs.append("design.challenge: say what was changed in response, or why nothing changed")
    ts = ch.get("recorded_at")
    if not isinstance(ts, str) or not ts.strip() or "todo" in _norm(ts):
        errs.append("design.challenge.recorded_at: when the challenge was recorded (an ISO timestamp, before building)")
    else:
        try:
            when = datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
            now = datetime.now(timezone.utc) if when.tzinfo else datetime.now()
            if (when - now).total_seconds() > 3600:
                errs.append("design.challenge.recorded_at: %r is in the future" % ts)
        except ValueError:
            errs.append("design.challenge.recorded_at: %r is not an ISO timestamp" % ts)
    return errs


def main(args=()):
    """`sisi design`: the owner's principles and the design questions, before a contract exists."""
    from . import principles
    print("Choosing the approach: work out what the goal and the owner's principles imply, "
          "use what already exists, and have the design attacked as the owner would - before building.\n")
    recs = principles.statements()
    if recs:
        print("The owner's standing principles (`sisi oracle` prints them in full, with his words):")
        for i, rec in enumerate(recs, 1):
            print("%d. %s" % (i, principles.plain_of(rec)))
        print()
    else:
        print("No standing principles are recorded yet (`sisi learn --scope user \"<his words>\"` records one).\n")
    print(QUESTIONS)
    print("\nSkeleton for .sisi/contract.json (the gate checks it on a large change):")
    print(json.dumps({"design": skeleton(recs)}, indent=2))
    return 0
