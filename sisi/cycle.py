"""The learning cycle: proposed learnings become mechanisms in the user store.

Due by a counter (no scheduler). A worker writes a cycle file; `sisi cycle apply FILE`
treats it as untrusted input, validates everything before changing anything, replays
command checks against the originating unit's commits in a temporary worktree, refuses
protected rules, parks consequential changes for `sisi approve`, and commits each change
to the user store so revert is exact. What cannot be replayed is promoted as
`unvalidated` and always reported as such; nothing is labelled `validated` without a
validation run that passed.

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

Mechanism data files other modules read (all in the user store overlay):
  enforced.json {"checks": [{"type": "command"|"contract-requirement", "lesson": id, ...}]}
  risk-adjustments.json {"adjustments": [{"pattern", "profile", "learning"}]}
  routing-adjustments.json {"adjustments": [{"kind", "difficulty", "prefer"|"avoid", "learning"}]}
  benchmarks/<name>.json  one benchmark case per file
"""
import json, os, shutil, subprocess, sys, tempfile, time

from . import documents, learning as L, overlay, paths, pdata

DUE_AFTER = 5  # proposed learnings waiting make a cycle due (a counter, checked in normal use)
MECHANISM_KINDS = ("contract-requirement", "command-check", "library", "rule-text",
                   "risk", "routing", "benchmark")


class CycleError(Exception):
    pass


# ---- enforced checks (verify.py seam; shape unchanged) --------------------------

def enforced_path():
    return paths.overlay_dir("enforced.json")


def load_enforced():
    try:
        with open(enforced_path(), encoding="utf-8") as f:
            d = json.load(f)
        checks = d.get("checks") if isinstance(d, dict) else None
        return [c for c in checks if isinstance(c, dict)] if isinstance(checks, list) else []
    except (OSError, ValueError):
        return []


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
    """Result rows for enforced checks, in the shape verify.run returns. Command checks run
    only in trusted projects; only checks installed by a validated cycle run."""
    out = []
    checks = load_enforced()
    if not checks:
        return out
    from . import trust, verify as V
    trusted = trust.is_trusted(project)
    for e in checks:
        lid = e.get("lesson")
        base = {"item": "enforced", "tier": "fast", "id": "enforced:lesson-%s" % lid, "kind": None,
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
            st, dur, tail = V.run_cmd(e["cmd"], project, to, e.get("expect") or {"exit": 0})
            out.append(dict(base, status=st, duration_s=round(dur, 3), tail=tail,
                            claim="enforced learning %s: %s" % (lid, e["cmd"])))
    return out


# ---- due-ness (a counter, checked during normal use) ----------------------------

def proposed(rows=None):
    rows = L.load_learnings() if rows is None else rows
    return [r for r in rows if r.get("status") == "proposed" and not r.get("candidate")]


def due_notice(session=None):
    try:
        pend = L.pending_notice()
        n = len(proposed())
        fl = len(L.flagged())
        parts = []
        if n >= DUE_AFTER or fl:
            parts.append("a learning cycle is due (%d proposed learning(s)%s; `sisi cycle` prints the brief)"
                         % (n, ", %d flagged not working" % fl if fl else ""))
        if pend:
            parts.append(pend)
        return "sisi: " + "; ".join(parts) if parts else ""
    except Exception:
        return ""


def brief_text():
    rows = L.load_learnings()
    lines = ["Learning cycle brief. Base: %s" % L.store_base(rows), "",
             "Write one cycle file (JSON, format in `sisi cycle help`) turning proposed "
             "learnings into mechanisms. Prefer an executable mechanism over rule text. "
             "A command check is replayed against its unit's commits and must fail before "
             "the fix and pass after. Protected rules (canon/protected.json) cannot be "
             "touched. Consequential changes wait for the owner.", ""]
    for r in proposed(rows):
        lines.append("- %s [%s] %s\n  change: %s\n  expect: %s  validate: %s"
                     % (r["id"], r.get("proposed", {}).get("mechanism"), r.get("title"),
                        r.get("proposed", {}).get("description"), r.get("expected_effect"),
                        (r.get("validation") or {}).get("method")))
    for r in L.flagged(rows):
        lines.append("- %s FLAGGED NOT WORKING (%d recurrences since promotion): this cycle "
                     "must revise or revert it." % (r["id"], r.get("recurrences_after_promotion", 0)))
    return "\n".join(lines) + "\n"


# ---- protected rules --------------------------------------------------------------

def protected_rules():
    try:
        with open(paths.canon("protected.json"), encoding="utf-8") as f:
            d = json.load(f)
        return set(d.get("rules") or [])
    except (OSError, ValueError):
        return set()


# ---- replay validation --------------------------------------------------------------

def _run_at(repo, sha, cmd, timeout=120):
    """Run cmd in a temporary worktree at sha. Never touches the user's working tree."""
    tmp = tempfile.mkdtemp(prefix="sisi-replay-")
    wt = os.path.join(tmp, "wt")
    try:
        p = subprocess.run(["git", "worktree", "add", "--detach", "-q", wt, sha], cwd=repo,
                           capture_output=True, text=True, timeout=60)
        if p.returncode != 0:
            return None, "worktree at %s failed: %s" % (sha[:12], (p.stderr or "").strip()[:200])
        try:
            p = subprocess.run(cmd, shell=True, cwd=wt, capture_output=True, text=True, timeout=timeout)
            return p.returncode, (p.stdout + p.stderr)[-400:]
        except subprocess.TimeoutExpired:
            return None, "timed out"
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=repo,
                       capture_output=True, timeout=60)
        shutil.rmtree(tmp, ignore_errors=True)


