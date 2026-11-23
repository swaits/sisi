---
id: kani
title: Kani bounded model checking for Rust
answers: Can this Rust function panic, overflow or break an assertion for any input within a bound?
rung: 1
section: prove
languages: rust
kinds: general, money, parsing
cost: medium
detect: cargo kani --version
ran_here: yes
verified: ran
---

## Use when
- A small, mostly pure function (money arithmetic, index maths, bounded parsers, state transitions) must hold for all inputs, not a sample.
- You want "cannot panic or overflow" for every value of the input types, such as every `u32`.
- A property test would be the next best thing but you want a proof within the bound.

## Do not use when
- The claim needs unbounded sizes or heavy loops over big data; use `lean4-proofs` or `verus`.
- The function does I/O, threads or unsupported FFI.
- You have not read `kani-proof-hygiene`. A Kani pass can be vacuous.

## Set up
`cargo install --locked kani-verifier && cargo kani setup` (once; downloads a nightly toolchain and CBMC). Put harnesses under `#[cfg(kani)]` so normal builds ignore them.

## Minimal example
`src/lib.rs`:
```rust
pub fn add_cents(a: u32, b: u32) -> Option<u32> { a.checked_add(b) }

#[cfg(kani)]
mod proofs {
    use super::*;

    #[kani::proof]
    fn add_cents_is_exact_or_none() {
        let a: u32 = kani::any();
        let b: u32 = kani::any();
        let wide = a as u64 + b as u64;
        match add_cents(a, b) {
            Some(s) => assert_eq!(s as u64, wide),
            None => assert!(wide > u32::MAX as u64),
        }
        kani::cover!(add_cents(a, b).is_none(), "overflow case reachable");
        kani::cover!(add_cents(a, b).is_some(), "ok case reachable");
    }
}
```
Loops need `#[kani::unwind(N)]`; restrict inputs with `kani::assume(...)`, sparingly.

## Run
`cargo kani --output-format terse`

Passing looks like: exit 0, `2 of 2 cover properties satisfied`, `VERIFICATION:- SUCCESSFUL` and `Complete - 1 successfully verified harnesses, 0 failures, 1 total.` (Kani 0.68.0). Failure: `VERIFICATION:- FAILED` with the failing check and a nonzero exit. To select one harness use `--harness <fully::qualified::name> --exact`; an unqualified name with `--exact` is refused.

## As a contract check
```json
{"id": "prove-add-cents-kani", "claim": "add_cents never wraps: Some(sum) is exact and None only when the sum exceeds u32::MAX", "kind": "money", "rung": 1, "cmd": "cargo kani --output-format terse", "expect": {"exit": 0, "stdout_contains": "successfully verified harnesses, 0 failures"}, "tier": "deep", "timeout_s": 1800}
```

## What a pass does not prove
- Only inputs within the harness: `unwind` bounds, array lengths, `kani::assume`. Beyond them nothing is claimed.
- An over-tight `assume` or unreachable code makes the pass vacuous. See `kani-proof-hygiene`.
- Harness code can be wrong. Confirm each harness can fail: flip an assertion and see `FAILED`.
- Its model of the standard library has gaps (e.g. known bugs on bulk copies of symbolic length); a pass is not a statement about the real binary.
