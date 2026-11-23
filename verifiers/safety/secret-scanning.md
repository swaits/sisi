---
id: secret-scanning
title: Secret scanning with gitleaks or trufflehog on the diff and the history
answers: Did this change, or any earlier commit, put a password, key or token into the repository?
rung: 2
section: safety
languages: any
kinds: general
cost: low
detect: gitleaks version
ran_here: no
verified: docs
---

Note: neither gitleaks nor trufflehog is installed here, so nothing below was
run. Commands and exit codes were checked against the gitleaks README (v8.30.x,
which says gitleaks is "feature complete", with security patches only from now on;
the author's new project is Betterleaks, not covered here) and the trufflehog README.

## Use when
- Every change, before it is committed or pushed. A leaked key must be rotated, so catching it early is the whole value.
- Code touches configuration, tests with credentials, deployment files or `.env` handling.
- Before making a private repository public.

## Do not use when
- The worry is a secret that is not in the repository but in logs or output; see `sensitive-data-leak-test`.

## Set up
    # gitleaks: brew install gitleaks, the docker image ghcr.io/gitleaks/gitleaks, or a release binary
    gitleaks version
    # trufflehog: brew install trufflehog, or the install script / docker image in its README
    # optional allowlist for known fake values: .gitleaks.toml

## Minimal example
Scan only what is about to be committed, then the full history:

    gitleaks git --staged --redact -v
    gitleaks git --redact -v          # all commits (`gitleaks dir` scans files without git history)

`--redact` keeps the secret itself out of the report, which matters because the
report may be pasted into a log or chat.

## Run
    gitleaks git --redact --exit-code 1
    trufflehog git file://. --results=verified --fail --no-update     # alternative; verifies keys against the provider

Passing looks like: gitleaks exits 0 (README: "0 - no leaks present"). A finding exits 1 (the default, set with `--exit-code`) and names
the file, line and rule; an error also exits 1 and an unknown flag exits 126. trufflehog exits 0 with no results, 1 on an error, and 183 when results were found, which only happens with `--fail`.
`--results=verified` counts only keys the provider confirms are live; use `--results=verified,unknown` to also fail on keys it could not check.
`gitleaks detect` and `protect` still work but are deprecated since 8.19.0. If a real secret is found, rotate it first; removing it
from history does not make it safe again.

## As a contract check
    {"id": "no-secrets", "claim": "No secrets in the working tree or history", "kind": "general", "rung": 2, "cmd": "gitleaks git --redact --exit-code 1", "expect": {"exit": 0}, "timeout_s": 300, "tier": "deep"}

## What a pass does not prove
Scanners match known key shapes and high-entropy strings; a custom token format
or a password in prose is missed. A shallow CI clone hides history, so fetch
full depth. An allowlist entry that is too broad hides real leaks: read changes
to `.gitleaks.toml`. Check the check by committing a fake AWS-style key on a
scratch branch and confirming it is flagged.
