---
id: feedback-as-amendment
title: Feedback restated as a one-line contract amendment, with a scope check on the diff
answers: Did I change only what the human's feedback asked for, and nothing else?
rung: 3
section: intent
languages: any
kinds: general
cost: low
detect: git --version
ran_here: yes
verified: ran
---

## Use when
- The human reacts to your work ("the button is too big", "round down not up", "the second paragraph is wrong"). Rule 1 (own-the-outcome): this is an amendment, not licence to rework.
- A previous change reached further than the request; you want to make that impossible.
- You are fixing a review comment and the diff must show only that fix.

## Do not use when
- The feedback truly spans the work ("start over"). Then write a new contract.

## Set up
Record the amendment in one line in `.sisi/contract.json` (as a new check or a
note) and name the paths it may touch. Note the commit you start from:
`git rev-parse HEAD`. Re-run the invariants from rule 3 (define-done).

## Minimal example
Amendment: "Round fees down to the cent, only in `src/fees.py`." Scope script
`scope.sh` fails on any changed or new file outside the given paths:

    #!/usr/bin/env bash
    set -eu
    base=$1; shift
    changed=$( { git diff --name-only "$base"; git ls-files -o --exclude-standard; } | sort -u)
    allowed=$(git ls-files -c -o --exclude-standard -- "$@" | sort -u)
    outside=$(comm -23 <(printf '%s\n' "$changed") <(printf '%s\n' "$allowed") | sed '/^$/d')
    [ -z "$outside" ] || { echo "outside the amendment:"; echo "$outside"; exit 1; }
    echo "ok: all changes inside $*"

For regions inside one file, list the hunks: `git diff -U0 "$base" -- src/fees.py | grep '^@@'`
and check each range lies in the function the amendment names.

## Run
    scope.sh "$BASE" src/fees.py tests/test_fees.py

Passing looks like: `ok: all changes inside ...` and exit 0 (run here on a scratch
repository). Failure prints `outside the amendment:` and the files, exit 1.
Formatting churn, renames and lockfile changes show up here; revert them.

## As a contract check
    {"id": "amendment-scope", "claim": "Only the files named by the amendment changed since the base commit", "kind": "general", "rung": 3, "cmd": "bash scripts/scope.sh $(cat .sisi/base) src/fees.py tests/test_fees.py", "expect": {"exit": 0, "stdout_contains": "ok: all changes inside"}, "timeout_s": 60}

## What a pass does not prove
That the change inside the allowed file is correct, or that it did not damage
behaviour in a file that depends on it. Run the invariants for that. The
allowed list is a decision: keep it as small as the feedback. Staged and
unstaged changes are both covered by `git diff BASE`; commit history is not.
