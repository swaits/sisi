"""The per-unit scorecard (eight dimensions, every value classed) and `sisi status`.

Every scorecard value is {"value": ..., "class": measured|inferred|estimated|unavailable}.
Missing data is unavailable with value None: never zero, never good. No single score is
ever computed or printed. Check statistics and escape candidates (work declared verified
that then turned out wrong) live here too: they feed the correctness and intent dimensions.
"""
import json, os, re, time

from . import harvest, store

CLASSES = ("measured", "inferred", "estimated", "unavailable")


def val(v, cls):
    assert cls in CLASSES
    return {"value": v, "class": cls}


def unavailable():
    return {"value": None, "class": "unavailable"}


# ---------------------------------------------------------------- check statistics

MANY_RUNS = 10
# rows written by earlier versions: neither of these ever meant a pass
_LEGACY = {"timeout": "not-run", "awaiting-human": "not-run"}


def norm_status(s):
    return _LEGACY.get(s, s)


def check_stats(results):
    by, byv = {}, {}
    for r in results:
        if not isinstance(r, dict) or not r.get("check") or r.get("check") == "gate":
            continue
        keys = [("check", r["check"], by)]
        if r.get("verifier"):
            keys.append(("verifier", r["verifier"], byv))
        for _, k, d in keys:
            s = d.setdefault(k, {"runs": 0, "failures": 0, "not_run": 0,
                                 "total_s": 0.0, "timed_runs": 0})
            s["runs"] += 1
            if isinstance(r.get("duration_s"), (int, float)) and not isinstance(r.get("duration_s"), bool):
                s["total_s"] += r["duration_s"]
                s["timed_runs"] += 1
                s["tier"] = r.get("tier", "fast")
            st = norm_status(r.get("status"))
            if st == "failed":
                s["failures"] += 1
            elif st == "not-run":
                s["not_run"] += 1
    def fin(d):
        out = []
        for k, s in sorted(d.items()):
            s = dict(s, id=k)
            s["never_seen_failing"] = s["runs"] >= MANY_RUNS and s["failures"] == 0 and s["not_run"] == 0
            out.append(s)
        return out
    return {"checks": fin(by), "verifiers": fin(byv)}


# ---------------------------------------------------------------- escape candidates

WEEK_S = 7 * 86400
_FIXLIKE = re.compile(r"\b(fix|bug|broken|wrong|regress|revert|fails?|failing|doesn'?t work|not working|error|crash)", re.I)


def passed_runs(results):
    """[{ts, t, project, contract, session, run}] for runs with a real pass and no failure.
    A run of only skipped/not-run checks is not a pass: nothing that did not run passed."""
    groups = {}
    for r in results:
        if not isinstance(r, dict) or r.get("check") == "gate":
            continue
        key = r.get("run") or "%s|%s|%s" % (r.get("ts"), r.get("contract"), r.get("project"))
        groups.setdefault(key, []).append(r)
    out = []
    for key, rs in groups.items():
        sts = [norm_status(x.get("status")) for x in rs]
        if any(s == "passed" for s in sts) and all(s in ("passed", "skipped", "not-applicable") for s in sts):
            t = harvest.epoch(rs[0].get("ts") or "")
            if t is not None:
                out.append({"ts": rs[0]["ts"], "t": t, "project": rs[0].get("project"), "contract": rs[0].get("contract"),
                            "session": rs[0].get("session"), "run": key})
    return sorted(out, key=lambda x: x["t"])


def _inside(path, parent):
    if not path or not parent:
        return False
    p, q = path.rstrip("/"), parent.rstrip("/")
    return p == q or p.startswith(q + "/") or q.startswith(p + "/")


def attribute(run, sessions):
    if run["session"]:
        hit = [s for s in sessions if s["id"] == run["session"]]
        if hit:
            return hit, False
    hit = [s for s in sessions if s["t0"] is not None and s["t0"] <= run["t"] <= (s["t1"] or s["t0"]) + 60
           and (_inside(s["cwd"], run["project"]) or _inside(s["repo_root"], run["project"]))]
    return hit, len(hit) > 1


