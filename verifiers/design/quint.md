---
id: quint
title: Quint specifications with a simulator and Apalache model checker
answers: Can I describe my state machine in a typed, programmer-style language and have a tool explore its states for violations?
rung: 1
section: design
languages: any
kinds: state-machine, concurrency
cost: medium
detect: quint --version
ran_here: no
verified: docs
---

## Use when
- You want the TLA+ style of design check but with types, modules and a syntax close to TypeScript or Rust.
- You want a fast random simulation first (seconds) and an exhaustive bounded check second.
- The team will keep the spec in the repo and edit it; readability and a type checker matter.

## Do not use when
- You need liveness proofs or the full TLA+ toolbox. Use `tlaplus`.
- The design is relational/structural. Use `alloy`.

## Set up
`npm install -g @informalsystems/quint` (version 0.34.0 tried). `quint verify` downloads Apalache on first use and needs Java 21 or newer; with Java 17 it fails with `UnsupportedClassVersionError`.

## Minimal example
`lock.qnt`:
```
module lock {
  var holder: str
  action init = holder' = "none"
  action enter(p) = all { holder == "none", holder' = p }
  action leave = all { holder != "none", holder' = "none" }
  action step = any { enter("a"), enter("b"), leave }
  val ok = (holder == "none") or (holder == "a") or (holder == "b")
}
```

## Run
```
quint typecheck lock.qnt
quint run lock.qnt --init=init --step=step --invariant=ok --max-samples=200 --max-steps=10
quint verify lock.qnt --init=init --step=step --invariant=ok
```
Passing looks like: `typecheck` and `run` exit 0; `run` prints `[ok] No violation found`. A violated invariant prints `[violation] Found an issue`, the states, and exits 1 (seen with `val ok = holder != "b"`). `verify` should exit 0 with `[ok] No violation found`; not run here because Java 21 was unavailable, so that line is unconfirmed.

## As a contract check
```json
{"id": "design-lock-quint", "claim": "In every run of the lock model, holder is always none, a or b", "kind": "state-machine", "rung": 1, "cmd": "quint verify lock.qnt --init=init --step=step --invariant=ok", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 900}
```
Use `quint run` in the contract only if you accept rung 2, since it samples.

## What a pass does not prove
- `quint run` is random sampling: rung 2. Only `quint verify` explores exhaustively, and only up to `--max-steps` (default 10).
- It checks the spec, not the code. See `model-coverage`.
- An invariant that is always true is a vacuous pass; confirm a deliberately wrong invariant fails.
