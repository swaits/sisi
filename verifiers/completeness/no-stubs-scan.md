---
id: no-stubs-scan
title: Scanning for stubs, skipped tests, commented-out assertions and placeholder data
answers: Is anything still a placeholder, skipped, or switched off in what I am calling finished?
rung: 3
section: completeness
languages: any
kinds: general
cost: low
detect: git --version
ran_here: yes
verified: ran
---

## Use when
- Always before saying "done". An unfinished function that compiles is the most common false finish.
- Tests were added or changed: skipped and `#[ignore]`d tests count as missing.
- You edited tests to get a green run (deleting or commenting an assertion is how a failing test gets quieted).

## Do not use when
- It is the only check. It finds markers, not missing work with no marker.

## Set up
Commit `scripts/stubscan.sh`. Tune the pattern to the languages in use. Where a
marker is legitimate (a documented known gap), list the file in the script's
exclusions with a reason, not a blanket `|| true`.

## Minimal example
`scripts/stubscan.sh`:

    #!/usr/bin/env bash
    pat='todo!\(|unimplemented!\(|NotImplementedError|^\s*sorry\b|#\[ignore|@pytest\.mark\.(skip|xfail)|\.skip\(|\bxit\(|t\.Skip\(|^\s*//\s*(assert|expect)|^\s*#\s*assert|lorem ipsum'
    if git grep -n -I -E -i -e "$pat" -- . ':!scripts/stubscan.sh' ':!docs'; then exit 1; fi

`git grep` exits 0 when it finds a match, so a match fails the script. Also look in the diff:
`git diff BASE | grep -E '^-.*(assert|expect)'` lists assertions you removed.
For `unwrap()`/`panic!("not yet")` and `pass`-only bodies, add patterns to taste.

## Run
    bash scripts/stubscan.sh

Passing looks like: no output, exit 0. Failure (run here) prints file:line for each
`todo!()`, `#[ignore]` and commented assertion, and exits 1. Then also ask: is
there placeholder data (names like `foo`, `test@example.com`, `12345`) in
shipped files, not tests? Grep for it by hand.

## As a contract check
    {"id": "no-stubs", "claim": "No stub markers, skipped tests or commented-out assertions in the tree", "kind": "general", "rung": 3, "cmd": "bash scripts/stubscan.sh", "expect": {"exit": 0}, "timeout_s": 60}

## What a pass does not prove
A stub written without a marker (`return 0`, an empty `else`) passes. A test that
asserts nothing passes (see `vacuity-check`, `assertion-strength-review`). The
scan checks tracked and untracked files but not ignored ones. Do not weaken the
pattern to get a pass; add a justified exclusion instead.
