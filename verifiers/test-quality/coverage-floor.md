---
id: coverage-floor
title: Coverage as a ratchet that may not fall
answers: Did my change make any code or branch stop being exercised by tests?
rung: 3
section: test-quality
languages: rust, python, javascript, typescript, go
kinds: general
cost: low
detect: cargo llvm-cov --version
ran_here: yes
verified: ran
---

## Use when
- A change might delete, narrow or replace tests, and the loss should not go unnoticed.
- You want a cheap tripwire in CI: a recorded floor that the number may not drop below.
- New code should come with tests that execute it.

## Do not use when
- You want to know whether the code is correct. Coverage shows what ran, not what was checked. In my run the Python function had 100% line and branch coverage and 3 of 7 mutants survived. Use `cargo-mutants`, `mutmut` or `stryker`.
- You would set a high target and chase it. A floor that only ratchets up is the use; a target invites empty tests.

## Set up
- Rust: `cargo llvm-cov` (ran 0.9.1). Branch coverage needs nightly: `--branch`.
- Python: `pip install coverage`; `coverage run --branch -m pytest`.
- JavaScript: `npx c8 <test command>`, with `--check-coverage --lines 80` (from c8's docs; not run here). Vitest and Jest have built-in coverage with thresholds.
- Go: `go test -cover ./...` and `-coverprofile=c.out`, then `go tool cover -func=c.out` (from the Go docs; not run here).

## Minimal example
Record the floor in a file (the value of the last good run), then compare:

    cargo llvm-cov --summary-only
    # coverage.py
    coverage run --branch -m pytest -q && coverage report --fail-under=100

The ratchet: store the total in a doc or a file, fail if the new total is more than a small tolerance below it, and raise the stored number when coverage rises. One Rust project does this with a script that reads the TOTAL row of the report, compares line cover to the recorded floor with a 0.5 point tolerance, and is wired in as a recipe.

## Run
    cargo llvm-cov --fail-under-lines 80

Passing looks like: the report prints and exit is 0. Failure: exit 1 when lines are below the limit (checked here: 85.71% failed at 100, passed at 80). Python: `coverage report --fail-under=N` exits 2 below N.

## As a contract check
    {"id": "coverage-floor", "claim": "Line coverage has not fallen below the recorded floor of 80", "kind": "general", "rung": 3, "cmd": "cargo llvm-cov --fail-under-lines 80", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 1200}

## What a pass does not prove
- Only that code was executed, not that results were checked. Tests with no assertions give full coverage.
- Excluded files and generated code lower the denominator; list what is excluded.
- Lowering the floor to get a pass defeats the check. A floor change in the diff needs a stated reason.
- Check the check: delete a test and confirm the number drops and the gate fails.
