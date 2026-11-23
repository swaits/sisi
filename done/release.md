---
id: release
title: Releasing a version
applies_to: Tagging, packaging and publishing a version of a program or library.
---

## Done means
- The version in the manifest, the tag, the changelog and the package name agree.
- The full test set ran on this exact commit, including the slow set, and its result is recorded with its age.
- The package was built from a clean checkout, not a developer's working tree, and its contents were inspected: licence, notices, the binary and nothing secret.
- Third-party notices and dependency audits are current.
- A fresh machine can install it, run it, and upgrade from the previous version with user data intact.
- Publishing was done from the gate, not by hand; it can be undone or was left as a draft until the owner tried it.

## Checks
- One command: `release-gate`, `single-gate-command` (completeness), rung 3.
- Depth and freshness: `check-tiering` (completeness); mutation, proofs and fuzz evidence dates recorded.
- Package: `packaging-install-upgrade`, `clean-clone-build`, `cross-platform-matrix` (real-world), rung 3.
- Legal and security: `licence-notices`, `dependency-audit-rust` or `dependency-audit-general`, `secret-scanning` (safety).
- Interface: `api-semver-rust`, `api-breaking-schema` (regression) for the version bump.
- After publishing: `smoke-after-deploy` (real-world); the human, `owner-acceptance-runbook` (intent), rung 6.

## Common false finishes
- Tests ran on the branch, then more commits landed before the tag.
- The tag and the manifest version differ, or the changelog is for the last release.
- Built on a dirty tree; a file that is not committed is in the package.
- The package lacks the licence or notices file, or includes a `.env` or test data.
- Install was tested on the machine that built it, where all the dependencies already exist.
- Upgrade from the previous version was not tried, and the data format changed.
- Slow tests, fuzzing and proofs were last run weeks ago and the release says "all checks passed".
- Published by hand, skipping the gate, because it was urgent.
