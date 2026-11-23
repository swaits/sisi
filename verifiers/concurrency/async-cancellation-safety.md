---
id: async-cancellation-safety
title: Cancellation-safety tests that drop a future at every await point
answers: If this async function is cancelled at any await, does shared state stay consistent?
rung: 2
section: concurrency
languages: rust, any
kinds: concurrency, state-machine, money
cost: medium
detect: cargo --version
ran_here: yes
verified: ran
---

## Use when
- An async function mutates shared state, holds a lock, sends a message or writes a file across more than one `.await`.
- The future may be dropped: `select!`, `timeout`, task abort, client disconnect, request cancellation.
- You changed the order of effects around an await, or added an await in the middle of an update.

## Do not use when
- The function has no await between related effects; plain tests are enough.
- You need races between tasks, not cancellation of one. Use `shuttle` or `loom`.

## Set up
No dependency is needed. Drive the future by hand with `Waker::noop()` (stable since Rust 1.85): poll it `k` times, drop it, then assert the invariant. Loop `k` from 1 until the future completes. Each `k` is one await point. In Tokio code, put the same loop on a current-thread runtime with `tokio::time::pause`.

## Minimal example
`src/lib.rs`. `transfer` debits, awaits, then credits; the test finds the lost money.

    pub async fn transfer(a: &Account, amt: i64) {
        *a.from.borrow_mut() -= amt;
        yield_now().await;               // cancelled here: money vanishes
        *a.to.borrow_mut() += amt;
    }
    fn run_until_dropped<F: Future<Output = ()>>(fut: F, k: usize) -> bool {
        let mut fut = std::pin::pin!(fut);
        let mut cx = Context::from_waker(Waker::noop());
        for _ in 0..k { if fut.as_mut().poll(&mut cx).is_ready() { return true; } }
        false                            // dropped on return
    }
    #[test] fn conserved_when_dropped_at_every_await() {
        for k in 1..=10 {
            let a = Account { from: RefCell::new(100), to: RefCell::new(0) };
            let done = run_until_dropped(transfer(&a, 30), k);
            assert_eq!(*a.from.borrow() + *a.to.borrow(), 100, "after {k} polls");
            if done { return; }
        }
        panic!("never finished");
    }

`yield_now` is a hand-written future that returns `Pending` once and calls `wake_by_ref`. Fix the bug by crediting and debiting together, or with a drop guard that restores state.

## Run
    cargo test conserved_when_dropped_at_every_await

Passing looks like: `test result: ok. 1 passed`. Failure shows `assertion failed: ... after 1 polls`, exit 101.

## As a contract check
    {"id": "cancel-safe", "claim": "Invariants hold when transfer is dropped at every await", "kind": "concurrency", "rung": 2, "cmd": "cargo test conserved_when_dropped_at_every_await", "expect": {"exit": 0, "stdout_contains": "1 passed"}, "tier": "deep", "timeout_s": 300}

## What a pass does not prove
- It cancels at poll boundaries of one future in isolation, not with other tasks running between polls. Combine with `shuttle` for that.
- Real I/O futures complete or fail on their own timing; this only tests your own await points with stubbed dependencies.
- The bound on `k` must exceed the real await count, which is why the test panics if it never finishes.
- Check the check: reintroduce the bug and confirm the failure message.
