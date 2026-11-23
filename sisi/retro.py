"""`sisi retro`: the retrospective at the close of a work unit, grounded in the record.

No arguments: print the unit's record and what stands out. With --finding: record one
finding with a disposition. Only the fields the disposition needs are asked for; search
terms, topics and short lines are derived by the tool. A finding that resembles an
existing learning is attached to it as a recurrence candidate, never refused in a loop.
"""
import hashlib, json, os, subprocess, sys

from . import learning as L, paths


def repo_of(cwd):
    return L.project_key(cwd)


def _git_head(cwd):
    try:
        p = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True,
                           text=True, timeout=10)
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def unit_summary(project):
    """What `sisi retro` with no arguments prints: the unit's record and what stands out."""
    from . import unit as _unit
    text = _unit.summary_for_retro(project)
    if text:
        return text
    lines = []
    try:
        with open(os.path.join(project, ".sisi", "contract.json"), encoding="utf-8") as f:
            c = json.load(f)
        lines.append("unit %s: %s" % (c.get("id", "?"), c.get("goal", "")))
        checks = c.get("checks") or []
        lines.append("checks in contract: %d" % len(checks))
    except (OSError, ValueError):
        lines.append("no open contract in this project; recording against unit %s" % L.unit_id(project))
    # what the existing delivery and result stores hold for the current request
    try:
        with open(paths.state_file("results.jsonl"), encoding="utf-8") as f:
            rows = [json.loads(x) for x in f if x.strip()][-20:]
        fails = [r for r in rows if r.get("status") == "failed"]
        if rows:
            lines.append("recent verification: %d result(s) on record, %d failed" % (len(rows), len(fails)))
    except (OSError, ValueError):
        pass
    head = _git_head(project)
    if head:
        lines.append("project HEAD: %s" % head[:12])
    lines += ["", "What stands out? Record at least one finding:",
              "  sisi retro --finding \"<what happened, with the evidence>\" --cause \"<root cause>\" "
              "--impact value|correctness|time|cost|attention --disposition promote|record|drop ..."]
    return "\n".join(lines) + "\n"


OPTS = ("finding", "cause", "impact", "disposition", "change", "mechanism", "scope",
        "expect", "validate", "limits", "why-not", "same-as", "adopt", "target")


def _parse(argv):
    out, i = {}, 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            k = a[2:]
            if "=" in k:
                k, v = k.split("=", 1)
            elif k in OPTS and i + 1 < len(argv):
                v, i = argv[i + 1], i + 1
            else:
                v = "1"
            out[k] = v
        i += 1
    return out


def _refuse(msg):
    print("sisi retro: %s" % msg, file=sys.stderr)
    return 2


def _adopt(lid, project):
    """A parent adopts a subagent's candidate by id. Never by resemblance, never from a subagent."""
    if L.is_subagent_session():
        return _refuse("a subagent cannot adopt a candidate; the parent session adopts it by id")
    try:
        rec = L.adopt(lid, L.unit_id(project), project)
    except L.LearningError as e:
        return _refuse(str(e))
    print("learning %s adopted: no longer a candidate, delivered like any learning in its project" % rec["id"])
    return 0


