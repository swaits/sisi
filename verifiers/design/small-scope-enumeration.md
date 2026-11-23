---
id: small-scope-enumeration
title: Exhaustive enumeration of all states of a small design in plain code
answers: Can I check every reachable state of this small design without learning a spec tool?
rung: 1
section: design
languages: any
kinds: state-machine, concurrency
cost: low
detect:
ran_here: yes
verified: ran
---

## Use when
- The design has a handful of actors and a few values each, so all reachable states fit in memory (thousands to a few million).
- You want a fast check of an invariant in the language the team already uses, run as a normal test.
- TLA+, Quint or Alloy would be more set-up than the design deserves.

## Do not use when
- The state space grows past what a set can hold; use `tlaplus` (it handles it and gives traces).
- You need liveness (something eventually happens). A plain loop can only check safety easily.

## Set up
Nothing. Write the state as an immutable value (tuple, frozen dataclass), a `steps(state)` function yielding every next state, and an `invariant(state)` function. Explore with a queue and a `seen` set.

## Minimal example
`explore.py`, a two-worker lock:
```python
from collections import deque
W = (0, 1)
INIT = (("idle", "idle"), None)          # (pc per worker, lock holder)

def steps(state):
    pc, holder = state
    for w in W:
        if pc[w] == "idle" and holder is None:
            yield f"enter{w}", (pc[:w] + ("cs",) + pc[w+1:], w)
        if pc[w] == "cs":
            yield f"leave{w}", (pc[:w] + ("idle",) + pc[w+1:], None)

def invariant(state):
    pc, holder = state
    return sum(p == "cs" for p in pc) <= 1 and (holder is None) == all(p == "idle" for p in pc)

seen, todo = {INIT}, deque([INIT])
while todo:
    s = todo.popleft()
    assert invariant(s), f"invariant broken in {s}"
    for _, t in steps(s):
        if t not in seen:
            seen.add(t); todo.append(t)
assert len(seen) == 3, len(seen)         # pin the count: a model change must be noticed
print(f"explored {len(seen)} states, invariant holds")
```
Do not name the file `enum.py` or any standard-library module name; it shadows the library and breaks imports.

## Run
`python3 explore.py`

Passing looks like: exit 0 and `explored 3 states, invariant holds`. A broken design raises an `AssertionError` naming the bad state. Pinned count: if it changes unexpectedly, the model changed.

## As a contract check
```json
{"id": "design-lock-enumeration", "claim": "Every reachable state of the two-worker lock model satisfies mutual exclusion", "kind": "state-machine", "rung": 1, "cmd": "python3 explore.py", "expect": {"exit": 0, "stdout_contains": "invariant holds"}, "tier": "deep", "timeout_s": 120}
```

## What a pass does not prove
- It checks a model written by you, not the code. Link them with `model-coverage` and by replaying paths through the real code.
- Only the sizes enumerated. Try the next size up once; if it blows up, you have learned the limit.
- Safety only. Check that the check can fail: weaken a guard and confirm the assertion fires.
