"""The learning cycle: proposed learnings become mechanisms in the user store.

Due by a counter (no scheduler). A worker writes a cycle file; `sisi cycle apply FILE`
treats it as untrusted input, validates and plans everything before writing anything,
replays command checks against the originating unit's commits in a temporary worktree
(one replay implementation: evaluate.validate_command), refuses protected rules, parks
consequential changes for the owner (`sisi approve`), and commits each change to the user
store so revert is exact. What cannot be replayed is `unvalidated` and always reported as
such; nothing is labelled `validated` without a validation run that passed.

What a mechanism reaches is decided here from the learning, never from the cycle file: a
mechanism is written with the learning's id and the scope the learning has *earned*
(learning.earned_scope: its origin project, unless it was seen in two units in two projects or
is an owner statement made at user scope). A scope or `every_project` flag in the file is only
a request for more; a request for more than the learning has earned, any enforced command that
is not proven in its origin project, any risk pattern that lowers a profile, any replacement or
disabling of a rule, and any rule or library entry from a learning confined to one project
wait for the owner. Readers filter by project; nothing reads a flag the cycle author wrote.

Cycle file (JSON):
  {"base": "<store base from `sisi cycle` brief>", "actions": [
    {"action": "promote", "learning": "L-0001", "mechanism_kind": "command-check",
     "cmd": "...", "expect": {"exit": 0}, "before": "<sha>", "after": "<sha>"},
    {"action": "promote", "learning": "L-0002", "mechanism_kind": "contract-requirement",
     "when": "csv import", "require_kind": "property"},
    {"action": "promote", "learning": "L-0003", "mechanism_kind": "rule-text",
     "rule_id": "new-rule", "rule_text": "## Title {#new-rule}\\n\\n... Why: ..."},
    {"action": "promote", "learning": "L-0004", "mechanism_kind": "library",
     "library_kind": "recipe"|"verifier", "entry_text": "..."},
    {"action": "promote", "learning": "L-0005", "mechanism_kind": "risk",
     "pattern": "src/auth/**", "profile": "critical"},
    {"action": "promote", "learning": "L-0006", "mechanism_kind": "routing",
     "kind": "impl", "difficulty": 2, "prefer": "worker-x"},
    {"action": "promote", "learning": "L-0007", "mechanism_kind": "benchmark",
     "name": "csv-import", "case": {"...": "..."}},
    {"action": "revise"|"revert"|"reject", "learning": "L-0008", "why": "..."}]}

Mechanism data files (user store overlay); every entry carries learning, scope, project:
  enforced.json {"checks": [{"type": "command"|"contract-requirement", "learning": id, ...}]}
  risk-adjustments.json {"adjustments": [{"pattern", "profile", "learning", ...}]}
  routing-adjustments.json {"adjustments": [{"kind", "difficulty", "prefer"|"avoid", "learning", ...}]}
  benchmarks/<name>.json  one benchmark case per file
"""
import copy, difflib, json, os, re, sys, time

from . import documents, evaluate, learning as L, overlay, paths, pdata

DUE_AFTER = 5  # proposed learnings waiting make a cycle due (a counter, checked in normal use)
MECHANISM_KINDS = ("contract-requirement", "command-check", "library", "rule-text",
                   "risk", "routing", "benchmark")
GLOBAL_KINDS = ("rule-text", "library")  # they change what every project loads: reach is `user`
# What a cycle changes on a learning record; revert restores exactly these fields, so records
# and findings written after the cycle survive a revert.
CYCLE_FIELDS = ("status", "validation", "mechanism_ref", "mechanism_scope", "promoted_at",
                "flagged_not_working", "recurrences_after_promotion", "version", "history", "proposed")
STORE_FILES = {"learnings.jsonl", "learnings-ledger.jsonl", "pending.json", "findings.jsonl",
               "approvals.jsonl"}
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class CycleError(Exception):
    pass


def protected_rules():
    try:
        return overlay.protected_rules()
    except overlay.OverlayError as e:
        raise CycleError(str(e))


# ---- mechanism entries and who they apply to ------------------------------------

