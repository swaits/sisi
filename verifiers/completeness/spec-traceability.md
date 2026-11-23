---
id: spec-traceability
title: Requirement ids cited by code and tests, with a test that fails on an unknown, uncited or untested id
answers: Is every requirement implemented and tested, and does every cited id exist?
rung: 3
section: completeness
languages: any
kinds: general, state-machine, money
cost: medium
detect: python3 --version
ran_here: yes
verified: ran
---

Modelled on a reference project, where each rule has an id, tests live
under a `spec/` folder keyed by those ids, and a loader test fails when a
claim has no test. The script below was run here on a scratch repository.

## Use when
- There is a written specification (rules, requirements, invariants) and "all of it is done" must be checkable.
- The request has many separate rules and one is easy to forget.
- A reviewer asks "where is rule R-17 implemented, and what tests it?"

## Do not use when
- The task is small or has no written requirements. Use `requirement-to-check-map` for the request's sentences.
- Ids would be cited without being exercised. The citation proves a link, not that the test is strong; see `assertion-strength-review`.

## Set up
Give every requirement a stable id in one file (`spec/requirements.md`, lines
`- R-001: text`). Code cites `implements: R-001` in a comment; each test cites
`covers: R-001`. Never renumber; retire an id with a note.

## Minimal example
`scripts/spec_trace.py` (standard library, run from the repository root):

    import re, subprocess, sys
    ids = set(re.findall(r"^- (R-\d+):", open("spec/requirements.md").read(), re.M))
    files = subprocess.run(["git","ls-files","-co","--exclude-standard","src","tests"],
                           capture_output=True, text=True, check=True).stdout.split()
    impl, cov = set(), set()
    for f in files:
        t = open(f, errors="ignore").read()
        impl |= set(re.findall(r"implements:\s*(R-\d+)", t))
        cov |= set(re.findall(r"covers:\s*(R-\d+)", t))
    bad = [f"unknown id cited: {i}" for i in sorted((impl|cov)-ids)]
    bad += [f"{i}: no code cites it" for i in sorted(ids-impl)]
    bad += [f"{i}: no test covers it" for i in sorted(ids-cov)]
    print("\n".join(bad) or f"ok: {len(ids)} requirements traced")
    sys.exit(1 if bad else 0)

## Run
    python3 scripts/spec_trace.py

Passing looks like: `ok: N requirements traced`, exit 0. Failure lists each problem
(`R-002: no test covers it`, `unknown id cited: R-009`) and exits 1 (run here).

## As a contract check
    {"id": "spec-traced", "claim": "Every requirement id is cited by code and by a test, and every cited id exists", "kind": "general", "rung": 3, "cmd": "python3 scripts/spec_trace.py", "expect": {"exit": 0, "stdout_contains": "requirements traced"}, "timeout_s": 60}

## What a pass does not prove
That a test citing `covers: R-001` actually checks R-001, or even passes. A
comment is cheap. Strengthen it: the test run must also pass, and the cited test
should fail when the requirement's code is broken (`mutation-on-diff`). Also
count the ids: a spec that was quietly shortened passes, so compare the id count to the
agreed spec in review.
