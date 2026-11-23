---
id: cli-tool
title: Building or changing a command-line tool
applies_to: A program run from a shell, with arguments, standard input and output, and exit codes.
---

## Done means
- Every command and flag in the help text works as described, and the help matches what the code does.
- The exit code is 0 only on success and a stable non-zero on each kind of failure; errors go to standard error, results to standard output.
- Bad input (missing file, bad flag, empty input, huge input, a broken pipe) gives a clear message and no stack trace or partial output file.
- Output is stable and machine-readable where scripts depend on it, and pinned by tests.
- It installs and runs from a clean checkout or the built package on a machine that is not the author's.
- It does not print or store secrets, and does not touch files it was not asked to.

## Checks
- Behaviour by transcript: `cli-transcript-tests` (real-world), rung 3 to 4, including exit codes and standard error.
- Output format: `golden-files-hand-verified`, `snapshot-insta` (regression), rung 4.
- Bad input: `hostile-input-from-schema`, `cargo-fuzz` or `atheris` (many-inputs), rung 2.
- Public contract: `api-breaking-schema` (regression) for flags and output fields.
- Install: `clean-clone-build`, `packaging-install-upgrade`, `cross-platform-matrix` (real-world).
- Scripts: `shellcheck` (safety). Secrets: `sensitive-data-leak-test`.
- Done: `single-gate-command`, `no-stubs-scan` (completeness).

## Common false finishes
- Tested by calling the internal function, not the binary. Flag parsing, defaults and exit codes are untested.
- Exit code is 0 after an error was printed.
- Errors and results both go to standard output, which corrupts pipelines.
- The tool works in a terminal and breaks when output is piped (colour codes, prompts, width detection).
- Paths with spaces, relative paths, and a non-existent directory were never tried.
- The help text was not updated after a flag changed.
- A file is half-written when the program fails; no atomic write.
- Passing on Linux only when the user is on another system.