def escape_candidates(con, results=None):
    results = store.read("results") if results is None else results
    sessions = [dict(r) for r in con.execute(
        "SELECT s.id, s.cwd, s.t0, s.t1, s.first_message, s.machine, g.repo_root, g.files, g.start_kind "
        "FROM sessions s LEFT JOIN groundtruth g ON g.session_id=s.id WHERE s.kind='main'")]
    out = []
    for run in passed_runs(results):
        hit, ambiguous = attribute(run, sessions)
        for s in hit:
            later = con.execute("SELECT idx, ts, t FROM user_msgs WHERE session_id=? AND correction=1 AND t>? ORDER BY t",
                                (s["id"], run["t"])).fetchall()
            for m in later[:3]:
                out.append({"kind": "contract-then-correction", "session": s["id"], "run": run["run"], "contract": run["contract"],
                            "passed_at": run["ts"], "evidence": {"user_msg_idx": m["idx"], "at": m["ts"]}, "ambiguous": ambiguous})
            files = set(json.loads(s["files"] or "[]"))
            if files and s["repo_root"]:
                for o in sessions:
                    if o["id"] == s["id"] or o["repo_root"] != s["repo_root"] or o["machine"] or o["t0"] is None:
                        continue
                    if not (run["t"] < o["t0"] <= run["t"] + WEEK_S):
                        continue
                    common = files & set(json.loads(o["files"] or "[]"))
                    if common and _FIXLIKE.search((o["first_message"] or "")[:1500]):
                        out.append({"kind": "contract-then-fix-session", "session": s["id"], "run": run["run"],
                                    "contract": run["contract"], "passed_at": run["ts"],
                                    "evidence": {"later_session": o["id"], "common_files": sorted(common)[:10]},
                                    "ambiguous": ambiguous})
    for r in con.execute("SELECT m.session_id, m.idx, m.ts FROM user_msgs m WHERE m.correction=1 AND m.after_completion=1 ORDER BY m.t"):
        out.append({"kind": "premature-done", "session": r["session_id"], "evidence": {"user_msg_idx": r["idx"], "at": r["ts"]},
                    "ambiguous": False})
    return out


# ---------------------------------------------------------------- the eight dimensions

def _latest_by_check(results):
    out = {}
    for r in results:
        if isinstance(r, dict) and (r.get("check") or r.get("id")):
            out[r.get("check") or r.get("id")] = r
    return out


