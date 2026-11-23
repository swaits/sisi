---
id: cross-platform-matrix
title: Running build and tests on the other operating systems in CI
answers: Does this also work on Windows and macOS, not just on the Linux machine I tested on?
rung: 3
section: real-world
languages: any
kinds: general
cost: medium
detect: gh --version
ran_here: no
verified: docs
---

## Use when
- The software ships for more than one OS, or touches paths, file permissions, line endings, case sensitivity, processes, sockets or the clock.
- You changed anything that reads or writes files, spawns processes or draws a UI.

## Do not use when
- The product is Linux-server-only and says so. Then a matrix is cost without benefit.
- You cannot reach CI. Say so; a Linux pass does not support a claim about other systems.

## Set up
Use the CI provider's hosted runners. For GitHub Actions the labels are `ubuntu-latest` (or a pinned `ubuntu-24.04`), `windows-latest` and `macos-latest`. Pin versions where results must not drift.

## Minimal example
`.github/workflows/matrix.yml`
```yaml
name: matrix
on: [push, pull_request]
jobs:
  test:
    strategy:
      fail-fast: false          # one OS failing must not hide the others
      matrix:
        os: [ubuntu-24.04, windows-latest, macos-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - run: cargo test --locked
        shell: bash
```
Write the platform code with the differences in mind and test them: `#[cfg(unix)]` for permission bits (a read-only folder cannot be made on Windows; use the read-only attribute), path separators, `\r\n`. A test that cannot run on one OS must be skipped explicitly with a reason, never silently.
After pushing, read the result: `gh run list --branch "$(git branch --show-current)"` and `gh run view <id> --log-failed`.

## Run
Push and wait for the workflow. Passing looks like: every matrix job green (`gh run view` shows `✓` for each OS). Failure: a red job named after the OS; read its log, do not rerun until green.

## As a contract check
```json
{"id": "ci-matrix", "claim": "Tests pass on Linux, Windows and macOS in CI for this commit", "kind": "general", "rung": 3,
 "cmd": "gh run list --commit $(git rev-parse HEAD) --workflow matrix.yml --json conclusion --jq '.[0].conclusion' | grep -x success", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 120}
```

## What a pass does not prove
- Only the OS versions of the hosted runners, with their tools. Real desktops differ (graphics, locale, antivirus).
- Skipped tests are invisible in a green run. Count them in the log.
- GUI pixel comparisons differ across OS renderers; compare structure or shapes there (`visual-regression-native-gui`).
- Not run here: no CI access in this session; the workflow syntax is standard GitHub Actions, the `gh` commands were not executed.
- Check the check: confirm the workflow file actually lists the OSes, and that `gh run list` returns a run for this commit rather than nothing.
