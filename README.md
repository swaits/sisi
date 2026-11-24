# sisi

A self-improvement loop for AI coding agents. It is two loops and nothing else.

**Learning.** Hooks into the agent force a retro when work was done. The retro sets what happened against
the objective, names the gap and its cause, and states the instruction that would have prevented it. That
instruction becomes a rule at once, and the next session reads it. Now and then a cheap worker audits and
organizes the rules.

**Delegation.** The lead agent is told to delegate everything, and is stopped when it does the work itself.
It routes by a models table: which workers you have, what each is good at, what it costs. A research worker
rebuilds that table when it gets old, and every judged delegation feeds the next research.

## Install

```
git clone <this repository> && cd sisi
./bin/sisi release      # runs the tests, then puts a copy in ~/.local/lib/sisi
./bin/sisi install      # adds four hooks to Claude Code's settings and the rulebook to its instructions
sisi doctor
```

Python 3 standard library only. `sisi rollback` goes back to the release before.

## What the agent does with it

| Command | What it is for |
|---|---|
| `sisi retro` | Print what happened in this piece of work, to set against the objective |
| `sisi retro --gap … --cause … --improve … [--scope user]` | Record the gap; the improvement is a rule at once |
| `sisi retro --no-gap …` / `--later …` | Nothing fell short; or the work is not finished yet |
| `sisi learn [--project] "…"` | The person's own words become a rule at once |
| `sisi rules` / `sisi rules organize [--record FILE]` / `sisi rules revert` | See the learned rules; have a worker organize them; undo the last change |
| `sisi models` / `sisi models research [--record FILE]` | The workers table; have a worker rebuild it |
| `sisi judge WORKER good\|bad "…"` | How a delegation went |
| `sisi direct "…"` | Allow more direct tool calls this turn, with the reason |

## Where things live

- **The product** (this repository): the code in `sisi/`, the rulebook in `canon/core.md`. The same for
  everyone. `SPEC.md` is what it aims at.
- **Your store** (`~/.local/share/sisi`, a git repository): `rules/user.md` and `rules/projects/*.md` (what
  was learned), `models.md` (your workers), `retro.jsonl` and `outcomes.jsonl` (what happened). All plain
  text you can read and edit.
- **The rulebook every session loads** is generated from the two: `canon/core.md`, then your learned rules.

Settings go under `"core"` in `config.json` in your store: `gate`, `meter`, `direct_calls` (8),
`direct_extension` (8), `rules_lines` (30), `rules_chars` (2500), `organize_after` (8), `research_days` (7).
