---
id: cargo-fuzz
title: Coverage-guided fuzzing of Rust with cargo-fuzz (libFuzzer)
answers: Can any input I did not think of make this Rust code panic, overflow, hang or break an assertion?
rung: 2
section: many-inputs
languages: rust
kinds: parsing, general, state-machine
cost: medium
detect: cargo fuzz --version
ran_here: yes
verified: ran
---

## Use when

- Rust code takes untrusted or complex input: parsers, decoders, importers, journal and file readers, request handlers.
- You want a run with a time budget and a saved reproducer for any crash.
- You have a few valid example inputs to seed the search.

## Do not use when

- The input must satisfy a grammar that raw bytes rarely meet; use `structure-aware-fuzzing`.
- You need a law checked on structured values with shrinking: `proptest`.
- You cannot run nightly Rust. cargo-fuzz needs a nightly toolchain.

## Set up

    cargo install cargo-fuzz          # once; needs rustup nightly
    cargo fuzz init                   # creates fuzz/ with fuzz_target_1
    mkdir -p fuzz/corpus/fuzz_target_1 fuzz/seeds/fuzz_target_1

Put small valid inputs in `fuzz/seeds/<target>/` and commit them. The `corpus/`
directory grows during runs and is normally git-ignored. Crash files appear in
`fuzz/artifacts/<target>/`.

## Minimal example (`fuzz/fuzz_targets/fuzz_target_1.rs`)

    #![no_main]
    use libfuzzer_sys::fuzz_target;

    fuzz_target!(|data: &[u8]| {
        if let Ok(s) = std::str::from_utf8(data) {
            let _ = mycrate::parse_pair(s);   // must never panic, only return None/Err
        }
    });

## Run

    cd <crate> && RUSTUP_TOOLCHAIN=nightly cargo fuzz run fuzz_target_1 \
        fuzz/corpus/fuzz_target_1 fuzz/seeds/fuzz_target_1 -- -max_total_time=60 -timeout=10

The first directory after the target is where new inputs are written; later ones
are read-only seeds. The directory must already exist (the run refuses with
"The required directory ... does not exist" otherwise).
Passing looks like: `Done N runs in 60 second(s)`, exit 0.
Failure shows the panic message, `Test unit written to fuzz/artifacts/fuzz_target_1/crash-<hash>`,
and exit 1. Replay one crash with `cargo fuzz run fuzz_target_1 fuzz/artifacts/fuzz_target_1/crash-<hash>`;
after the fix, copy it into `fuzz/seeds/fuzz_target_1/` as a regression case.

## As a contract check

    {"id": "fuzz-parse-pair", "claim": "parse_pair neither panics nor hangs on 60 seconds of fuzzed input", "kind": "parsing", "rung": 2, "cmd": "cd fuzz-host && RUSTUP_TOOLCHAIN=nightly cargo fuzz run fuzz_target_1 fuzz/corpus/fuzz_target_1 fuzz/seeds/fuzz_target_1 -- -max_total_time=60 -timeout=10", "expect": {"exit": 0, "stdout_contains": "Done"}, "tier": "deep", "timeout_s": 600}

## What a pass does not prove

- A clean run only means nothing was found in that time. The bug seeded in the example needs a specific prefix; a 30-second run on a numeric comparison deeper in the code did not find an equivalent one. Longer runs and good seeds matter.
- It finds crashes, not wrong answers. Add assertions inside the target (round trip, agreement with a reference) to catch those.
- Check the check: plant a panic behind a recognisable input and see the fuzzer find it, then remove it. Also check the target actually reaches the code (`cargo fuzz coverage`).
