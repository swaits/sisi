---
id: flaky-test-detection
title: Detect flaky tests with repeat runs, random order and fixed seeds
answers: Does this test give the same result every time, in any order?
rung: 3
section: test-quality
languages: any
kinds: general, concurrency
cost: low
detect: cargo nextest --version
ran_here: yes
verified: ran
---

## Use when
- You added or changed a test and want to know it is stable before calling it done.
- A test failed once and passed on rerun.
- You suspect order dependence: a test passes alone and fails in the suite.

## Do not use when
- You are looking for a concurrency bug in the code itself. Repetition samples; use `loom`, `shuttle` or `stress-repeat` with the right framing.
- The failure is deterministic. Fix it; do not repeat it.

## Set up
- Rust: `cargo install cargo-nextest`. Repeat with `--stress-count N` (also `--stress-duration`), retry with `--retries N`, which marks a test that failed then passed as flaky (nextest 0.9.143; `--flaky-result` controls whether that counts as pass or fail, see `--help`). Shuffled order needs nightly: `cargo +nightly test -- -Zunstable-options --shuffle` (from memory; confirm).
- Python: `pytest-randomly` shuffles by default and prints the seed; rerun with `-p randomly -p no:randomly` to disable, or `--randomly-seed=<seed>` to reproduce an order (from its docs). `pytest-repeat` adds `--count=N`.
- Go: `go test -count=20 -shuffle=on -race ./pkg`; it prints `-test.shuffle <seed>`, reuse it as `-shuffle=<seed>`.
- JavaScript: Vitest `--sequence.shuffle`; Jest `--randomize`.

## Minimal example
`cargo nextest run --stress-count 50 my_test` reruns one test 50 times.

## Run
    cargo nextest run --stress-count 50 -E 'test(my_test)'
    cargo nextest run --retries 2        # report which tests needed a retry

Passing looks like: every iteration passes and no `FLAKY` label is shown. Failure shows the failing iteration and its output. When a test is flaky, capture the seed, or the shuffle seed, from the first failure before rerunning.

Quarantining honestly: if a test is flaky and cannot be fixed now, do not delete it or add a blanket retry. Mark it ignored with a comment naming the issue and the date, keep it running in a separate non-gating job so its failure rate stays visible, and list it in the final report as an open problem. A quarantined test is not a passing test.

## As a contract check
    {"id": "no-flaky", "claim": "The new test passes 50 consecutive runs", "kind": "general", "rung": 3, "cmd": "cargo nextest run --stress-count 50 -E 'test(my_test)'", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 900}

## What a pass does not prove
- Fifty passes bound the failure rate only roughly: a 1-in-100 flake passes fifty runs more than half the time. Run more, or use controls from `test-determinism`.
- Order dependence appears only in the orders tried. Record seeds.
- Retries hide flakiness. A contract that relies on `--retries` to pass is hiding the problem; require zero retries.
- Check that the filter matched a test (`no tests to run` exits 4 in nextest unless `--no-tests=pass` is set).
