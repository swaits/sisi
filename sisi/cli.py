"""Command dispatch. Heavy modules are imported lazily so hooks (tick, gate) stay fast."""
import json, os, sys


def _pop_opt(args, name):
    """Remove `name VALUE` from args, return value or None."""
    if name in args:
        i = args.index(name)
        v = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
        return v
    return None


def cmd_contract(args):
    from . import contract as C, gitutil, store, trust
    sub = args[0] if args else ""
    if sub == "init":
        goal = _pop_opt(args, "--goal")
        p = os.path.join(os.getcwd(), C.REL)
        project = os.getcwd()
        if os.path.exists(p):
            try:
                old = C.load(p)
            except (OSError, ValueError):
                old = None
            from . import unit as _U
            if not _U.is_closed(old):
                print("sisi: %s already exists and the unit %s is still open. Close it first with "
                      "`sisi unit close`, or record why it stopped with "
                      "`sisi unit close --abandon \"<reason>\"`." % (p, (old or {}).get("id", "?")))
                return 1
            # A closed unit is replaced. Its archive should already exist; if a hand-edited
            # contract claims closed with none, archive it now so nothing is ever lost.
            if old is not None and old.get("id") and not os.path.exists(_U.archive_path(project, old["id"])):
                try:
                    import time as _t
                    rec = _U.build_record(old, project, old.get("delivery_status") or "abandoned", _t.time())
                    _U.archive_record(rec, project)
                    if not _U._summary_exists(project, rec["id"]):
                        store.append("units", _U.summary_line(rec))
                except Exception as e:
                    store.log_error("contract-init-archive", e)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        skel = C.skeleton(goal, project)
        from . import unit as _U
        skel["id"] = _U.fresh_id(skel["id"], project)
        skel["base_head"] = gitutil.head(project)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(skel, f, indent=2)
            f.write("\n")
        trust.add(os.getcwd())
        print("created %s as a SKELETON, not a contract yet: replace the placeholder check with a real command "
              "(rung 1-4) and add every check that shows the work is done. Until then `sisi verify` fails and "
              "the end-of-turn gate ignores it." % p)
        try:
            from . import learning as _L
            block = _L.delivery_text(os.getcwd(), goal or "")
            if block:
                print(block)
        except Exception:
            pass
        return 0
    if sub == "check":
        p = C.find(os.getcwd())
        if not p:
            print("sisi: no contract found")
            return 2
        try:
            c = C.load(p)
        except (OSError, ValueError) as e:
            print("sisi: cannot read %s: %s" % (p, e))
            return 1
        errs = C.validate(c)
        for e in errs:
            print("  - " + e)
        if not errs:
            for w in C.warnings(c):
                print("warning: " + w)
        print("contract invalid" if errs else "contract ok: %s" % p)
        return 1 if errs else 0
    if sub == "waive":
        rest = list(args[1:])
        waived_check = _pop_opt(rest, "--check")
        reason = " ".join(rest).strip()
        if not reason:
            print('usage: sisi contract waive [--check ID] "<reason>"')
            return 1
        import time
        project = gitutil.root(os.getcwd()) or os.getcwd()
        extra = {}
        if gitutil.root(os.getcwd()):
            m = gitutil.measure(os.getcwd())
            extra = {"head": gitutil.head(os.getcwd()), "lines": m["lines"], "files": m["files"]}
        store.append("waivers", store.stamp(dict({"project": project, "reason": reason, "check": waived_check,
                                                  "ns": time.time_ns()}, **extra)))
        cp = C.find(os.getcwd())
        if cp:
            try:
                c = C.load(cp)
                if isinstance(c, dict):
                    c.setdefault("deviations", []).append(
                        {"reason": reason, "check": waived_check, "ts": store.now()})
                    C.save(cp, c)
            except (OSError, ValueError):
                pass
        print("deviation recorded for %s%s: the unit does not pass; it closes as a deviation "
              "and the completion report must say so" % (project, (" (check %s)" % waived_check) if waived_check else ""))
        return 0
    if sub in ("trust", "untrust"):
        p = C.find(os.getcwd())
        if not p:
            print("sisi: no contract found here")
            return 2
        (trust.add if sub == "trust" else trust.remove)(C.project_dir(p))
        _commit_personal(trust._file(), "trust: %s %s" % (sub, C.project_dir(p)))
        print("%sed %s" % (sub, C.project_dir(p)))
        return 0
    print("usage: sisi contract init|check|waive|trust|untrust")
    return 1


def _commit_personal(path, msg):
    """Commit a personal file that just changed (no-op for files outside the personal folder)."""
    from . import paths, pdata
    if os.path.dirname(path) == paths.data():
        pdata.commit(msg, [os.path.basename(path)])


def cmd_oracle():
    from . import principles
    sys.stdout.write(principles.oracle_text())
    return 0


def cmd_wiring(name, args=()):
    from . import wiring
    if name == "install" and "--dry-run" in args:
        rc, notes = wiring.install_dry_run()
        for n in notes:
            print(n)
        return rc
    if name == "doctor":
        rows = wiring.doctor()
        w = max(len(r["tool"]) for r in rows)
        for r in rows:
            line = "%-*s  %-9s  blocking hook: %-8s  %s" % (w, r["tool"], r["status"], r["blocking_hook"][:60], r["detail"])
            if r.get("action"):
                line += " | you need to: " + r["action"]
            print(line)
        try:
            from . import overlay
            print("always loaded      : " + overlay.cost_line())
        except Exception:
            pass
        return 0
    rc, notes = getattr(wiring, name)()
    for n in notes:
        print(n)
    return rc


