---
id: proof-bridging
title: Bridging a proof on a simplified type to the real type with a differential test
answers: My proof was done on a simpler representation (like i64); does the real code (like Decimal) behave the same?
rung: 2
section: prove
languages: any
kinds: money, general
cost: medium
detect:
ran_here: yes
verified: ran
---

## Use when
- A proof tool handles only a simple model (Kani on `i64`, Lean on `Nat`, Dafny on `int`) and the production code uses another type (`Decimal`, `BigInt`, floating point, a struct).
- You want to say the proof carries over to the real code, with evidence you can run.

## Do not use when
- You can prove the real type directly (`aeneas-rust-to-lean`, `verus`). Do that instead.
- The two types differ in the property you proved (rounding, overflow, ordering): then the bridge must show where they agree, and the claim shrinks to that region.

## Set up
Write the model function and the real function with the same shape. In the test, generate inputs, run both, convert the model result to the real type, and assert equal. Include an independent exact reference (a big-integer or rational one) as a third voice when the model is lossy. Use `proptest` in Rust or `hypothesis` in Python for random inputs, plus a fixed list of edge cases (zero, minimum, maximum, ties, negatives).

## Minimal example
```rust
fn halve_model(x: i64) -> i64 { x / 2 }          // what the proof covers
fn halve_real(x: i128) -> i128 { x / 2 }         // what production runs (wider type)

#[test]
fn bridge_agrees() {
    let mut s: u64 = 0x9E37_79B9_7F4A_7C15;       // fixed seed: reproducible
    for _ in 0..100_000 {
        s ^= s << 13; s ^= s >> 7; s ^= s << 17;  // xorshift
        let x = s as i64;
        assert_eq!(halve_model(x) as i128, halve_real(x as i128));
    }
}
```
State in the test's doc comment which proof it carries (`kani proof halve_is_floor`), over which inputs, and what is assumed equal.

## Run
`cargo test bridge`

Passing looks like: exit 0 and `test tests::bridge_agrees ... ok`. Failure: the first disagreeing input in the panic message.

## As a contract check
```json
{"id": "prove-bridge-i64-to-wide", "claim": "The real halve agrees with the proved i64 model on 100000 seeded inputs and the edge cases", "kind": "money", "rung": 2, "cmd": "cargo test bridge", "expect": {"exit": 0, "stdout_contains": "test result: ok"}, "tier": "deep", "timeout_s": 600}
```

## What a pass does not prove
- It samples, so the bridge is rung 2, and the proved claim for the real type is only as strong as the bridge. Say so in the contract claim.
- The bridge must show: same results where both are defined; both refuse (error or `None`) on the same inputs; behaviour at the model's bounds; and every wrapper between the proof and the real call. A wrapper that is not in the bridge is unproved.
- Compare against an independent exact reference where the model truncates (for example integer division drops fractions that `Decimal` keeps), or you test two things that share a flaw.
- Generators that rarely hit edges miss them; list ties, zero, min and max explicitly.