def cmd_retro(argv, stdin=None):
    project = os.getcwd()
    if not argv:
        sys.stdout.write(unit_summary(project))
        return 0
    o = _parse(argv)
    if o.get("adopt"):
        return _adopt(o["adopt"], project)
    finding = (o.get("finding") or "").strip()
    cause = (o.get("cause") or "").strip()
    impact = (o.get("impact") or "").strip()
    disp = (o.get("disposition") or "").strip()
    change = (o.get("change") or "").strip()
    if not finding or not cause:
        return _refuse("--finding and --cause are required (run `sisi retro` alone for the unit record)")
    if len(finding) < 12 or len(cause) < 8 or L.is_generic(finding) or L.is_generic(cause) \
            or (change and L.is_generic(change)):
        return _refuse("generic findings are refused: say what happened, with evidence, and the root cause")
    if impact not in L.IMPACTS:
        return _refuse("--impact must be one of %s" % "|".join(L.IMPACTS))
    if disp not in ("promote", "record", "drop"):
        return _refuse("--disposition must be promote, record or drop")
    if disp == "promote":
        if not change:
            return _refuse("promote needs --change \"<the exact improvement>\"")
        if o.get("mechanism") not in L.MECHANISMS:
            return _refuse("--mechanism must be one of %s" % "|".join(L.MECHANISMS))
        if o.get("scope") and o["scope"] not in L.SCOPES:
            return _refuse("--scope must be one of %s" % "|".join(L.SCOPES))
        if not (o.get("expect") or "").strip() or not (o.get("validate") or "").strip():
            return _refuse("promote needs --expect \"<observable effect>\" and --validate \"<how it will be tested>\"")
    if disp == "record" and not (o.get("limits") or "").strip():
        return _refuse("record needs --limits \"<where it applies and where it does not>\"")
    if disp == "drop" and not (o.get("why-not") or "").strip():
        return _refuse("drop needs --why-not \"<why it is not worth promoting>\"")
    if o.get("same-as") and o.get("new"):
        return _refuse("--same-as and --new contradict each other")

    uid = L.unit_id(project)
    pk = L.project_key(project)
    sub = L.is_subagent_session()
    rows = L.load_learnings()
    visible = L.learnings_in_scope(project, rows)  # only learnings in force here can be matched
    target, how = None, None
    if o.get("same-as"):
        if sub:
            return _refuse("a subagent's findings are held as candidates; it cannot attach to a learning")
        target = L.get(visible, o["same-as"])
        how = "named with --same-as"
        if target is None:
            # A learning from another project: this finding, a unit here, is its own evidence for
            # it, but only if it plainly is the same thing.
            other = L.get(rows, o["same-as"])
            if other is None or not L.is_registered(other) or other.get("candidate") or other.get("status") in L.ENDED:
                return _refuse("no learning %r" % o["same-as"])
            if len(L.stems(finding + " " + cause + " " + change) & set(other.get("terms") or [])) < 2:
                return _refuse("this finding does not share enough with %s to be a recurrence of it; "
                               "record it as its own (--new)" % other["id"])
            target, how = other, "named with --same-as; this project's own finding is the evidence"
    elif not sub and not o.get("new"):
        sim = L.similar_learnings(visible, finding + " " + change, limit=1)
        if sim:
            target, how = sim[0], "resembles it (--new records this finding as its own learning instead)"

    replay = None
    head = _git_head(project)
    if head:
        replay = {"repo": pk, "after": head, "before": None}
    ts = L.now()
    fid = "F-" + hashlib.sha1(("%s|%s|%s|%s" % (uid, pk, ts, finding)).encode()).hexdigest()[:8]
    f = {"id": fid, "unit": uid, "project": pk, "ts": ts, "finding": L.scrub_secrets(finding),
         "cause": L.scrub_secrets(cause), "impact": impact, "disposition": disp,
         "learning": target["id"] if target else None, "recurrence_of": target["id"] if target else None,
         "by_subagent": sub}
    L.append_finding(f)

    if target is not None:
        added = L.add_recurrence(target, uid, project, rows, finding=fid)
        print("finding recorded for unit %s; attached to learning %s (%s) as a recurrence%s%s"
              % (uid, target["id"], how, "" if added else " (this unit was already counted for it)",
                 " (flagged not working: the next cycle must revise or revert it)"
                 if target.get("flagged_not_working") else ""))
        return 0
    if disp == "drop":
        print("finding recorded for unit %s; dropped: %s" % (uid, o.get("why-not", "")))
        return 0
    rec = L.new_record(finding, cause, impact, disp, project, uid,
                       change=change or None, mechanism=o.get("mechanism"), scope=o.get("scope"),
                       expect=(o.get("expect") or "").strip() or None,
                       validate=(o.get("validate") or "").strip() or None,
                       limits=(o.get("limits") or "").strip() or None,
                       why_not=(o.get("why-not") or "").strip() or None,
                       subagent=sub, replay=replay, target=(o.get("target") or "").strip() or None)
    print("finding recorded for unit %s; learning %s (%s)%s"
          % (uid, rec["id"], rec["status"],
             ", held as a candidate until the parent adopts it (`sisi retro --adopt %s`)" % rec["id"]
             if rec.get("candidate") else ""))
    return 0


def cmd_lessons(argv):
    """sisi lessons [show ID] [--json] — list learning records. No digest; see status --learning."""
    rows = L.load_learnings()
    if argv and argv[0] == "digest":
        print("sisi lessons: digest is retired; `sisi status --learning` is the one report",
              file=sys.stderr)
        return 2
    if argv and argv[0] == "show" and len(argv) > 1:
        r = L.get(rows, argv[1])
        if r is None:
            print("no learning %r" % argv[1], file=sys.stderr)
            return 2
        print(json.dumps(r, indent=2, sort_keys=True))
        return 0
    if "--json" in argv:
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0
    if not rows:
        print("no learnings recorded")
        return 0
    ledger = L.load_ledger()
    for r in rows:
        val = (r.get("validation") or {}).get("result") or "unvalidated"
        print("%s  %-11s %-11s %s%s" % (r["id"], r.get("status"), val if val == "validated" else "unvalidated",
                                        L.derive_title(r.get("title", ""), 100),
                                        "" if L.is_registered(r, ledger) else "  [not delivered: not written by sisi's commands]"))
    return 0
