---
id: model-test-from-spec
title: Model test transcribed from a formal spec (TLA+ or Lean)
answers: Does the implementation behave like the formally specified design, step by step, including what it must refuse?
rung: 2
section: many-inputs
languages: any
kinds: state-machine, money
cost: high
detect: python3 -c "import hypothesis"
ran_here: yes
verified: ran
---

## Use when

- A TLA+, Lean or similar model of the design exists (or is being written) and its properties are proved or model-checked.
- You need the proof to reach the code: the proved design is only worth something if the implementation does what it says.
- Refusal rules matter (what must be rejected, and why), not just happy paths.

## Do not use when

- There is no formal model. Write a plain `stateful-model-test` instead.
- The model can be run directly as a program; then use `differential-executable-spec`, which needs no transcription.

## Set up

Write the model as a small pure function in the implementation's language, one
branch per spec action, from the spec text and not from the implementation.
Name each branch after the spec rule it transcribes. Then use the tooling from
`stateful-model-test` to drive both with random command sequences.

## Minimal example (Python; the spec fragment is a TLA+ `Withdraw` action)

    from hypothesis import strategies as st
    from hypothesis.stateful import RuleBasedStateMachine, rule

    # Spec: Withdraw(n) == n > 0 /\ n <= balance /\ balance' = balance - n
    def spec_withdraw(balance, n):                 # returns (new_balance, refusal)
        if n <= 0: return balance, "bad_amount"
        if n > balance: return balance, "insufficient"
        return balance - n, None

    class Account:                                 # implementation under test
        def __init__(self): self.balance = 100
        def withdraw(self, n):
            if n <= 0: return "bad_amount"
            if n > self.balance: return "insufficient"
            self.balance -= n

    class AgainstSpec(RuleBasedStateMachine):
        def __init__(self):
            super().__init__(); self.impl, self.balance = Account(), 100

        @rule(n=st.integers(-5, 150))
        def withdraw(self, n):
            self.balance, want = spec_withdraw(self.balance, n)
            assert self.impl.withdraw(n) == want   # same decision, same reason
            assert self.impl.balance == self.balance

    TestAgainstSpec = AgainstSpec.TestCase

## Run

    python3 -m pytest -q test_against_spec.py

Passing looks like: `1 passed`, exit 0. Failure names the command that diverged, with
the shrunk sequence. Keep the spec's rule ids in comments so a mismatch points at a rule.

## As a contract check

    {"id": "model-vs-spec", "claim": "the implementation accepts and refuses commands as the TLA+ Withdraw action does", "kind": "state-machine", "rung": 2, "cmd": "python3 -m pytest -q test_against_spec.py", "expect": {"exit": 0, "stdout_contains": "passed"}, "tier": "deep", "timeout_s": 300}

## What a pass does not prove

- The transcription is by hand. If it drifts from the spec, you test your reading of the spec; have it reviewed against the spec text.
- It samples sequences. The proof covers all of them; this only shows no counterexample was found.
- Commands the generator cannot express are not compared. List them. (One reference project's Lean differential test lists the model commands its input format cannot reach and leaves those to review.)
- Make the test fail on purpose: change one comparison in the implementation, or let the model allow something the spec forbids.
