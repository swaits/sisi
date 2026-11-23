---
id: dafny
title: Dafny verified algorithms that compile to a target language
answers: Does this algorithm meet its specification for all inputs, and can I run the verified code?
rung: 1
section: prove
languages: dafny
kinds: general, state-machine
cost: medium
detect: dafny --version
ran_here: yes
verified: ran
---

## Use when
- You are writing an algorithm or data structure from scratch and can write it in Dafny, then compile to Python, Go, Java, C# or JavaScript.
- You want pre/postconditions and loop invariants checked by an SMT solver for all inputs.
- A spec-first workflow fits: `requires`/`ensures` first, body second.

## Do not use when
- The code already exists in Rust, C or Python and must be verified as is. Use `verus`, `kani`, `frama-c-wp` or `crosshair`.
- The compiled output must meet tight performance or integration needs the target backend cannot.

## Set up
Download the release zip from github.com/dafny-lang/dafny/releases (4.11.0 tried; it includes its own runtime, Z3 included) and unzip. No global install needed: call `./dafny/dafny`.

## Minimal example
`a.dfy`:
```dafny
method Abs(x: int) returns (y: int)
  ensures y >= 0 && (y == x || y == -x)
{
  if x < 0 { y := -x; } else { y := x; }
}

method SumTo(n: nat) returns (s: nat)
  ensures s == n * (n + 1) / 2
{
  s := 0;
  var i := 0;
  while i < n
    invariant i <= n && s == i * (i + 1) / 2
  {
    i := i + 1;
    s := s + i;
  }
}

method Main() { var r := Abs(-3); print r, "\n"; }
```

## Run
`dafny verify a.dfy`, then `dafny run --target:py a.dfy` to compile and run on Python.

Passing looks like: exit 0 and `Dafny program verifier finished with 4 verified, 0 errors`. Failure: an error with the failing line and `finished with 3 verified, 1 error`, exit 4 (observed after changing `s + i` to `s + i + 1`). Use `--verification-time-limit <seconds>` (default 30) to bound each assertion batch; a timeout is reported as an error.

## As a contract check
```json
{"id": "prove-sumto-dafny", "claim": "SumTo and Abs satisfy their postconditions for all inputs", "kind": "general", "rung": 1, "cmd": "dafny verify a.dfy", "expect": {"exit": 0, "stdout_contains": "0 errors"}, "tier": "deep", "timeout_s": 600}
```

## What a pass does not prove
- Only the written `ensures`. A weak postcondition (say `ensures true`) verifies trivially; review the specs.
- `assume` statements, `{:axiom}` and `{:verify false}` skip proof; grep for them. Termination is checked unless `decreases *` is used.
- The compiled program is trusted to match: the compiler and runtime are not verified. Target-language integers and I/O are outside the proof.
