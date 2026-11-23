---
id: new-product
title: Building a whole new product from a short statement
applies_to: Turning a one-line or short description (an app, a service, a tool) into working software for real users.
---

## Done means
- The statement was turned into a written contract the human confirmed once: who it is for, what it must do, what it must never do, with concrete acceptance examples.
- Every requirement has an id, code and tests cite them, and none is left unbuilt (no stubs, skipped tests or placeholder data).
- The core logic has strong checks: proofs or property tests for its laws, a reference to compare to, hostile input for every parser.
- The product runs from a clean machine, installs, starts, and does the real job end to end through its public surface.
- It is safe: dependencies audited, secrets handled, trust boundaries modelled, data stored survives crashes and upgrades.
- One command defines done; documentation says how to run and verify it; a release path exists.
- The owner walked it and accepted it, and what was assumed is reported.

## Checks
- What to build: `acceptance-examples`, `requirement-to-check-map` (completeness), `spec-traceability`; design: `tlaplus` or `quint` for state machines (design).
- Logic: `lean4-proofs`, `kani` or `proptest` (prove, many-inputs), rung 1 to 2; `stateful-model-test`, `differential-reference`, `round-trip`.
- Tests are real: `cargo-mutants` or the language's mutation tool, `vacuity-check`, `assertion-strength-review` (test-quality).
- Real world: `e2e-playwright` or `cli-transcript-tests`, `clean-clone-build`, `packaging-install-upgrade`, `cross-platform-matrix`.
- Safety: `rust-lints-strict`, `dependency-audit-rust`, `secret-scanning`, `threat-model-checklist`, `licence-notices`.
- Done: `single-gate-command`, `no-stubs-scan`, `check-tiering`, `release-gate`; the human: `owner-acceptance-runbook` (intent), rung 6.

## Common false finishes
- The demo path works. The error, empty, large and concurrent cases were never tried.
- Features that were in the statement are quietly dropped or stubbed, and the final report does not list them.
- The tests are many and shallow: they pass, and mutants survive.
- It works from the author's environment and fails on a clean machine.
- Only what the agent chose to test was tested; no independent check, no owner walk-through.
- There is no persistence, backup or upgrade story, so the first update loses data.
- Decisions were made silently. Every assumption belongs in the contract and the report.
- "Done" was declared with no single command that proves it.
