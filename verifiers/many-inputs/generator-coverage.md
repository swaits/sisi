---
id: generator-coverage
title: Checking that random tests actually reach interesting cases
answers: Is my property or model test really exercising edge cases and rare commands, or is it passing because it never gets there?
rung: 2
section: many-inputs
languages: any
kinds: general, state-machine
cost: low
detect: python3 -c "import hypothesis"
ran_here: yes
verified: ran
---

## Use when

- You wrote a property, model or fuzz test and it passes on the first try.
- The generator filters, rejects or chooses by weights, so most cases may be boring or discarded.
- A model test might never post, reverse or close anything.

## Do not use when

- The test is a fixed example.

## Set up

Count what happens. In Hypothesis use `event()` and `target()` and read
`--hypothesis-show-statistics`; in proptest print a count per accepted command and per
refusal (one reference project's model test does this under `MODEL_STATS=1`); in fast-check use
`fc.statistics`; in a fuzzer use `cargo fuzz coverage` or the coverage output.

## Minimal example (Python)

    from hypothesis import given, event, strategies as st

    @given(st.integers(-5, 150), st.integers(0, 100))
    def test_withdraw_cases_all_occur(amount, balance):
        if amount <= 0:
            event("bad amount")
        elif amount > balance:
            event("insufficient")
        else:
            event("success")
        # ... the real assertions about withdraw(amount, balance) go here

## Run

    python3 -m pytest -q test_cov.py --hypothesis-show-statistics

Passing looks like: `1 passed` and, in the statistics block, each event
(`bad amount`, `insufficient`, `success`) with a share well above zero. Failure here is
a reading task: any event at 0 percent or under about 1 percent means that branch is
effectively untested, and the generator needs fixing. To make this automatic, assert
on counts with a collected dictionary in a small harness, or fail on health-check
warnings (`HealthCheck.filter_too_much`, `too_slow`) by not suppressing them.

## As a contract check

    {"id": "generators-reach-cases", "claim": "the withdraw property test exercises bad, insufficient and successful cases", "kind": "general", "rung": 2, "cmd": "python3 -m pytest -q test_cov.py --hypothesis-show-statistics", "expect": {"exit": 0, "stdout_contains": "success"}, "tier": "deep", "timeout_s": 300}

## What a pass does not prove

- Events show that a case occurred, not that the assertion beside it is strong.
- A generator that reaches every named case can still miss ones you did not name; add boundary values by hand (`@example`).
- Check the check: narrow the generator (balance always 0) and confirm "success" disappears from the statistics.
