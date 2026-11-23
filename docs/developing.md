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

## The live orchestration check

Before any release that touches the hooks or the rulebook, run

    python3 tools/live_orchestration_check.py

It starts the host's command-line tool headless with its least expensive model in two small temporary
projects, with the hooks from this checkout and a temporary `SISI_DATA` and `SISI_STATE` (the real sisi data is
never read or written; the script asserts that it did not change). Scenario 1 asserts that the meter refused a
tool call with its message, that the session then ran `sisi route` and delegated with a named model or recorded
a reason with `sisi unit direct`, and that the ledger or events hold the matching record. Scenario 2 uses a fake
provider that always answers with a quota error and a reset time: the provider must be marked down until that
time, the session must go on with another worker, never call the question dialog and never mention the
failure in its final message. It costs a few cents and needs the host's login, so it is not part of the unit
suite; synthetic hook input is what let an earlier release ship broken. If the agent ignores a refusal or the
host does not honour it, that is a finding: fix the hook output, do not weaken the assertion.

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
