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

DELIVERY_STATUSES = ("delivered", "delivered-with-deferred", "deviation", "unverified", "abandoned")  # the five of SPEC 10.3


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


# ---------------------------------------------------------------- sources the record draws on

def _git_diff_text(project, base):
    import subprocess
    top = gitutil.root(project)
    if not top:
        return ""
    try:
        p = subprocess.run(["git", "diff", "--no-ext-diff", base or gitutil.head(top) or gitutil.EMPTY_TREE,
                            "--", ".", ":(exclude).sisi"], cwd=top, capture_output=True, timeout=10)
        return p.stdout.decode("utf-8", "replace")[:200000]
    except Exception:
        return ""


def risk_floor(c, project):
    """The risk floor from what changed since the unit started (committed or not), by the
    product's and the project's risk table. Unavailable outside a repository."""
    ch = _changed_artifacts(c, project)
    if ch is None:
        return unavailable(), []
    try:
        from . import risk
        profile, reasons = risk.assess(ch["files"], diff_text=_git_diff_text(project, c.get("base_head")),
                                       patterns=risk.load_patterns(project))
        return val(profile, "measured"), list(reasons)
    except Exception as e:
        store.log_error("unit-risk-floor", e)
        return unavailable(), []


def retro_findings(c, project):
    """The retro findings recorded for this unit (the learning store holds them)."""
    try:
        from . import learning
        return learning.findings_for_unit(project, c.get("id"))
    except Exception as e:
        store.log_error("unit-findings", e)
        return []


def learning_activity(c, project):
    """(ids of learnings this unit created, count of recurrences it recorded)."""
    try:
        from . import learning
        pk = learning.project_key(project)
        made, rec = [], 0
        for r in learning.load_learnings():
            if r.get("source_unit") == c.get("id") and r.get("origin_project") == pk:
                made.append(r.get("id"))
            for pv in r.get("provenance") or []:
                if isinstance(pv, dict) and pv.get("kind") == "recurrence" \
                        and pv.get("unit") == c.get("id") and pv.get("project") == pk:
                    rec += 1
        return made, rec
    except Exception as e:
        store.log_error("unit-learnings", e)
        return [], None


def delegations(project, t0, t1):
    """The ledger's attempts for this project inside the unit's window, from the orchestration
    record. The ledger names a project by its folder name. None when it cannot be read."""
    if t0 is None:
        return None
    try:
        from . import workers
        return workers.delegations_for_project(os.path.basename(project.rstrip(os.sep)), t0, t1)
    except Exception as e:
        store.log_error("unit-delegations", e)
        return None


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
    # named by role, never by path: the same policies hash the same in any clone or project
    for role, p in (("rulebook", rulebook), ("floors", paths.canon("floors.json")),
                    ("risk table", paths.canon("risk.json")),
                    ("project risk table", os.path.join(project, ".sisi", "risk.json"))):
        try:
            with open(p, "rb") as f:
                h.update(role.encode() + b"\0" + f.read() + b"\0")
        except OSError:
            h.update(role.encode() + b"\0missing\0")
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
    tel["cost"] = _estimated_cost(tel.get("tokens_by_model"))

    dg = delegations(project, t0, t1)
    if dg is None:
        for k in ("delegations", "overlapped_delegations", "worker_minutes", "time_in_delegations_s"):
            tel[k] = unavailable()
        rows = []
    else:
        rows = dg["delegations"]
        tel["delegations"] = val(dg["count"], "measured")
        if dg["count"]:
            tel["worker_minutes"] = val(round(dg["worker_minutes"], 1), "estimated")
            tel["time_in_delegations_s"] = val(round(dg["wall_minutes"] * 60, 1), "estimated")
            tel["overlapped_delegations"] = val(dg["overlapping_pairs"], "inferred")
        else:
            tel["worker_minutes"] = val(0, "measured")
            tel["time_in_delegations_s"] = val(0, "measured")
            tel["overlapped_delegations"] = val(0, "measured")

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
    learnings, recurrences = learning_activity(c, project)
    tel["retro_findings"] = val(len(findings), "measured")
    tel["learnings_created"] = val(len(learnings), "measured")
    tel["recurrences"] = val(recurrences, "measured") if recurrences is not None else unavailable()
    tel["_models"] = models
    tel["_delegation_rows"] = rows
    tel["_findings"] = findings
    tel["_learnings"] = learnings
    tel["_changed"] = changed
    return tel


