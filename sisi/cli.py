"""sisi: hooks that force a retro and turn what it finds into rules, and a models table to delegate by."""
import os, sys, time

HELP = """sisi: a self-improvement loop for AI coding agents.

Before and after the work
  sisi done --goal G --check C [--check C ...] --next N
                                   record what done means and what the person will need next; nothing starts before
  sisi done --pass N EVIDENCE | --fail N WHY
                                   give a check its verdict; `sisi done` alone shows it

The learning loop
  sisi retro                       what happened in this piece of work, to set against the objective
  sisi retro --gap G --cause C --improve I --term T [--scope user]
                                   record the gap; the improvement becomes a rule at once
  sisi retro --no-gap TEXT --term T --better B | --later TEXT
                                   nothing fell short; or the work is not finished yet
  sisi learn [--project] TEXT      the person's own words become a rule at once
  sisi rules                       the learned rules in force here
  sisi rules organize [--record FILE]
                                   the brief for a cheap worker to audit and organize them; record its answer
  sisi rules revert                undo the last change to the learned rules

Delegation
  sisi models                      the workers you have: what each is good at and what it costs
  sisi models research [--record FILE]
                                   the brief for a research worker to rebuild that table; record its answer
  sisi pick routine|ordinary|hard [--review-of WORKER] [--not WORKER ...]
                                   the wheel gives you one worker of that class; one pick, one delegation
  sisi judge WORKER good|bad WHY   how a delegation went
  sisi direct REASON               allow yourself more direct tool calls this turn, with the reason

Setting up
  sisi install | uninstall | doctor
                                   put the rulebook (and hooks, where the tool has them) into every agent tool
                                   installed here; take them out again; show how each tool stands
  sisi release | rollback          make this copy the one the hooks run; go back to the one before
  sisi update                      fetch the newest sisi from where this release came from and release it

Hooks (the agent tool calls these): sisi tick | prompt | watch | gate

Your rules, models table and retro log live in ~/.local/share/sisi ($SISI_DATA, else $XDG_DATA_HOME/sisi), a git repository. Settings: "core" in
its config.json (gate, meter, direct_calls, direct_extension, rules_lines, rules_chars, organize_after,
research_days, shell_workers)."""


def main(argv):
    from . import hooks, models, rules, store
    cmd, args = (argv[0] if argv else "help"), argv[1:]
    if cmd in ("tick", "prompt", "watch", "gate"):
        try:
            p = hooks.payload()
            if cmd == "gate":
                return hooks.gate(p, "--subagent" in args)
            return {"tick": hooks.tick, "prompt": hooks.prompt, "watch": hooks.watch}[cmd](p)
        except Exception as e:  # a hook must never break the agent's session
            store.append(os.path.join(store.STATE, "core-errors.log"), "%s %s: %r" % (time.strftime("%Y-%m-%dT%H:%M:%S"), cmd, e))
            return 0
    if cmd in ("retro", "done"):
        from . import retro
        return (retro.run if cmd == "retro" else retro.done)(args)
    one = {"rules": rules.run, "pick": models.pick, "learn": rules.learn, "models": models.run, "judge": models.judge,
           "direct": hooks.direct}
    if cmd in one:
        return one[cmd](args)
    if cmd in ("install", "uninstall", "release", "update", "rollback", "doctor"):
        from . import install
        return getattr(install, cmd)()
    if cmd == "rulebook":
        print(rules.build_rulebook())
        return 0
    if cmd == "version":
        print(store.read(os.path.join(store.ROOT, "VERSION")).strip())
        return 0
    print(HELP)
    return 0 if cmd in ("help", "--help", "-h") else 1
