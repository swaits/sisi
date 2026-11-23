# **sisi** is still improving

**Your AI agents get better at working for you on every turn, in every tool, automatically, just by
being used. There is nothing to schedule or maintain.** Each piece of work ends with the agent
recording how it could have gone better. That lesson goes into one store that every agent in every
tool reads, so a later turn in any tool can start from it. A lesson that recurs after being shown is
strengthened until an enforced check stops the mistake.

The direction is fixed: state an outcome at a higher level and get it back correct, complete,
verified by the strongest method available and fast, with fewer interruptions. An agent writes
down how success will be checked, runs those checks before saying it is done, and is sent back
when they fail.

sisi is a shared rulebook and a small command-line tool in plain Python with no dependencies. What
it learns about you is kept outside the clone, so updating never loses it.

The name is recursive: its first word is the name itself. It is also a plain statement of where
things stand: each turn leaves your tools a little better, and that work is never finished. What is
not yet shown is that this makes agents measurably better over weeks of real use. `sisi improve`
reports the counted evidence for that question, and it needs real use to have data.

## How it works

`sisi retro` ends each piece of work by recording how it could have gone better: the moment, the
cause, and the change that would make a later agent do it right without being told, in the words a
different agent would use for that work. The lesson takes effect in your personal store at once and
is offered to later agents starting matching work. If the problem recurs after a lesson has been
shown, it is strengthened: a note, a candidate rule, then an enforced check the gate runs.
`sisi cycle` consolidates lessons into rules and library entries without growing the rulebook.
Whether it is due is checked during normal use, so nothing is scheduled; see
[docs/learning.md](docs/learning.md). `sisi lessons digest` prints what has been learned in plain
words, grouped by topic. Where a tool allows it, the matching recipe and lessons are also delivered
the moment a request arrives (`sisi prompt`), and each rule names the command that explains it
(`sisi rule`). Delegated work is routed the same way, by measured results rather than a fixed
list of models: `sisi workers` and `sisi delegate`; see [docs/workers.md](docs/workers.md).

Improvement needs a way to tell success from failure:

- **A contract of executable checks.** `.sisi/contract.json` lists the checks that decide success,
  each with its claim, a command, the result expected and its rung, plus invariants (what must not
  get worse), assumptions and open questions. The agent drafts it from the request.
- **A ladder of six rungs.** Rung 1 proof, model checking or the type system; rung 2
  property-based testing, fuzzing or comparison with a reference; rung 3 examples; rung 4 golden
  files and snapshots, including screenshots; rung 5 a rubric scored by an independent judge; rung
  6 the human. Use the highest feasible rung; some claim kinds have a minimum (concurrency,
  parsing, money, state machines, data migration).
- **An end-of-turn gate.** A hook runs `sisi verify` when the agent tries to finish. A failing or
  unrun check sends it back, a large change with no contract sends it back to write one, and small
  edits pass. After repeated send-backs it is let through marked unverified, so a broken check
  cannot trap a session.
- **Time to delivery.** When the gate lets a turn end, sisi records how long the verified result
  took and how often the agent was sent back. `sisi time` reports it.
- **One shared store.** Rulebook, lessons, results and settings are written once and read by every
  tool, connected by reference (an import line or a symlink), never by copy.

## Quick start

Requirements: Python 3.9 or newer, and `git`, on Linux or macOS. Windows is not supported (the code
imports `fcntl`). The minimum Python version is proved by CI; the reasoning is in
[CONTRIBUTING.md](CONTRIBUTING.md).

    git clone https://github.com/swaits/sisi.git
    cd sisi
    bin/sisi install --dry-run
    bin/sisi install
    bin/sisi doctor

The dry run prints every change and makes none. Install backs up every file it edits, adds only an
import line, a link, hook entries or a generated plugin, and skips a missing configuration folder.
It links the command as `~/.local/bin/sisi`; make sure that folder is on your `PATH`, or call
`bin/sisi` from the clone. `sisi doctor` shows what is wired and anything you must still do.

For a first contract, change to one of your own projects and run
`sisi contract init --goal "slugify() turns titles into URL slugs"`. That skeleton's placeholder
check fails until you replace it. For a small function with a test next to it:

    {
      "id": "slugify",
      "goal": "slugify() turns titles into URL slugs",
      "checks": [
        {
          "id": "examples",
          "claim": "known titles give the expected slugs, and slugifying twice changes nothing",
          "kind": "general",
          "rung": 3,
          "cmd": "python3 -m unittest -q test_slugify",
          "expect": {"exit": 0},
          "timeout_s": 30
        }
      ],
      "invariants": [],
      "assumptions": ["Non-ASCII letters are dropped, not transliterated."],
      "questions": []
    }

Trimmed output:

    $ sisi verify
    ...
    OK

