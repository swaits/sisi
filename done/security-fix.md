---
id: security-fix
title: Fixing a security vulnerability
applies_to: A reported or discovered weakness (injection, access control, leaked secret, unsafe deserialisation, dependency flaw).
---

## Done means
- The vulnerability is reproduced by an exploit-shaped test that fails before the fix and passes after, using the attacker's route, not an internal call.
- The root cause is fixed everywhere the pattern occurs, not just at the reported spot.
- Variants of the attack (encoding, case, path forms, another endpoint) are tried and refused.
- Legitimate behaviour is unchanged: the existing suite and the happy paths pass.
- If a secret leaked, it was rotated and the leak path was closed; history cleanup is not a substitute for rotation.
- The advisory or write-up says what was affected, the fixed version, and what users must do.

## Checks
- Exploit test: `red-before-green` (test-quality), rung 3; `hostile-input-from-schema`, `cargo-fuzz` or `atheris` (many-inputs) for input flaws, rung 2.
- Variants and siblings: `static-analysis-semgrep`, `codeql` (safety), rung 2; record in `findings-log` (completeness).
- Written model: `threat-model-checklist` (safety) with a check for each way in.
- Leaks: `secret-scanning`, `sensitive-data-leak-test`; dependency issues: `dependency-audit-rust`, `dependency-audit-general`.
- Access: `multi-user-isolation` (real-world).
- No regressions: `baseline-before-change`, `single-gate-command`; memory issues: `address-and-ub-sanitizers`, `unsafe-audit`.

## Common false finishes
- The exploit was blocked for the example payload; one encoding variant (URL, Unicode, double encoding) still works.
- The check is in the UI, not on the server.
- The reported route is fixed; the same code path is reachable by another endpoint.
- A leaked key was removed from the repository but not rotated.
- A denylist was added instead of an allowlist or a safe API.
- The fix breaks a legitimate use and was reverted under pressure; run the full suite.
- The error message still reveals what was probed, or a stack trace.
- No test; the next refactor reintroduces it.
- Upgrading the dependency is called done without checking the advisory's affected range against the lockfile.
