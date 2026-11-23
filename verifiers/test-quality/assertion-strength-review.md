---
id: assertion-strength-review
title: Review that tests assert on outcomes, not just that code ran
answers: Do these tests check the result that matters, or would they pass for wrong behaviour too?
rung: 5
section: test-quality
languages: any
kinds: general, money, parsing, state-machine
cost: low
detect:
ran_here: no
verified: docs
---

## Use when
- You wrote or were handed tests and want to know they would fail on wrong output.
- A suite has high coverage and passes but a bug shipped.
- Before reporting done: a last read of your own new tests, with the checklist below.

## Do not use when
- A mutation tool is available and fast enough: it measures this mechanically. This review is judgement (rung 5) and is for cases the tool cannot reach or as a quick first pass.

## Set up
No tool. Read each new test and ask the questions below. A second agent or reviewer, given only the tests and the spec (not your reasoning), makes the review less biased. Cheap mechanical aids: `grep` for the smells; run mutation testing on the changed file (`mutation-on-diff`).

## Minimal example
Smells and what to do instead:

| Smell | Why it is weak | Instead |
|---|---|---|
| `assert!(result.is_ok())` | passes for any success value | compare the value: `assert_eq!(result.unwrap(), expected)` |
| Test calls the function and asserts nothing, or "does not panic" | passes if the output is garbage | assert the output, the state change or the error variant |
| Snapshot of the whole output, accepted blindly | records the current behaviour, right or wrong | review the snapshot line by line against the spec; assert key fields too |
| Assertion computed with the same code under test | tests the code against itself | use a hand-calculated constant or an independent oracle |
| `assert!(x > 0)` where an exact value is known | allows many wrong values | assert the exact value |
| Mock returns what the test expects; test checks the mock was called | tests the mock | assert the observable effect |
| Assertion inside a loop over an empty list, or in a callback that may not fire | vacuous | assert the count first; see `vacuity-check` |
| Only the happy path | misses boundaries | add the boundary, the empty input, the error case |

## Run
For each new test, write down in one line what wrong implementation it would catch. If you cannot name one, the test is weak. Then check it mechanically: temporarily change the code (flip a comparison, return a constant) and run the test; it must fail.

Passing looks like: every test has a named wrong behaviour it rejects, and the temporary breakage turns it red. Failure: a test stays green under a plausible bug.

## As a contract check
    {"id": "assertion-review", "claim": "Each new test fails when the behaviour it covers is broken", "kind": "general", "rung": 5, "cmd": "cargo mutants --in-diff /tmp/change.diff", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 1800}

The review itself is judged; the mechanical stand-in is mutation testing of the diff, with the same limits as in `mutation-on-diff`.

## What a pass does not prove
- A judged review is only as good as the reviewer's reading of the spec. It can miss subtle gaps.
- Strong assertions on the wrong expected value are still wrong. Derive expected values from the specification, not from the output you just got.
- It does not show the tests were run. See `vacuity-check`.
