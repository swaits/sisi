# Developing sisi

If you only use sisi, you can skip this page. Cloned it and ran `sisi install`? Nothing
changes for you: the clone is the installed copy.

## Two copies

When you both use sisi and work on it, keep them apart:

- the **source folder**: where you edit. It may be broken half the time.
- the **stable copy** in `~/.local/lib/sisi/`: what the tools actually run, so a running
  session is protected while sisi itself is being changed.

The stable copy is a set of releases, `~/.local/lib/sisi/releases/<UTC timestamp>/`, each
holding only the product files. A link called `current` points at the active one. Once a
`current` release exists, `sisi install` wires the hooks and `~/.local/bin/sisi` to it. A
release is built under a hidden name and renamed into place, and `current` is switched
atomically, so a running tool never sees a half-written copy: a process that has started
keeps running the release it started with. `sisi doctor` shows which copy is live and
whether the source folder is ahead of it.

## Make a release

Run from the clone (a release is made from the running launcher's folder):

    bin/sisi release          # runs the checks; refuses if they fail
    bin/sisi release --deep   # also needs the slow checks to pass

It copies the product files, switches `current`, rebuilds your rulebook with the new code,
keeps the newest releases, and prints what changed. The first time, run `sisi install`
afterwards so the tools point at the stable copy (release tells you if they do not).

## Roll back

    bin/sisi rollback

Switches `current` to the release before it and rebuilds the rulebook.

## Promote a personal addition

Rules, verifiers and recipes you added live in your personal overlay. Run from the clone:

    bin/sisi promote <id>            # shows what would be written, and every term it scrubbed
    bin/sisi promote <id> --apply    # writes it into the source folder

It replaces your home path, user name and email addresses, and any terms listed under
`developer.personal_terms` in your personal `config.json`, with placeholders. If a personal
term still appears afterwards, it stops and names the lines. A rule goes into the base
rulebook; a verifier or recipe into the library. It never commits. Review the change,
commit it, make a release, then remove your overlay copy so the two do not drift apart.
