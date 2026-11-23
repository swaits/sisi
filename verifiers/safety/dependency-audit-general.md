---
id: dependency-audit-general
title: Vulnerability scans for any ecosystem with osv-scanner, npm audit and pip-audit
answers: Do the packages this project depends on have known vulnerabilities?
rung: 2
section: safety
languages: any
kinds: general
cost: low
detect: osv-scanner --version
ran_here: no
verified: docs
---

Note: `npm audit --help` was read here, and the `pip-audit` commands below
were run here (pip-audit 2.10.1, in a throwaway virtualenv, needs network). `osv-scanner` is not
installed here; its commands and exit codes come from the osv-scanner
documentation (google.github.io/osv-scanner).

## Use when
- The change adds or upgrades a dependency, or you are about to release.
- The project spans several ecosystems (npm, PyPI, Go, Maven, crates): osv-scanner reads their lockfiles together.
- A scheduled job must catch advisories published after the code was written.

## Do not use when
- The project is Rust only and wants licence and source rules as well; use `dependency-audit-rust`.
- No lockfile is committed. Scans of loose version ranges give answers about a build nobody ran.

## Set up
    go install github.com/google/osv-scanner/v2/cmd/osv-scanner@latest   # needs a recent Go; or: brew install osv-scanner, or a release binary
    pipx install pip-audit        # needs Python 3.10 or newer
    # npm audit ships with npm

## Minimal example
Commit the lockfiles (`package-lock.json`, `poetry.lock`, `requirements.txt` with
pins, `go.mod`), then scan them.

## Run
    osv-scanner scan source -r .
    npm audit --audit-level=high --omit=dev
    pip-audit -r requirements.txt --strict

Passing looks like: osv-scanner exits 0 (the docs define 0 as "packages found, none match a vulnerability"; its exact message is not documented); `npm audit` exits
0 and prints "found 0 vulnerabilities" at or above the chosen level; `pip-audit`
exits 0 and prints "No known vulnerabilities found". Any finding exits 1 for all three. osv-scanner
also exits 128 when it found no packages to scan (wrong directory, no lockfile) and 127 on a general error: both are failures, not passes.
`pip-audit` with unpinned requirements resolves dependencies itself; `--strict` turns a failed resolution into a failure.
`--omit=dev` limits npm to what ships; drop it if build tools run on untrusted input.

## As a contract check
    {"id": "dep-vulns", "claim": "No known vulnerabilities in locked dependencies", "kind": "general", "rung": 2, "cmd": "osv-scanner scan source -r .", "expect": {"exit": 0}, "timeout_s": 300, "tier": "deep"}

## What a pass does not prove
osv-scanner reports vulnerabilities of every severity; the docs page for its CLI mentions no severity filter, so the contract above is "none at all", not "none above high". Use `npm audit --audit-level=high` if you want a severity cut.
Only advisories already in the database, for versions the lockfile names.
Network is needed; an offline run that silently skips the database must not
count (check the output says it queried). Ignoring a finding in a config file
is the usual way this check is defeated: review the diff of any ignore list. A
vulnerable package that is installed but unreachable is still reported, and a
reachable vulnerable function in an unreported package is not.