def replay_validate(rec, action):
    """(result, detail): 'validated' only when the check fails before and passes after."""
    cmd = action.get("cmd") or ""
    exp = (action.get("expect") or {}).get("exit", 0)
    replay = rec.get("replay") or {}
    repo = action.get("repo") or replay.get("repo") or rec.get("origin_project")
    before = action.get("before") or replay.get("before")
    after = action.get("after") or replay.get("after")
    if not before or not after:
        # ask groundtruth for the unit's commits when it knows them
        try:
            from . import groundtruth
            if repo and not before:
                before = None  # no start commit on the record: honestly unvalidated below
        except Exception:
            pass
    if not (repo and before and after and cmd):
        return "unvalidated", "no before/after commits known; promoted as unvalidated"
    rb, db = _run_at(repo, before, cmd)
    ra, da = _run_at(repo, after, cmd)
    if rb is None or ra is None:
        return "unvalidated", "replay could not run (%s / %s); promoted as unvalidated" % (db, da)
    if rb != exp and ra == exp:
        return "validated", "replay: failed at %s (exit %d), passed at %s" % (before[:12], rb, after[:12])
    return "failed", "replay: exit %d before, %d after (expected fail then %d)" % (rb, ra, exp)


# ---- validation of a cycle file (untrusted input; all-or-nothing) -------------------

def _consequential(action, rec):
    """Disabling a rule, widening scope to all projects, or a command in every project."""
    if action.get("action") == "disable-rule":
        return True
    if action.get("scope") == "organization":
        return True
    if action.get("mechanism_kind") == "command-check" and action.get("every_project"):
        return True
    return False


