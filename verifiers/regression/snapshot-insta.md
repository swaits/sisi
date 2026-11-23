---
id: snapshot-insta
title: Snapshot testing with insta (Rust), Jest/Vitest and syrupy (Python)
answers: Is the output of this function, report or message exactly what it was before?
rung: 4
section: regression
languages: rust, javascript, typescript, python
kinds: general, parsing
cost: low
detect: cargo --version
ran_here: yes
verified: ran
---

## Use when
- Output is large or structured (a report, error text, a parsed tree) and hand-writing expected values is impractical.
- You are refactoring and the output must stay the same.

## Do not use when
- The output contains time, random ids or paths; redact them first or use an example assertion.
- You would approve snapshots without reading them. Then the test records, it does not check.

## Set up
- Rust: `cargo add --dev insta`, and optionally `cargo install cargo-insta` for `cargo insta review`.
- Jest or Vitest: built in, `expect(x).toMatchSnapshot()` or `toMatchInlineSnapshot()`.
- Python: `pip install syrupy`; tests take the `snapshot` fixture.

## Minimal example
```rust
#[test]
fn greeting() { insta::assert_snapshot!(greet("Ada")); }
```
Python (syrupy): `def test_x(snapshot): assert {"a": 1} == snapshot`. Jest: `expect(render()).toMatchSnapshot()`.
Create the baselines BEFORE refactoring: Rust `INSTA_UPDATE=always cargo test`, syrupy `pytest --snapshot-update`, Jest `jest -u`. Commit the `.snap`, `.ambr` or `__snapshots__` files, then edit code.

## Run
- `INSTA_UPDATE=no cargo test` (use `no` in CI so nothing is written), or `cargo insta test`.
- `pytest`; `jest --ci` (does not write new snapshots).

Passing looks like: `test result: ok` / `1 passed`. Failure: insta prints `-old snapshot` / `+new results` and exits 101; syrupy reports `assert [+ received] == [- snapshot]`. By default insta writes a `.snap.new` file next to the old one; delete or review it, never commit it unseen.

## As a contract check
```json
{"id": "snapshots", "claim": "All snapshot tests match the committed snapshots", "kind": "general", "rung": 4,
 "cmd": "INSTA_UPDATE=no cargo test", "expect": {"exit": 0, "stdout_contains": "test result: ok"}, "tier": "deep", "timeout_s": 600}
```

## What a pass does not prove
- That the snapshot was right when recorded. Read each new snapshot like a diff.
- Updating snapshots turns every failure into a pass. The evidence is `git diff` on the snapshot files showing only intended changes.
- Obsolete snapshots can pile up: `cargo insta test --unreferenced=reject` (flag listed in cargo-insta source, not run here) and `jest --ci` flag obsolete ones.
- Check the check: change the function and see the failure (done here with insta 1.49 and syrupy).
