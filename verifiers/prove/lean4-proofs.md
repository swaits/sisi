---
id: lean4-proofs
title: Proving properties in Lean 4 with a lake project and lake build
answers: Is this property true for all inputs, with a machine-checked proof rather than tests?
rung: 1
section: prove
languages: any
kinds: general, money, state-machine
cost: high
detect: lake --version
ran_here: yes
verified: ran
---

## Use when
- The claim is a law over all inputs of a function you can write in Lean (or a model of your code): sums are conserved, a rounding step is within half a unit, an operation is its own inverse.
- Tests and Kani only cover bounded cases and you need the law at any size.
- You can state the law as a `theorem` and let `lake build` be the judge.

## Do not use when
- The code under test is Rust or C and you need the proof about that code. Use `aeneas-rust-to-lean`, `kani` or `verus`.
- The property is a quick bounded check. `kani` or `exhaustive-small-domain` cost far less.

## Set up
```
lake new demo           # then in lakefile.toml set defaultTargets = ["Demo"] and delete the lean_exe stanza and Main.lean
cd demo
```
`lean-toolchain` pins the Lean version; commit it and `lake-manifest.json`. Mathlib is optional: add `[[require]] name = "mathlib" scope = "leanprover-community"` to `lakefile.toml` only when you need it (a first build downloads a large cache; run `lake exe cache get`). Without Mathlib, the tactics `simp`, `omega` and `decide` already handle most arithmetic.

## Minimal example
`Demo/Basic.lean`:
```lean
def clamp (lo hi x : Nat) : Nat := if x < lo then lo else if hi < x then hi else x

theorem clamp_le (lo hi x : Nat) (h : lo ≤ hi) :
    lo ≤ clamp lo hi x ∧ clamp lo hi x ≤ hi := by
  unfold clamp
  split <;> (try split) <;> omega
```
The agent loop: edit, run `lake build`, read the error (it shows the unsolved goal), adjust. Put `sorry` in one place at a time to see the goal, then replace it. `lake env lean Demo/Basic.lean` checks one file faster.

## Run
`lake build --wfail`

Passing looks like: exit 0 with lines like `✔ Built Demo.Basic`. A wrong proof gives `error:` with the goal and exit 1 (observed). Plain `lake build` exits 0 even when a proof contains `sorry` (it only warns), so use `--wfail` and the audit in `lean-axiom-audit`.

## As a contract check
```json
{"id": "prove-clamp-lean", "claim": "clamp stays within [lo, hi] for all Nat inputs, proved in Lean 4", "kind": "general", "rung": 1, "cmd": "lake build --wfail", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 1800}
```

## What a pass does not prove
- It proves the theorem about the Lean definition. If the definition is not the real code, add a bridge (`proof-bridging`, `aeneas-rust-to-lean`).
- A theorem that is easier than the claim (wrong statement, hypotheses that cannot hold) builds fine. Read the statement, and prove a non-trivial instance with `example`.
- `sorry` and extra axioms pass the build; see `lean-axiom-audit`.
