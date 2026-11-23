---
id: check-tiering
title: Fast checks on every change, deep checks before release or on a schedule, with the freshness recorded
answers: Which checks must run now, which run later, and how old is the evidence from the deep ones?
rung: 3
section: completeness
languages: any
kinds: general
cost: medium
detect: just --version
ran_here: no
verified: docs
---

Note: modelled on a reference project, which keeps a table of each
technique, its command, its cost, how often it runs and the date and result of the
last run, and has CI run the heavy ones weekly. Not run here.

## Use when
- Some checks (mutation testing, long proofs, fuzzing, full end to end) take minutes or hours and cannot run on every edit.
- You want "done" for a small change to be fast and "release" to be thorough, with no confusion over which is which.
- Deep evidence goes stale after code changes and you need to see that.

## Do not use when
- All checks finish in under a minute. Put them in one gate (`single-gate-command`).

## Set up
Two commands: `check` (fast, every change) and `deep` (slow, release or schedule).
Keep a table `docs/verification-status.md`: technique, command, cost, cadence,
last run date, commit, result.

## Minimal example
`docs/verification-status.md`:

    | technique | command | cost | cadence | last run | commit | result |
    | clippy, tests | just check | 2 min | every change | CI | HEAD | pass |
    | cargo-mutants | just mutants | 2 h | weekly | 2026-11-14 | a1b2c3d | 312 caught, 4 equivalent (see findings-log) |
    | kani proofs | just prove | 20 min | before release | 2026-11-20 | e4f5a6b | pass |

A scheduled workflow (`on: schedule: - cron: "0 3 * * 1"`) runs `just deep`.

## Run
    git rev-list --count a1b2c3d..HEAD -- src/       # commits since the deep evidence

Passing looks like: the fast set passes on this change, and for each deep
technique the recorded commit is the current one for the code it covers, or the count
of commits since touching that code is zero. If not zero, the deep result is stale:
say "last run at <commit>, N commits behind", never "passes".

## As a contract check
    {"id": "deep-evidence-fresh", "claim": "Deep verification was run on the current code, or its age is reported", "kind": "general", "rung": 3, "cmd": "python3 tools/evidence_age.py docs/verification-status.md --max-commits 0", "expect": {"exit": 0}, "timeout_s": 60}

## What a pass does not prove
That the deep run itself was strong. A date with no commit hash is
unusable, and one hand-edited without running is false evidence: have CI write
the table. Splitting into tiers is only safe if release runs the deep tier; see
`release-gate`.
