---
id: cli-transcript-tests
title: Recorded CLI sessions with trycmd, cram or scrut
answers: Does the command-line tool still print exactly what its documented examples show?
rung: 4
section: real-world
languages: any
kinds: general, parsing
cost: low
detect: scrut --version
ran_here: no
verified: docs
---

## Use when
- You build or change a command-line tool and want its documented usage checked like tests.
- Output, exit codes and error messages are part of the product.

## Do not use when
- The output includes times or absolute paths and you cannot normalise them; use patterns or a different assertion.
- The tool is a library; use ordinary unit tests.

## Set up
- Rust: `cargo add --dev trycmd`, and `tests/cli.rs` containing `#[test] fn cli() { trycmd::TestCases::new().case("tests/cmd/*.toml").case("README.md"); }`.
- Any language: `scrut` (Markdown or `.t` files, `scrut test file.md`) or Python `cram` (`pip install cram`, `cram tests/*.t`).

## Minimal example
A cram or scrut file (`tests/basic.t`): commands indented with `$ `, expected output below, and `(re)` for a regex line.
```
  $ mytool --version
  mytool 1.2.3
  $ mytool add 2 3
  5
  $ mytool add x 3
  error: 'x' is not a number
  [2]
```
`[2]` is the expected exit status. Record the file by running the tool BEFORE changing it and reading the output yourself. Write error cases too: what the user sees when it fails is part of the contract. trycmd writes new expectations when run with `TRYCMD=overwrite`; use that only to accept an intended change.

## Run
`scrut test tests/basic.t` or `cram tests/basic.t` or `cargo test --test cli`

Passing looks like: a summary of passed tests and exit 0. Failure prints a diff of expected against actual output and exits 1.

## As a contract check
```json
{"id": "cli-transcripts", "claim": "CLI behaviour matches the recorded transcripts", "kind": "general", "rung": 4,
 "cmd": "cargo test --test cli", "expect": {"exit": 0, "stdout_contains": "test result: ok"}, "tier": "deep", "timeout_s": 600}
```

## What a pass does not prove
- Only the invocations recorded. A flag nobody wrote a case for is not covered.
- Transcripts record what the program printed, not what it should have printed. Review expected output as you would a spec.
- Overwrite modes pass anything; look at the `git diff` of the transcript files.
- Not run here (none of these tools is installed). The trycmd and scrut forms are from their READMEs; the `cram` syntax and the `[2]` exit-status line are from memory; test them on a trivial file first.
- Check the check: change an output string in the tool and confirm a diff.
