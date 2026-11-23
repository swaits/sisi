"""`sisi retro`: the retrospective at the close of a work unit, grounded in the record.

No arguments: print the unit's record and what stands out. With --finding: record one
finding with a disposition. Only the fields the disposition needs are asked for; search
terms, topics and short lines are derived by the tool. A finding that resembles an
existing learning is attached to it as a recurrence candidate, never refused in a loop.

Gate compatibility (gate.py calls these; its control flow is unchanged): TEMPLATE,
satisfied(), repo_of(), lessons_block().
"""
import json, os, subprocess, sys

from . import learning as L, paths

TEMPLATE = (
    "Before this turn ends, record the retro for this unit ({n}).\n"
    "Run `sisi retro` first: it prints the unit's record. Then record at least one finding:\n"
    "  sisi retro --finding \"<what happened, with the evidence>\" --cause \"<root cause>\" "
    "--impact value|correctness|time|cost|attention --disposition promote|record|drop\n"
    "  promote also needs: --change \"<exact improvement>\" --mechanism policy|orchestration|skill|tool|"
    "infrastructure|verification|knowledge|benchmark --expect \"<observable effect>\" --validate \"<how it will be tested>\"\n"
    "  record also needs:  --limits \"<where it applies and where it does not>\"\n"
    "  drop also needs:    --why-not \"<why it is not worth promoting>\"\n"
    "Generic findings are refused. A recurrence of a known learning may add --same-as ID."
)


def repo_of(cwd):
    return L.project_key(cwd)


def notes_for(entry_id):
    """Field notes per library entry were part of the retired trace regime; none remain."""
    return None


def _git_head(cwd):
    try:
        p = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True,
                           text=True, timeout=10)
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def satisfied(repo, since, fp):
    """Gate seam: was a retro recorded for the current unit of this project?"""
    try:
        uid = L.unit_id(repo)
        if L.findings_for_unit(repo, uid):
            return True
        # A finding recorded in this project since the request started also counts:
        # the gate passes `since` from its own session bookkeeping.
        pk = L.project_key(repo)
        return any(f.get("project") == pk and (since is None or str(f.get("ts", "")) >= str(since))
                   for f in L.load_findings()) if since else False
    except Exception:
        return False


def lessons_block(query, place, session=None, limit=3, max_chars=600, extra=""):
    """Gate seam: learnings in scope as background information. Nothing is recorded as shown."""
    try:
        text = L.delivery_text(os.getcwd(), str(query))
        return text[:max_chars] if text else ""
    except Exception:
        return ""


def unit_summary(project):
    """What `sisi retro` with no arguments prints: the unit's record and what stands out."""
    try:
        from . import unit as _unit  # work-unit worker's module, when merged
        text = _unit.summary_for_retro(project)
        if text:
            return text
    except Exception:
        pass
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
    try:
        from . import delivery
        d = delivery.current(project) if hasattr(delivery, "current") else None
        if d:
            lines.append("delivery: %s" % d)
    except Exception:
        pass
    head = _git_head(project)
    if head:
        lines.append("project HEAD: %s" % head[:12])
    lines += ["", "What stands out? Record at least one finding:",
              "  sisi retro --finding \"<what happened, with the evidence>\" --cause \"<root cause>\" "
              "--impact value|correctness|time|cost|attention --disposition promote|record|drop ..."]
    return "\n".join(lines) + "\n"


OPTS = ("finding", "cause", "impact", "disposition", "change", "mechanism", "scope",
        "expect", "validate", "limits", "why-not", "same-as", "candidate")


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


