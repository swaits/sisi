---
id: ratchet-floor
title: A ratchet, a count that may only move one way, checked against the base commit
answers: Is this number (warnings, coverage, done items) no worse than it was before my change?
rung: 4
section: regression
languages: any
kinds: general
cost: low
detect: git --version
ran_here: yes
verified: ran
---

## Use when
- A count must never get worse: lint warnings may only fall, test coverage or "done" items in a plan may only rise.
- A test inside the tree cannot see the history. Only a comparison with the base commit shows a number was quietly lowered.

## Do not use when
- The number is allowed to move both ways with the work (lines of code, file counts).
- There is no base commit: a brand-new repository has nothing to compare with.

## Set up
Keep the number in one machine-readable line in a committed file, for example `**Floor: 12 done**` in `docs/parity.md`, or a `.ratchet/warnings.txt` containing `37`. Write a script that reads it at the base ref and in the working tree.

## Minimal example
`scripts/floor.sh <base-ref>` (a version of this pattern runs in a reference project):
```sh
#!/bin/bash
set -euo pipefail
base_ref="${1:?usage: floor.sh <base-ref>}"
floor_of() { sed -n 's/^\*\*Floor: \([0-9][0-9]*\) done\*\*.*/\1/p' | head -n 1; }
base=$(git show "${base_ref}:docs/parity.md" | floor_of)
now=$(floor_of < docs/parity.md)
[ -n "$base" ] || { echo "no floor at ${base_ref}; nothing to compare"; exit 0; }
[ -n "$now" ]  || { echo "working tree has no floor line" >&2; exit 1; }
echo "floor: base ${base}, now ${now}"
[ "$now" -ge "$base" ] || { echo "the floor never decreases" >&2; exit 1; }
```
For a count that may only fall (warnings), flip the last test to `-le`. Run it with `origin/main` or the merge base as `<base-ref>`, not with `HEAD`, because `HEAD` already contains your edit once committed.

## Run
`scripts/floor.sh origin/main`

Passing looks like: a `floor: base N, now M` line with M at least N, exit 0. Failure prints `the floor never decreases` and exits 1. A missing floor line in the working tree is a failure, not a pass.

## As a contract check
```json
{"id": "ratchet-floor", "claim": "The done-item floor is not lower than on the base branch", "kind": "general", "rung": 4,
 "cmd": "scripts/floor.sh origin/main", "expect": {"exit": 0}, "timeout_s": 30}
```

## What a pass does not prove
- That the counted items are real. If an agent marks items done without doing the work, the floor rises and the check passes. Pair it with a check on each item.
- Deleting the line fails here, but deleting the whole file and the script passes the ratchet vacuously; protect the script by also running it from a trusted base ref where possible.
- Check the check: lower the number by one in a scratch copy and confirm exit 1 (run here with a throwaway git repo: `ratchet fails: 4 < 5`).
