---
id: thread-sanitizer
title: Data-race detection with ThreadSanitizer (C, C++, Rust, Go)
answers: Do any two threads touch the same memory without synchronisation while my tests run?
rung: 2
section: concurrency
languages: c, cpp, rust, go
kinds: concurrency
cost: medium
detect: cc --version
ran_here: yes
verified: ran
---

## Use when
- You have C, C++ or Rust code (including `unsafe` or FFI) running threads, and Miri cannot run it.
- You want a race check on a real, full-speed test run or integration test.
- You changed locking, atomics or shared buffers.

## Do not use when
- It is Go: `go test -race` is the same engine, see `go-race-detector`.
- You need exhaustive coverage of orderings. TSan reports races only on paths that actually ran.
- You also need ASan in the same binary; the two cannot be combined. Run them in separate builds.

## Set up
- C/C++: compile and link with `-fsanitize=thread -g` (gcc or clang), plus `-pthread`.
- Rust: needs nightly and the `rust-src` component, because the standard library must be rebuilt instrumented:

      rustup toolchain install nightly --component rust-src

## Minimal example
`t.c`, two threads incrementing a global:

    #include <pthread.h>
    int n = 0;
    void *w(void *a) { n++; return 0; }
    int main(void) { pthread_t t; pthread_create(&t, 0, w, 0); n++; pthread_join(t, 0); return 0; }

## Run
    clang -fsanitize=thread -g t.c -o t -pthread && ./t
    RUSTFLAGS="-Zsanitizer=thread" cargo +nightly test -Zbuild-std --target x86_64-unknown-linux-gnu

Passing looks like: no `WARNING: ThreadSanitizer` text and exit 0. Failure prints `WARNING: ThreadSanitizer: data race` with both stacks and exits 66. For Rust, the harness line can still say `test result: ok` while the process exits 66, so check the exit status, not the text. Pass `--target` explicitly or build scripts get instrumented too. Output may differ between runs; here gcc reported the race on some runs only, clang on the first, so repeat the run.

## As a contract check
    {"id": "tsan-tests", "claim": "No data race reported by ThreadSanitizer in the test suite", "kind": "concurrency", "rung": 2, "cmd": "RUSTFLAGS=\"-Zsanitizer=thread\" cargo +nightly test -Zbuild-std --target x86_64-unknown-linux-gnu", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 1800}

## What a pass does not prove
- Only races on paths the run exercised, under the schedules that happened. Rung 2 at best. Run it several times.
- It flags data races, not logic races (a check-then-act bug using proper locks is invisible), and not deadlocks.
- Code not built with the flag (a prebuilt C library) is not watched.
- Check the check: keep the racy example in a test, build it the same way, and confirm exit 66.