`sisi verify` succeeds only when every check passes; `sisi help` lists the other exit meanings.
With a hook wired you do not run it yourself: the agent writes the contract and the gate runs it.

## Supported tools

Enforcement is what happens at the end of a turn; evidence is how the wiring was checked.
`sisi doctor` gives the live state on your machine. Per-tool detail, limits and steps you must
take are in [docs/harnesses.md](docs/harnesses.md).

| Tool | Enforcement | Evidence |
|---|---|---|
| Claude Code | blocks | ran end to end |
| Codex CLI | blocks | documentation; session-start hook fired live |
| Gemini CLI | blocks | documentation |
| GitHub Copilot CLI | blocks | ran end to end |
| Pi | blocks | documentation; extension loaded, tick ran live |
| Qwen Code | blocks | documentation; session-start hook fired live |
| Cursor (no confirmed global rulebook file) | sends a follow-up | documentation |
| Aider (existing config file only) | rulebook only | documentation |
| Amp | rulebook only | documentation |
| Cline | rulebook only | documentation |
| Crush | rulebook only | documentation |
| Goose | rulebook only | documentation |
| Grok CLI | rulebook only | verified with `grok inspect` |
| Kiro | rulebook only | documentation |
| Windsurf (pointer file) | rulebook only | documentation |
| Zed | rulebook only | documentation |
| Antigravity (through the shared Gemini file) | unknown | nothing wired separately |
| Muse Code (through Claude Code or Codex files) | unknown | nothing wired directly |
| OpenCode | unknown | documentation; plugin loading verified live |
| Orca | through its provider | host app; nothing to wire |
| T3 Code | through its provider | host app; nothing to wire |

Where there is no gate, the rulebook still tells the agent to write and run a contract, but nothing
enforces it.

## The verifier library

sisi ships verification techniques and recipes that say what "done" means for a kind of work, such
as a bug fix or a data migration. Each technique gives an example, the exact command, what passing
looks like, and a check to paste into a contract. `sisi verifiers` and `sisi done` list them, so
agents query them instead of inventing a check. Trimmed output:

    $ sisi verifiers for "a parser that must not crash on hostile input"
    1. hostile-input-from-schema  rung 2  cost medium  installed: no
    2. klee  rung 1  cost high  installed: no

Matching is by word overlap, weighted toward the question each entry answers, so phrase the claim
as a doubt and read the top results rather than trusting the first. `sisi verifiers show ID` prints
an entry in full, `sisi verifiers doctor` reports installed tools, and `sisi done for "bug fix"`
prints a recipe. Format and quality bar: [docs/verifier-format.md](docs/verifier-format.md).

## Where data lives, updating and uninstalling

- **The product** is the clone: code, base rulebook, library and defaults. It is never written at
  run time.
- **What sisi learns for you** lives in `~/.local/share/sisi` (or `$SISI_DATA`), a local git
  repository that is never pushed.
- **Scratch** that can be rebuilt lives in `~/.local/state/sisi` (or `$SISI_STATE`).

`sisi update` replaces only the product, after backing up your personal data, and reapplies what
you learned. `sisi status` shows the live state; the layout is in
[docs/personal-data.md](docs/personal-data.md).

`sisi uninstall` removes the import line, hooks and links. A file you have not edited since install
is restored byte for byte. A file you edited keeps your edits and loses only sisi's entries. A file
sisi cannot edit with certainty is skipped and reported. Personal data and scratch are left for you
to delete. The exact guarantee is in [docs/harnesses.md](docs/harnesses.md).

## Designed but not built

[docs/design.md](docs/design.md) separates what is built from what is not. The main missing pieces:

- The build conductor (`sisi build "<what I want>"`) and its question queue (`sisi inbox`).
  Neither command exists.
- Replay experiments on a task set before a learned change ships, a separate coach run, brief
  templates and playbooks. Learned changes instead ship to your overlay first and are judged by
  measured deliveries, with exact revert as the safety net.
- The taste judge (a model judging at rung 5), a git-survival signal, transcript harvest beyond
  Claude Code, and proven end-to-end enforcement in OpenCode, reported by `sisi doctor` as unknown.

## Security

sisi runs commands from a project contract, so a contract you did not write is untrusted until you
read it and run `sisi contract trust`; until then `sisi verify` refuses and the gate runs nothing.
sisi does not sandbox what a trusted contract runs. See [SECURITY.md](SECURITY.md), including how
to report a problem privately.

## Contributing

Running the tests, the standard-library-only rule, the library entry format, and what belongs in
the product rather than your own overlay are in [CONTRIBUTING.md](CONTRIBUTING.md). For the release
you have, run `sisi --version`; changes between releases are in [CHANGELOG.md](CHANGELOG.md), and
all docs are indexed in [docs/README.md](docs/README.md).

## Licence

MIT. Copyright (c) Stephen Waits. See [LICENSE](LICENSE).