def _estimated_cost(tokens_by_model):
    """Cost from the recorded price facts (`sisi workers fact`) and the measured tokens per model.
    Estimated when every model used has a recorded price; unavailable otherwise, and when
    there are no tokens to price. Never a guess at a missing price."""
    if not tokens_by_model or tokens_by_model.get("class") != "measured":
        return unavailable()
    try:
        from . import workers
        prices = workers.load_prices()
        total = 0.0
        for model, slot in tokens_by_model["value"].items():
            cost = workers.estimate_cost(slot.get("total"), workers._price_for(prices, None, model, model))
            if cost is None:
                return unavailable()
            total += cost
        return val(round(total, 6), "estimated")
    except Exception as e:
        store.log_error("unit-cost", e)
        return unavailable()


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

def latest_results(c, rows):
    """The standing result of every check and invariant of the contract, and of the floor and
    enforced items of the latest fast run. A check with no record gets a synthesized `not-run`:
    nothing that has no record of running is ever shown as passed. Each entry also says whether
    the check ever passed in this unit, ever failed, and was waived."""
    ids = {x["id"] for x in (c.get("checks") or []) + (c.get("invariants") or [])
           if isinstance(x, dict) and x.get("id")}
    last_fast = None
    for r in rows:
        if r.get("tier", "fast") == "fast" and r.get("run"):
            last_fast = r["run"]
    waived = {d.get("check") for d in (c.get("deviations") or []) if isinstance(d, dict) and d.get("check")}
    latest, ever_passed, ever_failed = {}, set(), set()
    for r in rows:
        cid = r.get("check")
        if not cid or r.get("item") not in ("check", "invariant", "floor", "enforced"):
            continue
        if r["item"] in ("floor", "enforced"):
            if r.get("run") != last_fast:
                continue
        elif cid not in ids:
            continue  # a check since removed from the contract no longer speaks for it
        st = scorecard.norm_status(r.get("status"))
        if st == "passed":
            ever_passed.add(cid)
        if st == "failed":
            ever_failed.add(cid)
        latest[cid] = {"item": r["item"], "id": cid, "status": st, "reason": r.get("reason"),
                       "duration_s": r.get("duration_s", 0.0), "mandatory": r.get("mandatory", True),
                       "tier": r.get("tier", "fast"), "ts": r.get("ts")}
    for x in (c.get("checks") or []) + (c.get("invariants") or []):
        if isinstance(x, dict) and x.get("id") and x["id"] not in latest:
            latest[x["id"]] = {"item": "check", "id": x["id"], "status": "not-run",
                               "reason": "needs human" if x.get("rung") in (5, 6) else "never run",
                               "duration_s": 0.0, "mandatory": x.get("mandatory", True),
                               "tier": x.get("tier", "fast"), "ts": None}
    out = []
    for cid, r in latest.items():
        r["ever_passed"] = cid in ever_passed
        r["seen_failing"] = cid in ever_failed
        r["waived"] = cid in waived
        out.append(r)
    return out


def _justified_by_selection(r):
    """A check kept back because the change did not touch what it watches, where files it
    watches exist. A watch that matches no file at all justifies nothing."""
    return r["status"] == "skipped" and str(r.get("reason") or "").startswith("not affected")


def never_run(latest):
    """Mandatory checks that never ran to a pass in this unit and that nothing justifies
    skipping. A unit with any of these cannot close as plainly delivered."""
    out = []
    for r in latest:
        if r["item"] not in ("check", "invariant") or not r.get("mandatory", True):
            continue
        if r["ever_passed"] or _justified_by_selection(r):
            continue
        out.append(r)
    return out


def decide_status(c, rows, abandon=None):
    """(delivery status or None, blocking, unrun). None with blocking results means the unit
    cannot close as delivered. A waiver or an abandonment is recorded as what it is."""
    from . import verify as V
    latest = latest_results(c, rows)
    block = V.blocking(latest)
    unrun = never_run(latest)
    if abandon is not None:
        return "abandoned", block, unrun
    if c.get("deviations"):
        return "deviation", block, unrun
    if block:
        released = any(r.get("check") == "gate" and r.get("status") == "unverified" for r in rows)
        return ("unverified" if released else None), block, unrun
    if any(r["status"] == "not-run" for r in latest) or unrun or C.deferred_checks(c):
        return "delivered-with-deferred", block, unrun
    return "delivered", block, unrun


