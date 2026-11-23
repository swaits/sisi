---
id: differential-executable-spec
title: Differential testing against an executable formal model
answers: Does the implementation agree, on random cases, with the formal model that was proved, run as a program?
rung: 2
section: many-inputs
languages: any
kinds: state-machine, money, parsing
cost: high
detect:
ran_here: yes
verified: ran
---

## Use when

- The design has a formal model that can be run: a Lean checker binary, a TLA+ trace checker, an Alloy or Dafny program.
- You want the implementation compared to the model itself, not to a hand transcription of it.
- A mismatch must name which side is wrong, so each case carries both answers.

## Do not use when

- The model cannot be executed. Use `model-test-from-spec` with a hand transcription.
- A checker run is slow per case: batch many cases into one call, or the test will be too slow to run in CI.

## Set up

Build the checker once and pin its revision. Write the glue: run each random
case through the implementation, write the case and the implementation's answer
as a file in the checker's input format, run the checker once for the whole
batch, and fail if it reports any mismatch. Fail loudly if the checker is missing
(never skip silently): one reference project makes the test fail when `lake` is absent.

## Minimal example (Python; `checker.py` stands in for the formal model's binary)

    # test_vs_checker.py
    import json, subprocess, sys
    from hypothesis import given, settings, strategies as st

    def impl_total(prices):                       # implementation under test
        return sum(prices)

    CASES = st.lists(st.integers(0, 10**6), max_size=20)

    @settings(max_examples=50, deadline=None)
    @given(st.lists(CASES, min_size=1, max_size=20))
    def test_against_checker(batch):
        cases = [{"input": c, "got": impl_total(c)} for c in batch]
        out = subprocess.run([sys.executable, "checker.py"], input=json.dumps(cases),
                             capture_output=True, text=True, check=True).stdout
        mismatches = json.loads(out)
        assert mismatches == [], mismatches

    # checker.py (the "executable spec": here a trivial model)
    import json, sys
    cases = json.load(sys.stdin)
    print(json.dumps([c for c in cases if sum(c["input"]) != c["got"]]))

## Run

    python3 -m pytest -q test_vs_checker.py

Passing looks like: `1 passed`, exit 0.
Failure shows the batch and the mismatch list from the checker, exit 1.

## As a contract check

    {"id": "diff-formal-model", "claim": "the implementation agrees with the formal model's checker on generated cases", "kind": "state-machine", "rung": 2, "cmd": "python3 -m pytest -q test_vs_checker.py", "expect": {"exit": 0, "stdout_contains": "passed"}, "tier": "deep", "timeout_s": 900}

## What a pass does not prove

- Only the cases generated, and only the commands the checker's input format can express. List what it cannot say.
- The checker may skip outcomes it does not know (one reference project's checker ignores refusal words it does not list); count skipped cases and fail if too many.
- The model may not match the intended behaviour. This shows code and model agree, not that either is right.
- Check the check: change the implementation by one rule and see the checker report a mismatch.
