# **sisi** is still improving

**sisi** is the operating layer that makes an AI coding tool behave as the engineering
organization described in [SPEC.md](SPEC.md): it understands intent, defines done before
building, verifies with the minimum sufficient evidence, delivers fast, and improves from
evidence after every piece of work. The host tool supplies the agent; **sisi** supplies the
operating policy, the records, the gates, the learning loop and the orchestration record, so
that behaviour is observable and improving rather than hoped for.

It is for anyone who uses an AI coding CLI for real work and wants the result back correct,
complete and verified, with less human attention spent checking it. One shared rulebook and
one learning store serve every tool on the machine, connected by reference, never by copy, so
a lesson learned in one tool is available in the next turn of any other.

**sisi** is a small command-line tool in plain Python with no dependencies. What it learns
about you is kept outside the clone, so updating never loses it.

## What it does

- **An operating policy.** A short rulebook of strategic direction is always loaded. The
  agent works out the tactics. Each rule states the behaviour, the reason, and what enforces
  or measures it.
- **Records.** Each piece of work can carry a contract of executable checks, a verification
  record that never reports an unrun check as passed, and delivery timing.
- **Gates.** Where a host exposes the moments, hooks check at session start, at each prompt
  and at the end of a turn. A failing check sends the agent back; after bounded send-backs
  the work is let through marked unverified, so a broken check cannot trap a session.
- **A learning loop.** Work ends with a recorded account of how it could have gone better.
  Lessons take effect in the personal store at once, are strengthened on recurrence, and are
  consolidated into rules, library entries and enforced checks.
- **An orchestration record.** The workers on the machine are discovered, work is routed to
  the most affordable usable worker by judged results, and every judgement is recorded.

The verifier library ships techniques and recipes that say what done means for a kind of
work, so agents query them instead of inventing a check. Format and quality bar:
[docs/verifier-format.md](docs/verifier-format.md).

## Install

Requirements: Python 3.9 or newer, and `git`, on Linux or macOS.

    git clone https://github.com/swaits/sisi.git
    cd sisi
    bin/sisi install --dry-run
    bin/sisi install
    bin/sisi doctor

The dry run prints every change and makes none. Install backs up every file it edits, adds
only an import line, a link, hook entries or a generated plugin, and skips a missing
configuration folder. It links the command as `~/.local/bin/sisi`; make sure that folder is
on your `PATH`, or call `bin/sisi` from the clone. `sisi doctor` shows what is wired, the
size of what is always loaded, and anything you must still do. Per-tool detail, limits and
steps you must take are in [docs/harnesses.md](docs/harnesses.md). Where there is no gate,
the rulebook still tells the agent to write and run a contract, but nothing enforces it.

For a first contract, change to one of your own projects and run `sisi contract init`. That
skeleton's placeholder check fails until you replace it with a real command. With a hook
wired you do not run the checks yourself: the agent writes the contract and the gate runs
them. `sisi help` lists every command and what each exit code means.

## What it does to your tools, and how to undo it

- **The product** is the clone: code, base rulebook, library and defaults. It is never
  written at run time.
- **What sisi learns for you** lives in `~/.local/share/sisi` (or `$SISI_DATA`), a local git
  repository that is never pushed.
- **Scratch** that can be rebuilt lives in `~/.local/state/sisi` (or `$SISI_STATE`).

`sisi update` replaces only the product, after backing up your personal data, and reapplies
what you learned. `sisi status` shows the live state; the layout is in
[docs/personal-data.md](docs/personal-data.md).

`sisi uninstall` removes the import line, hooks and links. A file you have not edited since
install is restored byte for byte. A file you edited keeps your edits and loses only sisi's
entries. A file sisi cannot edit with certainty is skipped and reported. Personal data and
scratch are left for you to delete. The exact guarantee is in
[docs/harnesses.md](docs/harnesses.md).

## Security

sisi runs commands from a project contract, so a contract you did not write is untrusted
until you read it and run `sisi contract trust`; until then the checks refuse to run. sisi
does not sandbox what a trusted contract runs. See [SECURITY.md](SECURITY.md), including how
to report a problem privately.

## Where to read more

- [SPEC.md](SPEC.md) — the standard sisi is built and judged against.
- [docs/target.md](docs/target.md) — how sisi meets that standard.
- `sisi help` — every command, with no per-command reference kept in this file.
- [docs/README.md](docs/README.md) — the index of the remaining documentation.
- [CONTRIBUTING.md](CONTRIBUTING.md) — how to run the tests and send a change.
- [CHANGELOG.md](CHANGELOG.md) — what changed.

## Licence

MIT. Copyright (c) Stephen Waits. See [LICENSE](LICENSE).
