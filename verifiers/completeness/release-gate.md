---
id: release-gate
title: One command or workflow that must pass before release
answers: Is this exact build safe to publish, with the right version, notices, full tests and package contents?
rung: 3
section: completeness
languages: any
kinds: general
cost: medium
detect: just --version
ran_here: no
verified: docs
---

Note: modelled on a release workflow in a reference project (tag must
equal the program's version; notices current; packages built on the oldest supported
system; each package inspected for its contents; the release left as a draft).
Not run here.

## Use when
- You are about to tag, publish a package, push an image or hand over a build.
- A release process has more than two manual steps and one has been missed before.

## Do not use when
- Nothing is being released. For everyday work use `single-gate-command`.

## Set up
A script `scripts/release-gate.sh` that the release workflow calls first and fails
fast. Keep publishing a separate step that runs only after the gate. Leave the
release a draft until the owner has tried the package.

## Minimal example
    #!/usr/bin/env bash
    set -euo pipefail
    ver=$(sed -n 's/^version = "\(.*\)"/\1/p' Cargo.toml | head -1)
    [ "${GITHUB_REF_NAME:-v$ver}" = "v$ver" ] || { echo "tag != version $ver" >&2; exit 1; }
    scripts/notices.sh --check
    just check
    cargo package --list | grep -q '^LICENSE' || { echo "LICENSE missing from package" >&2; exit 1; }
    cargo package --locked --allow-dirty >/dev/null
    git diff --exit-code   # nothing the gate regenerated is uncommitted

## Run
    scripts/release-gate.sh

Passing looks like: exit 0 and each step's own success line. Failure names the step
(`tag != version`, `notices out of date`). Then install the built package on a clean
machine and run it (`packaging-install-upgrade`, `clean-clone-build`); the gate
alone does not do that. Include the changelog entry and the deep tier (`check-tiering`).

## As a contract check
    {"id": "release-gate", "claim": "The release gate passes for the version being released", "kind": "general", "rung": 3, "cmd": "scripts/release-gate.sh", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 3600}

## What a pass does not prove
That the release works for users. A gate on a developer machine proves little
about a clean one; run it in CI from a fresh clone. A gate someone can skip by
tagging by hand is not a gate: have the workflow trigger on the tag and refuse
to publish unless the gate job passed.
