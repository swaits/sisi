---
id: go-race-detector
title: Data-race detection in Go with go test -race
answers: Do my goroutines read and write the same variable without synchronisation?
rung: 2
section: concurrency
languages: go
kinds: concurrency
cost: low
detect: go version
ran_here: no
verified: docs
---

## Use when
- You touched goroutines, channels, shared maps or slices, `sync` types or closures that capture loop variables.
- You want a cheap, always-on check in CI for any Go package with concurrency.
- A Go test is flaky and you suspect a race.

## Do not use when
- You want proof of no races. It sees only races that actually happen in the run.
- Cgo is disabled or no C compiler is installed; the race detector needs both.
- The race is a logic race over properly locked data; it only reports unsynchronised access.

## Set up
Nothing to install beyond the Go toolchain (and a C compiler on non-macOS). Supported on linux/amd64, arm64, and several other platforms listed in Go's race detector doc. Not checked on this machine: Go is not installed here, so commands come from go.dev/doc/articles/race_detector.

## Minimal example
`race_test.go`:

    package race

    import ("sync"; "testing")

    func TestCounter(t *testing.T) {
        n := 0
        var wg sync.WaitGroup
        for i := 0; i < 2; i++ {
            wg.Add(1)
            go func() { defer wg.Done(); n++ }() // race: use sync/atomic or a mutex
        }
        wg.Wait()
    }

## Run
    go test -race ./...
    GORACE="halt_on_error=1 history_size=2" go test -race -count=5 ./...

Passing looks like: `ok  <pkg>` lines, exit 0. Failure prints `WARNING: DATA RACE` with the conflicting reads and writes and goroutine creation stacks, and the test fails (`testing.go: race detected during execution of test`); the binary exit status after a race is 66 by default. Add `-count=N` to repeat; the detector is per-run.

## As a contract check
    {"id": "go-race", "claim": "No data race detected across the Go test suite", "kind": "concurrency", "rung": 2, "cmd": "go test -race -count=3 ./...", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 900}

## What a pass does not prove
- Races only on code paths that ran. Execution is 2x to 20x slower and uses 5x to 10x more memory, so some teams run only part of the suite; say which.
- It finds data races, not deadlocks, goroutine leaks, or ordering bugs on synchronised data.
- Build-tagged `//go:build !race` tests are skipped under `-race`; check none hide the test you care about.
- Check the check: introduce the unsynchronised write above and confirm `go test -race` fails. If you add `-run` or a package filter, confirm tests actually ran (`go test -race -v` lists them; `no tests to run` means vacuous).
