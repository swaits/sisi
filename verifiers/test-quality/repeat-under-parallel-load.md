---
id: repeat-under-parallel-load
title: Repeat a test about 30 times with copies running in parallel
answers: Does this test still pass when copies of it run at the same time and the machine is busy?
rung: 3
section: test-quality
languages: any
kinds: general, concurrency
cost: low
detect: xargs --version
ran_here: yes
verified: ran
---

## Use when
- You wrote a new test module and are about to report it as passing.
- A test passes alone and fails in the full suite, or fails once and passes on rerun.
- The test uses time, a fixed path or port, a shared directory, the current directory, or random data.

## Do not use when
- The failure is deterministic. Fix it; do not repeat it.
- You need to find a race in the code itself. Repetition only samples; use a model checker or a stress tool built for that.

## Set up
- Nothing beyond `xargs` (GNU or BSD) and `seq`, and the standard test runner of the language. The tests must be hermetic: each copy gets its own temporary directory, state and ports.

## Minimal example
Python's standard library, a module `test_mod.py`:

    python3 -m unittest -q test_mod

## Run
Thirty runs, eight at a time. `xargs` exits 123 if any run exits non-zero:

    seq 30 | xargs -P 8 -I{} python3 -m unittest -q test_mod

Passing looks like: exit status 0 and no output from unittest. Failure shows as exit 123 with the failing copy's output above it. Reproduce one failure alone, then under load again. Use `-P` near the number of processors, or higher, to make timing worse; run the whole suite as one of the parallel copies when order matters.

## As a contract check
    {"id": "repeat-parallel", "claim": "The new test module passes 30 runs, 8 at a time", "kind": "general", "rung": 3, "cmd": "seq 30 | xargs -P 8 -I{} python3 -m unittest -q test_mod", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 900}

## What a pass does not prove
- Thirty passes bound a flake rate only roughly: a 1-in-20 flake can still pass thirty runs. Raise the count for anything that matters.
- Copies that already isolate their state cannot show a shared-state bug between them; check that the test really shares something (a path, a port) when you suspect it.
- Check that the module name matched tests (Python 3.12 and later exit 5 when a module has no tests; older versions exit 0, so check with `-v` once).
- A pass says nothing about the code under test being correct, only that the test is stable.
