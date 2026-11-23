---
id: rust-lints-strict
title: Clippy with warnings denied, pedantic groups and an unsafe policy
answers: Does the Rust code compile with zero warnings and no lint the project has chosen to forbid?
rung: 1
section: safety
languages: rust
kinds: general, money, parsing
cost: low
detect: cargo clippy --version
ran_here: yes
verified: ran
---

## Use when
- Any Rust change: this is the cheapest check there is and catches real bugs (lossy casts, unchecked indexing, missing `#[must_use]`).
- Code handles money or untrusted input, where `as` casts, `unwrap` and `panic` are hazards.
- You want "warnings are errors" stated once, so it is not a matter of taste.

## Do not use when
- You need to know the code does the right thing. Lints find shapes, not wrong answers.

## Set up
Put the policy in the manifest so every command sees it (`Cargo.toml`):

    [lints.rust]
    unsafe_code = "forbid"

    [lints.clippy]
    pedantic = { level = "warn", priority = -1 }
    unwrap_used = "deny"
    expect_used = "deny"
    cast_possible_truncation = "deny"
    indexing_slicing = "deny"

## Minimal example
`src/lib.rs`:

    #[must_use]
    pub fn add(a: u64, b: u64) -> Option<u64> { a.checked_add(b) }

## Run
    cargo clippy --workspace --all-targets --all-features -- -D warnings
    cargo fmt --all --check

Passing looks like: exit 0 and no `warning:` or `error:` lines. Failure shows as
`error: could not compile` with the lint name; here, dropping `#[must_use]`
fails with `clippy::must_use_candidate` (run here, clippy 0.1.100). `-D
warnings` promotes every enabled pedantic warning to an error, which is the
point. Do not fix a lint with a blanket `#![allow(...)]`; allow one item and
give the reason in a comment.

## As a contract check
    {"id": "clippy-strict", "claim": "Zero clippy warnings including pedantic and the unsafe policy", "kind": "general", "rung": 1, "cmd": "cargo clippy --workspace --all-targets --all-features -- -D warnings", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 900}

## What a pass does not prove
Not that the logic is right. `--all-targets` is needed or tests and examples
are skipped; `--all-features` is needed or feature-gated code is skipped. A
crate with `#![allow(clippy::all)]` or a `[lints]` override passes trivially:
grep for `allow(` additions in the diff. Check the check by adding a
deliberate `.unwrap()` and seeing it fail.
