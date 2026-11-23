---
id: lock-order-and-deadlock
title: Deadlock detection and lock-order checking (parking_lot, Go, Clang)
answers: Can my code deadlock by taking locks in conflicting orders?
rung: 2
section: concurrency
languages: rust, go, c, cpp
kinds: concurrency
cost: low
detect: cargo --version
ran_here: yes
verified: ran
---

## Use when
- Code takes more than one lock, or calls out to user code while holding one.
- A test or service hangs and you suspect a deadlock.
- You changed lock acquisition order, or added a new lock to a module.

## Do not use when
- A single lock and no callbacks; there is nothing to order.
- You need a guarantee. These tools report deadlocks that happen or conflicts that were seen, not all possible ones; `loom` or `shuttle` explore more orderings.

## Set up
- Rust: `cargo add parking_lot --features deadlock_detection`, use `parking_lot::Mutex`, and run a checker thread.
- Go: the runtime prints `fatal error: all goroutines are asleep - deadlock!` and exits 2 when every goroutine blocks. Partial deadlocks are not detected; add a test timeout (`go test -timeout 60s`).
- C/C++: ThreadSanitizer reports `lock-order-inversion` (potential deadlock) even if no hang occurred; build with `-fsanitize=thread`.

## Minimal example
Rust checker thread, started at program or test start:

    std::thread::spawn(|| loop {
        std::thread::sleep(std::time::Duration::from_secs(1));
        let d = parking_lot::deadlock::check_deadlock();
        if d.is_empty() { continue; }
        for (i, ts) in d.iter().enumerate() {
            eprintln!("deadlock #{i}");
            for t in ts { eprintln!("thread {:?}\n{:?}", t.thread_id(), t.backtrace()); }
        }
        std::process::exit(101);
    });

A program where two threads lock `a` then `b` and `b` then `a` (with a short sleep between) prints `deadlock #0` with backtraces and exits 101. Without the checker it hangs forever.

## Run
    cargo test            # with the checker thread started in the test setup
    timeout 120 cargo test

Passing looks like: tests finish, exit 0. Failure is the `deadlock #N` report and exit 101, or a timeout (exit 124 from `timeout`).

## As a contract check
    {"id": "no-deadlock", "claim": "Test suite finishes with no parking_lot deadlock reported", "kind": "concurrency", "rung": 2, "cmd": "timeout 300 cargo test --features deadlock_detection", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 330}

## What a pass does not prove
- It detects a deadlock only if the test actually drove the threads into it. Rung 2. A hang with no checker is the failure signal, so always run under a timeout.
- `parking_lot` detection covers its own locks, not `std::sync::Mutex`, channels or async mutexes.
- Go's detector misses deadlocks while any other goroutine is alive (such as an HTTP server).
- Check the check: keep a two-lock inversion test and confirm it fails with the checker on.