def cmd_personal(cmd, args):
    from . import lifecycle, overlay, pdata
    try:
        if cmd == "overlay":
            return overlay.main(args)
        if cmd == "update":
            return lifecycle.cmd_update(args)
        if cmd == "export":
            print("exported to %s" % lifecycle.export(args[0] if args else None))
            return 0
        if cmd == "import":
            if len(args) != 1:
                print("usage: sisi import PATH")
                return 1
            for n in lifecycle.import_archive(args[0]):
                print(n)
            print("imported")
            return 0
    except (pdata.DataError, overlay.OverlayError) as e:
        print("sisi %s: %s" % (cmd, e), file=sys.stderr)
        return 1
    return 64


def cmd_help(args):
    """`sisi help` (four groups, one line per command) or `sisi help COMMAND` (that command in full)."""
    from . import helptext
    if not args:
        print(helptext.short(), end="")
        return 0
    text = helptext.long(args[0])
    if text is None:
        print("sisi: no command %r (try `sisi help`)" % args[0], file=sys.stderr)
        return 64
    print(text, end="" if text.endswith("\n") else "\n")
    return 0


def main(argv):
    args = list(argv)
    t = _pop_opt(args, "--tool")
    if t:
        os.environ["SISI_TOOL"] = t
    cmd = args.pop(0) if args else "help"
    if args[:1] in (["--help"], ["-h"]) and cmd not in ("help", "-h", "--help"):
        args = [cmd]
        cmd = "help"
    if cmd == "gate":
        if t and t != "claude-code":
            from . import hookio
            if hookio.known(t):
                return hookio.gate_main(t, args)
        from . import gate
        return gate.main(args)
    if cmd == "watch":
        if t and t != "claude-code":
            from . import hookio
            if hookio.known(t):
                return hookio.watch_main(t, args)
        from . import watch
        return watch.main(args)
    if cmd == "tick":
        if t and t != "claude-code":
            from . import hookio
            if hookio.known(t):
                return hookio.tick_main(t, args)
        from . import tick
        return tick.main(args)
    if cmd == "prompt":
        if t and t != "claude-code":
            from . import hookio
            if hookio.known(t):
                return hookio.prompt_main(t, args)
        from . import prompt
        return prompt.main(args)
    if cmd == "rule":
        from . import rulecmd
        return rulecmd.main(args)
    if cmd in ("version", "--version", "-V"):
        from . import paths
        try:
            with open(os.path.join(paths.REPO, "VERSION"), encoding="utf-8") as f:
                print(f.read().strip())
        except OSError:
            print("sisi: no VERSION file in %s" % paths.REPO, file=sys.stderr)
            return 1
        return 0
    if cmd in ("help", "-h", "--help"):
        return cmd_help(args)
    if cmd == "contract":
        return cmd_contract(args)
    if cmd == "verify":
        from . import verify
        return verify.cmd_verify(args)
    if cmd in ("install", "uninstall", "doctor"):
        return cmd_wiring(cmd, args)
    if cmd in ("update", "export", "import", "overlay"):
        return cmd_personal(cmd, args)
    if cmd in ("release", "rollback", "promote"):
        from . import release
        try:
            return {"release": release.cmd_release, "rollback": release.cmd_rollback,
                    "promote": release.cmd_promote}[cmd](args)
        except release.ReleaseError as e:
            print("sisi %s: %s" % (cmd, e), file=sys.stderr)
            return 1
    if cmd == "learn":
        from . import scope
        return scope.cmd_learn(args)
    if cmd == "handover":
        from . import handover
        return handover.main(args)
    if cmd == "retro":
        from . import retro
        return retro.cmd_retro(args)
    if cmd == "lessons":
        from . import retro
        return retro.cmd_lessons(args)
    if cmd == "cycle":
        from . import cycle
        return cycle.cmd_cycle(args)
    if cmd == "approve":
        from . import cycle
        return cycle.cmd_approve(args)
    if cmd == "oracle":
        return cmd_oracle()
    if cmd == "risk":
        from . import risk
        return risk.main(args)
    if cmd == "status":
        from . import scorecard
        return scorecard.cmd_status(args)
    if cmd == "unit":
        from . import unit
        return unit.cmd_unit(args)
    if cmd == "verifiers":
        from . import verifiers
        return verifiers.main(args)
    if cmd == "done":
        from . import verifiers
        return verifiers.done_main(args)
    if cmd == "workers":
        from . import workers
        return workers.cmd_workers(args)
    if cmd == "route":
        from . import workers
        return workers.cmd_route(args)
    if cmd == "delegate":
        from . import workers
        return workers.cmd_delegate(args)
    if cmd == "eval":
        from . import evaluate
        return evaluate.cmd_eval(args)
    if cmd in ("tasks", "checks"):
        from . import evaluate
        return evaluate.cmd_folded(cmd, args)
    rc = _learn_cli(cmd, args)
    if rc is not None:
        return rc
    print("sisi: unknown command %r (try `sisi help`)" % cmd, file=sys.stderr)
    return 64


def _learn_cli(cmd, args):
    """Data-layer commands (harvest, tasks, ...) live in learn_cli; None when `cmd` is not one of them."""
    import argparse
    from . import learn_cli
    ap = argparse.ArgumentParser(prog="sisi")
    sub = ap.add_subparsers(dest="cmd")
    learn_cli.register(sub)
    if cmd not in sub.choices:
        return None
    ns = ap.parse_args([cmd] + args)
    return ns.func(ns)
