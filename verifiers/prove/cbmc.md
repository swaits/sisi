---
id: cbmc
title: CBMC bounded model checking for C
answers: Can this C code overflow, read out of bounds or break an assert for any input within a loop bound?
rung: 1
section: prove
languages: c
kinds: general, parsing
cost: medium
detect: cbmc --version
ran_here: yes
verified: ran
---

## Use when
- C code with buffers, indexes and integer arithmetic needs a check over all inputs up to a loop bound.
- You want memory-safety and overflow checks without writing a contract language.

## Do not use when
- You need unbounded proofs. Use `frama-c-wp`.
- The code is Rust. Use `kani`, which is built on CBMC.

## Set up
Install `cbmc` from your package manager or releases (github.com/diffblue/cbmc). Tried with 6.11.0, the binary that Kani bundles (`~/.kani/kani-*/bin/cbmc`). A C compiler is not needed for checking.

## Minimal example
`a.c`:
```c
#include <assert.h>
#include <stdint.h>

int clamp(int lo, int hi, int x) { return x < lo ? lo : (x > hi ? hi : x); }

uint32_t sum(const uint8_t *a, unsigned n) {
  uint32_t s = 0;
  for (unsigned i = 0; i < n; i++) s += a[i];
  return s;
}

int main(void) {
  int lo, hi, x;                 /* uninitialised = any value */
  __CPROVER_assume(lo <= hi);
  int r = clamp(lo, hi, x);
  assert(lo <= r && r <= hi);

  uint8_t buf[4];
  unsigned n;
  __CPROVER_assume(n <= 4);
  assert(sum(buf, n) <= 4 * 255);
  return 0;
}
```

## Run
`cbmc a.c --bounds-check --pointer-check --signed-overflow-check --unwind 5 --unwinding-assertions`

Passing looks like: `VERIFICATION SUCCESSFUL`, exit 0, and `** 0 of N failed`. Failure: `VERIFICATION FAILED` and exit 10 (seen after changing the assert to `lo < r`). `--unwinding-assertions` makes a loop that needs more iterations than `--unwind` fail instead of passing silently.

## As a contract check
```json
{"id": "prove-clamp-cbmc", "claim": "clamp stays in [lo, hi] and sum has no memory errors for n <= 4", "kind": "general", "rung": 1, "cmd": "cbmc a.c --bounds-check --pointer-check --signed-overflow-check --unwind 5 --unwinding-assertions", "expect": {"exit": 0, "stdout_contains": "VERIFICATION SUCCESSFUL"}, "tier": "deep", "timeout_s": 900}
```

## What a pass does not prove
- Only paths within the unwind bound and the `assume`s. Omit `--unwinding-assertions` and the bound is not even checked.
- An unsatisfiable `__CPROVER_assume` makes everything pass; add a reachability assertion such as `__CPROVER_assert(0, "reached")` expecting failure, or use `--cover location`, to see the point is reached.
- Library calls without a model are treated as returning any value, which may cause false alarms but not false passes.
