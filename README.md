# sisi

sisi is a rulebook and a small command-line tool, shared by every AI coding agent on your machine (Claude Code,
Codex, OpenCode). It makes an agent write down how success will be checked, run those checks before it says it is
done, and record afterwards how the work could have gone better. It is plain Python with no dependencies, and what
it learns about you is kept outside the clone, so updating never loses it.

## Why it exists

- **Agents report "done" without proof.** The definition of done is usually a sentence in an instruction file.
  Nothing makes the agent write it as something runnable, and nothing stops it ending a turn when a check fails.
- **Each tool learns separately.** A lesson learned in one tool is lost to the others, and instructions drift apart
  across `CLAUDE.md`, `AGENTS.md` and friends.
- **The work takes too long.** Nobody measures the time from a request to a result that is actually verified, so
  nobody can tell whether a change to the instructions helped.

## How it works

- **A contract per piece of work.** `.sisi/contract.json` in the project lists the checks that decide success,
  each with the claim it supports, a command, the result expected and its rung (below). It can also list
  invariants (what must not get worse), assumptions and open questions. The agent drafts it from the request.
- **A ladder of checks.** Each check is rated by how strong the evidence is: 1 proof, model checking or the type
  system; 2 property-based tests, fuzzing, comparison with a reference; 3 example tests; 4 golden files and
  snapshots, including screenshots; 5 a rubric scored by an independent judge; 6 the human. The rulebook tells the
  agent to use the highest rung that is feasible, and sets a minimum rung for kinds of claim that need it
  (concurrency, parsing, money, state machines, data migration).
- **An end-of-turn gate.** A hook calls `sisi verify` when the agent tries to finish. If a check fails or did not
  run, the agent is sent back with the failures. If a large change has no contract, it is sent back to write one.
  Small edits pass. After three send-backs in a row the agent is let through and the result is marked unverified,
  so a broken check cannot trap a session. Today this blocks in Claude Code only (see the table below).
- **A retrospective after each piece of work.** `sisi retro` records how the work could have gone better, against
  five aims: the human could have worked at a higher level, a stronger check was possible, the human was
  interrupted more than needed, the result was not what they meant, it took longer than it had to. Retros become
  shared lessons (`sisi lessons`), which every tool reads.
- **Time to delivery.** Each time the gate lets a turn end, sisi records the time since the human's last typed
  message, how many times it sent the agent back, and how long the checks took. `sisi time` compares the last 7
  days with the 7 before.
- **One shared store.** The rulebook, lessons, results and settings are written once and read by every tool, which
  are connected by reference (an import line or a symlink), never by copy.

## Quick start

Requirements: Python 3.9 or newer (see "Python versions" below), and `git`. Linux and macOS are what the tests and
CI are meant to cover; Windows is not supported (the code imports `fcntl`).

    git clone https://github.com/swaits/sisi.git
    cd sisi
    bin/sisi install      # wire sisi into the tools it finds; backs up every file it edits
    bin/sisi doctor       # shows what is wired in each tool

`sisi install` links `bin/sisi` as `~/.local/bin/sisi`; make sure that folder is on your `PATH`, or call
`bin/sisi` from the clone. It edits your tools' global instruction files only by adding an import line, and
`sisi uninstall` restores the originals exactly. It skips any tool whose configuration folder does not exist.

Now a first contract. Change to one of your own projects (not the sisi clone), where `sisi contract init --goal "slugify() turns titles into URL slugs"` creates a
skeleton whose placeholder check fails until you replace it. Replace it with a real check. Here, for a small
function and a test next to it:

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

Then:

    $ sisi verify
    ID        KIND     RUNG  TIER  STATUS  SECS
    examples  general  3     fast  passed  0.1

    OK

`sisi verify` exits 0 when every check passes, 1 when one fails, 2 when there is no contract and 3 when the
project is not trusted (see Security). With the hook installed you do not run it yourself: the agent writes the
contract, and the gate runs it at the end of each turn.

## Which tools are supported

| Tool | What `sisi install` does | Instructions loaded | Blocking end-of-turn gate | Session-start hook |
|---|---|---|---|---|
| Claude Code | adds an import line to `~/.claude/CLAUDE.md` and registers hooks in `~/.claude/settings.json` | yes | yes (`Stop` and `SubagentStop` hooks) | yes (`SessionStart`) |
| Codex | links `~/.codex/AGENTS.md` to the generated rulebook | yes | no: Codex hooks are documented but not built here | no |
| OpenCode | links `~/.config/opencode/AGENTS.md` to the generated rulebook | yes | no: no blocking hook has been verified | no |
| Muse | nothing: its global instruction path is unconfirmed | no | unknown | no |

This table comes from `sisi doctor` and the wiring code (`sisi/wiring.py`). Where there is no gate, the rulebook
still tells the agent to write and run a contract, but nothing enforces it. `sisi install` is skipped for a tool
whose configuration folder is missing. Agent skills linked into `~/.agents/skills` are supported by the wiring but
the product ships none yet.

## The verifier library