def validate_doc(doc, rows):
    """Every refusal is raised before anything is applied. Returns (normal, pending)."""
    if not isinstance(doc, dict) or not isinstance(doc.get("actions"), list) or not doc["actions"]:
        raise CycleError("the cycle file must be JSON with a non-empty \"actions\" list")
    base = doc.get("base")
    if base != L.store_base(rows):
        raise CycleError("stale base: the cycle was written against %r but the store is at %r; "
                         "take a fresh brief (`sisi cycle`)" % (base, L.store_base(rows)))
    prot = protected_rules()
    normal, pending = [], []
    acted = set()
    for a in doc["actions"]:
        if not isinstance(a, dict):
            raise CycleError("every action must be an object")
        act = a.get("action")
        if act == "disable-rule":
            rid = a.get("rule_id")
            if rid in prot:
                raise CycleError("rule %r is protected (canon/protected.json); a cycle may not touch it" % rid)
            pending.append(a)  # disabling any rule is consequential
            continue
        rec = L.get(rows, a.get("learning") or "")
        if rec is None:
            raise CycleError("no learning %r" % a.get("learning"))
        acted.add(rec["id"])
        if act in ("revise", "revert", "reject"):
            if not (a.get("why") or "").strip():
                raise CycleError("%s of %s needs a why" % (act, rec["id"]))
            normal.append((a, rec))
            continue
        if act != "promote":
            raise CycleError("unknown action %r" % act)
        if rec.get("candidate"):
            raise CycleError("learning %s is a subagent candidate; a parent retro must adopt it first" % rec["id"])
        kind = a.get("mechanism_kind")
        if kind not in MECHANISM_KINDS:
            raise CycleError("mechanism_kind for %s must be one of %s" % (rec["id"], "|".join(MECHANISM_KINDS)))
        if rec.get("proposed", {}).get("mechanism") == "tool":
            raise CycleError("learning %s is a tool change to sisi itself; it goes to the backlog "
                             "and the contribution export, not a cycle mechanism" % rec["id"])
        if kind == "command-check":
            if not (a.get("cmd") or "").strip():
                raise CycleError("command-check for %s needs a cmd" % rec["id"])
            if not _consequential(a, rec):  # replay now, so a failed replay refuses before anything applies
                a["_replay"] = replay_validate(rec, a)
                if a["_replay"][0] == "failed":
                    raise CycleError("replay validation failed for %s: %s; nothing is applied"
                                     % (rec["id"], a["_replay"][1]))
        if kind == "contract-requirement" and not (a.get("require_kind") and a.get("when")):
            raise CycleError("contract-requirement for %s needs when and require_kind" % rec["id"])
        if kind == "rule-text":
            rid = a.get("rule_id")
            if rid in prot:
                raise CycleError("rule %r is protected (canon/protected.json); a cycle may not touch it" % rid)
            documents.check_rule_text(a.get("rule_text") or "", rid)
        if kind == "library" and a.get("library_kind") not in ("recipe", "verifier"):
            raise CycleError("library for %s needs library_kind recipe|verifier and entry_text" % rec["id"])
        if kind == "risk" and not (a.get("pattern") and a.get("profile")):
            raise CycleError("risk for %s needs pattern and profile" % rec["id"])
        if kind == "routing" and not (a.get("kind") and (a.get("prefer") or a.get("avoid"))):
            raise CycleError("routing for %s needs kind and prefer|avoid" % rec["id"])
        if kind == "benchmark" and not (a.get("name") and isinstance(a.get("case"), dict)):
            raise CycleError("benchmark for %s needs a name and a case object" % rec["id"])
        (pending if _consequential(a, rec) else normal).append((a, rec) if not _consequential(a, rec) else a)
    ignored = [r["id"] for r in L.flagged(rows) if r["id"] not in acted]
    if ignored:
        raise CycleError("this cycle ignores learning(s) flagged not working: %s; "
                         "revise or revert each one" % ", ".join(ignored))
    return normal, pending


# ---- applying -----------------------------------------------------------------------

