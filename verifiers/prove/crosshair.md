---
id: crosshair
title: CrossHair symbolic checking of Python contracts
answers: Can I find any inputs that break this Python function's contract or type annotations?
rung: 2
section: prove
languages: python
kinds: general, parsing
cost: low
detect: crosshair --version
ran_here: yes
verified: ran
---

## Use when
- Pure Python functions with a docstring contract (`pre:` / `post:`) or PEP 316 / icontract / deal contracts.
- You want a solver to hunt for counterexamples before writing property tests.
- You want it to replay found inputs as ordinary tests.

## Do not use when
- The function does I/O, uses C extensions heavily or hashing-dependent logic: the solver gives up.
- You need a proof. Silence from CrossHair means "none found in the time given", so this is rung 2 here. Use `dafny`, `z3-smt` or `lean4-proofs` for rung 1.

## Set up
`pip install crosshair-tool` (5.4.1 observed; use a virtualenv). Contracts live in docstrings.

## Minimal example
`cc.py`:
```python
def clamp(lo: int, hi: int, x: int) -> int:
    """
    pre: lo <= hi
    post: lo <= __return__ <= hi
    """
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x
```
Add a function with a false postcondition to see failure, for example `post: __return__ >= 0` on `return x - 1 if x > 0 else x`.

## Run
`crosshair check cc.py --per_condition_timeout=30`

Passing looks like: no output and exit 0. Failure: a line like `cc.py:14: error: false when calling bad(-1) (which returns -1)` and exit 1 (observed). `--per_condition_timeout` bounds the search per function.

## As a contract check
```json
{"id": "prove-clamp-crosshair", "claim": "clamp satisfies its postcondition for all inputs CrossHair can find in 30 seconds", "kind": "general", "rung": 2, "cmd": "crosshair check cc.py --per_condition_timeout=30", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 600}
```

## What a pass does not prove
- A time-limited search that found nothing; it does not say it covered all paths. Raise the timeout once and see whether a failure appears.
- It checks only the contract you wrote. A weak or missing `post:` passes everything.
- Add a failing function as a canary to confirm the run really analyses your file.
