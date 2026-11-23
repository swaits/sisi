---
id: stress-repeat
title: Repeated and randomised-timing runs of concurrent tests
answers: Does this concurrent test keep passing when I run it many times under different timing?
rung: 3
section: concurrency
languages: any
kinds: concurrency
cost: low
detect:
ran_here: no
verified: docs
---

## Use when
- It is the only affordable check, and the code is too big for `loom`, `shuttle` or simulation.
- You are hunting a flaky failure and need to make it reproduce often enough to diagnose.
- As an extra layer beside a stronger check: run the same test with a race detector, sanitizer or Miri in a loop.

## Do not use when
- You can write an exhaustive or schedule-controlled test. Those find bugs repetition misses.
- You want to conclude the code is correct. Passing 1,000 runs only shows it did not fail in 1,000 runs.

## Set up
No special tooling. Tools that help:
- Rust: a shell loop around `cargo test`, and `cargo test -- --test-threads=1` versus the default to change contention.
- Go: `go test -count=N -race -cpu=1,2,4,8 -shuffle=on`.
- Any: a shell loop, `taskset -c 0` to confine to one CPU, a parallel CPU burner (`stress-ng --cpu 8`) to perturb timing, and random `sleep` or `yield` jitter injected in test hooks.

## Minimal example
    for i in $(seq 1 200); do
        cargo test --release my_concurrent_test || { echo "FAILED on run $i"; exit 1; }
    done

Go: `go test -race -count=200 -cpu=1,4 -run TestQueue ./queue`.

## Run
Use the loop above, with stderr kept so a failing run's output is not lost.

Passing looks like: every run exits 0 and the loop ends silently. Failure is the first non-zero exit with the run number; keep its output.

## As a contract check
    {"id": "stress-queue", "claim": "queue test passes 200 repeated runs under CPU contention", "kind": "concurrency", "rung": 3, "cmd": "for i in $(seq 1 200); do cargo test --release queue_concurrent || exit 1; done", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 1800}

## What a pass does not prove
- This is a weak check, rung 3. A rare schedule needs luck to occur, and a clean loop says little about it.
- Timing changes between machines. A bug that needs a particular core count or load may never appear on the test machine.
- A filtered name that matches no tests passes every iteration with `0 tests run`; assert that at least one test executed.
- Still worth having when: it can reproduce a known flaky failure, it runs alongside a race detector, or you have no better option and say so in the result. Check the check: it should fail when you add a known race and a short sleep.