sisi ships 140 verification techniques in ten sections (design, prove, many-inputs, concurrency, test-quality,
regression, real-world, safety, intent, completeness) and 20 recipes that say what "done" means for a kind of
work (a bug fix, a new library, a data migration, a web UI change, and so on). Each technique has a minimal
example, the exact command, what passing looks like, and a JSON check to paste into a contract. Agents query it
instead of inventing a check from memory:

    $ sisi verifiers for "a parser that must not crash on hostile input"
    1. hostile-input-from-schema  rung 2  cost medium  installed: no
       Does every call my API or tool accepts survive wrong, missing, huge and strange arguments with a clean error and no crash?
    2. klee  rung 1  cost high  installed: no
       Which inputs make this C program crash, overflow or break an assert, found by exploring its paths?
    3. afl-plus-plus  rung 2  cost medium  installed: no
       Can any input make this native program or library crash, hang or trip a sanitizer?
    4. atheris  rung 2  cost medium  installed: no
       Can any input make this Python code raise an exception it should not, hang, or crash the interpreter?

    $ sisi done for "bug fix"               # prints the full recipe for that kind of work

The chooser is keyword matching over each entry's header, so phrase the claim the way you would phrase a doubt, and
read the top few results rather than trusting the first. `sisi verifiers show ID` prints one entry in full, and
`sisi verifiers doctor` says which of the tools are installed on your machine. Format and quality bar:
[docs/verifier-format.md](docs/verifier-format.md). Most entries were run on the author's machine; the rest were checked against the
tools' documentation. Each header says which (`verified: ran | docs | memory`).

## Where data lives, and updating

| Place | Where | What |
|---|---|---|
| Product | the clone | code, base rulebook, verifier library, recipes, defaults. Never written at run time. |
| Personal data | `~/.local/share/sisi` (or `$SISI_DATA`) | lessons, learned changes to rules (an overlay), your preferences, settings, trusted projects. A local git repository with every change committed, never pushed. |
| Scratch | `~/.local/state/sisi` (or `$SISI_STATE`) | rebuildable: transcript index, locks, logs, results |

`sisi update` fast-forwards the clone (`git fetch` then a fast-forward merge; it refuses if you have local
changes), takes a backup of your personal data, migrates its format if needed, reapplies your overlay to the new
rulebook and rebuilds it. If the product changed a rule you had replaced, your version is kept and queued for a
re-test. `sisi export` and `sisi import` move personal data to another machine as one archive. More:
[docs/personal-data.md](docs/personal-data.md).

## Uninstalling

    sisi uninstall

removes the import line, hooks and links, restoring each edited file from its backup. Your personal data and
scratch folders are left alone; delete them yourself if you want them gone. Then delete the clone.

## Status

Version 0.1.0, an early release.

Works today, with tests:

- Contracts, `sisi verify` (fast and deep tiers), the trust mechanism, the end-of-turn gate and session-start hook.
- Wiring for Claude Code (with the blocking gate), Codex and OpenCode (rulebook only), and `sisi doctor`, `audit`.
- The verifier library and recipes, with `sisi verifiers lint`.
- Retros, lessons, quarantined preferences, time to delivery, personal data, overlay, update, export and import,
  releases and rollback.
- A data layer that reads past Claude Code transcripts into a local database and builds a task set, escape
  candidates, per-check statistics and a weekly scoreboard (`sisi harvest`, `tasks`, `escapes`, `checks`,
  `scoreboard`; these are not listed in `sisi help`).

Designed but not built (see [docs/design.md](docs/design.md)):

- The build conductor: `sisi build "<what I want>"` turning a statement into verified work, and the question queue
  (`sisi inbox`). Neither command exists.
- The model-driven learning loop: background runs, experiments on a task set, automatic shipping and removal of
  rule changes, the taste judge, playbooks. The data layer above is groundwork for it; nothing acts on it yet.
- Blocking gates outside Claude Code, and harvest of transcripts from tools other than Claude Code.

Not verified: macOS (no run yet), Python 3.9 and 3.10 by running the tests (see below), and whether Codex
and OpenCode obey the rulebook as well as Claude Code does. The library's claims about external tools are mostly
from their documentation.

### Python versions

The minimum is Python 3.9. This was determined by reading, not by running old interpreters. Every Python file parses
with `ast.parse(..., feature_version=(3, 8))`, and a search found no `match` statements, no `X | Y` types and no
walrus operators. The newest standard-library features in use are `shutil.copytree(..., dirs_exist_ok=True)` and
`sys.pycache_prefix`, both added in 3.8. The stated minimum is 3.9 because 3.8 is end of life and current macOS runners do not
offer it. The test suite was run here on Python 3.11 and 3.14 and passes. CI is configured for 3.9, 3.11 and 3.13 on
Linux and macOS; it has not run yet, so 3.9 and 3.10 are unconfirmed.

## Security

sisi runs commands that come from a project's contract. A contract in a project you did not write is untrusted
until you read it and run `sisi contract trust`; until then `sisi verify` refuses and the gate runs nothing. sisi
does not sandbox what a trusted contract runs. See [SECURITY.md](SECURITY.md), which also says how to report a
problem privately.

## Contributing

Tests, the standard-library-only rule, the verifier entry format and what belongs in the product versus your own
overlay are in [CONTRIBUTING.md](CONTRIBUTING.md). A change log is in [CHANGELOG.md](CHANGELOG.md), and all docs are
indexed in [docs/README.md](docs/README.md).

## Licence

MIT. Copyright (c) 2026 Stephen Waits. See [LICENSE](LICENSE).
