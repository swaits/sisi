---
id: go-fuzz
title: Native Go fuzzing with go test -fuzz
answers: Can any input make this Go function panic, hang or break an invariant?
rung: 2
section: many-inputs
languages: go
kinds: parsing, general
cost: low
detect: go version
ran_here: no
verified: docs
---

## Use when

- A Go function parses or processes input from outside: decoders, importers, request handlers.
- You want the standard toolchain only, with saved failing inputs that become regression tests automatically.

## Do not use when

- The input must be structured values and you want shrinking: `go-rapid`.
- The target needs more than one second a call; the engine treats that as a hang.

## Set up

Nothing to install beyond Go. Write a `FuzzXxx` function in a `*_test.go` file with
seeds via `f.Add`. Supported argument types: `string`, `[]byte`, the integer and
float types, and `bool`.

## Minimal example (`parse_test.go`)

    package pair

    import "testing"

    func FuzzParsePair(f *testing.F) {
        f.Add("1,2")
        f.Add("")
        f.Fuzz(func(t *testing.T, s string) {
            a, b, err := ParsePair(s)
            if err == nil && (a < 0 || b < 0) {
                t.Fatalf("accepted a negative value from %q", s)
            }
        })
    }

## Run

    go test -run=FuzzParsePair ./...                     # replays seeds and saved failures only
    go test -fuzz=FuzzParsePair -fuzztime=30s            # fuzzes for 30 seconds

`-fuzz` takes a regex that must match exactly one fuzz test in the package.
Passing looks like: the fuzz run ends at the time limit with exit 0 and no `--- FAIL`.
Failure writes a minimised input to `testdata/fuzz/FuzzParsePair/<hash>`, prints
`FAIL`, and exits 1. Commit that file: from then on plain `go test` replays it as a
unit test. Re-run just that case with `go test -run=FuzzParsePair/<hash>`.

## As a contract check

    {"id": "fuzz-parse-pair-go", "claim": "ParsePair survives 30 seconds of fuzzing and every saved failing input", "kind": "parsing", "rung": 2, "cmd": "go test -run=FuzzParsePair ./... && go test -fuzz=FuzzParsePair -fuzztime=30s", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 300}

## What a pass does not prove

- A clean run means nothing was found in that time. Coverage guidance works best on AMD64 and ARM64.
- Only the failures that panic, call `t.Fatal`, or run over time are caught; wrong answers need assertions in the target.
- Not run here (Go is not installed on this machine). Flags, directory layout and types are from the official Go fuzzing documentation. Check the check: add a deliberate panic behind a seed-adjacent input and see it found.
