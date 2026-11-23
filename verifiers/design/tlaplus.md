---
id: tlaplus
title: TLA+ model checking of a protocol or state machine with TLC and Apalache
answers: Can my protocol or state machine design reach a bad state in some interleaving of steps?
rung: 1
section: design
languages: any
kinds: state-machine, concurrency, migration
cost: high
detect: test -f tla2tools.jar && java -version
ran_here: yes
verified: ran
---

## Use when
- The design has several actors or steps that can interleave (locks, queues, retries, leader election, migrations) and the bugs live in the orderings.
- You must show "X never happens" (safety) or "Y eventually happens" (liveness) for the design, before or alongside the code.
- A short list of states and steps is enough to describe the behaviour. You can describe it in about 30 lines.

## Do not use when
- The risk is in arithmetic or data-structure code. Use `kani` or `lean4-proofs`.
- The design is structural (who may read what). Use `alloy`.
- The model would be as big as the code. Use `small-scope-enumeration` in plain code.

## Set up
Needs Java 11 or newer. Download `tla2tools.jar` from the releases page of github.com/tlaplus/tlaplus and put it in the project. Apalache (symbolic, needs type annotations) is a separate download; `apalache-mc check --config=Lock.cfg --inv=MutualExclusion Lock.tla` (flags from its docs, not run here).

## Minimal example
`Lock.tla`:
```
---- MODULE Lock ----
CONSTANT Procs
VARIABLES pc, lock
vars == <<pc, lock>>
Init == pc = [p \in Procs |-> "idle"] /\ lock = "none"
Enter(p) == pc[p] = "idle" /\ lock = "none" /\ lock' = p /\ pc' = [pc EXCEPT ![p] = "cs"]
Leave(p) == pc[p] = "cs" /\ lock' = "none" /\ pc' = [pc EXCEPT ![p] = "idle"]
Next == \E p \in Procs : Enter(p) \/ Leave(p)
Spec == Init /\ [][Next]_vars
MutualExclusion == \A p, q \in Procs : p /= q => ~(pc[p] = "cs" /\ pc[q] = "cs")
====
```
`Lock.cfg`:
```
CONSTANT Procs = {p1, p2}
SPECIFICATION Spec
INVARIANT MutualExclusion
```

## Run
`java -cp tla2tools.jar tlc2.TLC -config Lock.cfg Lock.tla`

Passing looks like: exit 0 and the line `Model checking completed. No error has been found.` Failure: exit 12 and `Invariant MutualExclusion is violated.` followed by the trace of states. (Checked: removing the `lock = "none"` guard from `Enter` produced exactly that.)

## As a contract check
```json
{"id": "design-lock-model", "claim": "No interleaving of Enter and Leave puts two processes in the critical section", "kind": "state-machine", "rung": 1, "cmd": "java -cp tla2tools.jar tlc2.TLC -config Lock.cfg Lock.tla", "expect": {"exit": 0, "stdout_contains": "No error has been found"}, "tier": "deep", "timeout_s": 900}
```

## What a pass does not prove
- It proves the model, not the code. Pair it with `model-coverage` and tests that replay model traces against the code.
- It covers only the constants in the `.cfg` (here two processes). A bug needing three is missed; run a bigger `.cfg` in CI.
- An invariant that is too weak passes. Check that the check can fail: break a guard and confirm TLC reports a violation.
- Without a `PROPERTY` line TLC checks no liveness. It also reports deadlock by default; the config must not disable that unless deadlock is intended.
