---
id: metamorphic
title: Metamorphic testing when there is no oracle
answers: Even though I cannot say what the right answer is, does changing the input in a known way change the output in the way it must?
rung: 2
section: many-inputs
languages: any
kinds: general, parsing, money
cost: low
detect:
ran_here: yes
verified: ran
---

## Use when

- You cannot compute the expected output independently (search ranking, compilers, numeric code, image or report generation) but you know how the output must relate across two related inputs.
- Typical relations: reordering the input does not change the result; scaling inputs scales outputs; adding an irrelevant item does not change the answer; a query with a stricter filter returns a subset.

## Do not use when

- An oracle or reference exists. Use `differential-reference`.
- The relation is only "decode undoes encode". That is `round-trip`.

## Set up

Pick relations from the domain, write each as a function of (input, transformed
input), and run them on generated inputs with `hypothesis`, `proptest` or
`fast-check`. One relation per test so a failure names it.

## Minimal example (Python; a median function)

    from statistics import median
    from hypothesis import given, strategies as st

    def my_median(xs):                              # under test
        s = sorted(xs)
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

    nums = st.lists(st.integers(-10**6, 10**6), min_size=1, max_size=50)

    @given(nums, st.randoms())
    def test_order_does_not_matter(xs, rnd):
        ys = xs[:]; rnd.shuffle(ys)
        assert my_median(ys) == my_median(xs)

    @given(nums, st.integers(-1000, 1000))
    def test_shift_shifts_median(xs, k):
        assert my_median([x + k for x in xs]) == my_median(xs) + k

    @given(nums, st.integers(1, 1000))
    def test_scale_scales_median(xs, k):
        assert my_median([x * k for x in xs]) == my_median(xs) * k

## Run

    python3 -m pytest -q test_metamorphic.py

Passing looks like: `3 passed`, exit 0. Failure names the relation and shrinks the input.

## As a contract check

    {"id": "meta-median", "claim": "median is order-independent and shifts and scales with its inputs", "kind": "general", "rung": 2, "cmd": "python3 -m pytest -q test_metamorphic.py", "expect": {"exit": 0, "stdout_contains": "3 passed"}, "tier": "deep", "timeout_s": 300}

## What a pass does not prove

- A relation only constrains the output, so a wrong function can satisfy one. Use several relations that together pin the behaviour down.
- It never proves the output is the right value, only that it is consistent.
- Check the check: replace the function with a plausible wrong one (the mean, the first element) and see at least one relation fail.
