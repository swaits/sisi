---
id: pluscal
title: PlusCal for algorithm-shaped designs, checked with TLC
answers: Does this step-by-step algorithm with several processes keep its invariant under every interleaving?
rung: 1
section: design
languages: any
kinds: concurrency, state-machine
cost: high
detect: test -f tla2tools.jar && java -version
ran_here: yes
verified: ran
---

## Use when
- The design reads like code: processes with sequential steps, shared variables, loops, locks. PlusCal writes that directly and a translator produces the TLA+.
- You want to show a race (lost update, double-spend, check-then-act) exists or does not.
- The reader of the spec is a programmer who would find raw TLA+ actions harder to follow.

## Do not use when
- The design is a set of independent events rather than processes. Raw `tlaplus` is clearer.
- You need fine control of fairness or refinement. Drop to TLA+.

## Set up
Same `tla2tools.jar` as `tlaplus` (it contains the translator, `pcal.trans`). Java 11 or newer.

## Minimal example
`Counter.tla`: two workers each read a shared counter then write it plus one. Each label (`Read:`, `Write:`) is one atomic step.
```
---- MODULE Counter ----
EXTENDS Integers
(*--algorithm Counter
variables x = 0;
process w \in 1..2
variable t = 0;
begin
  Read: t := x;
  Write: x := t + 1;
end process;
end algorithm; *)
\* BEGIN TRANSLATION
\* END TRANSLATION
BothDone == (\A self \in 1..2 : pc[self] = "Done") => x = 2
====
```
Translate, then write `Counter.cfg` with `SPECIFICATION Spec` and `INVARIANT BothDone`.

## Run
```
java -cp tla2tools.jar pcal.trans Counter.tla
java -cp tla2tools.jar tlc2.TLC -config Counter.cfg Counter.tla
```
Re-run the translator after every edit of the algorithm; TLC checks the generated text, not the comment.

Passing looks like: exit 0 and `No error has been found`. This example fails on purpose: TLC exits 12 with `Invariant BothDone is violated` and a trace where both workers read 0 (the lost update). Make `Read` and `Write` one label to fix it.

## As a contract check
```json
{"id": "design-counter-pluscal", "claim": "Two concurrent increments always leave the counter at 2", "kind": "concurrency", "rung": 1, "cmd": "java -cp tla2tools.jar pcal.trans Counter.tla && java -cp tla2tools.jar tlc2.TLC -config Counter.cfg Counter.tla", "expect": {"exit": 0, "stdout_contains": "No error has been found"}, "tier": "deep", "timeout_s": 900}
```
Note that `pcal.trans` also rewrites `Counter.cfg` if it does not exist; keep your own `.cfg` committed.

## What a pass does not prove
- Everything under `tlaplus` applies: it checks the model, only the constants in the `.cfg`, and nothing about the code.
- A label is one atomic step. Putting too much in one label hides races; split steps to match what the real code does atomically.
- If the translator is not re-run, TLC checks stale text and the pass means nothing.
