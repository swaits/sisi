"""sisi: hooks that force a retro and turn what it finds into rules, and a models table to delegate by."""
import os, sys, time

HELP = """sisi: a self-improvement loop for AI coding agents.

The learning loop
  sisi retro                       what happened in this piece of work, to set against the objective
  sisi retro --gap G --cause C --improve I [--scope user]
                                   record the gap; the improvement becomes a rule at once
  sisi retro --no-gap TEXT | --later TEXT
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
  sisi judge WORKER good|bad WHY   how a delegation went
  sisi direct REASON               allow yourself more direct tool calls this turn, with the reason

Setting up
  sisi install | doctor            wire the hooks and the rulebook into the agent tool; check them
  sisi release | rollback          make this copy the one the hooks run; go back to the one before

Hooks (the agent tool calls these): sisi tick | prompt | watch | gate

Your rules, models table and retro log live in ~/.local/share/sisi, a git repository. Settings: "core" in
its config.json (gate, meter, direct_calls, direct_extension, rules_lines, rules_chars, organize_after,
research_days)."""


def main(argv):
    from . import hooks, install, models, retro, rules, store
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
    if cmd == "retro":
        return retro.run(args)
    if cmd == "rules":
        return rules.run(args)
    if cmd == "learn":
        return rules.learn(args)
    if cmd == "models":
        return models.run(args)
    if cmd == "judge":
        return models.judge(args)
    if cmd == "direct":
        return hooks.direct(args)
    if cmd in ("install", "release", "rollback", "doctor"):
        return getattr(install, cmd)()
    if cmd == "rulebook":
        print(rules.build_rulebook())
        return 0
    if cmd == "version":
        print(store.read(os.path.join(store.ROOT, "VERSION")).strip())
        return 0
    print(HELP)
    return 0 if cmd in ("help", "--help", "-h") else 1
