# Developing sisi

If you only use sisi, you can skip this page. Cloned it and ran `sisi install`? Nothing changes for you:
the clone is the installed copy.

## Two copies

When you both use sisi and work on it, keep them apart:

- the **source folder** (for example `~/src/sisi`): where you edit. It may be broken half the time.
- the **stable copy** in `~/.local/lib/sisi/`: what Claude Code, Codex and OpenCode actually run.

The stable copy is a set of releases, `~/.local/lib/sisi/releases/<UTC timestamp>/`, each holding only the product
files (`bin/`, `sisi/`, `canon/`, `verifiers/`, `done/`, `docs/`, `config.default.json`, `VERSION`; no tests, notes or contract).
A link called `current` points at the active one. `SISI_LIB` moves the whole folder (tests use it).

Once a `current` release exists, `sisi install` wires the hooks and `~/.local/bin/sisi` to
`~/.local/lib/sisi/current/bin/sisi`. A running tool never sees a half-written copy: a release is built under a
hidden name and renamed into place, and `current` is switched by writing a new link and renaming it over the old
one. A process that has started keeps running the release it started with.

One limit, measured on btrfs: a lookup that lands on the exact instant of the switch can fail to find `current`
(about 1 lookup in 40,000 during a switch). A hook that hits it fails open, as any hook error does, and the next
call finds the new release.

## Make a release

From the source folder:

    sisi release          # runs `sisi verify`; refuses if it fails
    sisi release --deep   # also needs the slow checks to pass

It copies the product files, switches `current`, rebuilds your rulebook with the new code, keeps the newest three
releases, and prints what changed. The first time, run `sisi install` afterwards so the tools point at the stable
copy (release tells you if they do not).

`sisi doctor` shows which copy is live, its release time, and whether the source folder is ahead of it.

## Roll back

    sisi rollback

Switches `current` to the release before it and rebuilds the rulebook. It can be repeated until the oldest kept
release.

## Developer mode

    sisi dev on [PATH]    # remember where the source folder is (setting developer.source in your personal config)
    sisi dev off
    sisi dev status

Needed only when you run `sisi release` or `sisi promote` from somewhere else, such as through the installed
copy. Run from the source folder, they use that folder.

## Promote a personal addition

Rules, verifiers and recipes you added live in your personal overlay. To make one part of the product:

    sisi promote <id>            # shows what would be written, and every term it scrubbed
    sisi promote <id> --apply    # writes it into the source folder

It replaces your home path with `~`, your user name with `<user>`, email addresses with `<email>`, and any terms
listed under `developer.personal_terms` in your personal `config.json` with `<personal>`. If a personal term still
appears afterwards (for example in different capitals), it stops and names the lines; fix the overlay item and
try again. A rule goes into `canon/core.md` (replacing the rule with that id, or added as the next number); a
verifier into `verifiers/<section>/`; a recipe into `done/`. It never commits. Review the change, commit it, make a
release, then remove your overlay copy so the two do not drift apart.
