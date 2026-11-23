---
id: new-library
title: Writing a new library
applies_to: A new package or module other code will depend on, with a public interface.
---

## Done means
- The public interface is written down, every function and type has documented behaviour, errors and limits, and nothing internal is exported by accident.
- Each documented rule is exercised by tests, including edge cases, bad input and the empty case.
- Properties that should hold for all inputs (round trips, ordering, no panic) are tested at rung 2 or better.
- It builds from a clean clone with only the declared dependencies and passes on every supported platform and version.
- Dependencies are audited and their licences allowed; there is a licence file and a README with an example that runs.
- There is no stub, skipped test, or placeholder left.

## Checks
- Behaviour: `acceptance-examples` (intent) agreed with the human; `proptest`, `hypothesis`, `fast-check` or the language's equivalent (many-inputs), rung 2; `round-trip`, `algebraic-laws`.
- Tests are not hollow: `cargo-mutants`, `mutmut`, `stryker` or `pitest` (test-quality), `coverage-floor`.
- Interface: `api-semver-rust` or `api-surface-typescript` (regression) baseline recorded for the first release.
- Docs run: `doc-tests-and-links` (real-world). Clean machine: `clean-clone-build`, `cross-platform-matrix`.
- Safety: `rust-lints-strict`, `unsafe-audit`, `dependency-audit-rust` or `dependency-audit-general`, `licence-notices`.
- Complete: `no-stubs-scan`, `single-gate-command`, `spec-traceability` if a spec exists (completeness).

## Common false finishes
- Only the happy-path examples from the README are tested.
- The README example does not compile or run; nobody ran it.
- Everything is public. The first release then freezes accidental surface.
- It works with the author's dependency versions only; no lower-bound or clean-lock build was tried.
- Panics or exceptions on empty, huge or non-UTF-8 input are untested.
- Thread-safety or `Send`/`Sync` claims are unstated and untested.
- Licence is missing or a dependency's licence conflicts with it.
- Test coverage is high but assertions are weak, so mutants survive.
