---
id: dependency-upgrade
title: Upgrading a dependency or toolchain
applies_to: Raising the version of a library, framework, runtime or compiler the project depends on.
---

## Done means
- The project builds from a clean checkout with the new version pinned in the lockfile, on every supported platform.
- The whole test suite passes without any test being weakened, skipped or edited just to pass.
- Behaviour changes the upgrade introduced are read from its changelog, decided on, and either handled or ruled out.
- The new version has no known vulnerability, an allowed licence and a trusted source, and the transitive changes were looked at.
- Public output (formats, error text, API) that users rely on did not change unnoticed.
- Notices and size are current.

## Checks
- Builds and tests: `clean-clone-build`, `cross-platform-matrix` (real-world), `single-gate-command` (completeness), rung 3.
- Behaviour is unchanged: `differential-old-vs-new` (many-inputs), rung 2; `characterization-tests`, `golden-files-hand-verified`, `baseline-before-change` (regression).
- Public interface: `api-semver-rust`, `api-surface-typescript`, `api-breaking-schema` (regression).
- Security and legal: `dependency-audit-rust` or `dependency-audit-general`, `licence-notices` (safety).
- Compiler and lints: `rust-lints-strict`, `zero-warnings` (regression).
- Speed and size: `perf-regression`, `size-budget`.
- Tests can fail: `mutation-on-diff` for any test you changed.

## Common false finishes
- The lockfile was not committed, or `cargo update` / `npm update` moved many packages, and only the target was reviewed.
- Tests pass because deprecated-behaviour tests were skipped or snapshots were regenerated; read those diffs.
- Compile warnings about deprecated use were left, which become errors next release.
- It was only built on the author's platform.
- A transitive dependency changed licence, pulled in a yanked version, or added unsafe code.
- The changelog was not read; a changed default (timeouts, parsing strictness, rounding) does not break tests.
- A pin was loosened to make the resolver pass.
- Release notes were summarised from memory rather than read.
