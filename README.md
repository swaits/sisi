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
in exactly one class, so the wheel never mixes tiers; weighted by table order and by the square of the speed ratio),
and a delegation to a worker the wheel did not give is refused. One pick, one delegation. A host that names its models
shortly (Claude Code's `Agent` tool says `sonnet`) may give one whole segment of the picked model id, so name a worker
by its full model id (`claude-sonnet-5-5`); anywhere else the name must match whole.

**Done.** Nothing starts before `sisi done` has recorded the goal, the checks that decide success and what the
person will need next: delegating or editing is refused until then. Every check needs a verdict
(`sisi done --pass N` or `--fail N`) before the turn ends; a turn that changed things, or failed a check,
is sent to the retro, and any other closes itself, as does work that took under `retro_minutes`, passed every check and delegated nothing. While a delegated job is open and not late, a stop is not held up for checks without a verdict. Each record in `retro.jsonl` carries `session_id`, `retro_seconds` (when demanded),
the numbers (minutes, messages, tool calls, delegations, checks) and the `term` it fell short on (`value`, `evidence`, `time`, `cost`,
`attention` or `learning`: the terms of the objective), and `sisi retro` lays the facts out under those terms and shows their trend.

**Faults.** Record any fault you see with `sisi fault "<what is wrong>"` (kept per project across sessions).
Where the tool has hooks, session start and every request show the faults still not fixed, and with the gate
on, the end-of-turn hook sends the lead back up to twice on an open fault until a fix is started (`--started N`),
a blocker is named (`--blocked N`), or evidence closes it (`--fixed N`). sisi also opens faults itself at
session start and each request when free disk space falls below `disk_free_percent`, this session uses more
than `disk_drop_percent` of the disk, or the repository has more than `checkouts` linked worktrees. `sisi retro`
lists the faults still open.

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

| Tool | Rulebook (in its folder) | Hooks | Project rules |
|---|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md` | `settings.json` | session-start print (reads `AGENTS.md` only without `CLAUDE.md`) |
| Codex | `~/.codex/AGENTS.md` | `hooks.json` (the person trusts them once in Codex's `/hooks`) | session-start print; `AGENTS.md` note is in the file it reads |
| Qwen Code | `~/.qwen/QWEN.md` | `settings.json` | session-start print; `AGENTS.md` note is in the file it reads |
| Grok | `~/.grok/AGENTS.md` | none: Grok runs the hooks in `~/.claude/settings.json` | `AGENTS.md` note is in the file it reads |
| OpenCode, Antigravity (`~/.gemini`), Pi, Kiro, Copilot, Amp | their global instructions file | none: not confirmed | `AGENTS.md` note is in the file the tool reads |
| Crush | `~/.config/crush/CRUSH.md` | none: not confirmed | `AGENTS.md` note is read only when started at project root |
| Cursor | none documented | not covered | `AGENTS.md` note is in the file Cursor CLI reads |
| Muse | none documented | not covered | unconfirmed |

Hooks read a tool's input under whichever field names it uses (`session_id`, `sessionId`, `conversationId`,
`toolCall.name`, …), and the class of each tool call (shell, read, edit, search, web, delegate) comes from
`canon/tools.json`: add a tool's own names there. `sisi doctor` prints one line per tool with what it has and what
its limits are.

## What the agent does with it

| Command | What it is for |
|---|---|
| `sisi done --goal … --check … [--check …] --next …` | Record what done means and what comes next; nothing starts before |
| `sisi done --pass N "…"` / `--fail N "…"` | Give a check its verdict and evidence; `sisi done` alone shows it |
| `sisi fault "<what is wrong>"` / `--started\|--blocked\|--fixed N "…"` | Record an open fault in this project, start a fix, name a blocker, or close it; `sisi fault` alone lists them |
| `sisi pick routine\|ordinary\|hard [--review-of WORKER] [--not WORKER]` | The wheel gives one worker; a review goes to a different maker |
| `sisi retro` | Print what happened in this piece of work, to set against the objective |
| `sisi retro --gap … --cause … --improve … --term T [--scope user]` | Record the gap and the term of the objective it fell short on; the improvement is a rule at once |
| `sisi retro --no-gap … --term T --better …` | Nothing fell short, but work can always be done better: name the term and the one concrete thing that would have scored better (recorded with the retro; it becomes a rule only if it recurs, when the rules are organized) |
| `sisi retro --later …` | The work is not finished yet |
| `sisi learn [--project] "…"` | The person's own words become a rule at once |
| `sisi rules` / `sisi rules organize [--record FILE]` / `sisi rules revert` | See the learned rules; have a worker organize them; undo the last rule change made with `learn`, a retro or `organize`, in the user list or a project's `.sisi/rules.md` (not the one-time move of old rules; a second `revert` re-applies what the first undid; it declines, changing nothing, when the project file changed since or its folder moved or is gone) |
| `sisi models` / `sisi models research [--record FILE]` | The workers table; have a worker rebuild it |
| `sisi judge WORKER good\|bad "…" [--minutes N] [--newest]` | How a delegation went; the minutes are measured from the pick's delegation (or `--minutes N`) and make the wheel favour faster workers. With several of one worker's jobs open, the oldest is judged first, `--newest` the newest |
| `sisi direct "…"` | Allow more direct tool calls this turn, with the reason |

## Where things live

Rules live at three levels:

- **The product** (this repository): the code in `sisi/`, and the rulebook in `canon/core.md` — rules useful to everyone
  using sisi, the same for all users. `SPEC.md` is what it aims at.
- **Your store** (`$SISI_DATA`, else `$XDG_DATA_HOME/sisi`, else `~/.local/share/sisi`; a git repository): `rules/user.md`
  (how you like to work, across all your projects), `models.md` (your workers), `retro.jsonl` (each piece of work: session,
  `retro_seconds`, counts, goal, term) and `outcomes.jsonl` (each judged delegation: session, `project_key`, `model`,
  `started`/`ended`, minutes, verdict, why). All plain text you can read and edit.
- **Each project** (`.sisi/rules.md` in the project's folder: in a git repository, the root of its main checkout, shared by
  all its worktrees; outside git, the folder sisi is run in): rules specific to one project. In a bare repository with
  worktrees or a repository made with `--separate-git-dir`, each worktree (or the main checkout and linked worktree)
  has its own list, and `GIT_DIR` in the environment is followed. A worktree's own checked-in
  copy of `.sisi/rules.md` is the committed version; new rules are written in the main checkout, for you to commit. You choose
  whether to check `.sisi/` into git or ignore it (sisi works either way, and never commits or stages it for you). When
  sisi adds to, organizes or moves old rules into `.sisi/rules.md`, it also puts a marked note (`<!-- sisi:begin -->` ... `<!-- sisi:end -->`) in the project
  root's `AGENTS.md` pointing to `.sisi/rules.md`, so the note is in the file those tools read; `revert` does not add or remove the note; after undoing a project's only rule, the empty `.sisi/` folder and the note remain. It is skipped with a
  one-line reason when `AGENTS.md` is read-only, a folder, not UTF-8, a link that is broken or points outside the project
  or into `.git` or `.sisi`, or if writing fails. Deleting the block removes it only until the next rule is written, when
  sisi puts it back. If `AGENTS.md` is checked in, git shows it as modified until you commit it (sisi never commits it),
  and if `.sisi/` is git-ignored, people who clone the project get a note pointing at a file they do not have. A
  hard-linked `AGENTS.md` is replaced by a separate file. Old project rules moved from your store are not undone by
  `revert`; the old list stays in your store's git history (`git -C ~/.local/share/sisi log -p -- rules/projects`).
- **The rulebook every session loads** (`generated/core.md`) is built from the product (`canon/core.md`) and your user
  rules (`rules/user.md`). Project rules are not in the generated rulebook; they are printed at session start by the `tick`
  hook (for tools whose session-start output reaches the agent), pointed to by the `AGENTS.md` note, and shown by `sisi rules`.
- **Scratch** (session state, bytecode): `$SISI_STATE`, else `$XDG_STATE_HOME/sisi`, else `~/.local/state/sisi`.
  Releases live in `$SISI_LIB`, else `~/.local/lib/sisi`.

Settings go under `"core"` in `config.json` in your store: `gate`, `meter`, `direct_calls` (8),
`direct_extension` (8), `rules_lines` (30), `rules_chars` (4000), `organize_after` (8), `research_days` (7), `worker_minutes` (15),
`shell_workers` (false), `retro_minutes` (5: work that passed every check, delegated nothing and took less than this many minutes from `sisi done` closes without a retro),
`disk_free_percent` (20), `disk_drop_percent` (5), `checkouts` (8; setting any of these three to 0 turns that tripwire off). Workers are started with the host's own delegation tool, so by default a shell command
that starts a worker (`opencode`, `muse`, `agy`: the first word of a command line in your models table) is
refused. Set `"shell_workers": true` to allow it: it is then free on the meter, and needs a pick like any
delegation, and `sisi pick` prints the command line.
