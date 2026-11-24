# sisi

A self-improvement loop for AI coding agents. It is two loops and nothing else.

**Learning.** Hooks into the agent force a retro when work was done. The retro sets what happened against
the objective, names the gap and its cause, and states the instruction that would have prevented it. That
instruction becomes a rule at once, and the next session reads it. Now and then a cheap worker audits and
organizes the rules.

**Delegation.** The lead agent is told to delegate everything, and is stopped when it does the work itself.
It routes by a models table: which workers you have, what each is good at, what it costs. A research worker
rebuilds that table when it gets old, and every judged delegation feeds the next research. The lead does not
choose the worker: `sisi pick CLASS` spins a wheel over the workers of that class (a capability tier: each model is
in exactly one class, so the wheel never mixes tiers; weighted by table order and by speed),
and a delegation to a worker the wheel did not give is refused. One pick, one delegation. A host that names its models
shortly (Claude Code's `Agent` tool says `sonnet`) may give one whole segment of the picked model id, so name a worker
by its full model id (`claude-sonnet-5-5`); anywhere else the name must match whole.

**Done.** Nothing starts before `sisi done` has recorded the goal, the checks that decide success and what the
person will need next: delegating or editing is refused until then. Every check needs a verdict
(`sisi done --pass N` or `--fail N`) before the turn ends; a turn that changed things, or failed a check,
is sent to the retro, and any other closes itself. Each record in `retro.jsonl` carries the numbers
(minutes, messages, tool calls, delegations, checks) and the `term` it fell short on (`value`, `evidence`, `time`, `cost`,
`attention` or `learning`: the terms of the objective), and `sisi retro` lays the facts out under those terms and shows their trend.

## Install

```
git clone <this repository> && cd sisi
./bin/sisi release      # runs the tests, then puts a copy in ~/.local/lib/sisi
./bin/sisi install      # the rulebook (and hooks, where the tool has them) into every agent tool installed here
sisi doctor             # how each tool stands
```

Python 3 standard library only. `sisi rollback` goes back to the release before. `sisi uninstall` takes out exactly
what `install` put in. `sisi update` fetches the newest sisi from the repository the release in use was made from
(`sisi release` records that remote: `github`, else `origin`) and releases it, so a checkout is only needed once.
`sisi release` run through the installed command never copies that release onto itself: it releases the checkout the
release records it came from when that is a local checkout, and otherwise says to run it from a checkout.

## Which agent tools

`sisi install` looks at the tools in `canon/harnesses.json` (plain data: add a tool by adding a line). A tool that is
not installed (its folder is absent) gets nothing created. For a tool that is installed:

- **The rulebook.** An absent instructions file becomes a link to the generated rulebook. A real file gets the
  rulebook in a block between `<!-- sisi:begin -->` and `<!-- sisi:end -->` at the top, every other byte left alone;
  the block is refreshed whenever the rulebook is rebuilt (Claude Code gets an `@import` of the rulebook in the same
  block). A link that points anywhere else is not sisi's: it is left alone and reported.
- **The four hooks** (`tick`, `prompt`, `watch`, `gate`), only for tools whose hook files have been confirmed to take
  the same shape as Claude Code's: sisi's entries (old or new) are removed from the file and the current ones added;
  everything else in the file is kept. A file sisi cannot edit safely (comments, a trailing comma, a symlink to
  nowhere, read-only, hooks of an unexpected shape) is left alone and reported.

| Tool | Rulebook (in its folder) | Hooks |
|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md` | `settings.json` |
| Codex | `~/.codex/AGENTS.md` | `hooks.json` (the person trusts them once in Codex's `/hooks`) |
| Qwen Code | `~/.qwen/QWEN.md` | `settings.json` |
| Grok | `~/.grok/AGENTS.md` | none: Grok runs the hooks in `~/.claude/settings.json` |
| OpenCode, Antigravity (`~/.gemini`), Pi, Kiro, Copilot, Crush, Amp | their global instructions file | none: not confirmed |
| Muse, Cursor | none documented | not covered |

Hooks read a tool's input under whichever field names it uses (`session_id`, `sessionId`, `conversationId`,
`toolCall.name`, …), and the class of each tool call (shell, read, edit, search, web, delegate) comes from
`canon/tools.json`: add a tool's own names there. `sisi doctor` prints one line per tool with what it has and what
its limits are.

## What the agent does with it

| Command | What it is for |
|---|---|
| `sisi done --goal … --check … [--check …] --next …` | Record what done means and what comes next; nothing starts before |
| `sisi done --pass N "…"` / `--fail N "…"` | Give a check its verdict and evidence; `sisi done` alone shows it |
| `sisi pick routine\|ordinary\|hard [--review-of WORKER] [--not WORKER]` | The wheel gives one worker; a review goes to a different maker |
| `sisi retro` | Print what happened in this piece of work, to set against the objective |
| `sisi retro --gap … --cause … --improve … --term T [--scope user]` | Record the gap and the term of the objective it fell short on; the improvement is a rule at once |
| `sisi retro --no-gap … --term T --better …` | Nothing fell short, but work can always be done better: name the term and the one concrete thing that would have scored better (recorded with the retro; it becomes a rule only if it recurs, when the rules are organized) |
| `sisi retro --later …` | The work is not finished yet |
| `sisi learn [--project] "…"` | The person's own words become a rule at once |
| `sisi rules` / `sisi rules organize [--record FILE]` / `sisi rules revert` | See the learned rules; have a worker organize them; undo the last change |
| `sisi models` / `sisi models research [--record FILE]` | The workers table; have a worker rebuild it |
| `sisi judge WORKER good\|bad "…" [--minutes N] [--newest]` | How a delegation went; the minutes are measured from the pick's delegation (or `--minutes N`) and make the wheel favour faster workers. With several of one worker's jobs open, the oldest is judged first, `--newest` the newest |
| `sisi direct "…"` | Allow more direct tool calls this turn, with the reason |

## Where things live

- **The product** (this repository): the code in `sisi/`, the rulebook in `canon/core.md`. The same for
  everyone. `SPEC.md` is what it aims at.
- **Your store** (`$SISI_DATA`, else `$XDG_DATA_HOME/sisi`, else `~/.local/share/sisi`; a git repository): `rules/user.md` and `rules/projects/*.md` (what
  was learned), `models.md` (your workers), `retro.jsonl` and `outcomes.jsonl` (what happened). All plain
  text you can read and edit.
- **The rulebook every session loads** is generated from the two: `canon/core.md`, then your learned rules.
- **Scratch** (session state, bytecode): `$SISI_STATE`, else `$XDG_STATE_HOME/sisi`, else `~/.local/state/sisi`.
  Releases live in `$SISI_LIB`, else `~/.local/lib/sisi`.

Settings go under `"core"` in `config.json` in your store: `gate`, `meter`, `direct_calls` (8),
`direct_extension` (8), `rules_lines` (30), `rules_chars` (4000), `organize_after` (8), `research_days` (7),
`shell_workers` (false). Workers are started with the host's own delegation tool, so by default a shell command
that starts a worker (`opencode`, `muse`, `agy`: the first word of a command line in your models table) is
refused. Set `"shell_workers": true` to allow it: it is then free on the meter, and needs a pick like any
delegation, and `sisi pick` prints the command line.
