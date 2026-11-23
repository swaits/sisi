---
id: verus
title: Verus deductive verification for Rust
answers: Does this Rust code meet its requires/ensures specification for all inputs, with no size bound?
rung: 1
section: prove
languages: rust
kinds: general, state-machine
cost: high
detect: verus --version
ran_here: no
verified: docs
---

## Use when
- You write new Rust (or a core module) that needs unbounded proofs: data structures, allocators, protocols, algorithms with loops.
- You can accept writing specs and loop invariants inline in the Rust file, and ghost code.
- `kani` bounds are too small and a separate Lean model would drift from the code.

## Do not use when
- You need to verify existing unmodified Rust with traits and iterators everywhere: Verus supports a subset.
- A bounded proof is enough. `kani` takes minutes to set up.

## Set up
Download a release binary from github.com/verus-lang/verus/releases (the weekly point releases are recommended), unzip it, and run `./verus`. It tells you which `rustup` toolchain it pins (for example `rustup install 1.86.0-x86_64-unknown-linux-gnu`) and how to install it; repeat until `./verus` stops complaining. For a Cargo project the release also ships `cargo-verus`; put both on PATH, then `cargo verus new --bin my_project`, or in an existing crate `cargo add vstd` and add `[package.metadata.verus]` with `verify = true` to `Cargo.toml` (details in the guide chapter "Using Verus via Cargo"). Not installed here, so the example was not run.

## Minimal example
`max.rs`:
```rust
use vstd::prelude::*;

verus! {
fn max(a: u32, b: u32) -> (r: u32)
    ensures r >= a, r >= b, r == a || r == b
{
    if a > b { a } else { b }
}
} // verus!

fn main() {}
```
Loops need `invariant` and `decreases` clauses; arithmetic overflow is a proof obligation unless the type is `int`.

## Run
`verus max.rs`, or in a Cargo project `cargo verus verify` (not `cargo verus focus`, which skips the proofs of dependencies).

Passing looks like (from the guide):

    note: verifying root module

    verification results:: 1 verified, 0 errors

Failure prints `error: assertion failed` (or a failed `ensures`) with the source location, then `error: aborting due to previous error` and `verification results:: 0 verified, 1 errors`. The guide does not state the process exit status; Verus is a rustc-based driver and should exit non-zero on errors, but confirm it with a deliberately wrong spec before relying on exit alone. The contract below also checks the text. `verus file.rs --compile` additionally builds a binary.

## As a contract check
```json
{"id": "prove-max-verus", "claim": "max returns one of its arguments and is at least both", "kind": "general", "rung": 1, "cmd": "verus max.rs", "expect": {"exit": 0, "stdout_contains": "verified, 0 errors"}, "timeout_s": 900, "tier": "deep"}
```

## What a pass does not prove
- Only the `ensures` you wrote and only functions inside `verus!`; code outside it is trusted. Search for `#[verifier::external]`, `assume(`, `admit(` and `external_body`, which skip proof.
- Verus and its trusted specs of `vstd` are part of what you trust.
- Check the check can fail: weaken the body and confirm an error appears, and that the exit status is non-zero.
- Commands and output format were read from the Verus guide and INSTALL.md, not run here.
