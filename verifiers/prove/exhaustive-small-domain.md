---
id: exhaustive-small-domain
title: Brute-forcing every input when the domain is small enough
answers: Does this function give the right answer for every possible input, because I tried them all?
rung: 1
section: prove
languages: any
kinds: general, money, parsing
cost: low
detect:
ran_here: yes
verified: ran
---

## Use when
- The input domain is small: every `u8`, every `u16`, every pair of `u8` (65,536), every string up to length 3 over a small alphabet.
- You have a reference you trust (a wider type, a formula, a slow obvious version) to compare against.
- A proof tool would be heavier than a loop that finishes in seconds.

## Do not use when
- The domain is `u32` pairs or larger (about 1.8e19 cases). Use `kani`, `z3-smt` or a property test (rung 2).
- You would need to sample. Sampling is a property test, not this.

## Set up
Nothing. Count the cases first: `domain_size = product of each input's range`. Keep it under roughly 1e9 for fast code and write the number in the test.

## Minimal example
```rust
#[test]
fn every_u8_is_accepted_or_refused_correctly() {
    for v in 0..=u8::MAX {
        assert_eq!(Percent::new(v).is_some(), v <= 100);
    }
}

#[test]
fn every_u16_checked_add_matches_the_wide_sum() {
    let mut n = 0u64;
    for a in 0..=u16::MAX {
        for b in 0..=u16::MAX {
            let w = a as u32 + b as u32;
            assert_eq!(a.checked_add(b).map(u32::from), (w <= 65535).then_some(w));
            n += 1;
        }
    }
    assert_eq!(n, 65_536 * 65_536);          // proves the loop ran over the whole domain
}
```
In Python use `itertools.product(range(256), repeat=2)` and assert the count.

## Run
`cargo test --release every_`

Passing looks like: exit 0 and `test result: ok. 2 passed`. The full pair loop takes a few seconds in release mode. Failure: the first failing input is in the panic message.

## As a contract check
```json
{"id": "many-inputs-u16-add", "claim": "checked_add on u16 matches the exact sum for every pair of u16 values", "kind": "general", "rung": 1, "cmd": "cargo test --release every_", "expect": {"exit": 0, "stdout_contains": "test result: ok"}, "tier": "deep", "timeout_s": 600}
```

## What a pass does not prove
- It proves the claim only on that domain. A function on `u64` tested over `u16` is a sample of it, so call it rung 2 then.
- The reference answer can itself be wrong; derive it independently.
- Assert the loop count (as above) so that an edited range or an early `continue` cannot shrink the domain silently.
- If the domain is too large to finish, do not cut it down and still call it exhaustive.
