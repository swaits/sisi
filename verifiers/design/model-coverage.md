---
id: model-coverage
title: Model coverage test: every public operation maps to a model step
answers: Does the implementation have any public operation that the formal model does not describe?
rung: 1
section: design
languages: any
kinds: state-machine, general
cost: low
detect:
ran_here: yes
verified: ran
---

## Use when
- You have a TLA+, Quint, P, Alloy or Lean model and the code can drift from it as operations are added.
- You want a failing test the moment someone adds a public method with no model step.
- You want every deliberate gap written down with a reason.

## Do not use when
- There is no model; write one first (`tlaplus`, `quint`, `lean-executable-model`).
- The goal is to show the code behaves like the model. This test only checks the names line up; see `lean-executable-model` or replayed traces for behaviour.

## Set up
Keep a table in the test file: public operation name to model action name, plus an `EXCEPTIONS` table of operations the model deliberately leaves out, each with a reason. Enumerate the real public operations from the code itself (reflection in Python, a macro or `cargo public-api` style listing in Rust, the exports of a module in TypeScript), not from a hand-typed list.

## Minimal example
```python
import inspect

class Lock:
    def acquire(self): ...
    def release(self): ...
    def stats(self): ...
    def _private(self): ...

MODEL_STEPS = {"acquire": "Enter", "release": "Leave"}   # method -> model action
EXCEPTIONS = {"stats": "read-only, no state change"}     # name -> reason
assert len(EXCEPTIONS) == 1                              # pinned: growing it needs a review

public = {n for n, f in inspect.getmembers(Lock, inspect.isfunction) if not n.startswith("_")}
unmapped = public - MODEL_STEPS.keys() - EXCEPTIONS.keys()
stale = (MODEL_STEPS.keys() | EXCEPTIONS.keys()) - public
assert not unmapped, f"public operations with no model step: {sorted(unmapped)}"
assert not stale, f"mapping names a method that no longer exists: {sorted(stale)}"
print("model coverage ok")
```
Also check that each right-hand name exists in the model file (`grep -q "^Enter" Lock.tla`).

## Run
`python3 model_coverage.py` (or the project's test runner)

Passing looks like: exit 0 and `model coverage ok`. Adding `def reset(self)` to `Lock` fails with `public operations with no model step: ['reset']` and exit 1 (observed). Removing a method fails the `stale` check.

## As a contract check
```json
{"id": "design-model-coverage", "claim": "Every public operation of Lock is mapped to a model step or listed as a justified exception", "kind": "state-machine", "rung": 1, "cmd": "python3 model_coverage.py", "expect": {"exit": 0, "stdout_contains": "model coverage ok"}, "timeout_s": 60}
```

## What a pass does not prove
- Names only: a method can be mapped to the wrong action, or do something the action does not allow. Back it with replayed traces or a differential test.
- The pinned exceptions size is a speed bump. A reviewer must read each new exception's reason.
- Operations reachable only through private paths or generated code are missed unless the listing includes them.
