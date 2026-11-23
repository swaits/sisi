---
id: single-gate-command
title: One project command that runs everything required, so done has one definition
answers: Is there exactly one command whose success means the project's required checks all pass?
rung: 3
section: completeness
languages: any
kinds: general
cost: low
detect: just --version
ran_here: yes
verified: ran
---

Ran here: a two-step `justfile` recipe, failing and then passing. Make works the
same way with a `verify` target.

## Use when
- A project has several checks (format, lint, tests, dependency audit, notices) and people or agents run a different subset each time.
- You want the contract's required checks, CI and a developer's "am I done" to be the same thing.
- Starting a project: create the gate on day one, while it is small.

## Do not use when
- Some checks take hours. Put those in the deep tier (`check-tiering`); the gate is the fast set.

## Set up
    # justfile
    set shell := ["bash", "-euo", "pipefail", "-c"]
    check:
        cargo fmt --all --check
        cargo clippy --workspace --all-targets -- -D warnings
        cargo test --workspace
        scripts/stubscan.sh
        cargo deny check

CI must run `just check` and nothing else for the pull-request job, or the two definitions diverge.

## Minimal example
    check:
        test "$(cat flag.txt)" = ok
        echo "gate passed"

`just check` with `flag.txt` containing `bad` stops at the first failing line, prints
the line `error: recipe check failed on line 3 with exit code 1` and exits 1; with `ok` it prints `gate passed`, exit 0.

## Run
    just check

Passing looks like: exit 0, with each step's output visible. just stops at the first failing line. In Make, each line is its own shell and
also stops the recipe, but a multi-line `if` or loop needs `&&` chaining or `.ONESHELL` with `set -e`. Never write `command || true` in the gate.

## As a contract check
    {"id": "gate", "claim": "The project gate command passes", "kind": "general", "rung": 3, "cmd": "just check", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 1800}

## What a pass does not prove
Only what the gate contains. The usual rot is a check removed from the recipe, or a
step that exits 0 on failure. Review diffs to the gate file as closely as code, and
ensure a deliberately broken input fails it (check the check). A gate
that is too slow gets skipped; keep the fast set fast.
