---
id: codeql
title: CodeQL queries for data-flow security and custom bug classes
answers: Can untrusted input reach a dangerous call anywhere in this code?
rung: 2
section: safety
languages: any
kinds: general, parsing
cost: high
detect: codeql version
ran_here: no
verified: docs
---

## Use when
- The claim is about flow: user input reaching SQL, a shell, a file path or a deserialiser through several functions.
- You need a repeatable security scan in CI (GitHub code scanning runs the same engine).
- You want a custom query for a project-specific flow, such as "a value read from the request must pass `sanitize()` before `render()`".

## Do not use when
- Licence first: the CodeQL CLI terms (codeql-cli-binaries README) say it "can only be used on codebases that are released under an OSI-approved open source license, or to perform academic research" and "can't be used to generate CodeQL databases for or during automated analysis, continuous integration or continuous delivery" outside that; private commercial code needs GitHub code scanning (which is licensed) or a sales contract. Check this before putting it in a contract.
- A pattern match is enough; `static-analysis-semgrep` is far cheaper to set up.
- The language is not supported. The supported list is C/C++, C#, GitHub Actions workflows, Go, Java, Kotlin, JavaScript/TypeScript, Python, Ruby, Rust (editions 2021 and 2024, needs Cargo, no nightly features) and Swift (analysis needs macOS).
- You need to show behaviour is correct rather than safe.

## Set up
Download the CodeQL bundle (CLI plus the standard query packs) from the
`github/codeql-action` releases (assets `codeql-bundle-*`), unpack it and put
`codeql` on PATH. Then, per project; the database path comes last and must not exist yet:

    codeql database create db --language=python --source-root=.
    # compiled languages add: --command="make"
    # --build-mode=none exists for C#, Java, JavaScript/TypeScript, Python and Ruby only

## Minimal example
Run the maintained security suite, then your own query pack:

    codeql database analyze --format=sarifv2.1.0 --output=out.sarif -- db \
      codeql/python-queries:codeql-suites/python-security-extended.qls

## Run
    codeql database analyze --format=sarifv2.1.0 --output=out.sarif -- db <suite-or-pack>
    python3 -c "import json,sys; r=json.load(open('out.sarif'))['runs'][0]['results']; print(len(r)); sys.exit(1 if r else 0)"

Passing looks like: the analyze command exits 0 and the result count is 0.
The CLI manual does not document exit codes for `analyze`; the usual behaviour (not confirmed here, the tool is not installed) is exit 0 even when it finds issues, so the count check is what fails. The manual also says `sarif-latest` output changes between CodeQL versions and is unsuitable for automation, so the pinned `sarifv2.1.0` is used here. `--threads=0` uses every core.

## As a contract check
    {"id": "codeql-security", "claim": "CodeQL security-extended suite reports no results", "kind": "general", "rung": 2, "cmd": "codeql database analyze --format=sarifv2.1.0 --output=out.sarif -- db codeql/python-queries:codeql-suites/python-security-extended.qls && python3 -c \"import json,sys; sys.exit(1 if json.load(open('out.sarif'))['runs'][0]['results'] else 0)\"", "expect": {"exit": 0}, "timeout_s": 1800, "tier": "deep"}

## What a pass does not prove
Only the flows the queries model are found; custom sinks and sanitisers that
the library does not know produce misses or noise. A stale database
(created before your edit) gives a pass for old code, so recreate it each run.
Check the check: add a known-vulnerable line on a scratch branch and confirm it
is reported.