def build_scorecard(c, results, telemetry, delivery_status):
    """The scorecard stored in the unit record. `results` are the unit's recorded result rows
    (any dicts with check/status/duration_s, store rows or fresh verify results)."""
    latest = _latest_by_check(results)
    by_status = {}
    for r in latest.values():
        by_status[norm_status(r.get("status"))] = by_status.get(norm_status(r.get("status")), 0) + 1
    items = {x.get("id"): x for x in (c.get("checks") or []) + (c.get("invariants") or []) if isinstance(x, dict)}

    reqs = [r for r in (c.get("requirements") or []) if isinstance(r, dict)]
    with_check = [r for r in reqs if r.get("check")]
    passing = sum(1 for r in with_check
                  if norm_status((latest.get(r["check"]) or {}).get("status")) == "passed")
    first_ts = min((r["ts"] for r in results if isinstance(r, dict) and isinstance(r.get("ts"), str)), default=None)
    if first_ts and any(isinstance(r.get("added"), str) for r in reqs):
        surprise = val(sum(1 for r in reqs if isinstance(r.get("added"), str) and r["added"] > first_ts), "measured")
    else:
        surprise = unavailable()
    tel = telemetry or {}
    def T(key):
        return tel.get(key) or unavailable()
    tokens = T("tokens_by_category")
    total_tokens = val(tokens["value"]["total"], "measured") if tokens["class"] == "measured" \
        and isinstance(tokens.get("value"), dict) else unavailable()

    return {
        "intent_fulfilment": {
            "requirements_total": val(len(reqs), "measured") if "requirements" in c else unavailable(),
            "requirements_with_passing_check": val(passing, "measured") if with_check else unavailable(),
            "requirements_added_after_first_verification": surprise,
            "human_corrections": T("human_corrections"),
        },
        "correctness_and_assurance": {
            "results_by_status": val(by_status, "measured"),
            "techniques": val(sorted({"rung %s" % x.get("rung") for x in items.values()} |
                                     {str(x.get("kind")) for x in items.values() if x.get("kind")}), "measured"),
            "checks_seen_failing": val(sum(1 for r in latest.values() if r.get("seen_failing")), "measured"),
            "stronger_than_examples": val(any(x.get("rung") in (1, 2) for x in items.values()), "measured"),
            "independent_evidence": val(any(norm_status((latest.get(cid) or {}).get("status")) == "passed"
                                            for cid, x in items.items() if x.get("independent")), "measured"),
            "deviation": val(delivery_status == "deviation", "measured"),
            "unverified": val(delivery_status == "unverified", "measured"),
        },
        "delivery_velocity": {
            "time_to_first_useful_result_s": T("time_to_first_useful_result_s"),
            "time_to_validated_completion_s": T("time_to_validated_completion_s"),
            "time_in_checks_s": T("time_in_checks_s"),
            "time_in_waits_s": T("time_in_waits_s"),
            "time_in_delegations_s": T("time_in_delegations_s"),
        },
        "resource_efficiency": {
            "tokens_by_category": tokens,
            "tokens_by_model": T("tokens_by_model"),
            "tokens_total": total_tokens,
            "cost": T("cost"),
            "retries": T("send_backs"),
        },
        "parallelism": {
            "delegations": T("delegations"),
            "overlapped_delegations": T("overlapped_delegations"),
            "worker_minutes": T("worker_minutes"),
            "wall_time_s": T("time_to_validated_completion_s"),
        },
        "human_experience": {
            "human_messages": T("human_messages"),
            "question_dialogs": T("question_dialogs"),
            "human_corrections": T("human_corrections"),
        },
        "lifecycle_quality": {
            "files_changed": T("files_changed"),
            "lines_changed": T("lines_changed"),
            "tests_changed_with_code": T("tests_changed_with_code"),
            "public_surface_touched": T("public_surface_touched"),
        },
        "organizational_improvement": {
            "findings": T("retro_findings"),
            "learnings_created": T("learnings_created"),
            "recurrences": T("recurrences"),
        },
    }


# ---------------------------------------------------------------- `sisi status`

def load_unit_summaries(cwd=None):
    """Closed-unit summary lines from the user store, merged with this project's archived
    records (deduped by project+id; the archive wins). Returns dicts, oldest first."""
    units = {}
    for r in store.read("units"):
        if isinstance(r, dict) and r.get("id"):
            units[(r.get("project"), r["id"])] = r
    try:
        from . import contract as C
        p = C.find(cwd or os.getcwd())
        proj = C.project_dir(p) if p else None
        if proj:
            d = os.path.join(proj, ".sisi", "units")
            for n in sorted(os.listdir(d)) if os.path.isdir(d) else []:
                if not n.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(d, n), encoding="utf-8") as f:
                        rec = json.load(f)
                except (OSError, ValueError):
                    continue
                if isinstance(rec, dict) and rec.get("id"):
                    units[(rec.get("project") or proj, rec["id"])] = rec
    except Exception:
        pass
    return sorted(units.values(), key=lambda r: str(r.get("ended") or r.get("started") or ""))


def _num(v):
    x = v.get("value") if isinstance(v, dict) else None
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _metric(unit, *path):
    cur = unit.get("scorecard") or {}
    for k in path:
        cur = cur.get(k) if isinstance(cur, dict) else None
    return _num(cur) if cur is not None else None


