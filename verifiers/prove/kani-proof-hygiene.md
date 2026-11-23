---
id: kani-proof-hygiene
title: Keeping Kani proofs honest: covers, bounds, canary, harness list, time caps
answers: Are my Kani proofs vacuous, silently skipped, or cut off, so that "verified" means less than it says?
rung: 1
section: prove
languages: rust
kinds: general, money
cost: medium
detect: cargo kani --version
ran_here: yes
verified: ran
---

## Use when
- You have Kani harnesses and a CI check that says "all verified".
- Harnesses use `kani::assume`, `unwind`, or restricted inputs, where an over-tight bound makes a proof pass for no reason.
- The suite is slow, or you split it into fast and slow sets.

## Do not use when
- There are no Kani harnesses yet. See `kani`.

## Set up
A Rust and Lean 4 project does all of this in `justfile` with a shell wrapper around `cargo kani`. Copy the ideas, not its domain code.

## Minimal example
1. Cover every interesting case. `kani::cover!(cond, "message")` fails the check if `cond` is unreachable under the harness's assumptions:
```rust
#[kani::proof]
fn vacuous() {
    let x: u8 = kani::any();
    kani::assume(x > 10 && x < 5);      // impossible: nothing is checked
    assert!(x == 99);
    kani::cover!(x > 0, "never reached");
}
```
2. A canary for a known tool bug: keep a harness marked `#[kani::should_panic]` that exercises the buggy construct; when a Kani upgrade fixes the bug it starts failing and tells you to drop the workaround.
3. A harness list check: enumerate harnesses (`grep` for `#[kani::proof]`), then fail on duplicate names and on a name in the slow list that no harness has.
4. Time caps: `cargo kani -j "$(nproc)" -Z unstable-options --harness-timeout 900s`, and wrap the run in `timeout 1800`.

## Run
`cargo kani --output-format terse | tee kani.log` then
`grep -E '\*\* [0-9]+ of [0-9]+ cover properties satisfied' kani.log | awk '$2 != $4 {bad=1} END {exit bad}'`

Passing looks like: for the vacuous harness above, Kani itself prints `** 0 of 1 cover properties satisfied (1 unreachable)` yet `VERIFICATION:- SUCCESSFUL` and exits 0 (observed, 0.68.0). The awk line then exits 1; that is how the check catches it. Also require the line `Complete - N successfully verified harnesses, 0 failures, N total` with N equal to the number of harnesses you listed. A timed-out harness is reported, not silently passed; a missing line means the run was cut off.

## As a contract check
```json
{"id": "prove-kani-honest", "claim": "All Kani harnesses verify, the expected number ran, and every cover! is satisfiable", "kind": "general", "rung": 1, "cmd": "bash scripts/kani-check.sh", "expect": {"exit": 0, "stdout_contains": "successfully verified harnesses"}, "tier": "deep", "timeout_s": 3600}
```
`scripts/kani-check.sh` runs steps 3 and 4 and the awk test above.

## What a pass does not prove
- `cover!` shows each marked case is reachable, not that your marks cover all the cases that matter. Add one for each branch a reviewer would ask about.
- A harness proved on a smaller representation (e.g. `i64`) says nothing about the real type; see `proof-bridging`.
- The canary only watches the one bug you thought of. `--harness-timeout` needs `-Z unstable-options` and may change; check `cargo kani --help` after upgrades.