def _overlay_json(rel, key):
    try:
        with open(paths.overlay_dir(rel), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {key: []}
    except (OSError, ValueError):
        return {key: []}


def _put_json(rel, d, msg):
    pdata.write_text("overlay/" + rel, json.dumps(d, indent=2, sort_keys=True) + "\n")
    pdata.commit(msg, ["overlay/" + rel])


class _Authority:
    """Reads, once per call, what decides whether a wider-than-project entry may apply."""

    def __init__(self):
        self.rows = {r["id"]: r for r in L.load_learnings()}
        self.ledger = L.load_ledger()
        self.approved = L.approved_ids()

    def allows(self, e):
        sc = e.get("scope")
        if e.get("approval") in self.approved:
            return True
        rec = self.rows.get(e.get("learning"))
        return bool(rec is not None and L.is_registered(rec, self.ledger)
                    and L.SCOPE_RANK.get(L.earned_scope(rec), 0) >= L.SCOPE_RANK.get(sc, 99))


def entry_applies(e, project, auth=None):
    """Does this mechanism entry apply in this project? A project entry only in its own project;
    a wider entry only while the learning has earned that scope or the owner approved it."""
    sc = e.get("scope")
    if sc == "project":
        return bool(e.get("project")) and e.get("project") == L.project_key(project)
    if sc in ("user", "organization"):
        return (auth or _Authority()).allows(e)
    return False  # an entry that names no scope applies nowhere


def adjustments(rel, project):
    d = _overlay_json(rel, "adjustments")
    items = [x for x in d.get("adjustments", []) if isinstance(x, dict)]
    if not items:
        return []
    auth = _Authority()
    return [x for x in items if entry_applies(x, project, auth)]


def risk_patterns(cwd):
    """Risk-table patterns learned by cycles that apply in this project (risk.py reads these)."""
    return [{"glob": e["pattern"], "profile": e["profile"], "reason": "learning %s" % e.get("learning")}
            for e in adjustments("risk-adjustments.json", cwd) if e.get("pattern") and e.get("profile")]


def routing_adjustments(project):
    return adjustments("routing-adjustments.json", project)


# ---- enforced checks (verify.py seam) ----------------------------------------------

def load_enforced(project=None):
    """Enforced checks; with a project, only those that apply in it."""
    checks = [c for c in _overlay_json("enforced.json", "checks").get("checks", []) if isinstance(c, dict)]
    if project is None:
        return checks
    if not checks:
        return []
    auth = _Authority()
    return [c for c in checks if entry_applies(c, project, auth)]


def _requirement_met(c, entry):
    want, when = entry.get("require_kind"), str(entry.get("when") or "")
    w = L.stems(when)
    trig = any(ch.get("kind") == when or (w & L.stems((ch.get("claim") or "") + " " + (ch.get("id") or "")))
               for ch in c.get("checks", []) if isinstance(ch, dict)) or bool(w & L.stems(c.get("goal") or ""))
    if not trig:
        return True
    max_rung = entry.get("max_rung")
    return any(ch.get("kind") == want and (max_rung is None or (isinstance(ch.get("rung"), int) and ch["rung"] <= max_rung))
               for ch in c.get("checks", []) if isinstance(ch, dict))


def enforced_results(c, project, deadline=None, default_timeout=60):
    """Result rows for enforced checks, in the shape verify.run returns. Only checks whose
    scope reaches this project; command checks run only in trusted projects."""
    out = []
    checks = load_enforced(project)
    if not checks:
        return out
    from . import trust, verify as V
    trusted = trust.is_trusted(project)
    for e in checks:
        lid = e.get("learning")
        base = {"item": "enforced", "tier": "fast", "id": "enforced:learning-%s" % lid, "kind": None,
                "rung": None, "claim": "enforced learning %s" % lid, "duration_s": 0.0, "tail": ""}
        if e.get("type") == "contract-requirement":
            if not _requirement_met(c, e):
                msg = ("enforced learning %s: a contract touching %r must contain a check of kind %s"
                       % (lid, e.get("when"), e.get("require_kind")))
                out.append(dict(base, status="failed", claim=msg, tail=msg))
        elif e.get("type") == "command" and trusted:
            to = float(e.get("timeout_s") or default_timeout)
            if deadline is not None:
                to = min(to, deadline - time.time())
            st, dur, tail, ev = V.run_cmd(e["cmd"], project, to, e.get("expect") or {"exit": 0})
            out.append(dict(base, status=st, duration_s=round(dur, 3), tail=tail, evidence=ev,
                            claim="enforced learning %s: %s" % (lid, e["cmd"])))
    return out


# ---- due-ness (a counter, checked during normal use) ----------------------------

def proposed(rows=None):
    rows = L.load_learnings() if rows is None else rows
    ledger = L.load_ledger()
    return [r for r in rows if r.get("status") == "proposed" and not r.get("candidate")
            and L.is_registered(r, ledger)]


def due_notice(session=None):
    """Session-start lines: a cycle is due, and/or a decision waits for the owner. The callers
    (tick, the gate) catch and log a failure; it is not hidden here."""
    n = len(proposed())
    fl = len(L.flagged())
    lines = []
    # The user's config can silence the request to run a cycle (learning.cycle_notice: false).
    from . import store
    notice = (store.config().get("learning") or {}).get("cycle_notice", True)
    if notice and (n >= DUE_AFTER or fl):
        lines.append("sisi: a learning cycle is due (%d proposed learning(s)%s; `sisi cycle` prints the brief)"
                     % (n, ", %d flagged not working" % fl if fl else ""))
    pend = L.pending_notice()
    if pend:
        lines.append(pend)
    return "\n".join(lines)


def brief_text():
    rows = L.load_learnings()
    changed = L.monitor(rows)
    if changed:
        L.save_learnings(rows, "monitoring: %d learning(s) now monitored" % len(changed), touched=changed, via="cycle")
    lines = ["Learning cycle brief. Base: %s" % L.store_base(rows), "",
             "Write one cycle file (JSON, format in `sisi cycle help`) turning proposed "
             "learnings into mechanisms. Prefer an executable mechanism over rule text. "
             "A command check is replayed against its unit's commits and must fail before "
             "the fix and pass after (the repository must be trusted and the command must exist "
             "at both commits). A mechanism reaches only the scope its learning has earned; "
             "anything wider, any command that is not proven, any replaced or disabled rule "
             "waits for the owner. Protected rules (canon/protected.json) cannot be touched.", ""]
    for r in proposed(rows):
        lines.append("- %s [%s] %s (earned scope: %s)\n  change: %s\n  expect: %s  validate: %s"
                     % (r["id"], r.get("proposed", {}).get("mechanism"), r.get("title"), L.earned_scope(r),
                        r.get("proposed", {}).get("description"), r.get("expected_effect"),
                        (r.get("validation") or {}).get("method")))
    for r in L.flagged(rows):
        lines.append("- %s FLAGGED NOT WORKING (%d recurrences since promotion): this cycle "
                     "must revise or revert it." % (r["id"], r.get("recurrences_after_promotion", 0)))
    return "\n".join(lines) + "\n"


# ---- replay validation (one implementation: evaluate.validate_command) -----------------

def replay_validate(rec, action, run=True):
    """(result, detail): `validated` only when the command ran and failed before the fix and ran
    and passed after it, in the learning's own, trusted project, between the two commits the
    learning's OWN record holds (its unit's start and closing commits, or the ones stored with the
    finding). Commits, repository and project named in the cycle file are ignored. `unvalidated`
    (with the reason) when it could not be shown; `failed` when it ran and did not behave so;
    `vacuous` when the command names no path that differs between the two trees. With run=False
    nothing is executed (the preflight only): the result is `unvalidated` unless it is refused."""
    cmd = action.get("cmd") or ""
    exp = (action.get("expect") or {}).get("exit", 0)
    commits = L.replay_commits(rec)
    repo = rec.get("origin_project")
    if not (repo and commits and cmd):
        return "unvalidated", ("no commits are recorded for this learning (its unit %s has no start and closing "
                               "commit, and the finding stored none), so the command was never replayed"
                               % rec.get("source_unit"))
    before, after, where = commits
    if not run:
        stop = evaluate.replay_preflight(repo, before, after, cmd)
        if stop and stop["outcome"] == "vacuous":
            return "vacuous", stop["reason"]
        return "unvalidated", ("`check` runs nothing; `apply` replays it between the commits in %s"
                               % where if not stop else "not replayable: %s" % stop.get("reason"))
    out = evaluate.validate_command(repo, before, after, cmd, exp)
    if out["outcome"] == "validated":
        return "validated", "replay: failed at %s, passed at %s (commits from %s)" % (before[:12], after[:12], where)
    if out["outcome"] == "vacuous":
        return "vacuous", out.get("reason")
    if out["outcome"] == "not-run":
        return "unvalidated", "replay did not establish it: %s" % out.get("reason")
    return "failed", "replay: %s" % (out.get("reason") or out["outcome"])


# ---- planning a cycle file (untrusted input; nothing is written here) -------------------

def _need(cond, msg):
    if not cond:
        raise CycleError(msg)


def _text(a, key, rid):
    v = a.get(key)
    _need(isinstance(v, str) and v.strip(), "%s for %s needs %s" % (a.get("mechanism_kind"), rid, key))
    return v


def _risk_lowers(pattern, profile):
    from . import risk
    if profile == "trivial":
        return True
    sample = re.sub(r"\*+", "x", pattern)
    cur, _why = risk.assess([sample], patterns=risk._patterns_from(risk.default_table()))
    return risk._ORDER[profile] < risk._ORDER[cur]


def _plan_promote(a, rec, virtual_rules, run=True):
    """(normalized action, reasons that make it consequential, granted scope, replay)."""
    kind = a.get("mechanism_kind")
    lid = rec["id"]
    _need(kind in MECHANISM_KINDS, "mechanism_kind for %s must be one of %s" % (lid, "|".join(MECHANISM_KINDS)))
    _need(rec.get("proposed", {}).get("mechanism") != "tool",
          "learning %s is a tool change to sisi itself; it goes to the backlog and the contribution "
          "export (`sisi promote --export`), not a cycle mechanism" % lid)
    _need(not rec.get("candidate"), "learning %s is a subagent candidate; a parent retro must adopt it first "
                                    "(`sisi retro --adopt %s`)" % (lid, lid))
    n = {"action": "promote", "learning": lid, "mechanism_kind": kind}
    reasons, replay = [], None
    earned = L.earned_scope(rec)
    asked = a.get("scope") or ("organization" if a.get("every_project") else None)
    _need(asked in (None, "project", "user", "organization"), "scope for %s must be project|user|organization" % lid)
    base = "user" if kind in GLOBAL_KINDS else ("project" if kind == "command-check" else earned)
    granted = base
    if asked and L.SCOPE_RANK[asked] > L.SCOPE_RANK[base]:
        granted = asked
        reasons.append("the cycle asked for %s scope; learning %s has earned %s" % (asked, lid, earned))
    if kind in GLOBAL_KINDS and L.SCOPE_RANK[earned] < L.SCOPE_RANK["user"]:
        reasons.append("%s changes what every project loads, and learning %s has earned only its own project"
                       % (kind, lid))
    elif kind not in GLOBAL_KINDS and L.SCOPE_RANK[granted] > L.SCOPE_RANK[earned]:
        reasons.append("wider than learning %s has earned (%s)" % (lid, earned))

    if kind == "command-check":
        n["cmd"] = _text(a, "cmd", lid).strip()
        exp = a.get("expect") if isinstance(a.get("expect"), dict) else {}
        n["expect"] = {"exit": exp.get("exit", 0)}
        if a.get("timeout_s") is not None:
            _need(isinstance(a["timeout_s"], (int, float)) and 0 < a["timeout_s"] <= 600,
                  "timeout_s for %s must be between 0 and 600" % lid)
            n["timeout_s"] = a["timeout_s"]
        replay = replay_validate(rec, n, run)
        _need(replay[0] != "vacuous", "command check for %s is vacuous: %s. Write a command that reads a path "
                                      "the fix changed" % (lid, replay[1]))
        _need(replay[0] != "failed", "replay validation failed for %s: %s; nothing is applied" % (lid, replay[1]))
        if replay[0] != "validated":
            reasons.append("an enforced command nobody has seen fail and then pass in its own project (%s)" % replay[1])
        if L.SCOPE_RANK[granted] > 0:
            reasons.append("an enforced command that would run outside the origin project")
    elif kind == "contract-requirement":
        n["when"], n["require_kind"] = _text(a, "when", lid), _text(a, "require_kind", lid)
        if a.get("max_rung") is not None:
            _need(isinstance(a["max_rung"], int), "max_rung for %s must be an integer" % lid)
            n["max_rung"] = a["max_rung"]
    elif kind == "rule-text":
        rid = a.get("rule_id")
        _need(isinstance(rid, str) and overlay.ID_OK.match(rid), "rule-text for %s needs a plain rule_id" % lid)
        _need(rid not in protected_rules(), "rule %r is protected (canon/protected.json); a cycle may not touch it" % rid)
        text = _text(a, "rule_text", lid)
        parsed = documents.check_rule_text(text, rid)
        known = {x["id"] for x in overlay.base_rules()[1]} | set(overlay.overlay_rules())
        if rid in known or rid in virtual_rules:
            reasons.append("replaces the existing rule %s" % rid)
        virtual_rules[rid] = parsed
        ok, msg = documents.check_budgets(overlay.render_with(virtual_rules))
        _need(ok, "rule-text for %s breaks the rulebook budget: %s; nothing is applied" % (lid, msg))
        n["rule_id"], n["rule_text"] = rid, text
    elif kind == "library":
        _need(a.get("library_kind") in ("recipe", "verifier"), "library for %s needs library_kind recipe|verifier and entry_text" % lid)
        n["library_kind"], n["entry_text"] = a["library_kind"], _text(a, "entry_text", lid)
        eid = a.get("entry_id")
        _need(eid is None or (isinstance(eid, str) and overlay.ID_OK.match(eid)), "entry_id for %s is not a plain id" % lid)
        n["entry_id"], n["replacing"] = eid, bool(a.get("replacing"))
        try:
            n["entry_id"], _rel, _mine = overlay._put_entry(n["library_kind"], n["entry_text"], eid, n["replacing"])
        except overlay.OverlayError as e:
            raise CycleError("library entry for %s: %s" % (lid, e))
        if n["replacing"]:
            reasons.append("replaces the existing %s %s" % (n["library_kind"], n["entry_id"]))
    elif kind == "risk":
        from . import risk
        pat, prof = _text(a, "pattern", lid), a.get("profile")
        _need(prof in risk.PROFILES, "risk profile for %s must be one of %s" % (lid, "|".join(risk.PROFILES)))
        n["pattern"], n["profile"] = pat, prof
        if _risk_lowers(pat, prof):
            reasons.append("a risk pattern that lowers a profile (%s -> %s)" % (pat, prof))
    elif kind == "routing":
        _need(a.get("kind") and (a.get("prefer") or a.get("avoid")), "routing for %s needs kind and prefer|avoid" % lid)
        n.update({k: a[k] for k in ("kind", "difficulty", "prefer", "avoid") if a.get(k) is not None})
    elif kind == "benchmark":
        name = a.get("name")
        _need(isinstance(name, str) and SAFE_NAME.match(name) and ".." not in name,
              "benchmark for %s needs a plain name" % lid)
        _need(isinstance(a.get("case"), dict), "benchmark for %s needs a case object" % lid)
        n["name"], n["case"] = name, a["case"]
    return n, reasons, granted, replay


def validate_doc(doc, rows, run=True):
    """Every refusal is raised before anything is applied. Returns the plan: a list of
    {"kind": status|promote|disable-rule, "action", "rec", "pending", "reasons", "scope", "replay"}."""
    if not isinstance(doc, dict) or not isinstance(doc.get("actions"), list) or not doc["actions"]:
        raise CycleError("the cycle file must be JSON with a non-empty \"actions\" list")
    base = doc.get("base")
    if base != L.store_base(rows):
        raise CycleError("stale base: the cycle was written against %r but the store is at %r; "
                         "take a fresh brief (`sisi cycle`)" % (base, L.store_base(rows)))
    ledger = L.load_ledger()
    plan, acted, virtual = [], set(), {}
    for a in doc["actions"]:
        _need(isinstance(a, dict), "every action must be an object")
        act = a.get("action")
        if act == "disable-rule":
            rid = a.get("rule_id")
            _need(isinstance(rid, str) and rid, "disable-rule needs a rule_id")
            _need(rid not in protected_rules(), "rule %r is protected (canon/protected.json); a cycle may not touch it" % rid)
            known = {x["id"] for x in overlay.base_rules()[1]} | set(overlay.overlay_rules())
            _need(rid in known, "no rule %r" % rid)
            plan.append({"kind": "disable-rule", "action": {"action": "disable-rule", "rule_id": rid},
                         "rec": None, "pending": True, "scope": None, "replay": None,
                         "reasons": ["disables the rule %s" % rid]})
            continue
        rec = L.get(rows, a.get("learning") or "")
        _need(rec is not None, "no learning %r" % a.get("learning"))
        _need(L.is_registered(rec, ledger), "learning %s was not written by sisi's own commands "
                                            "(added or edited by hand); a cycle does not act on it" % rec["id"])
        acted.add(rec["id"])
        if act in ("revise", "revert", "reject"):
            _need((a.get("why") or "").strip(), "%s of %s needs a why" % (act, rec["id"]))
            plan.append({"kind": "status", "action": {"action": act, "learning": rec["id"], "why": a["why"]},
                         "rec": rec, "pending": False, "scope": None, "replay": None, "reasons": []})
            continue
        _need(act == "promote", "unknown action %r" % act)
        n, reasons, granted, replay = _plan_promote(a, rec, virtual, run)
        plan.append({"kind": "promote", "action": n, "rec": rec, "pending": bool(reasons),
                     "scope": granted, "replay": replay, "reasons": reasons})
    ignored = [r["id"] for r in L.flagged(rows) if r["id"] not in acted]
    _need(not ignored, "this cycle ignores learning(s) flagged not working: %s; "
                       "revise or revert each one" % ", ".join(ignored))
    return plan


# ---- applying -----------------------------------------------------------------------

def _remove_mechanisms(lid, msg):
    for rel, key in (("enforced.json", "checks"), ("risk-adjustments.json", "adjustments"),
                     ("routing-adjustments.json", "adjustments")):
        d = _overlay_json(rel, key)
        kept = [c for c in d.get(key, []) if c.get("learning") != lid]
        if kept != d.get(key, []):
            d[key] = kept
            _put_json(rel, d, "cycle: %s removes its %s" % (msg, rel))


def _stamp(entry, rec, granted, approval):
    entry.update({"learning": rec["id"], "scope": granted, "project": rec.get("origin_project")})
    if approval:
        entry["approval"] = approval
    return entry


def _apply_mechanism(a, rec, granted, approval=None):
    """Write one mechanism. Returns its reference text."""
    lid, kind = rec["id"], a["mechanism_kind"]
    if kind == "command-check":
        d = _overlay_json("enforced.json", "checks")
        d.setdefault("checks", []).append(_stamp(
            {"type": "command", "cmd": a["cmd"], "expect": a.get("expect") or {"exit": 0},
             "timeout_s": a.get("timeout_s")}, rec, granted, approval))
        _put_json("enforced.json", d, "cycle: enforced command check for %s" % lid)
        return "enforced command check"
    if kind == "contract-requirement":
        d = _overlay_json("enforced.json", "checks")
        d.setdefault("checks", []).append(_stamp(
            {"type": "contract-requirement", "when": a["when"], "require_kind": a["require_kind"],
             "max_rung": a.get("max_rung")}, rec, granted, approval))
        _put_json("enforced.json", d, "cycle: enforced contract requirement for %s" % lid)
        return "enforced contract requirement"
    if kind == "rule-text":
        rid = a["rule_id"]
        known = {x["id"] for x in overlay.base_rules()[1]} | set(overlay.overlay_rules())
        if rid in known:
            overlay.replace_rule(rid, a["rule_text"])
        else:
            overlay.add_rule(a["rule_text"], rid)
        overlay.build_canon()
        rec.setdefault("proposed", {})["target"] = rec.get("proposed", {}).get("target") or rid
        return "rule %s" % rid
    if kind == "library":
        eid = overlay.put_entry(a["library_kind"], a["entry_text"], a.get("entry_id"),
                                replacing=bool(a.get("replacing")))
        rec.setdefault("proposed", {})["target"] = rec.get("proposed", {}).get("target") or eid
        return "%s %s" % (a["library_kind"], eid)
    if kind == "risk":
        d = _overlay_json("risk-adjustments.json", "adjustments")
        d.setdefault("adjustments", []).append(_stamp(
            {"pattern": a["pattern"], "profile": a["profile"]}, rec, granted, approval))
        _put_json("risk-adjustments.json", d, "cycle: risk adjustment for %s" % lid)
        return "risk %s -> %s" % (a["pattern"], a["profile"])
    if kind == "routing":
        d = _overlay_json("routing-adjustments.json", "adjustments")
        adj = {k: a[k] for k in ("kind", "difficulty", "prefer", "avoid") if a.get(k) is not None}
        d.setdefault("adjustments", []).append(_stamp(adj, rec, granted, approval))
        _put_json("routing-adjustments.json", d, "cycle: routing adjustment for %s" % lid)
        return "routing %s" % a["kind"]
    if kind == "benchmark":
        rel = "overlay/benchmarks/%s.json" % a["name"]
        case = _stamp(dict(a["case"]), rec, granted, approval)
        pdata.write_text(rel, json.dumps(case, indent=2, sort_keys=True) + "\n")
        pdata.commit("cycle: benchmark case for %s" % lid, [rel])
        return "benchmark %s" % a["name"]
    raise CycleError("unknown mechanism kind %r" % kind)


def _promoted(rec, ref, granted, replay):
    result, detail = replay if replay else ("unvalidated", "no replay for this mechanism kind")
    method = rec["validation"].get("method") or ("replay" if replay else "")
    rec["validation"].update(result=result, detail=detail, method=method)
    rec["status"] = "promoted"
    rec["mechanism_ref"] = ref
    rec["mechanism_scope"] = granted
    rec["promoted_at"] = L.now()
    rec["flagged_not_working"] = False
    rec["recurrences_after_promotion"] = 0
    rec["version"] = int(rec.get("version") or 1) + 1
    return "%s promoted as %s: %s (%s)" % (rec["id"], result, ref, detail)


def _apply_status(a, rec):
    act = a["action"]
    rec["status"] = {"revise": "revised", "revert": "reverted", "reject": "rejected"}[act]
    rec["flagged_not_working"] = False
    rec.setdefault("history", []).append({"ts": L.now(), "action": act, "why": L.scrub_secrets(a.get("why", ""))})
    if act in ("revert", "revise"):
        _remove_mechanisms(rec["id"], "%s %s" % (act, rec["id"]))
    return "%s %s: %s" % (rec["id"], rec["status"], a.get("why", ""))


def _park(item_action, rec, reasons, granted, replay, items, added):
    pid = L.next_pending_id(items)
    items.append({"id": pid, "ts": L.now(), "learning": rec["id"] if rec else None, "action": item_action,
                  "reasons": reasons, "scope": granted, "replay": list(replay) if replay else None})
    added.append(pid)
    return pid


def _head():
    p = pdata.git("rev-parse", "HEAD", check=False)
    return p.stdout.strip() if p.returncode == 0 else None


def _show(rev, rel):
    p = pdata.git("show", "%s:%s" % (rev, rel), check=False)
    return p.stdout if p.returncode == 0 else None


def _changed(a, b):
    p = pdata.git("diff", "--name-only", a, b, check=False)
    return [x for x in p.stdout.splitlines() if x]


def _restore_files(before, files):
    """Put each of these store files back as it was at `before` (or remove it if it did not exist)."""
    done = []
    for f in files:
        old = _show(before, f)
        p = paths.data_file(f)
        if old is None:
            if os.path.exists(p):
                os.remove(p)
        else:
            pdata.write_text(f, old)
        done.append(f)
    return done


def _cycle_records():
    d = paths.data_file("cycles")
    out = []
    for n in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if n.endswith(".json"):
            try:
                with open(os.path.join(d, n), encoding="utf-8") as f:
                    r = json.load(f)
                if isinstance(r, dict):
                    out.append(r)
            except (OSError, ValueError):
                pass
    return out


def cycle_records():
    """The cycle records, oldest first (id, ts, before, after, lines, changed, ...)."""
    return _cycle_records()


def _transact(label, fn):
    """Run fn() -> (report lines, touched learning ids, pending ids added) as one cycle: every
    write is committed, the cycle is recorded with what it needs to be reverted exactly, and a
    failure part-way restores every file it changed."""
    pdata.ensure()
    before = _head()
    rows_before = {r["id"]: {k: copy.deepcopy(r[k]) for k in CYCLE_FIELDS if k in r} for r in L.load_learnings()}
    try:
        lines, touched, added = fn()
    except BaseException:
        if before:
            changed = set(_changed(before, "HEAD"))
            changed |= {x for x in pdata.git("diff", "--name-only", "HEAD", check=False).stdout.splitlines() if x}
            changed |= {x for x in pdata.git("ls-files", "--others", "--exclude-standard", "--", "overlay",
                                             check=False).stdout.splitlines() if x}
            changed = sorted(changed)
            if changed:
                _restore_files(before, changed)
                pdata.commit("cycle aborted: store restored", changed)
            try:
                overlay.build_canon()
            except Exception:
                pass
        raise
    after = _head()
    n = len(_cycle_records()) + 1
    cid = "cycle-%04d" % n
    rec = {"id": cid, "label": label, "ts": L.now(), "before": before, "after": after, "lines": lines,
           "changed": _changed(before, after) if before and after else [],
           "rows_before": {i: rows_before[i] for i in touched if i in rows_before},
           "pending_added": added}
    pdata.write_text("cycles/%s.json" % cid, json.dumps(rec, indent=2, sort_keys=True) + "\n")
    pdata.commit("cycle %s applied" % cid, ["cycles/%s.json" % cid])
    return cid, lines


def apply_file(path):
    """Validate and plan everything, then apply. A refusal changes nothing."""
    pdata.ensure()
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except ValueError as e:
        raise CycleError("the cycle file is not JSON: %s" % e)
    rows = L.load_learnings()
    plan = validate_doc(doc, rows)

    def run():
        lines, touched, added = [], [], []
        items = L.load_pending()
        for p in plan:
            a, rec = p["action"], p["rec"]
            if p["kind"] == "status":
                lines.append(_apply_status(a, rec))
                touched.append(rec["id"])
            elif p["kind"] == "promote" and not p["pending"]:
                ref = _apply_mechanism(a, rec, p["scope"])
                lines.append(_promoted(rec, ref, p["scope"], p["replay"]))
                touched.append(rec["id"])
            else:
                pid = _park(a, rec, p["reasons"], p["scope"], p["replay"], items, added)
                if rec is not None:
                    if p["replay"] and p["replay"][0] == "validated":
                        rec["validation"].update(result="validated", detail=p["replay"][1],
                                                 method=rec["validation"].get("method") or "replay")
                        if rec.get("status") in ("observed", "analyzed", "proposed", "implemented"):
                            rec["status"] = "validated"
                    touched.append(rec["id"])
                lines.append("%s waits for the owner (%s): `sisi approve` lists it, the owner decides with "
                             "`sisi approve %s --yes|--no`" % (rec["id"] if rec else a.get("rule_id"),
                                                                "; ".join(p["reasons"]), pid))
        if added:
            L.save_pending(items, "cycle: consequential change(s) pending")
        if touched:
            L.save_learnings(rows, "cycle: %d learning(s) changed" % len(set(touched)), touched=sorted(set(touched)), via="cycle")
        changed = L.monitor(rows)
        if changed:
            L.save_learnings(rows, "monitoring: learning(s) now monitored", touched=changed, via="cycle")
        return lines, sorted(set(touched) | {r["id"] for r in changed}), added

    return _transact("apply", run)


def revert_cycle(cid=None):
    """Undo one cycle's effects and nothing else: the mechanism files it wrote go back, the
    learning records it changed get back the fields it changed, the decisions it parked are
    dropped. Findings, statements and recurrences recorded after the cycle stay."""
    recs = [r for r in _cycle_records() if not r.get("reverted")]
    if not recs:
        raise CycleError("no cycles to revert")
    if cid:
        rec = next((r for r in recs if r.get("id") == cid), None)
        if rec is None:
            raise CycleError("no cycle %r that can be reverted" % cid)
    else:
        rec = recs[-1]
    before, after = rec.get("before"), rec.get("after")
    if not before or not after:
        raise CycleError("cycle %s has no recorded commits; cannot revert exactly" % rec["id"])
    files = [f for f in rec.get("changed", []) if f not in STORE_FILES and not f.startswith("cycles/")]
    for f in files:
        if _changed(after, "HEAD") and f in _changed(after, "HEAD"):
            raise CycleError("%s was changed after this cycle; revert the later change first" % f)
    _restore_files(before, files)
    rows = L.load_learnings()
    touched = []
    for lid, fields in (rec.get("rows_before") or {}).items():
        r = L.get(rows, lid)
        if r is None:
            continue
        for k in CYCLE_FIELDS:
            if k in fields:
                r[k] = copy.deepcopy(fields[k])
            else:
                r.pop(k, None)
        r.setdefault("history", []).append({"ts": L.now(), "action": "cycle-reverted", "cycle": rec["id"]})
        touched.append(r)
    if touched:
        L.save_learnings(rows, "revert %s: learning records restored" % rec["id"], touched=touched, via="cycle")
    gone = set(rec.get("pending_added") or [])
    if gone:
        L.save_pending([i for i in L.load_pending() if i.get("id") not in gone], "revert %s: parked changes dropped" % rec["id"])
    if files:
        pdata.commit("revert %s" % rec["id"], files)
    rec["reverted"] = L.now()
    pdata.write_text("cycles/%s.json" % rec["id"], json.dumps(rec, indent=2, sort_keys=True) + "\n")
    pdata.commit("revert %s recorded" % rec["id"], ["cycles/%s.json" % rec["id"]])
    try:
        overlay.build_canon()
    except Exception:
        pass
    return rec["id"]


# ---- approval -------------------------------------------------------------------------

def _stdin_is_tty():
    try:
        return bool(sys.stdin is not None and sys.stdin.isatty())
    except (ValueError, OSError):
        return False


def relay_allowed():
    """May an agent relay the owner's decision? Off unless the user's config says so."""
    try:
        from . import store
        return bool((store.config().get("learning") or {}).get("agent_relayed_approval"))
    except Exception:
        return False


def describe_pending(item):
    """The full action, in words and text, so the owner can see exactly what is approved."""
    a = item.get("action") or {}
    rec = L.get(L.load_learnings(), item.get("learning") or "")
    out = ["%s: %s" % (item["id"], (a.get("action") if a.get("action") != "promote" else
                                    "install a %s" % a.get("mechanism_kind")))]
    if rec:
        out.append("  learning %s: %s" % (rec["id"], L.derive_title(rec.get("title") or "", 120)))
        out.append("  seen in: %d unit(s), %d project(s); earned scope: %s"
                   % (len({p.get("unit") for p in rec.get("provenance") or []}),
                      len({p.get("project") for p in rec.get("provenance") or []}), L.earned_scope(rec)))
        out.append("  origin project: %s" % rec.get("origin_project"))
    kind = a.get("mechanism_kind")
    if kind == "command-check":
        out.append("  COMMAND (runs through the shell on every verify): %s" % a.get("cmd"))
        out.append("  expected exit: %s   timeout: %s" % ((a.get("expect") or {}).get("exit", 0), a.get("timeout_s") or "default"))
    elif kind == "contract-requirement":
        out.append("  a contract that mentions %r must contain a check of kind %s%s"
                   % (a.get("when"), a.get("require_kind"),
                      " at rung <= %s" % a["max_rung"] if a.get("max_rung") is not None else ""))
    elif kind == "risk":
        out.append("  risk pattern: %s -> profile %s" % (a.get("pattern"), a.get("profile")))
    elif kind == "routing":
        out.append("  routing: %s" % json.dumps({k: a[k] for k in ("kind", "difficulty", "prefer", "avoid") if k in a}, sort_keys=True))
    elif kind == "benchmark":
        out.append("  benchmark %s: %s" % (a.get("name"), json.dumps(a.get("case"), sort_keys=True)[:600]))
    elif kind == "library":
        out.append("  %s %s (%s):" % (a.get("library_kind"), a.get("entry_id") or "(id from its header)",
                                      "replaces the existing entry" if a.get("replacing") else "new"))
        out += ["    | " + l for l in str(a.get("entry_text") or "").splitlines()[:60]]
    if kind == "rule-text" or a.get("action") == "replace-rule":
        rid, new = a.get("rule_id"), a.get("rule_text") or ""
        cur = next((r for r in overlay.effective()[1] if r["id"] == rid), None)
        out.append("  rule %s: %s" % (rid, "text diff against the rule in force" if cur else "new rule"))
        old_text = overlay.rule_text(cur).splitlines() if cur else []
        try:
            new_text = overlay.rule_text(overlay.parse_rule_file(new, rid)).splitlines()
        except Exception:
            new_text = new.splitlines()
        diff = list(difflib.unified_diff(old_text, new_text, "in force", "proposed", lineterm=""))
        out += ["    " + l for l in (diff if cur else ["+ " + l for l in new_text])]
    if a.get("action") == "disable-rule":
        out.append("  switches off the rule %s" % a.get("rule_id"))
    out.append("  scope it would take effect in: %s" % (item.get("scope") or "all projects (a rule change)"))
    for r in item.get("reasons") or []:
        out.append("  needs you because: %s" % r)
    rp = item.get("replay")
    if rp:
        out.append("  replay: %s (%s)" % (rp[0], rp[1]))
    return out


def apply_pending(pid, yes, how=None):
    how = how or {}
    items = L.load_pending()
    item = next((i for i in items if i.get("id") == pid), None)
    if item is None:
        raise CycleError("no pending change %r (`sisi approve` lists them)" % pid)
    row = {"id": pid, "decision": "yes" if yes else "no", "ts": L.now(), "learning": item.get("learning"),
           "session": os.environ.get("SISI_SESSION_ID") or None, "terminal": bool(how.get("terminal")),
           "relayed": "relayed by an agent" if how.get("relayed") else None,
           "action": item.get("action")}
    left = [i for i in items if i.get("id") != pid]
    if not yes:
        L.record_approval(row)
        L.save_pending(left, "approve: %s refused by the owner" % pid)
        return "%s refused; nothing changed" % pid
    a = item["action"]

    def run():
        lines, touched = [], []
        if a.get("action") in ("disable-rule", "replace-rule"):
            rid = a.get("rule_id")
            _need(rid not in protected_rules(), "rule %r is protected; even approval cannot change it by cycle" % rid)
            if a["action"] == "disable-rule":
                overlay.set_disabled("rule", rid, True)
                lines.append("rule %s disabled (approved)" % rid)
            else:
                overlay.replace_rule(rid, a["rule_text"])
                lines.append("rule %s replaced (approved)" % rid)
            overlay.build_canon()
        else:
            rows = L.load_learnings()
            rec = L.get(rows, a.get("learning") or "")
            _need(rec is not None and rec.get("status") not in L.ENDED, "learning %r no longer exists" % a.get("learning"))
            _need(L.is_registered(rec), "learning %s was changed outside sisi's own commands" % rec["id"])
            if a.get("mechanism_kind") == "rule-text":
                rid = a["rule_id"]
                _need(rid not in protected_rules(), "rule %r is protected; even approval cannot change it by cycle" % rid)
                ok, msg = documents.check_budgets(overlay.render_with({rid: documents.check_rule_text(a["rule_text"], rid)}))
                _need(ok, "rule-text for %s breaks the rulebook budget: %s" % (rec["id"], msg))
            replay = tuple(item["replay"]) if item.get("replay") else None
            ref = _apply_mechanism(a, rec, item.get("scope") or "project", approval=pid)
            lines.append(_promoted(rec, ref, item.get("scope") or "project", replay) + " (approved)")
            L.save_learnings(rows, "approve: %s promotes %s" % (pid, rec["id"]), touched=[rec], via="cycle")
            touched.append(rec["id"])
        L.record_approval(row)
        L.save_pending(left, "approve: %s applied" % pid)
        return lines, touched, []

    cid, lines = _transact("approve %s" % pid, run)
    return lines[0]


def park_rule_change(action, reasons):
    """A rule change typed through `sisi overlay` waits for the owner like a cycle's."""
    items = L.load_pending()
    added = []
    pid = _park(action, None, reasons, None, None, items, added)
    L.save_pending(items, "overlay: %s waits for the owner" % action.get("action"))
    return pid


def cmd_approve(argv):
    items = L.load_pending()
    if not argv:
        if not items:
            print("nothing waits for a decision")
            return 0
        for i in items:
            print("\n".join(describe_pending(i)))
            print()
        print("The owner decides, in a terminal: sisi approve ID --yes | --no")
        return 0
    pid, yes = argv[0], "--yes" in argv
    if not yes and "--no" not in argv:
        print("usage: sisi approve [ID --yes | --no]", file=sys.stderr)
        return 2
    tty = _stdin_is_tty()
    relayed = False
    if not tty:
        if not relay_allowed():
            item = next((i for i in items if i.get("id") == pid), None)
            if item:
                print("\n".join(describe_pending(item)), file=sys.stderr)
            print("sisi approve: refused. A decision must be made by the owner in a terminal: this was run "
                  "without one (an agent, a script, a pipe). Show the owner what it does (the listing above) "
                  "and give the owner the command to type. To allow an agent to relay a decision, set "
                  "learning.agent_relayed_approval in the user config (off by default).", file=sys.stderr)
            return 2
        relayed = True
    try:
        print(apply_pending(pid, yes, {"terminal": tty, "relayed": relayed}))
        return 0
    except (CycleError, overlay.OverlayError, documents.DocumentError) as e:
        print("sisi approve: %s" % e, file=sys.stderr)
        return 2


HELP = """sisi cycle: turn proposed learnings into mechanisms. JSON cycle file:
  {"base": "<from `sisi cycle`>", "actions": [ ... ]}
promote actions, by mechanism_kind:
  command-check        {learning, cmd, expect?, before?, after?}  replayed in the origin project's trusted
                       repository: it must exist at both commits, fail before and pass after
  contract-requirement {learning, when, require_kind, max_rung?}
  rule-text            {learning, rule_id, rule_text}   (protected rules refused)
  library              {learning, library_kind: recipe|verifier, entry_text, entry_id?, replacing?}
  risk                 {learning, pattern, profile}     -> overlay/risk-adjustments.json
  routing              {learning, kind, difficulty?, prefer|avoid} -> overlay/routing-adjustments.json
  benchmark            {learning, name, case:{...}}     -> overlay/benchmarks/<name>.json
other actions: {action: revise|revert|reject, learning, why}; {action: disable-rule, rule_id}
Every mechanism is written with its learning's id and the scope that learning has earned (its origin
project unless it was seen in two units in two projects, or is an owner statement); a scope or
every_project flag only asks for more. These wait for the owner (`sisi approve`, in a terminal):
more scope than earned, a command not proven by replay, a risk pattern that lowers a profile, a
replaced or disabled rule, a rule or library entry from a learning confined to one project.
A cycle that ignores a flagged learning is refused. `sisi cycle revert` undoes only that cycle's changes.
"""


def cmd_cycle(args):
    if args and args[0] == "help":
        sys.stdout.write(HELP)
        return 0
    if args and args[0] == "apply" and len(args) > 1:
        try:
            cid, lines = apply_file(args[1])
        except (CycleError, OSError, documents.DocumentError, overlay.OverlayError) as e:
            print("sisi cycle: %s" % e, file=sys.stderr)
            return 2
        print("%s applied:" % cid)
        for x in lines:
            print("- " + x)
        return 0
    if args and args[0] == "check" and len(args) > 1:
        try:
            with open(args[1], encoding="utf-8") as f:
                doc = json.load(f)
            plan = validate_doc(doc, L.load_learnings(), run=False)
        except (CycleError, OSError, ValueError, documents.DocumentError, overlay.OverlayError) as e:
            print("sisi cycle: %s" % e, file=sys.stderr)
            return 2
        wait = sum(1 for p in plan if p["pending"])
        print("valid: %d action(s) apply at once, %d wait for the owner" % (len(plan) - wait, wait))
        return 0
    if args and args[0] == "revert":
        try:
            cid = revert_cycle(args[1] if len(args) > 1 else None)
        except (CycleError, OSError) as e:
            print("sisi cycle: %s" % e, file=sys.stderr)
            return 2
        print("%s reverted in the user store (only what that cycle changed)" % cid)
        return 0
    if args and args[0] == "due":
        print(due_notice() or "no cycle is due")
        return 0
    if args:
        print("usage: sisi cycle [apply FILE|check FILE|revert [ID]|due|help]", file=sys.stderr)
        return 2
    sys.stdout.write(brief_text())
    return 0
