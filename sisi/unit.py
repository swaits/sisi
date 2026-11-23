"""The durable work-unit record: close, pause, show, list.

The open unit is `.sisi/contract.json`. Closing archives the full record to
`.sisi/units/<id>.json` in the project (exclusive create: never overwritten) and appends
one summary line to the user store's `units.jsonl`, then marks the contract closed so a
new unit may replace it. Re-running close after a crash at any step converges without
duplicating or losing a record.
"""
import hashlib, json, os, time

from . import contract as C, gitutil, harvest, paths, scorecard, store
from .scorecard import unavailable, val

DELIVERY_STATUSES = ("delivered", "delivered-with-deferred", "deviation", "unverified", "abandoned")


def is_closed(c):
    return isinstance(c, dict) and c.get("status") == "closed"


def archive_path(project, uid):
    return os.path.join(project, ".sisi", "units", "%s.json" % store.safe_id(uid))


def list_archives(project):
    d = os.path.join(project, ".sisi", "units")
    out = []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for n in names:
        if n.endswith(".json"):
            try:
                with open(os.path.join(d, n), encoding="utf-8") as f:
                    out.append(json.load(f))
            except (OSError, ValueError):
                pass
    return out


def fresh_id(base, project):
    """A unit id not already used by an archived or summarised unit in this project."""
    used = {r.get("id") for r in list_archives(project)}
    used |= {r.get("id") for r in store.read("units") if isinstance(r, dict) and r.get("project") == project}
    if base not in used:
        return base
    n = 2
    while "%s-%d" % (base, n) in used:
        n += 1
    return "%s-%d" % (base, n)


# ---------------------------------------------------------------- later-wave hooks
# Each of these is the one small function a later wave calls or replaces. Until then the
# record carries an honest empty or unavailable value for what they will supply.

def risk_floor(c, project):
    """Risk-profile floor from changed paths. Later wave (risk profiles) computes it; a
    contract already carrying `risk_floor` has that value taken as measured."""
    if isinstance(c, dict) and c.get("risk_floor"):
        return val(c["risk_floor"], "measured")
    return unavailable()


def retro_findings(c, project):
    """Retro findings for this unit. Later wave (learning loop) fills these in."""
    return list(c.get("retro_findings") or []) if isinstance(c, dict) else []


def learning_ids(c, project):
    """Learning records this unit created. Later wave (learning loop) fills these in."""
    return list(c.get("learning_ids") or []) if isinstance(c, dict) else []


