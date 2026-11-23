---
id: zero-warnings
title: Lints, compiler and docs warnings as errors
answers: Does the code build, lint and document with no warnings at all?
rung: 4
section: regression
languages: any
kinds: general
cost: low
detect: cargo --version
ran_here: yes
verified: ran
---

## Use when
- Finishing any change in a project that keeps zero warnings, or you want it to.
- A warning is often a real fault: an unused variable that should have been used, a broken doc link, a deprecated call.

## Do not use when
- The project has hundreds of existing warnings. Use `ratchet-floor` on the count first.
- Do not put `-D warnings` into a committed build config for a library others compile with newer toolchains; a new compiler lint then breaks their build. Use it in CI only.

## Set up
Pick the tools for the language:
- Rust: `cargo clippy`, `cargo build`, `cargo doc`.
- Python: `ruff check`, `python -W error -m pytest` (warnings become failures).
- TypeScript: `tsc --noEmit --noUnusedLocals`, `eslint --max-warnings 0`.

## Minimal example
```sh
RUSTFLAGS="-D warnings" cargo build --all-targets
cargo clippy --all-targets -- -D warnings
RUSTDOCFLAGS="-D warnings" cargo doc --no-deps
cargo test --doc
```
Before changing anything, run these on the base commit and note which already fail, so you are not blamed for old problems and do not hide your own. Never silence a warning with `#[allow]` or `# noqa` without a one-line reason; if you add one, say so in the report.

## Run
The commands above, one after the other.

Passing looks like: every command exits 0 with no `warning:` lines. Failure: `error: unused variable: x` and `error: could not compile` (compiler), `error: unresolved link to broken` and `error: could not document` (docs), exit 101 under clippy `-D warnings`. All three ran here.

## As a contract check
```json
{"id": "zero-warnings", "claim": "No compiler, clippy or rustdoc warnings", "kind": "general", "rung": 4,
 "cmd": "cargo clippy --all-targets -- -D warnings && RUSTDOCFLAGS='-D warnings' cargo doc --no-deps", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 900}
```

## What a pass does not prove
- Absence of lint warnings says nothing about correctness. Clean code can be wrong.
- Only the code you compiled: feature flags, other targets and other operating systems are separate builds (`--all-features`, `cross-platform-matrix`).
- A suppression added to get green is a failure in disguise; compare `git diff` for new `allow` attributes.
- Check the check: introduce an unused variable and confirm the build fails.
