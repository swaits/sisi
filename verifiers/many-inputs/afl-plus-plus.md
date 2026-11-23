---
id: afl-plus-plus
title: Fuzzing C, C++ and Rust with AFL++
answers: Can any input make this native program or library crash, hang or trip a sanitizer?
rung: 2
section: many-inputs
languages: c, cpp, rust
kinds: parsing, general
cost: medium
detect: afl-fuzz -h
ran_here: no
verified: docs
---

## Use when

- The target is C or C++ (or Rust via `cargo-afl`) that reads a file or stdin, and you want a mature fuzzer with many mutation strategies.
- A program has a command-line entry point and cannot easily be turned into a libFuzzer function.
- You want to run several fuzzer processes for long periods on a server.

## Do not use when

- A libFuzzer-style function is easy to write: `cargo-fuzz`, `go-fuzz` or `jazzer` are less work.
- You only need a few minutes of sanity fuzzing of a Rust crate: `cargo-fuzz` is simpler.

## Set up

C and C++: build the target with an AFL compiler (`afl-clang-fast` or `afl-cc`):

    CC=afl-clang-fast CXX=afl-clang-fast++ ./configure --disable-shared && make

Rust: `cargo install cargo-afl`, add `afl = "*"` to `Cargo.toml`, then `cargo afl build`.
Put a few small valid inputs in `in/`.

## Minimal example (Rust, `src/main.rs`)

    #[macro_use]
    extern crate afl;

    fn main() {
        fuzz!(|data: &[u8]| {
            if let Ok(s) = std::str::from_utf8(data) {
                let _ = mycrate::parse_pair(s);
            }
        });
    }

C and C++: `afl-fuzz -i in -o out -- ./target @@` (`@@` is replaced by the input
file name; leave it out to feed stdin).

## Run

    cargo afl build
    cargo afl fuzz -i in -o out target/debug/<binary>

AFL runs until stopped; for a time budget use the time-limit option that
`afl-fuzz -h` lists (I believe `-V <seconds>`; not confirmed against the docs here).
Passing looks like: the run ends with "saved crashes: 0" in the status screen. Failure
leaves crashing inputs in `out/default/crashes/`. Reproduce one with
`cargo afl run <binary> < out/default/crashes/<file>`.

## As a contract check

    {"id": "afl-parse-pair", "claim": "AFL++ finds no crash in parse_pair in 60 seconds", "kind": "parsing", "rung": 2, "cmd": "sh scripts/afl-budget.sh 60 && test -z \"$(ls out/default/crashes 2>/dev/null | grep -v README)\"", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 600}

`scripts/afl-budget.sh` is yours: it must run `cargo afl fuzz` with the time limit
and exit. AFL itself exits non-zero or hangs in ways that need that wrapper.

## What a pass does not prove

- A run with no crashes means none found in the time given; a short run in a CI machine without core-pattern or CPU-governor tuning may fail to start (AFL prints the fix).
- It finds crashes, not wrong outputs. Add assertions in the harness.
- Not run here (AFL++ and `cargo-afl` are not installed). Compile and run commands for C and Rust are from the AFL++ and Rust fuzz book pages; the time-limit flag is unconfirmed. Check the check: plant a crash behind a recognisable input.
