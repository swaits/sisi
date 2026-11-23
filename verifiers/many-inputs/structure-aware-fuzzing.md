---
id: structure-aware-fuzzing
title: Structure-aware fuzzing with `arbitrary` and grammar-based inputs
answers: Can sequences of valid-looking operations, not just random bytes, break the code or its invariants?
rung: 2
section: many-inputs
languages: rust
kinds: state-machine, parsing, money
cost: medium
detect: cargo fuzz --version
ran_here: yes
verified: ran
---

## Use when

- Raw bytes almost never form valid input (JSON, command lists, balanced entries), so a plain fuzzer wastes its time on rejections.
- You want the fuzzer to drive a sequence of operations on a state machine and check invariants after each.
- The fuzz target should check more than "no panic": a model, a round trip, "a refused command changes nothing".

## Do not use when

- The input really is arbitrary bytes (a file format parser): use `cargo-fuzz` with `&[u8]`.
- You want shrinking and readable counterexamples: `proptest` is better at that.

## Set up

    cargo add arbitrary --features derive      # in the fuzz crate (cargo fuzz init already adds it)

Derive `Arbitrary` on the input types. For grammar-style input (valid SQL,
JSON), write a small generator that turns the fuzzer's bytes into a valid
document with `Unstructured`, or use a grammar-based fuzzer such as `Grammarinator`.

## Minimal example (`fuzz/fuzz_targets/fuzz_target_1.rs`)

    #![no_main]
    use libfuzzer_sys::fuzz_target;

    // in the library crate:
    // #[derive(Debug, arbitrary::Arbitrary)]
    // pub enum Op { Deposit(u32), Withdraw(u32) }
    // Account::apply(&mut self, &Op) -> Result<(), &'static str>

    fuzz_target!(|ops: Vec<mycrate::Op>| {
        let mut acct = mycrate::Account::default();
        let mut model: u64 = 0;
        for op in &ops {
            let before = acct.cents;
            if acct.apply(op).is_ok() {
                match op {
                    mycrate::Op::Deposit(n) => model += *n as u64,
                    mycrate::Op::Withdraw(n) => model -= *n as u64,
                }
            } else {
                assert_eq!(acct.cents, before, "refused op changed state");
            }
            assert_eq!(acct.cents as u64, model, "balance diverged from model");
        }
    });

## Run

    RUSTUP_TOOLCHAIN=nightly cargo fuzz run fuzz_target_1 fuzz/corpus/fuzz_target_1 -- -max_total_time=60

Passing looks like: `Done N runs in 60 second(s)`, exit 0.
Failure prints the panic or assertion and the input as the `Debug` of the Rust
value (`[Withdraw(...)]`), then exits 1 with a crash file in `fuzz/artifacts/`.
Print an old crash as Rust values with `cargo fuzz fmt fuzz_target_1 <crash-file>`.

## As a contract check

    {"id": "fuzz-account-ops", "claim": "no fuzzed operation sequence breaks the account model or changes state on refusal", "kind": "state-machine", "rung": 2, "cmd": "cd fuzz-host && RUSTUP_TOOLCHAIN=nightly cargo fuzz run fuzz_target_1 fuzz/corpus/fuzz_target_1 -- -max_total_time=60", "expect": {"exit": 0, "stdout_contains": "Done"}, "tier": "deep", "timeout_s": 600}

## What a pass does not prove

- Only what the run reached in its time budget; a clean run is not a proof.
- A derived `Arbitrary` makes uniform-looking values. If the interesting values (zero, maximum, the same account twice) are rare, bias the generator by hand.
- The invariants are only as good as the asserts. One reference project's operation-sequence target checks that the trial balance balances after any sequence; without that assert the same run would only look for panics.
- Check the check: seed a bug (the example subtracts one extra cent on withdrawal) and see the fuzzer find it within seconds.
