---
id: creusot
title: Creusot deductive verification for Rust
answers: Does this Rust code satisfy its contracts for all inputs, proved through Why3?
rung: 1
section: prove
languages: rust
kinds: general
cost: high
detect: cargo creusot --help
ran_here: no
verified: docs
---

## Use when
- You want proofs for safe Rust including ownership-heavy code (it models borrows prophetically) and are comfortable with the Why3 ecosystem.
- Contracts as attributes (`#[requires]`, `#[ensures]`, `#[logic]`) suit you better than a separate macro block.

## Do not use when
- You need low set-up cost. Use `kani`. Creusot needs opam, Why3 and SMT solvers.
- Unsafe or heavily dynamic code is involved.

## Set up
From the Creusot README and guide ("Installation"): there is no `cargo install`. Needs `rustup`, `opam` (for Why3 and `why3find`) and `curl` (to download the provers alt-ergo, z3, cvc4 and cvc5). Then:

    git clone https://github.com/creusot-rs/creusot
    cd creusot
    ./INSTALL                  # a few minutes; makes a private opam switch under ~/.local/share/creusot/_opam
    cargo creusot --help       # check the install

Create a project with `cargo creusot new project-name`, or add the contracts crate to an existing one (the crate is now `creusot-std`, imported as `creusot_std`; if the compiler says its items are missing, the guide's troubleshooting section shows a `[patch.crates-io]` entry pointing at the checkout). Not installed here, so the example was not run.

## Minimal example
```rust
use creusot_std::prelude::*;

#[requires(a@ + b@ <= u32::MAX@)]
#[ensures(result@ == a@ + b@)]
pub fn add(a: u32, b: u32) -> u32 { a + b }
```
`x@` is the logical (mathematical) value of `x`. Spec language details change by release; follow the guide's current examples.

## Run
`cargo creusot` compiles the crate to Coma (into `verif/`) and then runs the provers through Why3find. The two steps can be run separately: `cargo creusot --only=coma` and `cargo creusot --only=prove`. A Coma file can be named to prove just that one; `-i` opens the Why3 IDE when a proof fails; `--replay` only re-checks existing proofs (`proof.json`). There is no `cargo creusot prove` subcommand in the current guide.

Passing looks like: the guide says a successful run "gives us the certainty that functions defined in this package satisfy their contracts". It does not state what the output or exit status looks like for unproved goals; check on a deliberately wrong contract that `cargo creusot` exits non-zero before relying on exit alone. Only libraries and binaries are compiled, not tests or examples.

## As a contract check
```json
{"id": "prove-add-creusot", "claim": "add returns the exact sum when it fits in u32", "kind": "general", "rung": 1, "cmd": "cargo creusot", "expect": {"exit": 0}, "timeout_s": 1800, "tier": "deep"}
```

## What a pass does not prove
- Only the contracts written; functions marked `#[trusted]` are assumed. Grep for `trusted`.
- Proofs by SMT solvers can time out; whether an unproved goal makes `cargo creusot` exit non-zero is not documented, so test it.
- Not run here; commands come from the Creusot README, guide and command-line reference. `#[trusted]` (also in the guide) skips checking of the function body, and the `x@` notation for the logical value is as in the guide's quick start.
