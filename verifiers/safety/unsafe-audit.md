---
id: unsafe-audit
title: Auditing and forbidding unsafe Rust
answers: Is there any unsafe code in this crate or its dependencies, and is what exists justified and tested?
rung: 1
section: safety
languages: rust
kinds: general, concurrency
cost: low
detect: cargo --version
ran_here: yes
verified: ran
---

Ran here: `#![forbid(unsafe_code)]` refusing an `unsafe` block. Not run here:
`cargo geiger` (not installed) and Miri (component not on this toolchain);
their flags are from memory.

## Use when
- The crate says it needs no `unsafe`: make the compiler enforce that.
- A change adds `unsafe`, or a dependency is added or upgraded and you want its unsafe footprint.
- Unsafe code exists and you need its undefined behaviour checked (Miri).

## Do not use when
- The crate is a thin wrapper over FFI, where unsafe is the job; audit each block by hand and test under sanitisers instead.

## Set up
    # forbid: top of src/lib.rs and src/main.rs
    #![forbid(unsafe_code)]
    cargo install cargo-geiger        # counts unsafe in the crate and dependencies
    rustup +nightly component add miri

## Minimal example
`src/lib.rs`:

    #![forbid(unsafe_code)]
    pub fn first(v: &[u8]) -> Option<u8> { v.first().copied() }

Adding `unsafe { *v.get_unchecked(0) }` makes the build fail with
"usage of an `unsafe` block".

## Run
    cargo build
    cargo geiger --all-features              # report; unsafe counts per dependency
    cargo +nightly miri test                 # runs tests under the UB-detecting interpreter

Passing looks like: `cargo build` exits 0 under forbid; geiger shows 0 used
unsafe in your own crates (`🔒` rows); Miri exits 0. Failure: a compile error,
a non-zero geiger count in your crate, or a Miri "Undefined Behavior" message.
For concurrency, see `miri`, `loom` and `thread-sanitizer` in the concurrency section.

## As a contract check
    {"id": "no-unsafe", "claim": "The crate forbids unsafe code and builds", "kind": "general", "rung": 1, "cmd": "grep -q 'forbid(unsafe_code)' src/lib.rs && cargo build --all-features", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 600}

## What a pass does not prove
`forbid` covers your crate only; dependencies may still use unsafe (that is what
geiger reports, and it counts, it does not judge). Miri finds UB only on paths
the tests run, and cannot run most FFI or I/O. A `forbid` that someone moved
into `#![allow]` is a silent failure: keep the grep in the check.
