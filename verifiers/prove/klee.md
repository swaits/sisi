---
id: klee
title: KLEE symbolic execution of C programs
answers: Which inputs make this C program crash, overflow or break an assert, found by exploring its paths?
rung: 1
section: prove
languages: c, c++
kinds: general, parsing
cost: high
detect: klee --version
ran_here: no
verified: docs
---

## Use when
- C programs or functions with many branches where you want generated inputs that reach each path and trigger errors.
- You want concrete test cases for each path as a by-product.

## Do not use when
- You want a simpler tool: `cbmc` is easier to run and gives a proof within a bound.
- The code does a lot of I/O, threads, floating point or deep loops over symbolic sizes.

## Set up
Easiest is the Docker image (from the KLEE Docker page; 3.0 is the current tag there):

    docker pull klee/klee:3.0
    docker run --rm -ti --ulimit='stack=-1:-1' klee/klee:3.0     # then `klee --version` inside

The `--ulimit` avoids stack overflows inside KLEE. Building from source needs LLVM (the site recommends LLVM 18), clang and an SMT solver; see klee-se.org. Programs include `klee/klee.h`; compile with `-I` pointing at KLEE's `include` directory. Not installed here, so the example was not run.

## Minimal example
`a.c`:
```c
#include <klee/klee.h>
int clamp(int lo, int hi, int x) { return x < lo ? lo : (x > hi ? hi : x); }
int main(void) {
  int lo, hi, x;
  klee_make_symbolic(&lo, sizeof lo, "lo");
  klee_make_symbolic(&hi, sizeof hi, "hi");
  klee_make_symbolic(&x, sizeof x, "x");
  klee_assume(lo <= hi);
  int r = clamp(lo, hi, x);
  klee_assert(lo <= r && r <= hi);
  return 0;
}
```

## Run
```
clang -I /path/to/klee/include -emit-llvm -c -g -O0 -Xclang -disable-O0-optnone a.c -o a.bc
klee a.bc
```
The tutorial says `-O0 -Xclang -disable-O0-optnone` is preferred over plain `-O0` on LLVM newer than 5.0. Output goes to `klee-out-N/` (lowest unused N) with a `klee-last` symlink to the newest.

Passing looks like (from the tutorial):

    KLEE: done: total instructions = 33
    KLEE: done: completed paths = 3
    KLEE: done: partially completed paths = 0
    KLEE: done: generated tests = 3

with no `KLEE: ERROR` lines and no `test*.err` files in `klee-last/`. Failure: `KLEE: ERROR: ... ASSERTION FAIL` and a file `test000001.assert.err` next to the `.ktest` that reproduces it (the file docs give the pattern `test<N>.<error-type>.err`; `ktest-tool` prints a `.ktest`). The KLEE docs fetched do not state the exit status; KLEE is generally reported to exit 0 even when it found errors, so test for the `.err` files rather than the exit code, and confirm that on your version.

## As a contract check
```json
{"id": "prove-clamp-klee", "claim": "KLEE finds no assertion failure or memory error in clamp", "kind": "general", "rung": 1, "cmd": "bash -c 'klee a.bc && ! ls klee-last/*.err 2>/dev/null'", "expect": {"exit": 0}, "timeout_s": 1800, "tier": "deep"}
```

## What a pass does not prove
- Only completes if exploration ends before limits (`--max-time`, `--max-memory`); if it stops early the pass is partial. Look for "partially completed paths = 0".
- Symbolic sizes and the modelled environment (`--posix-runtime`, `--libc=uclibc`) bound what is covered.
- Commands and output come from the KLEE tutorial and docs, not from a run here.
