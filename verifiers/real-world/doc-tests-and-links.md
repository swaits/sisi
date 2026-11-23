---
id: doc-tests-and-links
title: Doctests, compiled examples and link checking
answers: Do the examples in the docs and comments still run, and do the links still resolve?
rung: 3
section: real-world
languages: rust, python, any
kinds: general
cost: low
detect: cargo --version
ran_here: yes
verified: ran
---

## Use when
- You wrote or changed documentation, a README, or a doc comment that contains code or links.
- You change a public function: the examples that show it must still compile and give the stated result.

## Do not use when
- The examples need unavailable services. Mark them (`no_run` in Rust) so they at least compile, and say so.

## Set up
- Rust: `cargo test --doc` compiles and runs each fenced example in doc comments and in the crate's README when included with `#![doc = include_str!("../README.md")]`.
- Python: `python3 -m doctest -v file.py` or `pytest --doctest-modules`.
- Links: `lychee` (https://github.com/lycheeverse/lychee) checks Markdown and HTML links; `lychee --offline` checks local file links only.

## Minimal example
```rust
/// Adds two numbers.
///
/// ```
/// assert_eq!(mycrate::add(2, 2), 4);
/// ```
pub fn add(a: i32, b: i32) -> i32 { a + b }
```
```python
def f(x):
    """
    >>> f(2)
    4
    """
    return x * 2
```
Make the example the real documentation of behaviour: assert results, not just calls. Check docs build without broken intra-doc links: `RUSTDOCFLAGS="-D warnings" cargo doc --no-deps` (see `zero-warnings`).

## Run
`cargo test --doc`, `python3 -m doctest file.py`, `lychee --offline README.md docs/`

Passing looks like: `test result: ok` (Rust), no output and exit 0 (Python doctest), `0 errors` (lychee). Failure: Rust marks `test src/lib.rs - add (line 3) ... FAILED`; Python prints `***Test Failed*** 1 failure` and exits 1. Both ran here; lychee was not usable here, so its output is from its README.

## As a contract check
```json
{"id": "doctests", "claim": "All documentation examples compile and pass", "kind": "general", "rung": 3,
 "cmd": "cargo test --doc", "expect": {"exit": 0, "stdout_contains": "test result: ok"}, "tier": "deep", "timeout_s": 600}
```

## What a pass does not prove
- Examples with no assertion pass when they only run. `0 passed` also appears when there are no doctests at all; require a count above zero.
- An external link that answers 200 can still point to the wrong page. Network link checks are flaky; run them separately from the main gate.
- Prose can still be wrong. Only code and links are tested.
- Check the check: change an expected value and see the failure (done here with Rust and Python).
