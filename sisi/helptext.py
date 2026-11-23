"""Help text for `sisi help`: four groups of commands, one line each, and the long text per command.

`sisi help` must fit 60 lines of 110 characters (tests/test_public.py checks it); the long explanation of a
command is printed by `sisi help COMMAND` and `sisi COMMAND --help`.
"""

LONG = {
    'contract': '  sisi contract init [--goal TEXT]   start a work unit: create .sisi/contract.json here (refuses while one is open)\n  sisi contract check                validate the contract (vacuous checks are refused)\n  sisi contract waive [--check ID] "<reason>"\n      record a deviation: a waived check does not pass; the unit closes as a deviation and the report must say so\n  sisi contract trust | untrust      allow / stop allowing this project\'s contract to run commands',
    'unit': '  sisi unit close [--abandon "<reason>"]\n      archive the unit to .sisi/units/<id>.json with its scorecard; --abandon records why it stopped\n  sisi unit pause "<what it waits for>"\n      record a wait; the turn may end with no demands\n  sisi unit direct "<reason>"\n      say why doing this work yourself is cheaper than delegating it; a specific reason allows more direct calls this turn and is kept with the unit record\n  sisi unit show [ID] | list         print the open unit or an archived record; list this project\'s units',
    'verify': '  sisi verify [--json]               run the selected fast checks (five statuses; nothing unrun passes); exit 0 ok, 1 failure, 2 no contract, 3 untrusted\n  sisi verify --deep [--background]  run the deep (long) checks; --background detaches and returns at once\n  sisi verify --all | --state        run every check in both tiers; print only the deep-check state (with --json)',
    'gate': "  sisi gate [--tool NAME]            end-of-turn hook (reads hook JSON on stdin; NAME selects the tool's hook shape)",
    'tick': '  sisi tick [--tool NAME]            session-start hook',
    'prompt': '  sisi prompt [--tool NAME]          prompt-submission hook: prints the matching recipe and lessons for the human\'s request as added context (silent when nothing strictly matches); `sisi prompt "<request>"` tries it by hand',
    'rule': '  sisi rule [N|ID]                   the effective rules and how each is enforced; with N or ID: one rule in full (reasons, history, lessons behind it, how it is enforced)',
    'watch': '  sisi watch [--before|--after]      before/after shell-tool hook: measures whether the command changed the project',
    'install': '  sisi install [--dry-run] | uninstall | doctor\n      wire sisi into the tools (by reference), undo, inspect; --dry-run only prints what would change',
    'release': "  sisi release [--deep]              run the source's checks, then make the stable copy the tools run (see docs/developing.md)",
    'rollback': '  sisi rollback                      switch the stable copy back to the previous release',
    'promote': '  sisi promote [ID|L-NNNN] [--apply] | --export [PATH]\n      no ID: list items not yet in the product (learnings that change\n      sisi itself, or earned organization scope); an ID scrubs a\n      personal overlay item into the source folder and drops the\n      personal copy once the product contains it (dry run unless\n      --apply); L-NNNN promotes the rule or recipe a learning was\n      folded into, from the clone; --export writes a contribution file\n      (universal text only; nothing is sent anywhere)',
    'update': '  sisi update                        fast-forward the product clone, then back up, migrate and rebuild personal data',
    'export': '  sisi export [PATH] | import PATH   one tar.gz of personal data, results and session records; restore it',
    'overlay': '  sisi overlay list|diff|add-rule|replace-rule|disable-rule|enable-rule|add-verifier|...|revert COMMIT\n      learned changes to rules, verifiers and recipes; each one a commit in your personal repo',
    'retro': "  sisi retro                         print the unit's record and what stands out in it\n  sisi retro --finding F --cause C --impact value|correctness|time|cost|attention --disposition promote|record|drop [--same-as ID | --new] [--target ID]\n      record one finding; promote also needs --change, --mechanism,\n      --expect and --validate; record needs --limits; drop needs --why-not;\n      a match in scope is printed and attached as a recurrence (--new records\n      a learning of its own); --target names the rule or recipe it concerns\n  sisi retro --adopt ID              a parent adopts a subagent's candidate learning, by id",
    'lessons': '  sisi lessons [--json] | show ID    the learning records and their statuses',
    'cycle': '  sisi cycle [due|apply FILE|check FILE|revert [ID]|help]\n      turn proposed learnings into mechanisms (no scheduler:\n      due-ness is a counter); apply validates and replays before\n      promoting; help prints the cycle file format',
    'approve': "  sisi approve [ID --yes|--no]       list, in full, the consequential changes waiting for the owner; decide one\n      (in a terminal: an agent's --yes without one is refused)",
    'learn': '  sisi learn [--scope user|project] TEXT\n      record an owner statement; it takes effect at once and\n      `sisi oracle` prints it. Scope for other learnings is\n      earned by evidence, never claimed\n  sisi learn --withdraw ID --reason WHY\n      take a statement recorded by mistake out of delivery (kept in history)',
    'risk': '  sisi risk [--json]                 risk floor for the working-tree change, with reasons and\n      what that profile requires',
    'handover': "  sisi handover [--all] | done ID --where PATH [--quote FRAGMENT]\n      project-scope learnings waiting to be filed in this project's own docs or\n      work list; done confirms one is filed (the named file must contain\n      its key text) and removes it from the list",
    'oracle': '  sisi oracle                        print what the human wants: the standing principles from\n      `sisi learn`, live at once (project-scoped ones only in their project)',
    'status': '  sisi status [--json] [--learning]  recent units with their scorecards, then trends by project, risk profile, model and policy version (median and p95; no single score)',
    'verifiers': '  sisi verifiers [WORDS] [--lang L] [--kind K] [--rung N] [--section S] [--installed] [--json]\n      list ways to know work is correct, by section\n  sisi verifiers show ID [--trace]   one entry in full, and whether its tool is installed here; --trace also prints where each folded lesson lives in it\n  sisi verifiers for "<claim>"       best-matching verifiers for a claim or piece of work\n  sisi verifiers doctor | lint       which tools are installed; validate the library',
    'done': '  sisi done [ID] [--trace]           recipes: which checks make a kind of work done; --trace also prints where each folded lesson lives in the recipe\n  sisi done for "<work>"             best-matching recipe',
    'workers': '  sisi workers [--refresh]           the agent tools and models found here, what is usable now and why not, allowance and price where known, delegations waiting for a judgement, and the judged record as three tables\n  sisi workers fact W --price N|--score N --source S  record a price (per million tokens) or benchmark standing (0-100), with its source and date\n  sisi workers avoid|prefer PATTERN --why TEXT  your own routing constraints, honoured by `sisi route`\n  sisi workers only PROVIDER PATTERN... --why TEXT | --remove  make only the matching models of that provider routable\n  sisi workers note PATTERN \"TEXT\" --why SOURCE | --remove  a standing fact about workers matching PATTERN, shown with route results\n  sisi workers down W --reason limit|auth|missing|error [--until DATE|TIME] | up W  mark a worker unavailable / available again\n  sisi workers import FILE           merge another ledger file into the delegation ledger (row counts printed; safe to repeat)',
    'route': '  sisi route --kind K --difficulty N [--review-of W] [--explain]\n      the most affordable usable worker for this kind and difficulty, and the mechanism to start it with (host subagents, host cross-provider delegation, or sisi delegate); --explain says why',
    'delegate': '  sisi delegate brief | check FILE | guide  the delegation-contract template (eight parts); which parts a brief lacks; the orchestration playbook\n  sisi delegate --kind K --difficulty N --brief FILE [--worker W] [--review-of W] [--cwd DIR]\n      run one brief on the chosen worker unattended; prints only its final report, the transcript path, and the judge command; a brief without outcome, acceptance or files it may change is refused\n  sisi delegate judge ID --outcome accepted|rejected --check none|diffstat|tests|read|review [--minutes N]\n      record your judgement of a delegation run, so the next choice learns from it; judge work run any other way with --worker W --type K --difficulty N instead of ID\n  sisi delegate amend ID | recent [-n N] [--project P]  mark a judged delegation that later proved wrong; list recent judgements to find an id',
    'eval': '  sisi eval list|add|run|compare|shadow|judge|status|import\n      the evaluation harness: benchmark cases from real work, isolated\n      replay, policy comparison and independent judging (see docs/evaluation.md);\n      `sisi eval` alone prints status; run without --tasks replays check cases only',
    'version': '  sisi version | --version           print the product version (the VERSION file in the product folder)',
    'help': '  sisi help                          this text',
}

