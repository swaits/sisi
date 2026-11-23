---
id: frama-c-wp
title: Frama-C WP for C with ACSL contracts
answers: Does this C function meet its contract and avoid undefined behaviour for all inputs?
rung: 1
section: prove
languages: c
kinds: general, parsing
cost: high
detect: frama-c -version
ran_here: no
verified: docs
---

## Use when
- Small, critical C functions (parsers, buffers, arithmetic, drivers) need a proof that holds for all inputs, with no unwinding bounds.
- You can write ACSL contracts (`requires`, `ensures`, `assigns`, loop invariants) in comments.

## Do not use when
- You only need a bounded check with minimal effort. Use `cbmc`.
- The code relies on heavy pointer aliasing, floating point, or concurrency without a plan.

## Set up
Install with opam (the Frama-C site's recipe: `opam init --compiler 4.14.1`, `eval $(opam env)`, `opam install frama-c`). Per the WP manual (written for Frama-C 33.0 "Arsenic", July 2026), the WP plug-in ships with Frama-C, needs the Why3 platform and at least one external prover, and opam installs Alt-Ergo and Why3 automatically; WP finds provers on `$PATH` and in the Why3 configuration. Not installed here, so nothing below was run.

## Minimal example
`abs.c`:
```c
#include <limits.h>
/*@ requires x > INT_MIN;
    assigns \nothing;
    ensures \result >= 0 && (\result == x || \result == -x);
*/
int my_abs(int x) { return x < 0 ? -x : x; }
```

## Run
`frama-c -wp -wp-rte -wp-timeout 20 abs.c`

Passing looks like: a line `[wp] Proved goals: N / N` (the manual shows `[wp] Proved goals: 4 / 4`; a run with a failure shows `Proved goals: 6 / 7` and an `Unknown:` count). `-wp-rte` adds the no-undefined-behaviour obligations (overflow, bounds) and `-wp-timeout` is the per-goal prover timeout in seconds (default 2). The manual does not document an exit status for unproved goals, and Frama-C is commonly seen exiting 0 with unproved goals, so the contract tests the text. Real output may pad the numbers with extra spaces, so the pattern allows them:
`frama-c ... | grep -E 'Proved goals: +([0-9]+) / \1$'` (the backreference is GNU grep).

## As a contract check
```json
{"id": "prove-abs-framac", "claim": "my_abs meets its contract and has no runtime errors when x > INT_MIN", "kind": "general", "rung": 1, "cmd": "bash -c \"frama-c -wp -wp-rte -wp-timeout 20 abs.c | tee /dev/stderr | grep -E 'Proved goals: +([0-9]+) / \\\\1$'\"", "expect": {"exit": 0}, "timeout_s": 900, "tier": "deep"}
```

## What a pass does not prove
- Only the written contract, under a memory model that assumes no aliasing the contract does not allow. `assigns` clauses must be right.
- All goals proved means none were skipped by `-wp-timeout`; a timeout counts as unproved, which the `N / N` test catches.
- Not run here; the output format is from the WP manual's examples. Confirm the exit status and spacing of the `Proved goals` line on your version, and check the check by weakening the `ensures` so a goal fails.