def build_record(c, project, delivery_status, ended_epoch, abandon_reason=None, rows=None):
    t0 = harvest.epoch(c["started"]) if isinstance(c.get("started"), str) else None
    rows = _unit_results(c, project, c.get("started")) if rows is None else rows
    tel = build_telemetry(c, project, rows, t0, ended_epoch)
    models = tel.pop("_models")
    delegation_rows = tel.pop("_delegation_rows")
    changed = tel.pop("_changed")
    findings = tel.pop("_findings")
    learnings = tel.pop("_learnings")
    ended = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ended_epoch)) + "Z"
    latest = latest_results(c, rows)
    unrun = never_run(latest)
    floor, floor_reasons = risk_floor(c, project)
    declared = c.get("risk") or {}
    rec = {
        "id": c["id"], "parent": c.get("parent"),
        "goal": c.get("goal"), "scope": c.get("scope") or {"in": [], "out": []},
        "project": project,
        "requirements": c.get("requirements") or [],
        "checks": c.get("checks") or [], "invariants": c.get("invariants") or [],
        "risk": {"floor": floor, "floor_reasons": floor_reasons,
                 "declared": declared.get("profile"), "why": declared.get("why"),
                 "blast_radius": declared.get("blast_radius"), "rollback": declared.get("rollback")},
        "approach": c.get("approach"),
        "plan": c.get("plan") or [],
        "workers": delegation_rows,
        "models": models, "budgets": c.get("budgets"),
        "started": c.get("started"), "ended": ended, "closed_at": ended, "telemetry": tel,
        "start_commit": c.get("base_head"),
        "closing_commit": gitutil.head(project) if gitutil.root(project) else None,
        "changed_artifacts": changed if changed is not None else {"files": [], "lines": None},
        "verification": rows,
        "final_verification": latest,
        "deferred": c.get("deferred") or [],
        "deferred_checks": [r["id"] for r in latest if r["status"] == "not-run"
                            and str(r.get("reason") or "").startswith(("deferred", "needs human"))],
        "never_run_mandatory": [{"id": r["id"], "status": r["status"], "reason": r.get("reason")} for r in unrun],
        "limitations": c.get("limitations") or [], "open_risks": c.get("open_risks") or [],
        "deviations": c.get("deviations") or [], "pauses": c.get("pauses") or [],
        "delivery_status": delivery_status,
        "abandon_reason": abandon_reason,
        "policy_version": policy_version(project, c),
        "retro_findings": findings, "learning_ids": learnings,
        "contract": c,
    }
    rec["scorecard"] = scorecard.build_scorecard(c, rows, tel, delivery_status)
    return rec


def summary_line(rec):
    risk = rec.get("risk") or {}
    floor = (risk.get("floor") or {}).get("value") if isinstance(risk.get("floor"), dict) else risk.get("floor")
    return {"id": rec["id"], "parent": rec.get("parent"), "project": rec.get("project"),
            "goal": rec.get("goal"), "delivery_status": rec.get("delivery_status"),
            "risk": {"declared": risk.get("declared"), "floor": floor},
            "models": rec.get("models") or [], "policy_version": rec.get("policy_version"),
            "started": rec.get("started"), "ended": rec.get("ended"), "closed_at": rec.get("closed_at"),
            "scorecard": rec.get("scorecard")}


def _summary_exists(project, uid):
    return any(isinstance(r, dict) and r.get("id") == uid and r.get("project") == project
               for r in store.read("units"))


def archive_record(rec, project):
    """Write the archive so that it appears whole or not at all and is never replaced: the
    full text goes to a temporary file, which is then hard-linked into place (the link fails
    if the archive exists). Returns (path, created). An existing archive stays byte for byte."""
    p = archive_path(project, rec["id"])
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = "%s.tmp%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=2, default=str)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    try:
        try:
            os.link(tmp, p)
        except FileExistsError:
            return p, False
        except OSError:  # a filesystem without hard links
            try:
                fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            except FileExistsError:
                return p, False
            with os.fdopen(fd, "w", encoding="utf-8") as f, open(tmp, encoding="utf-8") as src:
                f.write(src.read())
        return p, True
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _capture_case(rec):
    """Offer the closed unit to the evaluation harness as a benchmark case. Never stops a close."""
    try:
        from . import evaluate
        view = dict(rec)
        view["fix_commit"] = rec.get("closing_commit")
        view["request"] = rec.get("goal")
        evaluate.capture_case(view)
    except Exception as e:
        store.log_error("unit-capture-case", e)


