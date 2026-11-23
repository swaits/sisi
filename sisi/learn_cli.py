"""Commands for the data layer of the learning loop: harvest, tasks, escapes, checks, scoreboard.

Usable now as `python3 -m sisi.learn_cli <cmd>`. The main CLI hooks them in with
`learn_cli.register(subparsers)`; each command sets `func(args) -> exit code` on its parser.
No model calls anywhere. Session text stays in the state dir's harvest.db.
"""
import argparse, json, sys, time

from . import store


def _con():
    from . import harvest
    return harvest.connect()


def cmd_harvest(args):
    from . import groundtruth, harvest
    t = time.time()
    con = harvest.connect()
    say = (lambda m: print(m, file=sys.stderr)) if not args.quiet else None
    st = harvest.run(con=con, workers=args.workers, progress=say)
    t_parse = time.time() - t
    gt = groundtruth.run(con, progress=say) if not args.no_ground_truth else {"computed": 0, "skipped": 0}
    out = {"transcripts": st, "ground_truth": gt, "seconds": round(time.time() - t, 1), "parse_seconds": round(t_parse, 1)}
    if args.json:
        print(json.dumps(out))
    else:
        print("harvest: %(seen)d transcripts (%(parsed)d read, %(skipped)d unchanged, %(errors)d errors), %(sessions)d sessions" % st)
        print("ground truth: %(computed)d computed, %(skipped)d unchanged" % gt)
        print("took %.1fs" % out["seconds"])
    return 0 if st["errors"] == 0 else 1


def cmd_tasks(args):
    from . import harvest, taskset
    con = harvest.connect()
    sub = args.tasks_cmd
    if sub == "build":
        r = taskset.build(con)
        print("tasks: %(human)d human, %(brief)d brief (%(removed)d removed; %(ledger_records)d ledger records read)" % r)
        return 0
    if sub == "list":
        rows = taskset.list_tasks(con, args.kind, args.grade, args.split)
        if args.json:
            print(json.dumps([{k: v for k, v in r.items() if k != "request"} for r in rows]))
            return 0
        for r in rows:
            extra = ("%s %s" % (r["start_kind"], r["test_cmd"] or "-")) if r["kind"] == "human" else \
                    ("ledger:%s %s" % (r["match_confidence"], r["ledger_outcome"] or "-"))
            print("%-22s %-5s %-2s %-7s %s" % (r["id"], r["kind"], r["grade"] or "-", r["split"], extra))
        print("%d task(s)" % len(rows), file=sys.stderr)
        return 0
    if sub == "show":
        t = taskset.get_task(con, args.id)
        if not t:
            print("sisi: no single task matches %r" % args.id, file=sys.stderr)
            return 1
        t["reasons"] = json.loads(t["reasons"] or "[]")
        if not args.full and t["request"] and len(t["request"]) > 2000:
            t["request"] = t["request"][:2000] + " ...[truncated, use --full]"
        if args.json:
            print(json.dumps(t))
        else:
            for k, v in t.items():
                print("%s: %s" % (k, v if not isinstance(v, list) else "; ".join(v)))
        return 0
    return 2


def cmd_escapes(args):
    from . import escapes, harvest
    rows = escapes.find(harvest.connect())
    if args.json:
        print(json.dumps(rows))
        return 0
    by = {}
    for r in rows:
        by[r["kind"]] = by.get(r["kind"], 0) + 1
    for r in rows:
        print("%-26s session=%s %s%s" % (r["kind"], r["session"][:12], json.dumps(r["evidence"]), " (ambiguous)" if r.get("ambiguous") else ""))
    print("candidates: %s" % (", ".join("%s=%d" % kv for kv in sorted(by.items())) or "none"), file=sys.stderr)
    return 0


def cmd_checks(args):
    from . import scoreboard
    st = scoreboard.check_stats(store.read("results"))
    if args.json:
        print(json.dumps(st))
        return 0
    for title, key in (("check", "checks"), ("verifier", "verifiers")):
        if not st[key]:
            continue
        print("%-40s %5s %5s %5s" % (title, "runs", "fail", "tmo"))
        for s in st[key]:
            print("%-40s %5d %5d %5d%s" % (s["id"][:40], s["runs"], s["failures"], s["timeouts"],
                                           "  never seen failing" if s["never_seen_failing"] else ""))
    return 0


def cmd_scoreboard(args):
    from . import scoreboard
    sb = scoreboard.scoreboard(_con())
    if args.json:
        print(json.dumps(sb))
        return 0
    cols = ("sessions", "turns_per_session", "corrections_per_100", "questions_per_100", "contract_share", "premature_done_share")
    for title, key in (("week", "weeks"), ("repo", "repos")):
        print("%-18s %s" % (title, " ".join("%-12s" % c[:12] for c in cols)))
        for k, v in sb[key].items():
            print("%-18s %s" % (k[:18], " ".join("%-12s" % ("-" if v[c] is None else v[c]) for c in cols)))
        print()
    print("tasks:", json.dumps(sb["tasks"]))
    return 0


def register(subparsers):
    p = subparsers.add_parser("harvest", help="read agent transcripts into the harvest database (incremental)")
    p.add_argument("--workers", type=int, default=None)
    p.add_argument("--no-ground-truth", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_harvest)

    p = subparsers.add_parser("tasks", help="build, list and show the task set")
    ts = p.add_subparsers(dest="tasks_cmd", required=True)
    ts.add_parser("build").set_defaults(func=cmd_tasks)
    q = ts.add_parser("list")
    q.add_argument("--kind", choices=["human", "brief"])
    q.add_argument("--grade", choices=["A", "B", "C"])
    q.add_argument("--split", choices=["dev", "holdout"])
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_tasks)
    q = ts.add_parser("show")
    q.add_argument("id")
    q.add_argument("--full", action="store_true")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_tasks)

    p = subparsers.add_parser("escapes", help="candidate cases where verified work turned out wrong")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_escapes)

    p = subparsers.add_parser("checks", help="per-check and per-verifier run statistics")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_checks)

    p = subparsers.add_parser("scoreboard", help="weekly and per-repo trends from harvested sessions")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_scoreboard)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sisi")
    register(ap.add_subparsers(dest="cmd", required=True))
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