def cmd_retro(argv, stdin=None):
    project = os.getcwd()
    if not argv:
        sys.stdout.write(unit_summary(project))
        return 0
    o = _parse(argv)
    finding = (o.get("finding") or "").strip()
    cause = (o.get("cause") or "").strip()
    impact = (o.get("impact") or "").strip()
    disp = (o.get("disposition") or "").strip()
    def refuse(msg):
        print("sisi retro: %s" % msg, file=sys.stderr)
        return 2
    if not finding or not cause:
        return refuse("--finding and --cause are required (run `sisi retro` alone for the unit record)")
    if L.GENERIC.match(finding) or len(finding) < 20 or len(cause) < 12:
        return refuse("generic findings are refused: say what happened, with evidence, and the root cause")
    if impact not in L.IMPACTS:
        return refuse("--impact must be one of %s" % "|".join(L.IMPACTS))
    if disp not in ("promote", "record", "drop"):
        return refuse("--disposition must be promote, record or drop")
    if disp == "promote":
        if not (o.get("change") or "").strip():
            return refuse("promote needs --change \"<the exact improvement>\"")
        if o.get("mechanism") not in L.MECHANISMS:
            return refuse("--mechanism must be one of %s" % "|".join(L.MECHANISMS))
        if o.get("scope") and o["scope"] not in L.SCOPES:
            return refuse("--scope must be one of %s" % "|".join(L.SCOPES))
        if not (o.get("expect") or "").strip() or not (o.get("validate") or "").strip():
            return refuse("promote needs --expect \"<observable effect>\" and --validate \"<how it will be tested>\"")
    if disp == "record" and not (o.get("limits") or "").strip():
        return refuse("record needs --limits \"<where it applies and where it does not>\"")
    if disp == "drop" and not (o.get("why-not") or "").strip():
        return refuse("drop needs --why-not \"<why it is not worth promoting>\"")

    uid = L.unit_id(project)
    pk = L.project_key(project)
    rows = L.load_learnings()
    # recurrence candidate: --same-as, an adopted candidate id, or resemblance
    target = None
    for key in ("same-as", "candidate"):
        if o.get(key):
            target = L.get(rows, o[key])
            if target is None:
                return refuse("no learning %r" % o[key])
    if target is None:
        sim = L.similar_learnings(rows, finding + " " + (o.get("change") or ""), limit=1)
        target = sim[0] if sim else None

    replay = None
    head = _git_head(project)
    if head:
        replay = {"repo": pk, "after": head, "before": None}
    f = {"unit": uid, "project": pk, "ts": L.now(), "finding": finding, "cause": cause,
         "impact": impact, "disposition": disp,
         "learning": target["id"] if target else None, "recurrence_of": target["id"] if target else None}
    L.append_finding(f)

    if target is not None:
        if target.get("candidate") and not L.is_subagent_session():
            target["candidate"] = False  # a parent retro adopting a subagent candidate
        L.add_recurrence(target, uid, project, rows)
        print("finding recorded for unit %s; attached to learning %s as a recurrence candidate%s"
              % (uid, target["id"],
                 " (flagged not working: the next cycle must revise or revert it)"
                 if target.get("flagged_not_working") else ""))
        return 0
    if disp == "drop":
        print("finding recorded for unit %s; dropped: %s" % (uid, o.get("why-not", "")))
        return 0
    rec = L.new_record(finding, cause, impact, disp, project, uid,
                       change=(o.get("change") or "").strip() or None,
                       mechanism=o.get("mechanism"), scope=o.get("scope"),
                       expect=(o.get("expect") or "").strip() or None,
                       validate=(o.get("validate") or "").strip() or None,
                       limits=(o.get("limits") or "").strip() or None,
                       why_not=(o.get("why-not") or "").strip() or None,
                       subagent=L.is_subagent_session(), replay=replay)
    print("finding recorded for unit %s; learning %s (%s)%s"
          % (uid, rec["id"], rec["status"],
             ", held as a candidate until a parent retro adopts it" if rec.get("candidate") else ""))
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
    for r in rows:
        val = (r.get("validation") or {}).get("result") or "unvalidated"
        print("%s  %-11s %-11s %s" % (r["id"], r.get("status"), val if val == "validated" else "unvalidated",
                                      L.derive_title(r.get("title", ""), 100)))
    return 0
