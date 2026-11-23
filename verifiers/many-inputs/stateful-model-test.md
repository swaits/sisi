---
id: stateful-model-test
title: Stateful model testing against a simple in-memory model
answers: After any sequence of operations, does the real system agree with a trivially simple model of what it should do?
rung: 2
section: many-inputs
languages: rust, python, typescript, go
kinds: state-machine, general, money
cost: medium
detect: python3 -c "import hypothesis"
ran_here: yes
verified: ran
---

## Use when

- The system has state and commands (a store, ledger, cache, queue, editor buffer) and bugs appear only after particular sequences.
- You can write a model in a few dozen lines using lists and dictionaries, with no performance tricks.
- You need to show that refused commands change nothing and that accepted ones do what the model says.

## Do not use when

- The model would be as complex as the system. Then the two share bugs; use `model-test-from-spec` or `differential-reference` instead.
- The behaviour is stateless: use `proptest`, `hypothesis` or `fast-check` directly.
- The commands race each other. See the `concurrency` section.

## Set up

Python: `pip install hypothesis`. Rust: `cargo add --dev proptest proptest-state-machine`.
TypeScript: `npm i -D fast-check` (`fc.commands`, `fc.modelRun`). Go: `rapid`'s `T.Repeat`.

## Minimal example (Python, Hypothesis `RuleBasedStateMachine`)

    from hypothesis.stateful import RuleBasedStateMachine, rule, invariant
    from hypothesis import strategies as st

    class Stack:                      # the system under test
        def __init__(self): self.items = []
        def push(self, x): self.items.append(x)
        def pop(self): return self.items.pop()

    class StackMachine(RuleBasedStateMachine):
        def __init__(self):
            super().__init__()
            self.sut, self.model = Stack(), []

        @rule(x=st.integers())
        def push(self, x):
            self.sut.push(x); self.model.append(x)

        @rule()
        def pop(self):
            if self.model:                         # only when the model allows it
                assert self.sut.pop() == self.model.pop()

        @invariant()
        def same_contents(self):
            assert self.sut.items == self.model

    TestStack = StackMachine.TestCase

## Run

    python3 -m pytest -q test_stack.py

Passing looks like: `1 passed`, exit 0.
Failure prints the shortest failing sequence as `state.push(x=0)`, `state.push(x=1)`,
`state.pop()`, exit 1. Rust prints `minimal failing input` with the transition list;
fast-check prints `Counterexample: [push(0),push(1),pop()]`.

## As a contract check

    {"id": "model-stack", "claim": "the stack agrees with a list model after any command sequence", "kind": "state-machine", "rung": 2, "cmd": "python3 -m pytest -q test_stack.py", "expect": {"exit": 0, "stdout_contains": "passed"}, "tier": "deep", "timeout_s": 300}

## What a pass does not prove

- Sequences are short and random; a bug needing a rare long sequence can hide. Weight the generator toward commands that interact (post then reverse, close then add).
- A model that never reaches interesting states passes vacuously. Count how often each accepted command and each refusal occurs (one reference project's ledger test prints these under `MODEL_STATS=1`; its first version never posted an entry and agreed with the model for the wrong reason).
- Check the check: make the model wrong on purpose (for example allow a second reversal) and see the test fail quickly.
- It compares only what you read back. Compare every observable: results, refusals, and a full read of the state.