ENV = (
    "Three places: the product (this clone, read-only at run time), your personal data (~/.local/share/sisi,\n"
    "its own git repository), and scratch (~/.local/state/sisi). Environment: SISI_HOME, SISI_DATA, SISI_STATE,\n"
    "SISI_LIB, SISI_TOOL, SISI_VERIFIERS, SISI_DONE (what each means: `sisi help help`).\n")

# (heading, [(command names, usage shown, one line)]) in reading order. Every command the dispatcher
# accepts is named in exactly one row.
GROUPS = (
    ("For the person", (
        (("install", "uninstall", "doctor"), "install [--dry-run] | uninstall | doctor", "wire sisi into your tools, undo it, check it"),
        (("update",), "update", "update the product; back up, migrate, rebuild your data"),
        (("status",), "status [--json] [--learning]", "recent units with scorecards, then trends"),
        (("rollback",), "rollback", "switch the stable copy back to the previous release"),
        (("approve",), "approve [ID --yes|--no]", "list what waits for you; decide one (terminal only)"),
        (("oracle",), "oracle", "what you want: the principles recorded by `sisi learn`"),
        (("export", "import"), "export [PATH] | import PATH", "one tar.gz of personal data and results; restore it"),
    )),
    ("For the agent at work", (
        (("contract",), "contract init|check|waive|trust|untrust", "start, validate and bend the unit's contract"),
        (("unit",), "unit close|pause|direct|show|list", "close a unit with its scorecard, record a wait, look back"),
        (("risk",), "risk [--json]", "the risk floor of the working-tree change; what it requires"),
        (("verify",), "verify [--deep|--all|--state] [--json]", "run the contract's checks; nothing unrun passes"),
        (("retro",), "retro [--finding F ...|--adopt ID]", "the unit's record; record a finding, with its cause and fix"),
        (("learn",), "learn [--scope S] TEXT | --withdraw ID", "record what the owner said; take a mistaken one back"),
        (("route",), "route --kind K --difficulty N [--explain]", "the most affordable usable worker for a task"),
        (("delegate",), "delegate brief|check|guide|judge|amend", "write, check, run and judge a brief for a worker"),
        (("workers",), "workers [fact|avoid|prefer|only|note|down|up]", "workers found here, what each costs, the judged record"),
        (("verifiers",), "verifiers show|for|doctor|lint|WORDS", "ways to know work is correct"),
        (("done",), "done [ID|for \"<work>\"]", "the recipe saying what makes a kind of work done"),
        (("rule",), "rule [N|ID]", "the rules and how each is enforced"),
        (("handover",), "handover [--all] | done ID --where PATH", "learnings waiting to be filed in this project's docs"),
        (("lessons",), "lessons [--json] | show ID", "the learning records and their statuses"),
        (("eval",), "eval list|add|run|compare|shadow|status", "the evaluation harness: cases, replay, comparison"),
    )),
    ("Hooks (the tools call these)", (
        (("tick",), "tick [--tool NAME]", "session start"),
        (("prompt",), "prompt [--tool NAME]", "each request: the matching recipe and lessons as context"),
        (("gate",), "gate [--tool NAME]", "end of turn: sends the agent back if the work is not ready"),
        (("watch",), "watch [--before|--after]", "around shell commands: did the project change?"),
    )),
    ("Maintaining sisi", (
        (("release",), "release [--deep]", "check the source, then make the stable copy the tools run"),
        (("promote",), "promote [ID|L-NNNN] [--apply] | --export", "move a personal item or learning into the product"),
        (("cycle",), "cycle [due|apply|check|revert|help]", "turn proposed learnings into mechanisms"),
        (("overlay",), "overlay list|diff|add-rule|...|revert", "your learned changes to rules, verifiers, recipes"),
        (("harvest", "tasks", "escapes", "checks"), "harvest | tasks | escapes | checks", "the data layer behind `sisi eval`"),
        (("version",), "version", "print the product version"),
        (("help",), "help [COMMAND]", "this text, or one command in full"),
    )),
)


