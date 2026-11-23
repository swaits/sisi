---
id: shellcheck
title: ShellCheck for shell scripts
answers: Do my shell scripts have quoting, word-splitting or portability bugs?
rung: 2
section: safety
languages: any
kinds: general
cost: low
detect: shellcheck --version
ran_here: yes
verified: ran
---

## Use when
- You wrote or changed any `.sh` script, CI step, git hook or `just` recipe body in bash.
- A script deletes, moves or loops over files, where an unquoted variable can be destructive.
- A script must run on more than one shell (`sh`, `dash`, `bash`).

## Do not use when
- The script is a few lines of fixed commands with no variables. Run it instead.
- You need to know the script produces the right result; ShellCheck cannot say so. Run it on test input.

## Set up
    shellcheck --version        # package manager: pacman -S shellcheck, apt install shellcheck

## Minimal example
`bad.sh`:

    #!/usr/bin/env bash
    for f in $(ls *.txt); do rm $f; done

## Run
    shellcheck --severity=warning --shell=bash bad.sh
    git ls-files '*.sh' | xargs -r shellcheck -x --severity=warning

Passing looks like: no output, exit 0. Failure here (run on this machine,
v0.11.0) prints `SC2045 (error): Iterating over ls output is fragile. Use globs.`
and exits 1. `-x` follows `source`d files. Pick the shell with `--shell` or a
`# shellcheck shell=bash` line, or the wrong dialect is checked. Fix the cause;
only disable a code with `# shellcheck disable=SC2034` plus a comment saying why.

## As a contract check
    {"id": "shellcheck", "claim": "All shell scripts pass ShellCheck at warning level", "kind": "general", "rung": 2, "cmd": "git ls-files '*.sh' | xargs -r shellcheck -x --severity=warning", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 120}

## What a pass does not prove
It checks syntax and well-known pitfalls only. `set -euo pipefail` mistakes,
logic errors, and wrong command arguments pass. Scripts without a `.sh`
extension or only a shebang (`bin/tool`) are skipped by the `git ls-files '*.sh'`
glob, so list them. A file full of `disable=` comments passes: grep the diff.
