"""Command dispatch. Heavy modules are imported lazily so hooks (tick, gate) stay fast."""
import json, os, sys

HELP = """sisi is still improving

A shared rulebook and enforced definitions of done for every AI coding CLI.

  sisi contract init [--goal TEXT]   start a work unit: create .sisi/contract.json here (refuses while one is open)
  sisi contract check                validate the contract (vacuous checks are refused)
  sisi contract waive [--check ID] "<reason>"
                                     record a deviation: a waived check does not pass; the unit closes as a deviation and the report must say so
  sisi contract trust | untrust      allow / stop allowing this project's contract to run commands
  sisi unit close [--abandon "<reason>"]
                                     archive the unit to .sisi/units/<id>.json with its scorecard; --abandon records why it stopped
  sisi unit pause "<what it waits for>"
                                     record a wait; the turn may end with no demands
  sisi unit show [ID] | list         print the open unit or an archived record; list this project's units
  sisi verify [--json]               run the selected fast checks (five statuses; nothing unrun passes); exit 0 ok, 1 failure, 2 no contract, 3 untrusted
  sisi verify --deep [--background]  run the deep (long) checks; --background detaches and returns at once
  sisi verify --all | --state        run every check in both tiers; print only the deep-check state (with --json)
  sisi gate [--tool NAME]            end-of-turn hook (reads hook JSON on stdin; NAME selects the tool's hook shape)
  sisi tick [--tool NAME]            session-start hook
  sisi prompt [--tool NAME]          prompt-submission hook: prints the matching recipe and lessons for the human's request as added context (silent when nothing strictly matches); `sisi prompt "<request>"` tries it by hand
  sisi rule [N|ID]                   the effective rules and how each is enforced; with N or ID: one rule in full (reasons, history, lessons behind it, how it is enforced)
  sisi watch [--before|--after]      before/after shell-tool hook: measures whether the command changed the project
  sisi install [--dry-run] | uninstall | doctor
                                     wire sisi into the tools (by reference), undo, inspect; --dry-run only prints what would change
  sisi release [--deep]              run the source's checks, then make the stable copy the tools run (see docs/developing.md)
  sisi rollback                      switch the stable copy back to the previous release
  sisi promote [ID|L-NNNN] [--apply] | --export [PATH]
                                     no ID: list items not yet in the product (learnings that change
                                     sisi itself, or earned organization scope); an ID scrubs a
                                     personal overlay item into the source folder and drops the
                                     personal copy once the product contains it (dry run unless
                                     --apply); L-NNNN promotes the rule or recipe a learning was
                                     folded into, from the clone; --export writes a contribution file
                                     (universal text only; nothing is sent anywhere)
  sisi update                        fast-forward the product clone, then back up, migrate and rebuild personal data
  sisi export [PATH] | import PATH   one tar.gz of personal data, results and session records; restore it
  sisi overlay list|diff|add-rule|replace-rule|disable-rule|enable-rule|add-verifier|...|revert COMMIT
                                     learned changes to rules, verifiers and recipes; each one a commit in your personal repo
  sisi retro                         print the unit's record and what stands out in it
  sisi retro --finding F --cause C --impact value|correctness|time|cost|attention --disposition promote|record|drop [--same-as ID | --new] [--target ID]
                                     record one finding; promote also needs --change, --mechanism,
                                     --expect and --validate; record needs --limits; drop needs --why-not;
                                     a match in scope is printed and attached as a recurrence (--new records
                                     a learning of its own); --target names the rule or recipe it concerns
  sisi retro --adopt ID              a parent adopts a subagent's candidate learning, by id
  sisi lessons [--json] | show ID    the learning records and their statuses
  sisi cycle [due|apply FILE|check FILE|revert [ID]|help]
                                     turn proposed learnings into mechanisms (no scheduler:
                                     due-ness is a counter); apply validates and replays before
                                     promoting; help prints the cycle file format
  sisi approve [ID --yes|--no]       list, in full, the consequential changes waiting for the owner; decide one
                                     (in a terminal: an agent's --yes without one is refused)
  sisi learn [--scope user|project] TEXT
                                     record an owner statement; it takes effect at once and
                                     `sisi oracle` prints it. Scope for other learnings is
                                     earned by evidence, never claimed
  sisi learn --withdraw ID --reason WHY
                                     take a statement recorded by mistake out of delivery (kept in history)
  sisi risk [--json]                 risk floor for the working-tree change, with reasons and
                                     what that profile requires
  sisi handover [--all] | done ID --where PATH [--quote FRAGMENT]
                                     project-scope learnings waiting to be filed in this project's own docs or
                                     work list; done confirms one is filed (the named file must contain
                                     its key text) and removes it from the list
  sisi oracle                        print what the human wants: the standing principles from
                                     `sisi learn`, live at once (project-scoped ones only in their project)
  sisi status [--json] [--learning]  recent units with their scorecards, then trends by project, risk profile, model and policy version (median and p95; no single score)
  sisi verifiers [WORDS] [--lang L] [--kind K] [--rung N] [--section S] [--installed] [--json]
                                     list ways to know work is correct, by section
  sisi verifiers show ID [--trace]   one entry in full, and whether its tool is installed here; --trace also prints where each folded lesson lives in it
  sisi verifiers for "<claim>"       best-matching verifiers for a claim or piece of work
  sisi verifiers doctor | lint       which tools are installed; validate the library
  sisi done [ID] [--trace]           recipes: which checks make a kind of work done; --trace also prints where each folded lesson lives in the recipe
  sisi done for "<work>"             best-matching recipe
  sisi workers [--refresh]           the agent tools and models found here, what is usable now and why not, allowance and price where known, delegations waiting for a judgement, and the judged record as three tables
  sisi workers fact W --price N|--score N --source S  record a price (per million tokens) or benchmark standing (0-100), with its source and date
  sisi workers avoid|prefer PATTERN --why TEXT  your own routing constraints, honoured by `sisi route`
  sisi workers down W --reason limit|auth|missing|error [--until DATE] | up W  mark a worker unavailable / available again
  sisi workers import FILE           merge another ledger file into the delegation ledger (row counts printed; safe to repeat)
  sisi route --kind K --difficulty N [--review-of W] [--explain]
                                     the most affordable usable worker for this kind and difficulty, and the mechanism to start it with (host subagents, host cross-provider delegation, or sisi delegate); --explain says why
  sisi delegate brief | check FILE | guide  the delegation-contract template (eight parts); which parts a brief lacks; the orchestration playbook
  sisi delegate --kind K --difficulty N --brief FILE [--worker W] [--review-of W] [--cwd DIR]
                                     run one brief on the chosen worker unattended; prints only its final report, the transcript path, and the judge command; a brief without outcome, acceptance or files it may change is refused
  sisi delegate judge ID --outcome accepted|rejected --check none|diffstat|tests|read|review [--minutes N]
                                     record your judgement of a delegation run, so the next choice learns from it; judge work run any other way with --worker W --type K --difficulty N instead of ID
  sisi delegate amend ID | recent [-n N] [--project P]  mark a judged delegation that later proved wrong; list recent judgements to find an id
  sisi eval list|add|run|compare|shadow|judge|status|import
                                     the evaluation harness: benchmark cases from real work, isolated
                                     replay, policy comparison and independent judging (see docs/evaluation.md);
                                     `sisi eval` alone prints status; run without --tasks replays check cases only
  sisi version | --version           print the product version (the VERSION file in the product folder)
  sisi help                          this text

Three places: the product (this clone, never written at run time), your personal data
(~/.local/share/sisi, its own git repository), and scratch (~/.local/state/sisi).
Environment: SISI_HOME (stands in for the home directory), SISI_DATA (personal data folder),
SISI_STATE (scratch dir), SISI_LIB (where stable releases live, default ~/.local/lib/sisi), SISI_TOOL (name recorded with results), SISI_VERIFIERS and SISI_DONE
(library directories, default verifiers/ and done/ in the product).
"""


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
        skel = C.skeleton(goal)
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
            for f in C.floor_failures(c):
                errs.append(f["message"])
                print("  - " + f["message"])
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


def main(argv):
    args = list(argv)
    t = _pop_opt(args, "--tool")
    if t:
        os.environ["SISI_TOOL"] = t
    cmd = args.pop(0) if args else "help"
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
        print(HELP, end="")
        return 0
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
    """Data-layer commands (harvest, tasks, ...) live in learn_cli. The CLI works without it, even if it is broken."""
    try:
        import argparse
        from . import learn_cli
        ap = argparse.ArgumentParser(prog="sisi")
        sub = ap.add_subparsers(dest="cmd")
        learn_cli.register(sub)
        if cmd not in sub.choices:
            return None
        ns = ap.parse_args([cmd] + args)
        return ns.func(ns)
    except (ImportError, AttributeError, TypeError) as e:
        print("sisi: the %r command is unavailable (%s)" % (cmd, e), file=sys.stderr)
        return 70
