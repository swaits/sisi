---
id: vacuity-check
title: Check that tests and assertions actually ran
answers: Did my tests really execute and assert something, or did the run pass because nothing ran?
rung: 3
section: test-quality
languages: any
kinds: general, parsing, state-machine
cost: low
detect:
ran_here: yes
verified: ran
---

## Use when
- You ran a test with a name filter, a path, or a marker and it said "ok".
- A property or generated test might discard every input, so its body never runs.
- A pass is the only evidence for done. A pass with zero tests is a false finish.

## Do not use when
- It is not a separate check of the code. It guards the other checks; use it beside them.

## Set up
Know what "nothing ran" looks like in your runner. Measured here:

- `cargo test nomatch`: prints `0 passed; ... 2 filtered out`, exit 0.
- `cargo nextest run nomatch`: `error: no tests to run`, exit 4 (nextest 0.9.143). `--no-tests=pass` makes it exit 0, so do not add that flag.
- `pytest -k nomatch`: `2 deselected`, exit 5. An empty collection is exit 5, not 0.
- `go test -run Nomatch`: prints `testing: warning: no tests to run` and exits 0 (from the Go docs, not run here).
- Jest and Vitest fail on no tests by default, unless `--passWithNoTests` is set.

## Minimal example
Assert that the count of executed tests is at least one. For cargo:

    out=$(cargo test my_test 2>&1); echo "$out"
    echo "$out" | grep -E 'test result: ok\. [1-9][0-9]* passed' >/dev/null

For preconditions: assert the interesting case happened, for example in a property test count how many inputs were accepted and fail if none. In proptest use `prop_assume!` sparingly and check the rejection rate; in Hypothesis use `event()` and `target()`, and read `--hypothesis-show-statistics`; in a loop test keep a counter and `assert!(count > 0)` after the loop. For distributed tests, assert that a fault was actually injected.

## Run
Run the tests with a name filter, then check the count line as above. Also check skipped and ignored tests: `cargo test -- --include-ignored` runs them; pytest `-rs` lists skips; Go prints `SKIP`.

Passing looks like: at least one test is reported passed, none skipped that matter, and the assertion-count or event check is above zero. Failure is a zero count, or all tests skipped or filtered out.

## As a contract check
    {"id": "tests-ran", "claim": "At least one test matching the filter ran and passed", "kind": "general", "rung": 3, "cmd": "cargo test my_test 2>&1 | grep -E 'test result: ok\\. [1-9][0-9]* passed'", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 600}

## What a pass does not prove
- That the assertions inside the tests are meaningful; see `assertion-strength-review`.
- That the test is sensitive to the bug; see `red-before-green`.
- Counting tests does not count assertions. A test with an `if` that skips its assertion, or an assert in a callback that never fires, still passes. Add a counter or use mutation testing.
- Cargo's output format can change; keep the pattern tested against your version.
