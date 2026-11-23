---
id: linearizability-checking
title: Linearizability checking of recorded histories (Porcupine, Knossos)
answers: Can the operations my concurrent or distributed store returned be explained by some one-at-a-time order?
rung: 2
section: concurrency
languages: go, any
kinds: concurrency, state-machine
cost: high
detect: go version
ran_here: no
verified: docs
---

## Use when
- You built a concurrent map, queue, register, lock service or replicated store and claim "it behaves as if operations happen one at a time".
- Individual tests pass but you doubt results seen by concurrent clients.
- You can record, per operation, the call time, the return time, the input and the output.

## Do not use when
- The claim is a weaker consistency level; model that instead (Jepsen's Elle checks serializability and snapshot isolation).
- You only need to detect data races; use a race detector.
- Operations cannot be timestamped by a single clock source or logical order.

## Set up
Go: Porcupine, `go get github.com/anishathalye/porcupine`. Clojure: Knossos, used by Jepsen. Not run here: Go is not installed; the API below is from Porcupine's README and pkg.go.dev. Steps: (1) run many concurrent clients against the system with random operations, recording each as an `Operation`; (2) write a sequential model of the object; (3) check the history.

## Minimal example
A register (put/get) in Go:

    type in struct{ put bool; v int }
    model := porcupine.Model{
        Init: func() interface{} { return 0 },
        Step: func(state, input, output interface{}) (bool, interface{}) {
            i := input.(in)
            if i.put { return true, i.v }
            return output.(int) == state.(int), state
        },
    }
    // history []porcupine.Operation{ {ClientId, Input, Call, Output, Return}, ... }
    if !porcupine.CheckOperations(model, history) { t.Fatal("history is not linearizable") }

`CheckOperationsTimeout(model, history, d)` returns `Ok`, `Illegal` or `Unknown` (timeout). Use `porcupine.Visualize` for an HTML picture of a failure.

## Run
    go test -run TestLinearizable -count=1 ./...

Passing looks like: the test passes, exit 0, with a non-trivial history (many overlapping operations). Failure is `history is not linearizable` plus the visualisation file.

## As a contract check
    {"id": "linearizable", "claim": "Recorded concurrent histories are linearizable against the register model", "kind": "concurrency", "rung": 2, "cmd": "go test -run TestLinearizable -count=1 ./...", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 900}

## What a pass does not prove
- It checks the histories you generated. Different timing or faults may produce a bad one; run with fault injection and many seeds. Rung 2.
- A model that is too permissive passes anything. Check the check: edit the system to return a stale read and see the history be rejected.
- Weak workloads (one client, few keys, no overlap) pass trivially; assert that operations actually overlap.
- Checking can time out on long histories; `Unknown` is not a pass. Treat it as failure or shorten and partition by key.