_TREND_METRICS = (("validated completion (s)", ("delivery_velocity", "time_to_validated_completion_s")),
                  ("first useful result (s)", ("delivery_velocity", "time_to_first_useful_result_s")),
                  ("time in checks (s)", ("delivery_velocity", "time_in_checks_s")),
                  ("tokens", ("resource_efficiency", "tokens_total")),
                  ("human corrections", ("human_experience", "human_corrections")),
                  ("files changed", ("lifecycle_quality", "files_changed")))


def _pct(xs, p):
    s = sorted(xs)
    if not s:
        return None
    k = (len(s) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def trends(units):
    """{segment_kind: {segment: {metric: {n, median, p95} or 'too few'}}} by project, risk
    profile, model and policy version. Segments under five units say so; no single score."""
    def seg_of(u, kind):
        if kind == "project":
            return os.path.basename(str(u.get("project") or "").rstrip("/")) or "(unknown project)"
        if kind == "risk profile":
            return ((u.get("risk") or {}).get("declared") or (u.get("risk") or {}).get("profile")
                    or "(none recorded)")
        if kind == "model":
            models = u.get("models") or []
            return ", ".join(models) if isinstance(models, list) and models else "(no model recorded)"
        return str(u.get("policy_version") or "(none recorded)")[:12]
    out = {}
    for kind in ("project", "risk profile", "model", "policy version"):
        groups = {}
        for u in units:
            groups.setdefault(str(seg_of(u, kind)), []).append(u)
        seg_out = {}
        for seg, us in sorted(groups.items()):
            if len(us) < 5:
                seg_out[seg] = "too few"
                continue
            m = {}
            for name, path in _TREND_METRICS:
                xs = [x for x in (_metric(u, *path) for u in us) if x is not None]
                m[name] = {"n": len(xs), "median": _pct(xs, 50), "p95": _pct(xs, 95)} if xs else "unavailable"
            seg_out[seg] = m
        out[kind] = seg_out
    return out


def _fmt_val(v):
    if not isinstance(v, dict) or v.get("class") == "unavailable" or v.get("value") is None:
        return "unavailable"
    x = v["value"]
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, float):
        return "%g" % x
    if isinstance(x, dict):
        return ", ".join("%s=%s" % kv for kv in sorted(x.items(), key=lambda kv: str(kv[0]))) or "-"
    if isinstance(x, list):
        return ", ".join(str(i) for i in x) or "-"
    return str(x)


def format_dimension(dim, vals):
    shown = ["%s %s (%s)" % (k, _fmt_val(v), v.get("class")) for k, v in vals.items()
             if isinstance(v, dict) and v.get("class") != "unavailable"]
    n_un = sum(1 for v in vals.values() if isinstance(v, dict) and v.get("class") == "unavailable")
    return "  %s: %s%s" % (dim.replace("_", " "), "; ".join(shown) or "nothing recorded",
                           ("; %d unavailable" % n_un) if n_un else "")