LONG["help"] = (
    "  sisi help [COMMAND]                this text, or one command in full (also `sisi COMMAND --help`)\n"
    "  Environment: SISI_HOME (stands in for the home directory), SISI_DATA (personal data folder),\n"
    "      SISI_STATE (scratch dir), SISI_LIB (where stable releases live, default ~/.local/lib/sisi),\n"
    "      SISI_TOOL (name recorded with results), SISI_VERIFIERS and SISI_DONE (library directories,\n"
    "      default verifiers/ and done/ in the product).\n")


def names():
    """Every command named in GROUPS."""
    return [n for _h, rows in GROUPS for row in rows for n in row[0]]


def short():
    out = ["sisi: a shared rulebook and enforced definitions of done for every AI coding CLI.",
           "`sisi help COMMAND` or `sisi COMMAND --help` explains one command in full."]
    for heading, rows in GROUPS:
        out += ["", heading]
        out += ["  sisi %-41s %s" % (usage, text) for _names, usage, text in rows]
    out += ["", ENV.rstrip("\n")]
    return "\n".join(out) + "\n"


def long(cmd):
    """The full text for one command, or None when `cmd` is not a command."""
    for _h, rows in GROUPS:
        for names_, usage, text in rows:
            if cmd in names_:
                return LONG.get(cmd) or "  sisi %s    %s\n" % (usage, text)
    return None
