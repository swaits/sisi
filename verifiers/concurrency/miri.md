---
id: miri
title: Undefined behaviour and data-race detection for Rust with Miri
answers: Does my unsafe Rust code, or my threaded test, perform undefined behaviour or a data race?
rung: 2
section: concurrency
languages: rust
kinds: concurrency, general
cost: medium
detect: cargo +nightly miri --version
ran_here: yes
verified: ran
---

## Use when
- You wrote or changed `unsafe` code, raw pointers, `transmute`, FFI-free pointer arithmetic or custom `Send`/`Sync` impls.
- A test uses threads and you want data races on non-atomic memory detected.
- You want out-of-bounds, use-after-free, uninitialised reads and aliasing violations reported as errors.

## Do not use when
- The code does heavy I/O, FFI, or runs long. Miri is 10x to 100x slower and cannot run most foreign code.
- You need to find logic-level races on atomics or locks. Use `loom` or `shuttle`.

## Set up
    rustup toolchain install nightly --component miri
    cargo +nightly miri setup

Pin the nightly in CI so results are reproducible.

## Minimal example
Two threads write one `u32` without synchronisation:

    use std::thread;
    pub struct Racy(*mut u32);
    unsafe impl Send for Racy {}
    pub fn racy_count() -> u32 {
        let mut n = 0u32;
        let p = Racy(&mut n);
        let h = thread::spawn(move || { let p = p; unsafe { *p.0 += 1 }; });
        unsafe { *(&raw mut n) += 1 };
        h.join().unwrap();
        n
    }
    #[test] fn counts() { assert_eq!(racy_count(), 2); }

Plain `cargo test` passes. Miri fails it. Using `AtomicU32` instead makes Miri pass.

## Run
    cargo +nightly miri test
    MIRIFLAGS="-Zmiri-many-seeds=0..16" cargo +nightly miri test      # vary the thread schedule
    MIRIFLAGS="-Zmiri-disable-isolation" cargo +nightly miri test     # allow clock and file access

Passing looks like: normal test output, exit 0. Failure shows `error: Undefined Behavior: Data race detected between ...` (or the UB kind), exit 1.

## As a contract check
    {"id": "miri-ub", "claim": "No undefined behaviour or data race in the unit tests under Miri", "kind": "concurrency", "rung": 2, "cmd": "cargo +nightly miri test --lib", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 1800}

## What a pass does not prove
- Miri checks only executions the tests perform, on one schedule per seed. Use `-Zmiri-many-seeds` to sample more; it is still sampling, rung 2.
- It checks the Rust abstract machine, not hardware memory models in full.
- Tests that cannot run under Miri (FFI, some syscalls) are skipped or fail; do not mark them `#[cfg_attr(miri, ignore)]` without saying so.
- Check the check: introduce a known UB (read past a `Vec`'s end) and confirm Miri errors. Reduce proptest or loop counts under Miri (for example `PROPTEST_CASES=4`) so it finishes; say you did.