def _age(iso, now=None):
    """'3h', '2d', '15m' since an ISO UTC time; '?' when it cannot be read."""
    from . import harvest
    t = harvest.epoch(iso) if isinstance(iso, str) else None
    if t is None:
        return "?"
    s = max(0, (time.time() if now is None else now) - t)
    return "%dd" % (s // 86400) if s >= 86400 else "%dh" % (s // 3600) if s >= 3600 else "%dm" % (s // 60)


def open_units(cwd=None):
    """The unit that is open or paused in this project, as display rows. A unit that waits (paused)
    says what for and for how long; one that was declared below its floor says so, with the reason."""
    from . import contract as C, unit as U, assure
    out = []
    try:
        p = C.find(cwd or os.getcwd())
        c = C.load(p) if p else None
    except (OSError, ValueError):
        return out
    if not isinstance(c, dict) or not c.get("id") or c.get("status") == "closed" or C.is_unedited_skeleton(c):
        return out
    project = C.project_dir(p)
    started, basis = U.start_of(c, p)
    row = {"id": c["id"], "status": c.get("status", "open"), "age": _age(started), "goal": c.get("goal") or "",
           "age_basis": basis}
    if row["status"] == "paused":
        pz = next((x for x in reversed(c.get("pauses") or []) if isinstance(x, dict) and not x.get("until")), {})
        row["waiting_for"], row["paused_for"] = pz.get("what"), _age(pz.get("since"))
    rk = c.get("risk") or {}
    floor, _ = U.risk_floor(c, project)
    floor = floor.get("value") if isinstance(floor, dict) else floor
    if assure.is_lowered(floor, rk.get("profile"), rk.get("why")):
        row["lowered"] = "declared %s below the floor %s: %s" % (rk.get("profile"), floor, rk.get("why"))
    if c.get("unverified"):
        row["unverified"] = "; ".join(c["unverified"].get("why") or [])
    out.append(row)
    return out


def _lowered_note(u):
    rk = u.get("risk") or {}
    if not rk.get("lowered"):
        return ""
    floor = rk.get("floor")
    floor = floor.get("value") if isinstance(floor, dict) else floor
    return "  [lowered: declared %s, floor %s%s]" % (rk.get("declared"), floor,
                                                    (": " + str(rk["why"])) if rk.get("why") else "")


def _basis_note(r):
    return " (inferred from the contract file)" if r.get("age_basis") == "inferred" else ""


def format_open(rows):
    lines = []
    for r in rows:
        if r["status"] == "paused":
            lines.append("paused  %-24s age %s%s  waiting for: %s (for %s)" % (r["id"], r["age"], _basis_note(r), r.get("waiting_for") or "?", r.get("paused_for")))
        else:
            lines.append("open    %-24s age %s%s  %s" % (r["id"], r["age"], _basis_note(r), r["goal"][:80]))
        if r.get("lowered"):
            lines.append("          lowered: " + r["lowered"])
        if r.get("unverified"):
            lines.append("          released unverified by the gate: " + r["unverified"])
    return lines


def format_status(units, recent=5, opened=()):
    lines = []
    if opened:
        lines.append("units in progress:")
        lines += ["  " + ln for ln in format_open(opened)]
        lines.append("")
    if not units:
        lines.append("sisi status: no closed work units yet. Close one with `sisi unit close`; "
                     "its scorecard will appear here.")
    else:
        lines.append("recent units (newest first, %d closed in all):" % len(units))
        for u in list(reversed(units))[:recent]:
            lines.append("")
            lines.append("%s  %s  [%s]  %s%s" % (u.get("id"), str(u.get("ended") or "")[:10],
                                                u.get("delivery_status"), u.get("goal") or "", _lowered_note(u)))
            sc = u.get("scorecard") or {}
            for dim, vals in sc.items():
                lines.append(format_dimension(dim, vals))
        lines.append("")
        lines.append("trends (median / p95; segments under five units say 'too few'):")
        for kind, segs in trends(units).items():
            lines.append("  by %s:" % kind)
            for seg, m in segs.items():
                if m == "too few":
                    lines.append("    %-28s too few" % seg[:28])
                else:
                    cells = ["%s %s/%s (n=%d)" % (name, ("%g" % v["median"]) if v != "unavailable" else "unavailable",
                                                  ("%g" % v["p95"]) if v != "unavailable" else "-",
                                                  v["n"] if v != "unavailable" else 0)
                             for name, v in m.items()]
                    lines.append("    %-28s %s" % (seg[:28], "; ".join(cells)))
    return "\n".join(lines)


def format_learning():
    """The learning report alone (`sisi status --learning`)."""
    try:
        from . import learning as _L
        return _L.learning_report().rstrip("\n")
    except Exception as e:
        store.log_error("status-learning", e)
        return "learning: unavailable (%s)" % e


def cmd_status(args=(), cwd=None, out=print):
    units = load_unit_summaries(cwd)
    opened = open_units(cwd)
    if "--json" in args:
        out(json.dumps({"open": opened, "units": units, "trends": trends(units)}, indent=2, default=str))
        return 0
    if "--learning" in args:  # asked for the learning report: just that
        out(format_learning())
        return 0
    out(format_status(units, opened=opened))
    return 0