def close_unit(c, contract_path, project, abandon=None, now=None):
    """Archive the open unit and mark the contract closed. Returns (record_or_None, message, ok).
    Refuses with nothing written when verification blocks and no deviation, gate release or
    abandonment accounts for it. Safe to repeat after a crash at any step: an archive that
    exists is kept as it stands and the remaining steps are completed."""
    ended_epoch = time.time() if now is None else now
    rows = _unit_results(c, project, c.get("started"))  # under the id the results were recorded with
    path = archive_path(project, c["id"])
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                old = json.load(f)
        except (OSError, ValueError):
            old = None
        if is_closed(c):
            return None, "unit %s is already closed (%s); nothing changed" % (c["id"], path), True
        if isinstance(old, dict) and old.get("started") == c.get("started") and old.get("project") == project:
            rec, created = old, False  # a crash after archiving: complete the close from it
        else:
            c["id"] = fresh_id(c["id"], project)  # another unit owns this id: never overwrite it
            path = archive_path(project, c["id"])
            rec = None
    else:
        rec = None
    if rec is None:
        status, block, _ = decide_status(c, rows, abandon)
        if status is None:
            bad = ", ".join("%s (%s%s)" % (r["id"], r["status"], ": " + r["reason"] if r.get("reason") else "")
                            for r in block)
            return None, ("sisi: unit %s cannot close as delivered: %s. Fix and re-run `sisi verify`, "
                          "record a deviation with `sisi contract waive \"<reason>\"`, or close it with "
                          "`sisi unit close --abandon \"<reason>\"`." % (c["id"], bad)), False
        rec = build_record(c, project, status, ended_epoch, abandon_reason=abandon, rows=rows)
        _, created = archive_record(rec, project)
        if created:
            _capture_case(rec)
    if not _summary_exists(project, rec["id"]):
        store.append("units", summary_line(rec))
    c["status"] = "closed"
    c["ended"] = rec.get("ended")
    c["delivery_status"] = rec.get("delivery_status")
    for pz in c.get("pauses") or []:
        if isinstance(pz, dict) and not pz.get("until"):
            pz["until"] = rec.get("ended")
    C.save(contract_path, c)
    return rec, "closed unit %s (%s): %s" % (rec["id"], rec.get("delivery_status"), path), True


def resume(c, contract_path):
    """End a recorded wait: the unit is open again and the wait's length is recorded."""
    if c.get("status") != "paused":
        return False
    for pz in c.get("pauses") or []:
        if isinstance(pz, dict) and not pz.get("until"):
            pz["until"] = store.now()
    c["status"] = "open"
    c.pop("pause_fp", None)
    C.save(contract_path, c)
    return True


def summary_for_retro(project):
    """What `sisi retro` prints: the open unit's scorecard so far and what stands out in it."""
    p = os.path.join(project, C.REL)
    try:
        c = C.load(p)
    except (OSError, ValueError):
        return ""
    if not isinstance(c, dict) or not c.get("id"):
        return ""
    now = time.time()
    rows = _unit_results(c, project, c.get("started"))
    latest = latest_results(c, rows)
    tel = build_telemetry(c, project, rows, harvest.epoch(c["started"]) if isinstance(c.get("started"), str) else None, now)
    for k in [k for k in tel if k.startswith("_")]:
        tel.pop(k)
    card = scorecard.build_scorecard(c, rows, tel, "open")
    lines = ["unit %s (%s): %s" % (c["id"], c.get("status", "open"), c.get("goal") or ""), ""]
    for dim, vals in card.items():
        lines.append(scorecard.format_dimension(dim, vals))
    out = []
    seen = [r["id"] for r in latest if r["seen_failing"] and r["status"] == "passed"]
    if seen:
        out.append("failed and then passed (the evidence is real): %s" % ", ".join(seen))
    failing = [r["id"] for r in latest if r["status"] == "failed"]
    if failing:
        out.append("still failing: %s" % ", ".join(failing))
    nr = never_run(latest)
    if nr:
        out.append("mandatory checks that never ran to a pass: %s" % ", ".join(r["id"] for r in nr))
    if c.get("deviations"):
        out.append("a deviation was recorded: the unit cannot read as delivered")
    hc = (tel.get("human_corrections") or {}).get("value")
    if hc:
        out.append("%s human correction(s) inferred from the transcript" % hc)
    sb = (tel.get("send_backs") or {}).get("value")
    if sb:
        out.append("the gate sent the agent back %s time(s)" % sb)
    unav = sorted(k for k, v in tel.items() if isinstance(v, dict) and v.get("class") == "unavailable")
    if unav:
        out.append("not measurable here (unavailable): %s" % ", ".join(unav))
    lines += ["", "what stands out:"] + (["  - " + x for x in out] or ["  nothing in the record stands out"])
    lines += ["", "record each finding with `sisi retro --finding ... --cause ... --impact ... --disposition ...`; "
                  "then `sisi unit close` archives the unit."]
    return "\n".join(lines) + "\n"


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
        c["pause_fp"] = gitutil.fingerprint(project)  # a change to the tree ends the wait (see gate)
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
