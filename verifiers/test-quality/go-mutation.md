---
id: go-mutation
title: Mutation testing for Go with gremlins
answers: Would my Go tests notice if this code were wrong?
rung: 2
section: test-quality
languages: go
kinds: general, money, parsing
cost: medium
detect: gremlins --version
ran_here: no
verified: docs
---

## Use when
- A Go package has tests and you want evidence they can fail.
- Line coverage is high but you doubt the assertions.
- It is a check on other checks; it gives rung 2 confidence in the tests.

## Do not use when
- Gremlins is maintained slowly, not abandoned: its latest release is v0.6.0 (December 2025) and its last commit was March 2026. A more recently active alternative is the `avito-tech/go-mutesting` fork (commits in October 2026); the original `zimmski/go-mutesting` has been idle since July 2024. Pick one of the first two.
- The package has no tests, or its tests are slow; each mutant reruns them. The README says gremlins works well on smallish modules and takes hours on very big ones.
- You need a stable CLI: the README warns that flags and config can change between 0.x minor releases, and only the current minor is maintained.

## Set up
Needs Go (the repository's `go.mod` says 1.25). Install a release package (`.deb`, `.rpm`, or a binary from the GitHub releases page; Homebrew via `brew tap go-gremlins/tap && brew install gremlins` on macOS) or:

    go install github.com/go-gremlins/gremlins/cmd/gremlins@v0.6.0

Pin the version, as the install page does. Not installed on this machine, so the example below was not run.

## Minimal example
`price.go`:

    package shop

    func Price(qty, unit int) int {
        total := qty * unit
        if qty >= 10 { return total - total/10 }
        return total
    }

`price_test.go` with `Price(2,100)==200` and `Price(20,100)==1800` only. The boundary mutation (`>=` to `>`) lives, because no test uses `qty == 10`.

## Run
Run from the module root, with no package argument; gremlins takes its target from the current module:

    gremlins unleash --threshold-efficacy 80

Gremlins reports each mutant as KILLED, LIVED, NOT COVERED, TIMED OUT or NOT VIABLE (`RUNNABLE` with `--dry-run`) and prints a test efficacy and mutant coverage figure. Failure shows LIVED mutants with file and line, for example `LIVED CONDITIONALS_BOUNDARY at price.go:5:12`.

Passing looks like: exit 0. Exit codes from the docs: `--threshold-efficacy N` makes gremlins exit 10 when efficacy is below N; `--threshold-mcover N` exits 11 when mutant coverage is below N. Without either flag gremlins never fails on survivors, so a bare `gremlins unleash` exits 0 with LIVED mutants. `--silent` prints only errors; `--diff origin/main` limits the run to changed code; `--exclude-files REGEX` skips generated files.

## As a contract check
    {"id": "go-mutation", "claim": "Gremlins efficacy for the module meets the threshold", "kind": "general", "rung": 2, "cmd": "gremlins unleash --threshold-efficacy 80 --threshold-mcover 90", "expect": {"exit": 0}, "timeout_s": 3600, "tier": "deep"}

## What a pass does not prove
- Efficacy is `KILLED / (KILLED + LIVED)`; NOT COVERED mutants (no test reaches the line) are left out of it. Mutant coverage is `(KILLED + LIVED) / (KILLED + LIVED + NOT COVERED)`. That is why the contract sets `--threshold-mcover` too. Read both figures.
- LIVED mutants can be equivalent; justify each.
- The tool covers a fixed set of mutation operators (arithmetic, conditional boundary and negation, and similar), so passing does not mean the tests are thorough.
- Without a threshold flag the exit code says nothing. Check the check: delete an assertion and confirm the run exits 10.
- Commands and flags were read from the project's documentation sources in the repository (docs/docs), not run here.
