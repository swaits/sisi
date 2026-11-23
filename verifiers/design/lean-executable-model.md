---
id: lean-executable-model
title: An executable Lean 4 model as the specification and oracle
answers: Does my implementation give the same answers as a small, obviously correct model of what it should do?
rung: 1
section: design
languages: any
kinds: general, money, state-machine
cost: medium
detect: lean --version
ran_here: yes
verified: ran
---

## Use when
- You can write the rules as plain total functions (no I/O, no clever speed tricks) in a few dozen lines.
- You want the same model to be (a) executed as an oracle against the real code and (b) used later for proofs, with `lean4-proofs`.
- The implementation is optimised or in another language, so it needs an independent reference.

## Do not use when
- The behaviour is mostly I/O, timing or concurrency. Use `tlaplus`.
- Nobody will read Lean; a Python reference model compared by `proof-bridging` or a property test is cheaper.

## Set up
Install Lean 4 (elan or a release). Keep the model in its own file or a `lake` library (see `lean4-proofs`). Write it with `def`, structures and `Nat`/`Int`; avoid `partial` and `unsafe`, which cannot be reasoned about.

## Minimal example
`Model.lean` reads `lo hi x` lines from stdin and prints the model's answer:
```
def clamp (lo hi x : Nat) : Nat := if x < lo then lo else if hi < x then hi else x

def main : IO Unit := do
  let stdin ← IO.getStdin
  let mut line ← stdin.getLine
  while line != "" do
    match (line.trimAscii.toString.splitOn " ").map String.toNat! with
    | [lo, hi, x] => IO.println (clamp lo hi x)
    | _ => IO.eprintln s!"bad line: {line}"
    line ← stdin.getLine
```
`check.py` feeds every case in a small grid to `lean --run Model.lean` and to the implementation, and asserts the outputs are equal and the counts match (168 cases here).

## Run
`python3 check.py`

Passing looks like: exit 0 and the line `168 cases agree with the Lean model`. A disagreement raises an `AssertionError` listing the first differing cases and exits 1. Use `lake exe` and a compiled binary when the case count is large: `lean --run` re-elaborates the file each time.

## As a contract check
```json
{"id": "design-clamp-oracle", "claim": "clamp agrees with the Lean model on every case in the grid", "kind": "general", "rung": 1, "cmd": "python3 check.py", "expect": {"exit": 0, "stdout_contains": "cases agree"}, "tier": "deep", "timeout_s": 300}
```

## What a pass does not prove
- The comparison covers only the inputs you feed it. Over a finite grid this is a differential test (rung 2); it is rung 1 only for the model's own theorems proved in Lean.
- The model can itself be wrong. State a few theorems about it (`lean4-proofs`) and review it against the written requirement.
- Output formatting and parsing in the script are untested glue; keep them dull.
