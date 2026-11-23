---
id: static-analysis-semgrep
title: Semgrep rules, including a custom rule for a project-specific mistake
answers: Does any code match a known-bad pattern, including a mistake this project keeps making?
rung: 2
section: safety
languages: any
kinds: general, parsing
cost: medium
detect: semgrep --version
ran_here: yes
verified: ran
---

## Use when
- You want a scan for a known class of bug (injection, unsafe deserialisation, hard-coded keys) across many languages.
- The project keeps repeating one mistake (calling `float()` on money, using `datetime.now()` where a clock is injected). Write a rule once; every later change is checked.
- You fixed a bug and want to make sure no sibling of it exists elsewhere.

## Do not use when
- The claim is about behaviour or values. Semgrep matches syntax, so it cannot show a result is right.
- You need data-flow across files and functions that Semgrep's free taint mode cannot follow; see `codeql` (which has licence limits on private code; check it).

## Set up
    pipx install semgrep          # README's preferred way; also: uv tool install semgrep, brew install semgrep
    mkdir -p rules                # not a hidden directory: `semgrep --test` found nothing under `.semgrep/`

Not installed globally here; the example below was run in a throwaway virtualenv (`pip install semgrep`, version 1.186.0).

## Minimal example
`rules/no-float-money.yml`:

    rules:
      - id: no-float-money
        languages: [python]
        severity: ERROR
        message: Money must be Decimal or integer cents, not float.
        pattern-either:
          - pattern: float($X)
          - pattern: $X = $Y / $Z
        paths:
          include: ["/src/billing/"]

`src/billing/bad.py` containing `total = float(price)` is reported. `paths.include` patterns are matched relative to the scan target, so scan from the project root (`.`) and anchor the pattern with a leading `/`. A bare `src/billing/` still works but prints a warning that it will change meaning.

## Run
    semgrep scan --config rules/ --error --metrics=off .

Passing looks like: exit 0 and `Findings: 0`. With `--error` any finding exits 1; a fatal error (bad rule, bad config) exits 2. Without `--error`, findings still exit 0, so never drop the flag. Check the output also says `Targets scanned: N` with N above 0.

Test the rule itself. Next to the rule, in a file with the same base name and the language's extension (`rules/no-float-money.py`):

    # ruleid: no-float-money
    total = float(price)
    # ok: no-float-money
    total = price_cents

then `semgrep scan --test rules/`. It prints `1/1: ✓ All tests passed` and exits 0; a missed `ruleid:` line prints `missed lines: [N]` and exits 1.

## As a contract check
    {"id": "semgrep-project-rules", "claim": "No code matches the project's banned patterns", "kind": "general", "rung": 2, "cmd": "semgrep scan --config rules/ --error --metrics=off . && semgrep scan --test rules/", "expect": {"exit": 0}, "timeout_s": 300, "tier": "deep"}

## What a pass does not prove
A pass proves only that no code matches the patterns you wrote. A rule that
matches nothing passes forever. Two ways this happened while checking this
entry: a `paths.include` of `src/billing/` with the scan target `src/` scanned
zero files and exited 0, and `--test` against a hidden `.semgrep/` directory
printed "No unit tests found" and exited 0. So keep a `ruleid:` test file, run
`--test`, and read `Targets scanned`. Pattern rules miss aliasing, such as
`f = float; f(x)`. A rule is a sample of bad shapes, not a proof of safety.
Rule ids reported by `scan` carry the directory name as a prefix
(`rules.no-float-money`); the test annotations use the plain id.
