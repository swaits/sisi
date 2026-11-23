---
id: address-and-ub-sanitizers
title: Memory-error and undefined-behaviour detection with ASan, UBSan and MSan
answers: Does my C, C++ or unsafe Rust code read or write bad memory, overflow, or use uninitialised data while the tests run?
rung: 2
section: concurrency
languages: c, cpp, rust
kinds: general, concurrency
cost: low
detect: cc --version
ran_here: yes
verified: ran
---

## Use when
- You changed C, C++ or `unsafe` Rust, FFI, buffers, pointer arithmetic or parsing of untrusted bytes.
- A test crashes only sometimes, or output differs by build mode, which hints at undefined behaviour.
- You want a fast memory-safety check that works on code too heavy for Miri.

## Do not use when
- The code is safe Rust with no FFI; the compiler already prevents these.
- You need data-race detection; use `thread-sanitizer`. ASan and TSan cannot be combined in one binary.
- MSan on Linux needs clang and an instrumented standard library; skip it if you cannot rebuild dependencies.

## Set up
- ASan (heap and stack overflow, use-after-free, leaks): `-fsanitize=address -g`.
- UBSan (signed overflow, bad shifts, null deref): `-fsanitize=undefined -fno-sanitize-recover=undefined`, so a finding stops the run with a non-zero exit.
- MSan (uninitialised reads, clang only): `-fsanitize=memory -g`.
- Rust nightly: `RUSTFLAGS="-Zsanitizer=address"` (or `memory`) with `--target <host triple>`. `memory` also needs `-Zbuild-std`.

## Minimal example
`a.c`, a heap overflow:

    #include <stdlib.h>
    int main(int argc, char **argv) { int *a = malloc(4 * sizeof(int)); a[argc + 3] = 1; free(a); return 0; }

Rust, a read one past a vector:

    pub fn read_past_end() -> u8 { let v = vec![1u8, 2, 3]; unsafe { *v.as_ptr().add(3) } }
    #[test] fn t() { let _ = read_past_end(); }

## Run
    gcc -fsanitize=address -g a.c -o a && ./a
    RUSTFLAGS="-Zsanitizer=address" cargo +nightly test --target x86_64-unknown-linux-gnu --lib

Passing looks like: exit 0 and no `ERROR: AddressSanitizer` text. Failure prints `ERROR: AddressSanitizer: heap-buffer-overflow ... SUMMARY: ...` and exits 1; UBSan prints `runtime error: signed integer overflow` and, with `-fno-sanitize-recover`, exits 1. MSan prints `use-of-uninitialized-value` and exits 1.

## As a contract check
    {"id": "asan-tests", "claim": "No memory errors under AddressSanitizer in the unit tests", "kind": "general", "rung": 2, "cmd": "RUSTFLAGS=\"-Zsanitizer=address\" cargo +nightly test --target x86_64-unknown-linux-gnu --lib", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 900}

## What a pass does not prove
- It only watches code paths the tests execute. Rung 2 at best; pair with fuzzing to reach more paths.
- ASan misses uninitialised reads; MSan misses overflows; neither covers everything UBSan checks. Run the ones that fit.
- Only instrumented code is checked. A prebuilt library is not.
- Check the check: keep a deliberately bad test (the overflow above) and confirm each sanitizer build fails on it. The sanitizer runtime must be installed, or the build fails to link; a build failure is not a pass.
