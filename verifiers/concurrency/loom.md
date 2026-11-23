---
id: loom
title: Exhaustive interleaving tests for Rust concurrency with loom
answers: Is there any thread interleaving of this lock-free or shared-state code that breaks my assertion?
rung: 1
section: concurrency
languages: rust
kinds: concurrency, state-machine
cost: medium
detect: cargo --version
ran_here: yes
verified: ran
---

## Use when
- You wrote or changed a small concurrent core: an atomic counter, a lock-free queue, a channel, a mutex-protected state machine, a once-cell.
- A test passes "most of the time" and you need every ordering, not a sample of them.
- The claim is about memory ordering (`Relaxed`, `Acquire`, `Release`) and a stress test cannot show it.

## Do not use when
- The code is large or does I/O, sleeps, or uses `tokio`; loom's state space explodes. Use `shuttle` for those.
- The code is single-threaded. Use ordinary tests.
- You need to check real `unsafe` memory behaviour; use `miri` as well.

## Set up
Loom replaces `std::sync`, `std::thread` and atomics with model-checked versions. Gate it behind `--cfg loom` so normal builds are untouched.

    [target.'cfg(loom)'.dependencies]
    loom = "0.7"
    [lints.rust]
    unexpected_cfgs = { level = "warn", check-cfg = ['cfg(loom)'] }

In the code, import atomics and threads from `loom::` under `#[cfg(loom)]`, from `std::` otherwise.

## Minimal example
`src/lib.rs`. The counter below has a lost-update bug; loom finds it. Replace load+store with `fetch_add` and it passes.

    #[cfg(loom)] use loom::sync::atomic::{AtomicUsize, Ordering};
    #[cfg(not(loom))] use std::sync::atomic::{AtomicUsize, Ordering};
    pub struct Counter(AtomicUsize);
    impl Counter {
        pub fn new() -> Self { Counter(AtomicUsize::new(0)) }
        pub fn incr(&self) { self.0.fetch_add(1, Ordering::SeqCst); }
        pub fn get(&self) -> usize { self.0.load(Ordering::SeqCst) }
    }
    #[cfg(loom)]
    mod loom_tests {
        use super::*; use loom::{sync::Arc, thread};
        #[test] fn both_increments_counted() {
            loom::model(|| {
                let c = Arc::new(Counter::new()); let c2 = c.clone();
                let t = thread::spawn(move || c2.incr());
                c.incr(); t.join().unwrap();
                assert_eq!(c.get(), 2);
            });
        }
    }

## Run
    RUSTFLAGS="--cfg loom" cargo test --release --lib loom_tests

Passing looks like: `test result: ok. 1 passed`, exit 0. Failure shows as a panic inside `loom::model` (for the buggy version: `left: 1, right: 2`), exit 101. Set `LOOM_MAX_PREEMPTIONS=3` to bound a slow model.

## As a contract check
    {"id": "loom-counter", "claim": "No interleaving of two incr calls loses an update", "kind": "concurrency", "rung": 1, "cmd": "RUSTFLAGS=\"--cfg loom\" cargo test --release --lib loom_tests", "expect": {"exit": 0, "stdout_contains": "test result: ok"}, "tier": "deep", "timeout_s": 600}

## What a pass does not prove
- It covers only the threads, operations and inputs inside the `loom::model` closure. Rung 1 holds within those bounds only.
- With `LOOM_MAX_PREEMPTIONS` set, it is bounded, not exhaustive.
- Code that still uses `std::sync` types is invisible to it. Check every concurrency import is swapped under `cfg(loom)`.
- Check the check: put the bug back (load then store). The test must fail. Also confirm the test ran: a filter that matches nothing prints `0 passed` and exits 0.
