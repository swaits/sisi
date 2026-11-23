---
id: red-before-green
title: Prove a new test can fail by seeing it fail before the fix
answers: Does this new test actually fail without my change, so its passing means something?
rung: 3
section: test-quality
languages: any
kinds: general, money, parsing, state-machine
cost: low
detect: git --version
ran_here: yes
verified: ran
---

## Use when
- You fixed a bug and wrote a regression test.
- You added a feature and a test for it.
- Any time a test is the evidence for done: a test that cannot fail is not evidence.

This is a check on another check. The test itself is rung 3 (an example test). Seeing it fail on the old code adds confidence that the test is sensitive to the bug, but it does not raise the claim above rung 3; a property test or mutation run is what reaches rung 2.

## Do not use when
- The change is a pure refactor with no behaviour change; there is no red to see. Use existing tests and `mutation-on-diff`.
- The failure would only be a compile error because the new API does not exist yet. Stub the API first so the test compiles and fails on behaviour.

## Set up
Two ways to get the red run. Either write the test first and run it before editing the code, or after the fix revert only the fix and rerun. With git:

    git stash push -- src/                  # park the fix, keep the new tests
    # or: git checkout HEAD~1 -- src/file   # restore the old source

## Minimal example
Bug: `price(10, 100)` returned 1000 instead of 900. Add the test in a separate file, `tests/threshold.rs`: `#[test] fn threshold_discount() { assert_eq!(mycrate::price(10, 100), 900); }`. If it lives in the same file as the fix, stashing the fix stashes the test too.

    git stash push -- src/
    cargo test threshold_discount           # red
    git stash pop
    cargo test threshold_discount           # green

## Run
Run the exact new test by name on the old code, then on the new code.

Passing looks like: the first run fails with an assertion about the behaviour you fixed (`left: 1000, right: 900`), the second passes with `1 passed`. Failure of the check: the test passes on the old code (it tests nothing about the bug), or fails for a different reason (a compile error, a missing file, a typo). Read the failure message, not just the exit status. Also confirm the test ran: `0 passed` or `no tests to run` is not red.

## As a contract check
    {"id": "red-green", "claim": "The regression test fails on the pre-fix source and passes on the fixed source", "kind": "general", "rung": 3, "cmd": "git stash push -q -- src/ && ! cargo test threshold_discount; r=$?; git stash pop -q; test $r -eq 0 && cargo test threshold_discount", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 600}

## What a pass does not prove
- That the test fails for the right reason. Inspect the red failure output yourself.
- That the test is strong: it may fail on one input and miss nearby ones. Pair with `cargo-mutants` or a property test.
- If the fix and the test touch the same files, stashing the wrong paths removes the test too; check that the red run still contains the test.
- Always restore the fix afterwards (`git stash pop`) and rerun the green run.