def delegations(c, project, t0, t1):
    """Delegation ledger rows (user store `delegations.jsonl`) inside the unit's window.
    Rows naming another project are dropped; rows naming none are taken by time alone.
    Returns (rows, found_the_ledger)."""
    p = paths.data_file("delegations.jsonl")
    if not os.path.exists(p):
        return [], False
    rows = []
    try:
        with open(p, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return [], False
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not isinstance(r, dict):
            continue
        rp = r.get("project") or r.get("cwd")
        if rp and os.path.realpath(str(rp)) != os.path.realpath(project) \
                and not str(rp).startswith(project + os.sep):
            continue
        t = _row_epoch(r)
        if t is not None and t0 is not None and not (t0 <= t <= (t1 or t)):
            continue
        rows.append(r)
    return rows, True


def _row_epoch(r):
    for k in ("ts", "t", "started", "ended", "time"):
        v = r.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
        if isinstance(v, str):
            t = harvest.epoch(v)
            if t is not None:
                return t
    return None


def policy_version(project, c):
    """Hash of the policies in force: the effective rulebook, the floors and risk tables,
    the enforced checks, and the gate/verify config."""
    h = hashlib.sha256()
    rulebook = paths.generated()
    if not os.path.exists(rulebook):
        rulebook = paths.canon("core.md")
    for p in (rulebook, paths.canon("floors.json"), paths.canon("risk.json"),
              os.path.join(project, ".sisi", "risk.json")):
        try:
            with open(p, "rb") as f:
                h.update(p.encode() + b"\0" + f.read() + b"\0")
        except OSError:
            h.update(p.encode() + b"\0missing\0")
    try:
        from . import cycle
        h.update(json.dumps(cycle.load_enforced(), sort_keys=True, default=str).encode())
    except Exception:
        h.update(b"\0enforced-unavailable\0")
    cfg = store.config()
    h.update(json.dumps({k: cfg.get(k) for k in ("gate", "verify")}, sort_keys=True, default=str).encode())
    return h.hexdigest()


# ---------------------------------------------------------------- telemetry

def _unit_results(c, project, t0_iso):
    rows = []
    for r in store.read("results"):
        if not isinstance(r, dict) or r.get("contract") != c.get("id") or r.get("project") != project:
            continue
        if t0_iso and isinstance(r.get("ts"), str) and r["ts"] < t0_iso:
            continue
        rows.append(r)
    return rows


def _transcript_stats(project, t0, t1):
    """Aggregated transcript stats from session records for this project in the window.
    Returns None when no readable transcript was found at all."""
    cands = []
    sid = store.session_id()
    sids = [sid] if sid else []
    d = os.path.join(paths.state(), "sessions")
    try:
        names = [n for n in os.listdir(d) if n.endswith(".json")]
    except OSError:
        names = []
    # newest first, bounded: session files far outside the window cannot belong to the unit
    entries = []
    for n in names:
        try:
            entries.append((os.path.getmtime(os.path.join(d, n)), n))
        except OSError:
            pass
    entries.sort(reverse=True)
    names = [n for m, n in entries if t1 is None or m >= t1 - 7 * 86400][:200]
    for n in names:
        rec = store.load_session(n[:-5])
        tp, cwd = rec.get("transcript_path"), rec.get("cwd")
        if isinstance(tp, str) and isinstance(cwd, str) and (cwd == project or cwd.startswith(project + os.sep)):
            cands.append(tp)
    if sid:
        tp = store.load_session(sid).get("transcript_path")
        if isinstance(tp, str) and tp not in cands:
            cands.append(tp)
    agg = None
    for tp in cands:
        st = harvest.transcript_stats(tp, t0, t1)
        if st is None:
            continue
        if agg is None:
            agg = {"usage": None, "human_messages": 0, "corrections": 0, "question_dialogs": 0, "subagent_runs": 0}
        for k in ("human_messages", "corrections", "question_dialogs", "subagent_runs"):
            agg[k] += st[k]
        if st["usage"]:
            if agg["usage"] is None:
                agg["usage"] = {"by_category": {}, "by_model": {}}
            for cat, v in st["usage"]["by_category"].items():
                if cat != "total":
                    agg["usage"]["by_category"][cat] = agg["usage"]["by_category"].get(cat, 0) + v
            for model, slot in st["usage"]["by_model"].items():
                dst = agg["usage"]["by_model"].setdefault(model, {})
                for cat, v in slot.items():
                    if cat != "total":
                        dst[cat] = dst.get(cat, 0) + v
    if agg is not None and agg["usage"]:
        agg["usage"]["by_category"]["total"] = sum(agg["usage"]["by_category"].values())
        for slot in agg["usage"]["by_model"].values():
            slot["total"] = sum(slot.values())
    return agg


def build_telemetry(c, project, results, t0, t1):
    """Every value classed. Sources: deliveries, results, pauses on the contract, the
    host transcript where a session record names one, git, and the delegation ledger."""
    tel = {}
    tel["time_to_validated_completion_s"] = val(round(t1 - t0, 1), "measured") if t0 is not None else unavailable()
    if results:
        tel["time_in_checks_s"] = val(round(sum(float(r["duration_s"]) for r in results
                                                if isinstance(r.get("duration_s"), (int, float))), 3), "measured")
    else:
        tel["time_in_checks_s"] = unavailable()
    if isinstance(c.get("pauses"), list):
        waits = 0.0
        for p in c["pauses"]:
            if not isinstance(p, dict):
                continue
            a = harvest.epoch(p["since"]) if isinstance(p.get("since"), str) else None
            b = harvest.epoch(p["until"]) if isinstance(p.get("until"), str) else t1
            if a is not None and b is not None and b > a:
                waits += b - a
        tel["time_in_waits_s"] = val(round(waits, 1), "measured")
    else:
        tel["time_in_waits_s"] = unavailable()

    deliveries = []
    for r in store.read("deliveries"):
        if not isinstance(r, dict):
            continue
        end = harvest.epoch(r["end"]) if isinstance(r.get("end"), str) else None
        if end is not None and t0 is not None and t0 <= end <= t1 and \
                (r.get("project") in (project, None) or str(r.get("project", "")).startswith(project)):
            deliveries.append((end, r))
    if deliveries:
        tel["time_to_first_useful_result_s"] = val(round(min(e for e, _ in deliveries) - t0, 1), "measured")
        tel["send_backs"] = val(sum(int(r.get("send_backs", 0)) for _, r in deliveries), "measured")
    else:
        first_pass = None
        runs = {}
        for r in results:
            runs.setdefault(r.get("run"), []).append(r)
        for run_rows in runs.values():
            sts = [scorecard.norm_status(r.get("status")) for r in run_rows]
            if any(s == "passed" for s in sts) and all(s in ("passed", "skipped", "not-applicable") for s in sts):
                ts = harvest.epoch(run_rows[0]["ts"]) if isinstance(run_rows[0].get("ts"), str) else None
                if ts is not None and t0 is not None:
                    first_pass = ts if first_pass is None else min(first_pass, ts)
        tel["time_to_first_useful_result_s"] = val(round(first_pass - t0, 1), "inferred") if first_pass else unavailable()
        tel["send_backs"] = unavailable()

    stats = _transcript_stats(project, t0, t1)
    if stats is None:
        for k in ("human_messages", "question_dialogs", "human_corrections",
                  "tokens_by_category", "tokens_by_model"):
            tel[k] = unavailable()
        models = []
    else:
        tel["human_messages"] = val(stats["human_messages"], "measured")
        tel["question_dialogs"] = val(stats["question_dialogs"], "measured")
        tel["human_corrections"] = val(stats["corrections"], "inferred")
        if stats["usage"]:
            tel["tokens_by_category"] = val(stats["usage"]["by_category"], "measured")
            tel["tokens_by_model"] = val(stats["usage"]["by_model"], "measured")
            models = sorted(stats["usage"]["by_model"])
        else:  # the transcript has no usage numbers: tokens are unavailable, never zero
            tel["tokens_by_category"] = unavailable()
            tel["tokens_by_model"] = unavailable()
            models = []
    tel["cost"] = unavailable()  # no price facts live here; never estimated from thin air

    rows, have_ledger = delegations(c, project, t0, t1)
    if not have_ledger:
        for k in ("delegations", "overlapped_delegations", "worker_minutes", "time_in_delegations_s"):
            tel[k] = unavailable()
    else:
        tel["delegations"] = val(len(rows), "inferred")
        mins = [float(r["minutes"]) for r in rows if isinstance(r.get("minutes"), (int, float))]
        if mins:
            tel["worker_minutes"] = val(round(sum(mins), 1), "estimated")
            tel["time_in_delegations_s"] = val(round(sum(mins) * 60, 1), "estimated")
            ivs = [(_row_epoch(r), float(r["minutes"]) * 60) for r in rows
                   if _row_epoch(r) is not None and isinstance(r.get("minutes"), (int, float))]
            over = sum(1 for i in range(len(ivs)) for j in range(i + 1, len(ivs))
                       if ivs[i][0] < ivs[j][0] + ivs[j][1] and ivs[j][0] < ivs[i][0] + ivs[i][1])
            tel["overlapped_delegations"] = val(over, "inferred")
        else:
            tel["worker_minutes"] = unavailable()
            tel["time_in_delegations_s"] = unavailable()
            tel["overlapped_delegations"] = unavailable()

    changed = _changed_artifacts(c, project)
    tel["files_changed"] = val(len(changed["files"]), "measured") if changed else unavailable()
    tel["lines_changed"] = val(changed["lines"], "measured") if changed else unavailable()
    if changed:
        tests = [f for f in changed["files"] if _is_test(f)]
        code = [f for f in changed["files"] if not _is_test(f)]
        tel["tests_changed_with_code"] = val(bool(tests and code), "inferred")
        tel["public_surface_touched"] = val(any(_is_public(f) for f in changed["files"]), "inferred")
    else:
        tel["tests_changed_with_code"] = unavailable()
        tel["public_surface_touched"] = unavailable()

    findings = retro_findings(c, project)
    learnings = learning_ids(c, project)
    tel["retro_findings"] = val(len(findings), "measured")
    tel["learnings_created"] = val(len(learnings), "measured")
    tel["recurrences"] = unavailable()
    tel["_models"] = models
    tel["_delegation_rows"] = rows if have_ledger else []
    tel["_changed"] = changed
    return tel


def _is_test(f):
    base = os.path.basename(f)
    return base.startswith(("test_", "test-")) or base.endswith(("_test.py", "_test.go", ".test.js", ".spec.js")) \
        or "/tests/" in "/" + f


def _is_public(f):
    return os.path.basename(f) in ("__init__.py",) or f.endswith(".pyi") or f.startswith(("include/", "public/"))


def _changed_artifacts(c, project):
    if not gitutil.root(project):
        return None
    try:
        return gitutil.measure(project, c.get("base_head"))
    except Exception:
        return None


# ---------------------------------------------------------------- the record

def _latest_results(c, rows):
    """Latest recorded result per check, plus a synthesized not-run for checks never run.
    Synthesis is only ever not-run: a check with no record did not pass."""
    from . import verify as V
    latest = {}
    for r in rows:
        if r.get("item") in ("check", "invariant", "floor", "enforced") and r.get("check"):
            latest[r["check"]] = {"item": r.get("item"), "id": r["check"], "status": scorecard.norm_status(r.get("status")),
                                  "reason": r.get("reason"), "duration_s": r.get("duration_s", 0.0),
                                  "mandatory": r.get("mandatory", True), "seen_failing": r.get("seen_failing"),
                                  "tier": r.get("tier", "fast"), "tail": ""}
    for x in (c.get("checks") or []) + (c.get("invariants") or []):
        if isinstance(x, dict) and x.get("id") and x["id"] not in latest:
            latest[x["id"]] = {"item": "check", "id": x["id"], "status": "not-run",
                               "reason": "needs human" if x.get("rung") in (5, 6) else "never run",
                               "duration_s": 0.0, "mandatory": x.get("mandatory", True),
                               "seen_failing": False, "tier": x.get("tier", "fast"), "tail": ""}
    return list(latest.values())


def build_record(c, project, delivery_status, ended_epoch, abandon_reason=None):
    t0 = harvest.epoch(c["started"]) if isinstance(c.get("started"), str) else None
    rows = _unit_results(c, project, c.get("started"))
    tel = build_telemetry(c, project, rows, t0, ended_epoch)
    models = tel.pop("_models")
    delegation_rows = tel.pop("_delegation_rows")
    changed = tel.pop("_changed")
    ended = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ended_epoch)) + "Z"
    latest = _latest_results(c, rows)
    deferred_ids = [r["id"] for r in latest if r["status"] == "not-run"
                    and str(r.get("reason") or "").startswith(("deferred", "needs human"))]
    rec = {
        "id": c["id"], "parent": c.get("parent"),
        "goal": c.get("goal"), "scope": c.get("scope") or {"in": [], "out": []},
        "project": project,
        "requirements": c.get("requirements") or [],
        "checks": c.get("checks") or [], "invariants": c.get("invariants") or [],
        "risk": {"floor": risk_floor(c, project),
                 "declared": (c.get("risk") or {}).get("profile"),
                 "why": (c.get("risk") or {}).get("why"),
                 "blast_radius": (c.get("risk") or {}).get("blast_radius"),
                 "rollback": (c.get("risk") or {}).get("rollback")},
        "plan": c.get("plan") or [], "dependencies": c.get("dependencies") or [],
        "workers": delegation_rows,
        "models": models, "budgets": c.get("budgets"),
        "started": c.get("started"), "ended": ended, "telemetry": tel,
        "changed_artifacts": changed if changed is not None else {"files": [], "lines": None},
        "summary": c.get("summary"),
        "verification": rows,
        "deferred": c.get("deferred") or [], "deferred_checks": deferred_ids,
        "limitations": c.get("limitations") or [], "open_risks": c.get("open_risks") or [],
        "deviations": c.get("deviations") or [], "pauses": c.get("pauses") or [],
        "delivery_status": delivery_status,
        "abandon_reason": abandon_reason,
        "policy_version": policy_version(project, c),
        "retro_findings": retro_findings(c, project),
        "learning_ids": learning_ids(c, project),
        "contract": c,
    }
    rec["scorecard"] = scorecard.build_scorecard(c, rows, tel, delivery_status)
    return rec


