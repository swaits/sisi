---
id: cargo-mutants
title: Mutation testing for Rust with cargo-mutants
answers: Would my tests notice if this Rust code were wrong?
rung: 2
section: test-quality
languages: rust
kinds: general, money, parsing, state-machine
cost: medium
detect: cargo mutants --version
ran_here: yes
verified: ran
---

## Use when
- You wrote tests for new or changed logic and want evidence they can fail, not just that they pass.
- The code is money, parsing, validation or a state machine where a flipped comparison is costly.
- Coverage is high but you doubt the assertions. Mutation testing is a check on your other checks: it adds confidence in the tests, which is why it sits at rung 2.

## Do not use when
- You only touched a few lines and a full run is too slow; use `mutation-on-diff`.
- The tests are slow end-to-end tests; each mutant reruns them. Narrow with `--test-package`.
- The code has no tests yet. Everything survives.

## Set up
    cargo install cargo-mutants        # or: cargo binstall cargo-mutants
    cargo mutants --version

Optional `.cargo/mutants.toml` holds `exclude_globs`, `exclude_re`, `timeout_multiplier`. To mark a function as not worth mutating, add the `mutants` crate as a normal dependency and use `#[mutants::skip]` (source: mutants.rs docs).

## Minimal example
`src/lib.rs`, with a boundary the tests miss:

    pub fn price(qty: u32, unit: u32) -> u32 {
        let total = qty * unit;
        if qty >= 10 { total - total / 10 } else { total }
    }
    #[cfg(test)] mod tests { use super::*;
        #[test] fn small() { assert_eq!(price(2, 100), 200); }
        #[test] fn big() { assert_eq!(price(20, 100), 1800); } }

## Run
    cargo mutants -p mycrate --timeout-multiplier 3 --minimum-test-timeout 60 -j 2

Passing looks like: `N mutants tested ...: M caught` with no `MISSED` lines, exit 0. Failure shows `MISSED src/lib.rs:4:12: replace >= with > in price` (here: the `qty >= 10` boundary, caught only after adding `assert_eq!(price(10, 100), 900)`), exit 2. Missed mutants are in `mutants.out/missed.txt`, timeouts in `timeout.txt`, unviable (does not compile) in `unviable.txt`.

Reading survivors: for each, decide kill or equivalent. Kill it with a test that fails under the mutant. A mutant is equivalent when the changed code cannot alter observable behaviour; record the reason and exclude it with `#[mutants::skip]` or `-E <regex>`. Never delete a test or loosen an assertion to make it pass.

Long runs: `--shard k/n` splits work; `--iterate` reuses `mutants.out` and skips mutants already caught or unviable. Keep `mutants.out` between interrupted runs; the per-mutant build copy is large, so point `TMPDIR` at a disk with space. Use `--list` to preview the mutants without running.

## As a contract check
    {"id": "mutants-core", "claim": "Every viable mutant of the pricing module is caught by tests", "kind": "general", "rung": 2, "cmd": "cargo mutants -p mycrate --file src/pricing.rs --timeout-multiplier 3", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 3600}

## What a pass does not prove
- Caught mutants show the tests react to those small edits only. They do not show the specification is right.
- Equivalent mutants and `skip`ped code are not checked. List each exclusion and why.
- A timeout counts as caught by default but may mean a hang from a weak test; read `timeout.txt`.
- If the baseline run (unmutated tests) fails, nothing is tested; the exit is non-zero. Do not read it as survivors.
