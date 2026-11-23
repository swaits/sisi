---
id: architecture-lint
title: Forbidding operations or imports outside a designated module
answers: Does anything outside the one module allowed to do X still do X?
rung: 4
section: regression
languages: rust, python, typescript, java
kinds: general, money
cost: medium
detect: cargo clippy --version
ran_here: yes
verified: ran
---

## Use when
- A rule says "only module M may write files / do money arithmetic / import the database", and you want it enforced, not remembered.
- You are moving code and must show that no new call crosses a boundary.

## Do not use when
- The rule is about behaviour at run time (use tests).
- The forbidden thing is common and legitimate in many places; the allow-list would be longer than the rule.

## Set up
- Rust: `clippy.toml` with `disallowed-methods` and `disallowed-types`, each entry with a `reason`. The allowed module opts out with `#[allow(clippy::disallowed_methods)]`.
- Python: `pip install import-linter`, a `.importlinter` file with a `forbidden` contract.
- TypeScript: `dependency-cruiser`, `forbidden` rules in `.dependency-cruiser.js` (not run here).
- Java: ArchUnit rules in a JUnit test (not run here).

## Minimal example
Rust, `clippy.toml`:
```toml
disallowed-methods = [
  { path = "std::fs::write", reason = "writes go through store::save only" },
]
```
Python, `.importlinter`:
```ini
[importlinter]
root_package = pkg
[importlinter:contract:1]
name = domain must not import db
type = forbidden
source_modules = pkg.domain
forbidden_modules = pkg.db
```
Compare-two-lint-runs trick: a lint cannot always be limited to one type (`clippy::arithmetic_side_effects` flags every type). Run clippy twice with different configs, once flagging all types and once with your type in `arithmetic-side-effects-allowed`. What appears in the first run only is exactly the places that touch your type. Give each run its own `--target-dir` so neither reuses the other's cached result.

## Run
`cargo clippy --all-targets -- -D clippy::disallowed_methods` or `lint-imports`

Passing looks like: no output, exit 0. Failure: clippy names the method and the reason and exits 101 under `-D`; import-linter prints `pkg.domain.m -> pkg.db (l.1)` and exits nonzero. Both ran here.

## As a contract check
```json
{"id": "arch-boundary", "claim": "No file writes outside the store module", "kind": "general", "rung": 4,
 "cmd": "cargo clippy --all-targets -- -D clippy::disallowed_methods", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 900}
```

## What a pass does not prove
- Only the named paths. `std::fs::File::create` or a shell call passes if you did not list it. List every route to the effect.
- An `#[allow]` anywhere silences it. Count the waivers (`grep -rn "allow(clippy::disallowed" src | wc -l`) and review the number's changes with `ratchet-floor`.
- Macros and code in dependencies are not seen.
- Check the check: add a forbidden call in a scratch file and confirm the failure (done here for clippy and import-linter).
