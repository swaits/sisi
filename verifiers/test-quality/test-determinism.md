---
id: test-determinism
title: Make tests deterministic with fixed seeds, fake clocks and no network
answers: Will this test give the same result on any machine, at any time, with no network?
rung: 3
section: test-quality
languages: any
kinds: general, concurrency, money
cost: low
detect:
ran_here: no
verified: docs
---

## Use when
- A test uses randomness, the current time, timeouts, sleeps, the file system, the network or environment variables.
- You are writing tests an agent will rerun many times and compare across runs.
- A test result changes with the date, the time zone, the locale or the order of map iteration.

## Do not use when
- You are testing the integration itself against a real service. Keep that in a separate, labelled suite.

## Set up
Control each source of nondeterminism:
- Randomness: pass an explicit seed; print it on failure so the run can be replayed. Property tests: proptest stores failures in `proptest-regressions/`; Hypothesis in `.hypothesis/` (use `@seed` or `--hypothesis-seed`). Go: `rand.New(rand.NewSource(seed))`.
- Time: inject a clock. Rust Tokio: `tokio::time::pause()` with `#[tokio::test(start_paused = true)]`. Python: `freezegun` or `time-machine`. JavaScript: `vi.useFakeTimers()` or Jest fake timers. Never call `sleep` to wait for a result; wait on the event.
- Network: no real sockets. Use in-process fakes, a local listener bound to port 0, recorded fixtures or a simulator (see `deterministic-simulation`). Run the suite once with the network off (`unshare -rn cargo test` on Linux, or a sandbox) to prove it.
- Files: use a fresh temp directory per test; set `TMPDIR` explicitly.
- Order: do not depend on map or set iteration order; sort before comparing. Do not share mutable global state between tests.
- Environment: set `TZ=UTC`, `LC_ALL=C`, fixed locale.

## Minimal example
A test with an explicit seed, and a way to replay it:

    let seed = std::env::var("SEED").ok().and_then(|s| s.parse().ok()).unwrap_or(12345u64);
    eprintln!("seed = {seed}");
    let mut rng = StdRng::seed_from_u64(seed);

## Run
    SEED=12345 cargo test my_test
    unshare -rn cargo test --offline my_test     # no network, Linux user namespace

Passing looks like: the same result on repeated runs and with the network off. Failure: a test needing the network fails with a connection error, or results differ between two runs with the same seed. Not run here; `unshare` is Linux-specific and needs unprivileged user namespaces.

## As a contract check
    {"id": "hermetic", "claim": "Tests pass with no network access", "kind": "general", "rung": 3, "cmd": "unshare -rn cargo test --offline", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 900}

## What a pass does not prove
- That the code is correct; it proves the test is repeatable.
- Fixed seeds explore one input. Vary them in a separate property-test job.
- A fake clock hides real timing bugs. Keep a few real-time tests, labelled.
- Check the check: run twice with the same seed and diff the outputs; add `--test-threads=1` and the default to expose shared state.
