---
id: prusti
title: Prusti verification for Rust
answers: Does this Rust function satisfy its pre- and postconditions for all inputs?
rung: 1
section: prove
languages: rust
kinds: general
cost: high
detect: cargo prusti --version
ran_here: no
verified: docs
---

## Use when
- You are already on a Rust toolchain Prusti supports and want Viper-based proofs with contract attributes.
- The code is safe Rust with moderate complexity, and unbounded proofs are needed.

## Do not use when
- Status, checked on the repository: Prusti is not abandoned. It moved from `viperproject/prusti-dev` to `prusti/prusti`, has commits almost daily in November 2026 and publishes nightly pre-release builds. But its last non-pre-release was in February 2024 (`v-2024-02-28-1817`), and the user guide warns that some syntax it describes exists only in the "LatestDev" build. Expect the stable binary to be old; on current Rust prefer `verus`, `creusot` or `kani`, and check which Rust toolchain your Prusti build pins (the repository's `rust-toolchain` pins a nightly, `nightly-2026-08-15` at the time of writing).
- Your Rust is recent and you want the old stable build: it supports only the nightly it was built against, so it often cannot compile modern crates.

## Set up
Download a precompiled build from github.com/prusti/prusti/releases (Ubuntu, Windows, macOS; "Pre-release" builds are the current ones), or use the VS Code extension "Prusti Assistant", or build from source (`rustup`, `./x.py setup`, `./x.py build --release`). Every option provides `prusti-rustc` and `cargo-prusti`. Add the contracts crate to the project with `cargo add prusti-contracts` and put `use prusti_contracts::*;` in the file. Not installed here, so the example was not run.

## Minimal example
```rust
use prusti_contracts::*;

#[requires(a >= 0 && a < i32::MAX)]
#[ensures(result == a + 1)]
fn inc(a: i32) -> i32 { a + 1 }
```

## Run
`cargo prusti` from the crate root (Prusti on a single file: `prusti-rustc --edition=2018 path/to/file.rs`). By default Prusti also verifies absence of integer overflow and of reachable `panic!`/`unreachable!`; a `Prusti.toml` can switch overflow checks off.

Passing looks like: the guide says "Prusti should report that verification succeeded" (exact message not quoted there). Failure is reported like a compiler error with the prefix `Prusti: verification error`, for example `error: [Prusti: verification error] statement might panic`. The guide does not state the exit status; as a rustc wrapper it should exit non-zero on errors, but confirm with a wrong postcondition.

## As a contract check
```json
{"id": "prove-inc-prusti", "claim": "inc returns a + 1 for every a below i32::MAX", "kind": "general", "rung": 1, "cmd": "cargo prusti", "expect": {"exit": 0}, "timeout_s": 1800, "tier": "deep"}
```

## What a pass does not prove
- Only annotated functions; `#[trusted]` ones are assumed. Grep for it.
- Quantifiers and loops need invariants that the tool may fail to use, giving false alarms rather than false passes.
- Not run here; commands come from the Prusti README and user guide. The guide itself notes some syntax needs the LatestDev build, so the snippet may differ by version.
