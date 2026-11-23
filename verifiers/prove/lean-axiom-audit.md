---
id: lean-axiom-audit
title: Making a Lean proof trustworthy: no sorry, only the standard axioms
answers: Does my Lean proof really prove the theorem, or does it rely on sorry or an extra axiom?
rung: 1
section: prove
languages: any
kinds: general
cost: low
detect: lake --version
ran_here: yes
verified: ran
---

## Use when
- A Lean project is the evidence for a claim and a green `lake build` must mean the proof is complete.
- An agent wrote or edited proofs; `sorry`, `axiom` and `native_decide` are easy to slip in.
- You want a CI step that fails on anything but the standard axioms.

## Do not use when
- There is no Lean proof. See `lean4-proofs`.

## Set up
List the theorems that carry the claim in one file, `Audit.lean`, so the list is reviewed in one place:
```lean
import Demo
#print axioms clamp_le
#print axioms add_zero'
```

## Minimal example
```
lake build --wfail
lake env lean Audit.lean | tee audit.txt
! grep -v -E "depends on axioms: \[(propext|Quot.sound|Classical.choice)(, (propext|Quot.sound|Classical.choice))*\]$|does not depend on any axioms" audit.txt
```
The third line fails if any output line is not one of the allowed forms. The three allowed axioms are `propext`, `Classical.choice`, `Quot.sound`. This is the filter a Rust and Lean 4 project uses in its `prove` recipe.

## Run
Put the three lines in a script, `audit-lean.sh`, with `set -euo pipefail`.

Passing looks like: exit 0 and output such as `'clamp_le' depends on axioms: [propext, Classical.choice, Quot.sound]`. Failure shows `depends on axioms: [sorryAx]` for a theorem that uses `sorry` (observed: `lake build` itself exited 0 and only warned; `--wfail` made it exit 1). `native_decide` shows `Lean.ofReduceBool`, and a custom `axiom` appears by name; both fail the filter.

## As a contract check
```json
{"id": "prove-lean-axioms", "claim": "The Lean theorems depend on no sorry and only the three standard axioms", "kind": "general", "rung": 1, "cmd": "bash audit-lean.sh", "expect": {"exit": 0, "stdout_contains": "depends on axioms"}, "tier": "deep", "timeout_s": 1800}
```

## What a pass does not prove
- That the theorem statements say what you meant. Axiom-clean proofs of the wrong statement pass.
- Only theorems listed in `Audit.lean` are audited; a new theorem not listed is not. Compare the list against the project's theorems in review, or generate it.
- A trailing `sorry` in a file `Audit.lean` does not import is not seen; build the whole library.
- If `Audit.lean` prints nothing (a typo in a name raises an error, which is good) make sure the script checks that the output is non-empty.
