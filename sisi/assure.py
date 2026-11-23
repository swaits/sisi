"""What a risk profile requires, and what is missing from a unit (target section 3).

The gate enforces the `requirements` table in canon/risk.json and nothing else. This module reads
that table, looks at the contract and the evidence, and returns the missing items in plain words,
each with the command or field that supplies it. It never decides anything about the tree itself.

The profile that applies is the floor (what the changed paths say, by sisi/risk.py) unless the
contract declares a higher one. A contract may declare a lower one only by giving `risk.why`: the
unit then runs at the declared profile and is recorded as lowered, with floor, declared profile and
reason kept side by side (`sisi status` shows it).
"""
import os, time

from . import contract as C, harvest, risk, store

ORDER = {name: i for i, name in enumerate(risk.PROFILES)}


def effective_profile(floor, c):
    """(profile, info). `info` = {floor, declared, lowered, why, refused}: `refused` is set when a
    contract declared a lower profile without a reason, so the floor was kept."""
    rk = (c.get("risk") if isinstance(c, dict) else None) or {}
    declared = rk.get("profile") if rk.get("profile") in ORDER else None
    info = {"floor": floor, "declared": declared, "lowered": False, "why": rk.get("why"), "refused": False}
    if declared is None or ORDER[declared] >= ORDER[floor]:
        return (declared if declared and ORDER[declared] > ORDER[floor] else floor), info
    if C.is_placeholder(rk.get("why")):
        info["refused"] = True
        return floor, info
    info["lowered"] = True
    return declared, info


def is_lowered(floor, declared, why):
    """True when a unit declared a profile below its floor and gave a reason (what `sisi status` flags)."""
    return bool(floor in ORDER and declared in ORDER and ORDER[declared] < ORDER[floor]
                and not C.is_placeholder(why))


def requirements(profile):
    return risk.requirements_for(profile)


def stronger_technique(c):
    """True when some check or invariant uses a technique stronger than example tests: a proof or
    model check (rung 1), or properties, fuzzing or a reference comparison (rung 2)."""
    items = list((c or {}).get("checks") or []) + list((c or {}).get("invariants") or [])
    return any(isinstance(x, dict) and x.get("rung") in (1, 2) for x in items)


def _real(items, key):
    """Entries of a list whose `key` says something (not empty, not a placeholder)."""
    return [x for x in items or [] if isinstance(x, dict) and not C.is_placeholder(x.get(key))]


def _passing(r):
    return r.get("status") == "passed" or (r.get("status") == "skipped"
                                           and str(r.get("reason") or "").startswith("reused: passed"))


def review_evidence(project, c, now=None):
    """The accepted review delegations of this project inside the unit's window whose result was
    checked by something stronger than `none`. The ledger names a project by its folder name."""
    t0 = harvest.epoch(c["started"]) if isinstance(c.get("started"), str) else None
    if t0 is None:
        return []
    try:
        from . import workers
        dg = workers.delegations_for_project(os.path.basename(project.rstrip(os.sep)), t0,
                                             time.time() if now is None else now)
    except Exception as e:
        store.log_error("assure-delegations", e)
        return []
    return [r for r in dg["delegations"] if r.get("type") == "review" and r.get("outcome") == "accepted"
            and r.get("check") not in (None, "", "none")]


def independent_evidence(project, c, results, now=None):
    """What stands behind a unit as independent evidence: a judged review in the ledger, or a
    passing check that is marked independent AND says by whom or what it was produced."""
    out = []
    for r in review_evidence(project, c, now):
        out.append("review by %s" % (r.get("worker") or "a reviewer"))
    named = {x.get("id"): x for x in list(c.get("checks") or []) + list(c.get("invariants") or [])
             if isinstance(x, dict) and x.get("independent") is True and not C.is_placeholder(x.get("by"))}
    for r in results or []:
        if r.get("id") in named and _passing(r):
            out.append("check %s by %s" % (r["id"], named[r["id"]]["by"]))
    return out


