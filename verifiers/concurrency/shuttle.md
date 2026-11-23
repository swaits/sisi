---
id: shuttle
title: Randomised schedule testing for Rust concurrency with shuttle
answers: Does my concurrent or async Rust code hold its invariants across many different thread schedules?
rung: 2
section: concurrency
languages: rust
kinds: concurrency, state-machine
cost: medium
detect: cargo --version
ran_here: yes
verified: ran
---

## Use when
- The concurrent code is too large for `loom` to explore exhaustively, but you want schedule control and replay.
- You need a failing schedule you can replay exactly, which a plain stress test cannot give.
- You want to test code built on `std::sync`, `std::thread` or futures with a controlled scheduler.

## Do not use when
- The component is small enough for `loom`; exhaustive is stronger.
- The bug is in memory ordering. Shuttle models sequentially consistent execution, not weak memory.
- The code uses real I/O or wall-clock time; shuttle cannot control them.

## Set up
Add `shuttle` as a dev-dependency and have the code under test use `shuttle::sync` and `shuttle::thread` (via a `cfg` switch or a small facade module).

    cargo add --dev shuttle

## Minimal example
A lost-update bug; shuttle finds it within a few schedules.

    #[cfg(test)]
    mod tests {
        use shuttle::sync::{atomic::{AtomicUsize, Ordering}, Arc};
        use shuttle::thread;
        fn body() {
            let n = Arc::new(AtomicUsize::new(0)); let n2 = n.clone();
            let t = thread::spawn(move || { let v = n2.load(Ordering::SeqCst); n2.store(v + 1, Ordering::SeqCst); });
            let v = n.load(Ordering::SeqCst); n.store(v + 1, Ordering::SeqCst);
            t.join().unwrap();
            assert_eq!(n.load(Ordering::SeqCst), 2);
        }
        #[test] fn random_schedules() { shuttle::check_random(body, 1000); }
    }

Use `fetch_add` to fix it. Other entry points: `shuttle::check_pct(body, iters, depth)` and `shuttle::check_dfs(body, Some(max_iters))`.

## Run
    cargo test random_schedules

Passing looks like: `test result: ok. 1 passed`, exit 0. Failure prints `failing schedule:` followed by a string, then the panic; exit 101. Replay it with `shuttle::replay(body, "<schedule string>")` to debug deterministically.

## As a contract check
    {"id": "shuttle-schedules", "claim": "Invariant holds across 1000 random schedules", "kind": "concurrency", "rung": 2, "cmd": "cargo test random_schedules", "expect": {"exit": 0, "stdout_contains": "1 passed"}, "tier": "deep", "timeout_s": 300}

## What a pass does not prove
- It samples schedules. Rung 2 at best; a rare interleaving can be missed. Raise the iteration count and use `check_pct` for deeper bugs.
- It models sequential consistency only, so weak-memory bugs pass.
- Only code using shuttle's types is controlled. A stray `std::sync::Mutex` is not.
- Check the check: reinstate the bug and see `failing schedule`. Confirm the test name matched (`1 passed`, not `0 passed`).