def summary_line(rec):
    return {"id": rec["id"], "parent": rec.get("parent"), "project": rec.get("project"),
            "goal": rec.get("goal"), "delivery_status": rec.get("delivery_status"),
            "risk": {"declared": (rec.get("risk") or {}).get("declared"),
                     "floor": (rec.get("risk") or {}).get("floor")},
            "models": rec.get("models") or [], "policy_version": rec.get("policy_version"),
            "started": rec.get("started"), "ended": rec.get("ended"), "scorecard": rec.get("scorecard")}


def _summary_exists(project, uid):
    return any(isinstance(r, dict) and r.get("id") == uid and r.get("project") == project
               for r in store.read("units"))


def archive_record(rec, project):
    """Write the archive with exclusive create. Returns (path, created). An existing
    archive is left byte-for-byte intact (created=False): records are never overwritten."""
    p = archive_path(project, rec["id"])
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return p, False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=2)
        f.write("\n")
    return p, True


def close_unit(c, contract_path, project, abandon=None, now=None):
    """Archive the open unit. Returns (record_or_None, message, ok).
    Refuses with nothing written when verification blocks and no deviation, deferral
    outcome, gate release or abandonment accounts for it."""
    from . import verify as V
    ended_epoch = time.time() if now is None else now
    path = archive_path(project, c["id"])
    already = os.path.exists(path)
    if already and is_closed(c):
        return None, "unit %s is already closed (%s); nothing changed" % (c["id"], path), True
    rows = _unit_results(c, project, c.get("started"))
    latest = _latest_results(c, rows)
    gate_released = any(r.get("check") == "gate" and r.get("status") == "unverified" for r in rows)
    if abandon is not None:
        status = "abandoned"
    elif c.get("deviations"):
        status = "deviation"
    elif V.blocking(latest):
        if gate_released:
            status = "unverified"
        else:
            bad = ", ".join("%s (%s%s)" % (r["id"], r["status"], ": " + r["reason"] if r.get("reason") else "")
                            for r in V.blocking(latest))
            return None, ("sisi: unit %s cannot close as delivered: %s. Fix and re-run `sisi verify`, "
                          "record a deviation with `sisi contract waive \"<reason>\"`, or close it with "
                          "`sisi unit close --abandon \"<reason>\"`." % (c["id"], bad)), False
    elif any(r["status"] == "not-run" for r in latest) or C.deferred_checks(c):
        status = "delivered-with-deferred"
    else:
        status = "delivered"
    rec = build_record(c, project, status, ended_epoch, abandon_reason=abandon)
    _, created = archive_record(rec, project)
    if not created:
        # a crash after archiving: keep the archived record exactly as it stands
        try:
            with open(path, encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            pass
    if not _summary_exists(project, rec["id"]):
        store.append("units", summary_line(rec))
    c["status"] = "closed"
    c["ended"] = rec.get("ended")
    c["delivery_status"] = rec.get("delivery_status")
    try:
        from . import verify as _V
        c["closed_fp"] = _V.tree_fp(project, contract_path)
    except Exception:
        c["closed_fp"] = None
    for p in c.get("pauses") or []:
        if isinstance(p, dict) and not p.get("until"):
            p["until"] = rec.get("ended")
    C.save(contract_path, c)
    return rec, "closed unit %s (%s): %s" % (rec["id"], rec.get("delivery_status"), path), True


# ---------------------------------------------------------------- command

def _open_contract(cwd, out):
    p = C.find(cwd)
    if not p:
        out("sisi: no contract found (run `sisi contract init`)")
        return None, None, None
    try:
        c = C.load(p)
    except (OSError, ValueError) as e:
        out("sisi: cannot read %s: %s" % (p, e))
        return None, None, None
    return c, p, C.project_dir(p)


def cmd_unit(args, cwd=None, out=print):
    cwd = cwd or os.getcwd()
    sub = args[0] if args else ""
    if sub == "close":
        abandon = None
        rest = list(args[1:])
        if "--abandon" in rest:
            i = rest.index("--abandon")
            abandon = rest[i + 1] if i + 1 < len(rest) else ""
            if not str(abandon).strip():
                out('usage: sisi unit close [--abandon "<reason>"]')
                return 1
        c, p, project = _open_contract(cwd, out)
        if c is None:
            return 2
        errs = C.validate(c)
        if errs and abandon is None:
            out("sisi: invalid contract %s; fix it, or close with --abandon" % p)
            for e in errs:
                out("  - " + e)
            return 1
        rec, msg, ok = close_unit(c, p, project, abandon=abandon)
        out(msg)
        if rec is not None:
            out("delivery status: %s" % rec.get("delivery_status"))
            if rec.get("delivery_status") == "deviation":
                out("a deviation was recorded; the completion report to the human must say so")
            if rec.get("deferred_checks"):
                out("deferred checks: %s" % ", ".join(rec["deferred_checks"]))
        return 0 if ok else 1
    if sub == "pause":
        what = " ".join(args[1:]).strip()
        if not what:
            out('usage: sisi unit pause "<what it waits for>"')
            return 1
        c, p, project = _open_contract(cwd, out)
        if c is None:
            return 2
        if is_closed(c):
            out("sisi: unit %s is closed; start a new one with `sisi contract init`" % c.get("id"))
            return 1
        pauses = c.setdefault("pauses", [])
        open_pause = next((x for x in pauses if isinstance(x, dict) and not x.get("until")), None)
        if open_pause is not None:
            open_pause["what"] = what
        else:
            pauses.append({"what": what, "since": store.now(), "until": None})
        c["status"] = "paused"
        C.save(p, c)
        out("unit %s paused: %s" % (c.get("id"), what))
        return 0
    if sub == "show":
        uid = args[1] if len(args) > 1 else None
        if uid is None:
            c, p, project = _open_contract(cwd, out)
            if c is None:
                return 2
            out(json.dumps(c, indent=2))
            return 0
        p = C.find(cwd)
        project = C.project_dir(p) if p else None
        if project:
            for rec in list_archives(project):
                if rec.get("id") == uid:
                    out(json.dumps(rec, indent=2))
                    return 0
        for r in store.read("units"):
            if isinstance(r, dict) and r.get("id") == uid:
                ap = archive_path(r.get("project") or project or cwd, uid)
                if os.path.exists(ap):
                    with open(ap, encoding="utf-8") as f:
                        out(json.dumps(json.load(f), indent=2))
                else:
                    out(json.dumps(r, indent=2))
                return 0
        out("sisi: no unit record with id %r" % uid)
        return 1
    if sub == "list":
        p = C.find(cwd)
        project = C.project_dir(p) if p else (gitutil.root(cwd) or cwd)
        c = None
        if p:
            try:
                c = C.load(p)
            except (OSError, ValueError):
                c = None
        rows = []
        if project:
            for rec in list_archives(project):
                rows.append((rec.get("ended") or "", rec.get("id"), rec.get("delivery_status"), rec.get("goal") or ""))
        if c is not None and not is_closed(c):
            out("open     %-24s %s" % (c.get("id"), c.get("goal") or ""))
        for ended, uid, status, goal in sorted(rows, reverse=True):
            out("%-8s %-24s %-24s %s" % (str(ended)[:10], uid, status, goal))
        if c is None and not rows:
            out("no units in this project yet")
        return 0
    out("usage: sisi unit close [--abandon \"<reason>\"] | pause \"<what it waits for>\" | show [ID] | list")
    return 1
