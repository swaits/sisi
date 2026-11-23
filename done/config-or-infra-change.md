---
id: config-or-infra-change
title: Configuration, build, CI or infrastructure change
applies_to: Changes to build files, CI workflows, deployment, container images, infrastructure code and runtime configuration.
---

## Done means
- The change was run in the real system (a CI run, a build, a deploy to a staging copy), not only parsed.
- The failure path was exercised: the new step fails when it should.
- Secrets are not in the files or logs, and permissions are no wider than needed.
- Build and deploy work from a clean checkout and are repeatable.
- What the change affects is stated, and the rollback is known.
- Nothing else in the pipeline silently stopped running.

## Checks
- Runs: `clean-clone-build`, `smoke-after-deploy`, `cross-platform-matrix` (real-world), rung 3.
- The gate still gates: `single-gate-command`, `check-tiering` (completeness).
- Scripts: `shellcheck`; secrets: `secret-scanning`, `sensitive-data-leak-test`; `threat-model-checklist` (safety).
- Rules in config: `static-analysis-semgrep` (safety) for workflow or manifest patterns.
- Checker works: `check-the-checker` (test-quality) by breaking something on purpose.

## Common false finishes
- The YAML parses and was never run.
- A job was skipped by a condition, so the pipeline is green with fewer checks than before.
- The change works on the branch and not on the default branch, where secrets and permissions differ.
- A cache hid a missing dependency.
- Tokens were given write access "to make it work".
- A failing step was made non-fatal (`|| true`, `continue-on-error`).
