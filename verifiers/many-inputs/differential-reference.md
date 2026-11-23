---
id: differential-reference
title: Differential testing against an independent reference implementation
answers: Does my implementation give the same answer as an independent, trusted one on random inputs?
rung: 2
section: many-inputs
languages: any
kinds: general, parsing, money
cost: medium
detect:
ran_here: yes
verified: ran
---

## Use when

- Another library, tool or program already computes the same thing (a standard library, a database, a reference tool run in a container).
- The result is hard to state as a law but easy to compare.
- You wrote a faster or custom version of something with a trusted slow version.

## Do not use when

- The reference shares code or an algorithm with your implementation; agreement then proves little. Prefer one written independently.
- Both may legitimately differ (rounding rules, ordering of ties). Decide first what counts as equal.
- A prior version of your own code is the reference: use `differential-old-vs-new`.

## Set up

Choose the reference and pin its version. A program in a container is fine:
call it through a function that takes an input and returns a normalised answer.
Generate inputs with `hypothesis`, `proptest` or `fast-check`.

## Minimal example (Python: a custom decimal rounder against `decimal`)

    from decimal import Decimal, ROUND_HALF_EVEN
    from hypothesis import given, strategies as st

    def my_round_cents(units: int, scale: int) -> int:
        """units / 10**scale, rounded half to even, in cents (integers only)."""
        q, r = divmod(units * 100, 10**scale)
        twice = 2 * r
        if twice > 10**scale or (twice == 10**scale and q % 2 == 1):
            q += 1
        return q

    def reference(units: int, scale: int) -> int:
        d = Decimal(units).scaleb(-scale).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        return int(d.scaleb(2))

    @given(st.integers(-10**12, 10**12), st.integers(0, 9))
    def test_matches_reference(units, scale):
        assert my_round_cents(units, scale) == reference(units, scale)

## Run

    python3 -m pytest -q test_diff.py

Passing looks like: `1 passed`, exit 0.
Failure prints the shrunk input and both answers, exit 1.

## As a contract check

    {"id": "diff-rounding", "claim": "my rounding equals Python's decimal on generated amounts", "kind": "money", "rung": 2, "cmd": "python3 -m pytest -q test_diff.py", "expect": {"exit": 0, "stdout_contains": "passed"}, "tier": "deep", "timeout_s": 300}

## What a pass does not prove

- It shows agreement, not correctness: if the reference has the same bug or misreads the spec, both pass.
- Generated inputs that the reference rejects or that both treat identically make the pass thin; check the distribution (include edge scales, negatives, ties).
- Pin the reference version and record it; a drifting reference changes the answer.
- Check the check: introduce an off-by-one in the tie rule and see it fail.
