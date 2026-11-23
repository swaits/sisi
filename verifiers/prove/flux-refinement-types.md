---
id: flux-refinement-types
title: Flux refinement types for Rust
answers: Can my Rust signatures carry value constraints (positive, in range, indexes in bounds) that the compiler checks?
rung: 1
section: prove
languages: rust
kinds: general
cost: medium
detect: command -v cargo-flux
ran_here: no
verified: docs
---

## Use when
- The properties are small value constraints on arguments and results: an index below a length, a non-zero divisor, a sum within a bound.
- You want checking close to type checking, with little proof effort, and mostly automatic inference of loop invariants.

## Do not use when
- The property is relational or complex (sorted, permutation, money laws). Use `verus`, `lean4-proofs` or `kani`.
- You cannot use Flux's pinned nightly toolchain.

## Set up
From the Flux book ("Installing and Running Flux"): the only way to use Flux is to build it from source. Requirements: `rustup`, `liquid-fixpoint` (nightly binaries on its GitHub releases) and `z3` 4.15 or later, both on PATH. Then either `curl -fsSL https://raw.githubusercontent.com/flux-rs/flux/main/install.sh | bash`, or:

    git clone https://github.com/flux-rs/flux && cd flux
    cargo xtask install        # installs `flux` and `cargo-flux`, and the sysroot in ~/.flux/sysroot

The repository's `rust-toolchain.toml` pins the nightly. To use it in a Cargo package, add to `Cargo.toml`:

    [package.metadata.flux]
    enabled = true
    [dependencies]
    flux-rs = { git = "https://github.com/flux-rs/flux.git" }

Not installed here, so the example was not run.

## Minimal example
```rust
use flux_rs::attrs::*;

#[spec(fn(x: i32{x > 0}) -> i32{v: v > x})]
fn bump(x: i32) -> i32 { x + 1 }
```
On a single file run with the standalone `flux` binary, write the attribute as `#[flux::spec(...)]` instead. Overflow of `x + 1` is checked only if you switch on `check-overflow` in the `[package.metadata.flux]` section (default `none`; see the book's "Checking Overflows"); this example passes without it.

## Run
`cargo flux` (a package), or `flux --crate-type=lib path/to/file.rs` (one file; it accepts the same flags as `rustc`).

Passing looks like: no errors reported. Failure: the book's example shows `error[FLUX]: postcondition might not hold` with the source location (a wrong body such as `x - 1`). The book does not state the exit status; the driver is a rustc wrapper and should exit non-zero on errors, but confirm with a deliberately wrong body.

## As a contract check
```json
{"id": "prove-bump-flux", "claim": "bump returns a value greater than its positive argument", "kind": "general", "rung": 1, "cmd": "cargo flux", "expect": {"exit": 0}, "timeout_s": 900, "tier": "deep"}
```

## What a pass does not prove
- Only the refinements stated in signatures; unannotated code gets default (weak) types. `#[flux_rs::trusted]` (`#[flux::trusted]` on a single file) skips checking.
- Annotations are written by you; a trivially true refinement verifies trivially.
- Not run here; commands and messages come from the Flux book. Check the check: change the body to `x - 1` and confirm `cargo flux` fails.
