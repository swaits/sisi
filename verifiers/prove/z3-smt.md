---
id: z3-smt
title: Encoding a property directly for Z3 (Python or SMT-LIB)
answers: Does a counterexample to this property exist, found by a solver, when no verifier fits my language?
rung: 1
section: prove
languages: any
kinds: general, money, parsing
cost: medium
detect: python3 -c "import z3"
ran_here: yes
verified: ran
---

## Use when
- The property is a bit-level or arithmetic fact (overflow tests, rounding, bit tricks, small state-transition rules) you can restate as formulas.
- No verifier covers your language, or you want a quick independent check of a formula.

## Do not use when
- You can verify the real code (`kani`, `cbmc`, `dafny`). Re-encoding invites mistakes.
- The claim has unbounded loops, heap structures or floating-point subtleties.

## Set up
In a throwaway virtualenv: `python3 -m venv .venv && .venv/bin/pip install z3-solver`. The package also provides the `z3` command-line program for SMT-LIB files.

## Minimal example
`z.py`. Claim: for 32-bit unsigned `a`, `b`, `(a + b) < a` holds exactly when the addition overflowed.
```python
from z3 import BitVec, Solver, ULT, UGE, ZeroExt, sat, unsat

a, b = BitVec("a", 32), BitVec("b", 32)
wrapped_smaller = ULT(a + b, a)
really_overflowed = UGE(ZeroExt(32, a) + ZeroExt(32, b), 2**32)
s = Solver()
s.add(wrapped_smaller != really_overflowed)      # ask for a counterexample
r = s.check()
assert r == unsat, f"counterexample: {s.model()}" if r == sat else f"solver said {r}"
print("proved: overflow test is exact for all 32-bit a, b")
```
The same in SMT-LIB (`a.smt2`): declare `a`, `b` as `(_ BitVec 32)`, assert the negated claim, `(check-sat)`; expect `unsat`.

## Run
`python3 z.py` or `z3 a.smt2`

Passing looks like: `proved: ...` with exit 0; for SMT-LIB the single word `unsat`. Failure: `sat` (a model is a counterexample). Changing `>=` to `>` in `really_overflowed` gave the counterexample `a = 3489660928, b = 805306368` (their sum is exactly 2^32) and exit 1. The result `unknown` (timeout) is not a pass; the script asserts `unsat`.

## As a contract check
```json
{"id": "prove-overflow-test-z3", "claim": "(a + b) < a is equivalent to unsigned 32-bit overflow", "kind": "general", "rung": 1, "cmd": "python3 z.py", "expect": {"exit": 0, "stdout_contains": "proved"}, "tier": "deep", "timeout_s": 300}
```

## What a pass does not prove
- Only the formulas, not your code. A wrong translation proves something else; test the encoding against concrete values with `s.add(a == 3, ...)` expecting `sat`.
- You proved the negation is unsatisfiable. Check the formulas are not trivially unsat: assert that the model without the final constraint is `sat`.
- `z3-solver` versions differ in `unknown` behaviour; set `s.set("timeout", ms)` and treat `unknown` as failure.