def missing(profile, c, project, results=None, errors=None, deep_state=None, now=None):
    """[(what is missing, how to supply it)] for this profile. `c` is None when no contract is open.
    `errors` are the contract's validation errors. Nothing is asked that the table does not require."""
    req = requirements(profile)
    out = []
    if not req.get("contract"):
        return out
    if c is None:
        out.append(("a contract for this %s change" % profile,
                    "`sisi contract init`, then write at least one check that can fail"))
        c = {}
        absent = True
    else:
        absent = False
    if errors:
        shown = "; ".join(errors[:3]) + ("; and %d more" % (len(errors) - 3) if len(errors) > 3 else "")
        out.append(("a valid contract: %s" % shown, "fix it, then `sisi contract check`"))
    checks = [x for x in c.get("checks") or [] if isinstance(x, dict)]
    if not absent and not errors and int(req.get("min_checks", 0)) > len(checks):
        out.append(("at least one check that can fail", 'add it under "checks"'))
    if req.get("covers"):
        bare = [x.get("id") or "?" for x in checks if C.is_placeholder(x.get("covers"))]
        if bare or absent:
            out.append(("every check says what it covers" + (" (missing on %s)" % ", ".join(bare) if bare else ""),
                        '"covers": the failure that check would catch'))
    if req.get("invariants") and not _real(c.get("invariants"), "claim"):
        out.append(("invariants: what must not get worse",
                    '"invariants": a command that can fail, e.g. the existing tests'))
    if req.get("requirement_model") and not _real(c.get("requirements"), "text"):
        out.append(("a requirement list",
                    '"requirements": entries with "kind", "text" and "decision" (now, architect, defer, ignore)'))
    if req.get("risk_note"):
        rk = c.get("risk") if isinstance(c.get("risk"), dict) else {}
        lacking = [k for k in ("blast_radius", "rollback") if C.is_placeholder(rk.get(k))]
        if lacking:
            out.append(("a risk note: %s" % " and ".join(lacking),
                        '"risk": {"blast_radius": what this can break, "rollback": how to undo it}'))
    if req.get("approach"):
        ap = c.get("approach") if isinstance(c.get("approach"), dict) else {}
        if C.is_placeholder(ap.get("chosen")) or C.is_placeholder(ap.get("why")) \
                or not [a for a in ap.get("alternatives") or [] if not C.is_placeholder(a)]:
            out.append(("the approach: what you chose, why, and an alternative you rejected",
                        '"approach": {"chosen", "why", "alternatives": [...]}'))
    if req.get("independent_evidence") and not independent_evidence(project, c, results, now):
        out.append(("independent evidence that someone or something else checked this",
                    "a reviewer's judged result (`sisi delegate judge --type review --outcome accepted "
                    "--check review`), or a passing check with \"independent\": true and \"by\": \"<who or what>\""))
    if req.get("all_checks") and deep_state is not None and deep_state not in ("fresh-pass", "none"):
        out.append(("every check, deep ones included, passing on this tree (release)",
                    "`sisi verify --deep --background`, then `sisi verify --state`"))
    return out


# ---------------------------------------------------------------- messages

MAX_LINES = 25


def fit(lines, limit=MAX_LINES):
    """No message to the agent is longer than `limit` lines: over it, the tail is replaced by one line
    saying how many were cut. Every line is also kept short."""
    flat = []
    for ln in lines:
        for sub in str(ln).split("\n"):
            flat.append(sub if len(sub) <= 300 else sub[:297] + "...")
    if len(flat) <= limit:
        return "\n".join(flat)
    return "\n".join(flat[:limit - 1] + ["... (%d more lines; run `sisi verify` for the full output)"
                                         % (len(flat) - limit + 1)])


def failure_lines(results, per_check=4, checks=4):
    """A short report of the blocking results: id, status, and the last lines of what they printed."""
    from . import verify as V
    out = []
    bad = V.blocking(results)
    for r in bad[:checks]:
        head = "- %s [%s%s]" % (r["id"], r["status"], (": " + r["reason"]) if r.get("reason") else "")
        out.append(head)
        tail = [ln for ln in str(r.get("tail") or "").splitlines() if ln.strip()][-per_check:]
        out += ["    " + ln[:200] for ln in tail]
    if len(bad) > checks:
        out.append("- and %d more failing" % (len(bad) - checks))
    return out
