---
id: api-semver-rust
title: Public API compatibility for Rust crates with cargo-semver-checks
answers: Did my change break the public API of this crate for anyone who depends on it?
rung: 4
section: regression
languages: rust
kinds: general
cost: low
detect: cargo semver-checks --version
ran_here: no
verified: docs
---

## Use when
- You changed a library crate's public items (types, functions, traits, enum variants, features).
- You are about to bump or publish a version and must say whether the bump is right.

## Do not use when
- The crate is a binary with no public library API.
- No earlier version exists to compare against (the first release).

## Set up
```sh
cargo install cargo-semver-checks --locked
```
It compares the current source's rustdoc JSON against a baseline: the latest release on the registry, or one you name.

## Minimal example
Baseline options (from the tool's README): a registry version, or a git revision of your own history.
```sh
cargo semver-checks                                   # against the latest published version
cargo semver-checks --baseline-version 0.4.2          # against a named registry version
cargo semver-checks --baseline-rev v0.4.2             # against a git tag or commit
cargo semver-checks --package mylib                   # one package in a workspace
```
Before editing, run it once to know the starting state. A removed `pub fn` or a new required trait method fails with the lint name (for example `function_missing`) and the item's path.

## Run
`cargo semver-checks`

Passing looks like: a line such as `Summary no semver update required` (or the version bump you already made is enough) and exit 0. Failure lists each broken item and the required bump, exit 1.

## As a contract check
```json
{"id": "semver", "claim": "The public API of mylib is compatible with the last release for this version bump", "kind": "general", "rung": 4,
 "cmd": "cargo semver-checks --package mylib", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 900}
```

## What a pass does not prove
- It checks the API's shape (names, signatures, variants), not behaviour. A function can keep its signature and change what it returns.
- It runs a list of known break patterns; some breaks (trait coherence, unusual generics) are not detected. The README says the lint list is incomplete.
- A baseline equal to your own unpublished changes proves nothing. Make sure the baseline is the released version.
- Not run here (tool not installed); commands and the `--baseline-*` flags are from its README.
- Check the check: remove a `pub` function in a scratch copy and see it fail.