def _overlay_json(rel, key):
    try:
        with open(paths.overlay_dir(rel), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {key: []}
    except (OSError, ValueError):
        return {key: []}


def _apply_one(a, rec, rows):
    """Apply one validated action; commits to the user store. Returns a report line."""
    lid = rec["id"]
    kind = a.get("mechanism_kind")
    ref, result, detail = None, "unvalidated", "no replay for this mechanism kind"
    if kind == "command-check":
        result, detail = a.get("_replay") or replay_validate(rec, a)
        if result == "failed":
            raise CycleError("replay validation failed for %s: %s" % (lid, detail))
        d = _overlay_json("enforced.json", "checks")
        d.setdefault("checks", []).append(
            {"type": "command", "lesson": lid, "cmd": a["cmd"],
             "expect": a.get("expect") or {"exit": 0}, "timeout_s": a.get("timeout_s")})
        pdata.write_text("overlay/enforced.json", json.dumps(d, indent=2, sort_keys=True) + "\n")
        pdata.commit("cycle: enforced command check for %s" % lid, ["overlay/enforced.json"])
        ref = "enforced command check"
    elif kind == "contract-requirement":
        d = _overlay_json("enforced.json", "checks")
        d.setdefault("checks", []).append(
            {"type": "contract-requirement", "lesson": lid, "when": a["when"],
             "require_kind": a["require_kind"], "max_rung": a.get("max_rung")})
        pdata.write_text("overlay/enforced.json", json.dumps(d, indent=2, sort_keys=True) + "\n")
        pdata.commit("cycle: enforced contract requirement for %s" % lid, ["overlay/enforced.json"])
        ref = "enforced contract requirement"
    elif kind == "rule-text":
        rid = a["rule_id"]
        known = {x["id"] for x in overlay.base_rules()[1]} | set(overlay.overlay_rules())
        if rid in known:
            overlay.replace_rule(rid, a["rule_text"])
        else:
            overlay.add_rule(a["rule_text"], rid)
        ok, msg = documents.check_budgets()
        if not ok:
            raise CycleError("rule-text for %s breaks the rulebook budget: %s" % (lid, msg))
        overlay.build_canon()
        ref = "rule %s" % rid
    elif kind == "library":
        eid = overlay.put_entry("recipe" if a["library_kind"] == "recipe" else "verifier",
                                a["entry_text"], a.get("entry_id"),
                                replacing=bool(a.get("replacing")))
        ref = "%s %s" % (a["library_kind"], eid)
    elif kind == "risk":
        d = _overlay_json("risk-adjustments.json", "adjustments")
        d.setdefault("adjustments", []).append(
            {"pattern": a["pattern"], "profile": a["profile"], "learning": lid})
        pdata.write_text("overlay/risk-adjustments.json", json.dumps(d, indent=2, sort_keys=True) + "\n")
        pdata.commit("cycle: risk adjustment for %s" % lid, ["overlay/risk-adjustments.json"])
        ref = "risk %s -> %s" % (a["pattern"], a["profile"])
    elif kind == "routing":
        d = _overlay_json("routing-adjustments.json", "adjustments")
        adj = {"kind": a["kind"], "difficulty": a.get("difficulty"), "learning": lid}
        if a.get("prefer"):
            adj["prefer"] = a["prefer"]
        if a.get("avoid"):
            adj["avoid"] = a["avoid"]
        d.setdefault("adjustments", []).append(adj)
        pdata.write_text("overlay/routing-adjustments.json", json.dumps(d, indent=2, sort_keys=True) + "\n")
        pdata.commit("cycle: routing adjustment for %s" % lid, ["overlay/routing-adjustments.json"])
        ref = "routing %s" % a["kind"]
    elif kind == "benchmark":
        rel = "overlay/benchmarks/%s.json" % a["name"]
        pdata.write_text(rel, json.dumps(dict(a["case"], learning=lid), indent=2, sort_keys=True) + "\n")
        pdata.commit("cycle: benchmark case for %s" % lid, [rel])
        ref = "benchmark %s" % a["name"]
    method = rec["validation"].get("method") or ("replay" if kind == "command-check" else "")
    rec["validation"].update(result=result, detail=detail, method=method)
    rec["status"] = "promoted"
    rec["mechanism_ref"] = ref
    rec["promoted_at"] = L.now()
    rec["promoted_unit_seq"] = L.unit_seq()
    rec["flagged_not_working"] = False
    rec["recurrences_after_promotion"] = 0
    rec["version"] = int(rec.get("version") or 1) + 1
    L.save_learnings(rows, "cycle: promote %s (%s)" % (lid, result))
    return "%s promoted as %s: %s (%s)" % (lid, result, ref, detail)


def _apply_status(a, rec, rows):
    act = a["action"]
    rec["status"] = {"revise": "revised", "revert": "reverted", "reject": "rejected"}[act]
    rec["flagged_not_working"] = False
    rec.setdefault("history", []).append({"ts": L.now(), "action": act, "why": a.get("why", "")})
    if act in ("revert", "revise"):
        d = _overlay_json("enforced.json", "checks")
        kept = [c for c in d.get("checks", []) if c.get("lesson") != rec["id"]]
        if kept != d.get("checks", []):
            d["checks"] = kept
            pdata.write_text("overlay/enforced.json", json.dumps(d, indent=2, sort_keys=True) + "\n")
            pdata.commit("cycle: %s %s removes its enforced check" % (act, rec["id"]), ["overlay/enforced.json"])
    L.save_learnings(rows, "cycle: %s %s" % (act, rec["id"]))
    return "%s %s: %s" % (rec["id"], rec["status"], a.get("why", ""))


def _head():
    p = pdata.git("rev-parse", "HEAD", check=False)
    return p.stdout.strip() if p.returncode == 0 else None


def apply_file(path):
    """Validate everything, then apply. A refusal changes nothing."""
    pdata.ensure()
    with open(path, encoding="utf-8") as f:
        try:
            doc = json.load(f)
        except ValueError as e:
            raise CycleError("the cycle file is not JSON: %s" % e)
    rows = L.load_learnings()
    normal, pending = validate_doc(doc, rows)
    before = _head()
    lines = []
    for a, rec in normal:
        lines.append(_apply_status(a, rec, rows) if a["action"] != "promote"
                     else _apply_one(a, rec, rows))
    if pending:
        items = L.load_pending()
        for a in pending:
            pid = "P-%04d" % (len(items) + 1)
            items.append({"id": pid, "action": a, "ts": L.now()})
            lines.append("%s is consequential and waits for the owner: `sisi approve %s --yes|--no`"
                         % (a.get("learning") or a.get("rule_id"), pid))
        L.save_pending(items, "cycle: consequential change(s) pending")
    after = _head()
    cycles = [n for n in os.listdir(paths.data_file("cycles")) if n.endswith(".json")] \
        if os.path.isdir(paths.data_file("cycles")) else []
    cid = "cycle-%04d" % (len(cycles) + 1)
    rec = {"id": cid, "ts": L.now(), "before": before, "after": after, "lines": lines}
    pdata.write_text("cycles/%s.json" % cid, json.dumps(rec, indent=2, sort_keys=True) + "\n")
    pdata.commit("cycle %s applied" % cid, ["cycles/%s.json" % cid])
    return cid, lines


def revert_cycle(cid=None):
    d = paths.data_file("cycles")
    files = sorted(n for n in os.listdir(d) if n.endswith(".json")) if os.path.isdir(d) else []
    if not files:
        raise CycleError("no cycles to revert")
    name = (cid + ".json") if cid else files[-1]
    if name not in files:
        raise CycleError("no cycle %r" % cid)
    with open(os.path.join(d, name), encoding="utf-8") as f:
        rec = json.load(f)
    before, after = rec.get("before"), rec.get("after")
    if not before:
        raise CycleError("cycle %s has no recorded before-commit; cannot revert exactly" % rec["id"])
    # exact revert: restore the store tree to the before-commit, as one new commit
    pdata.git("restore", "--source", before, "--staged", "--worktree", "--", ".")
    # files the cycle added are not in `before`: remove paths tracked now but absent there
    now_files = set(pdata.git("ls-files").stdout.split())
    then_files = set(pdata.git("ls-tree", "-r", "--name-only", before).stdout.split())
    for extra in now_files - then_files:
        if extra.startswith("cycles/"):
            continue  # keep the cycle records themselves
        p = paths.data_file(extra)
        if os.path.exists(p):
            os.remove(p)
    pdata.git("add", "-A", "--", ".")
    pdata.git("commit", "-q", "-m", "revert %s (exact: restore %s)" % (rec["id"], before[:12]))
    return rec["id"]


# ---- approval -------------------------------------------------------------------------

def apply_pending(pid, yes):
    items = L.load_pending()
    item = next((i for i in items if i.get("id") == pid), None)
    if item is None:
        raise CycleError("no pending change %r (`sisi approve` lists them)" % pid)
    a = item["action"]
    items = [i for i in items if i.get("id") != pid]
    if not yes:
        L.save_pending(items, "approve: %s refused by the owner" % pid)
        return "%s refused; nothing changed" % pid
    rows = L.load_learnings()
    if a.get("action") == "disable-rule":
        if a.get("rule_id") in protected_rules():
            raise CycleError("rule %r is protected; even approval cannot disable it by cycle" % a.get("rule_id"))
        overlay.set_disabled("rule", a["rule_id"], True)
        overlay.build_canon()
        L.save_pending(items, "approve: %s applied" % pid)
        return "rule %s disabled (approved)" % a["rule_id"]
    rec = L.get(rows, a.get("learning") or "")
    if rec is None:
        raise CycleError("learning %r no longer exists" % a.get("learning"))
    line = _apply_one(a, rec, rows)
    L.save_pending(items, "approve: %s applied" % pid)
    return line + " (approved)"


def cmd_approve(argv):
    if not argv:
        items = L.load_pending()
        if not items:
            print("nothing waits for a decision")
            return 0
        for i in items:
            a = i["action"]
            print("%s: %s %s" % (i["id"], a.get("action"), a.get("learning") or a.get("rule_id")))
        print("decide with: sisi approve ID --yes | --no")
        return 0
    pid, yes = argv[0], "--yes" in argv
    if not yes and "--no" not in argv:
        print("usage: sisi approve ID --yes | --no", file=sys.stderr)
        return 2
    try:
        print(apply_pending(pid, yes))
        return 0
    except CycleError as e:
        print("sisi approve: %s" % e, file=sys.stderr)
        return 2


HELP = """sisi cycle: turn proposed learnings into mechanisms. JSON cycle file:
  {"base": "<from `sisi cycle`>", "actions": [ ... ]}
promote actions, by mechanism_kind:
  command-check        {learning, cmd, expect?, before?, after?}  replayed; fail-before/pass-after = validated
  contract-requirement {learning, when, require_kind, max_rung?}
  rule-text            {learning, rule_id, rule_text}   (protected rules refused)
  library              {learning, library_kind: recipe|verifier, entry_text, entry_id?, replacing?}
  risk                 {learning, pattern, profile}     -> overlay/risk-adjustments.json
  routing              {learning, kind, difficulty?, prefer|avoid} -> overlay/routing-adjustments.json
  benchmark            {learning, name, case:{...}}     -> overlay/benchmarks/<name>.json
other actions: {action: revise|revert|reject, learning, why}; {action: disable-rule, rule_id}
Consequential actions (disable-rule, scope organization, every_project command) are stored
as pending for `sisi approve ID --yes|--no`. A cycle that ignores a flagged learning is refused.
"""


def cmd_cycle(args):
    if args and args[0] == "help":
        sys.stdout.write(HELP)
        return 0
    if args and args[0] == "apply" and len(args) > 1:
        try:
            cid, lines = apply_file(args[1])
        except (CycleError, OSError) as e:
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
            normal, pending = validate_doc(doc, L.load_learnings())
        except (CycleError, OSError, ValueError) as e:
            print("sisi cycle: %s" % e, file=sys.stderr)
            return 2
        print("valid: %d action(s) apply at once, %d wait for the owner" % (len(normal), len(pending)))
        return 0
    if args and args[0] == "revert":
        try:
            cid = revert_cycle(args[1] if len(args) > 1 else None)
        except (CycleError, OSError) as e:
            print("sisi cycle: %s" % e, file=sys.stderr)
            return 2
        print("%s reverted exactly in the user store" % cid)
        return 0
    if args and args[0] == "due":
        print(due_notice() or "no cycle is due")
        return 0
    if args:
        print("usage: sisi cycle [apply FILE|check FILE|revert [ID]|due|help]", file=sys.stderr)
        return 2
    sys.stdout.write(brief_text())
    return 0
