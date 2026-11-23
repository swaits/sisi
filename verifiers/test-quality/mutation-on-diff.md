---
id: mutation-on-diff
title: Mutation testing only on the lines a change touched
answers: Do my tests catch wrong versions of the exact code I just changed?
rung: 2
section: test-quality
languages: rust, javascript, typescript, python, any
kinds: general, money, parsing
cost: low
detect: cargo mutants --version
ran_here: yes
verified: ran
---

## Use when
- You changed a handful of functions and a full mutation run (hours) does not fit in one task.
- You want a gate in a pull request: new or changed logic must have tests that can fail.
- It is a check on other checks, so it is rung 2 like the full run, but over a smaller area.

## Do not use when
- The change deletes code or only edits tests; there is nothing to mutate in a diff of removed lines.
- You need the whole-codebase mutation score. A diff run says nothing about untouched code, and an edit in one place can weaken the tests of another; run the full tool on a schedule.

## Set up
Rust, with cargo-mutants (ran 27.1.0): `--in-diff <file>` restricts mutants to lines in a unified diff. The diff must name files with `a/` and `b/` prefixes (or none). If your git config sets `diff.mnemonicPrefix`, the prefixes become `i/` and `w/` and cargo-mutants matches nothing: it prints `No mutants to filter` and exits 0. Force the prefixes:

    git diff --src-prefix=a/ --dst-prefix=b/ main...HEAD > /tmp/change.diff

Other tools: StrykerJS takes `--mutate "src/file.js:10-40"` line ranges, so generate them from the diff yourself; Stryker.NET has a `--since` option (not confirmed here); mutmut can target names, `mutmut run "module.function*"`; PIT has an SCM goal (see `pitest`; not confirmed).

## Minimal example
`price` has full tests; a new `shipping` function was added with none.

    pub fn shipping(weight: u32) -> u32 { if weight > 5 { 500 } else { 100 } }

## Run
    git diff --src-prefix=a/ --dst-prefix=b/ > change.diff
    cargo mutants --in-diff change.diff

Passing looks like: `N mutants tested: N caught`, exit 0. Failure: `MISSED src/lib.rs:15:49: replace > with == in shipping`, exit 2. In my run 5 of 5 mutants on the new function were missed; the old function's mutants were not run. Check the count: `cargo mutants --list --in-diff change.diff` must be non-empty, or the check is vacuous.

## As a contract check
    {"id": "mutants-on-diff", "claim": "Tests catch mutants of every line changed against main", "kind": "general", "rung": 2, "cmd": "git diff --src-prefix=a/ --dst-prefix=b/ main...HEAD > /tmp/c.diff && test -s /tmp/c.diff && cargo mutants --in-diff /tmp/c.diff", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 1800}

## What a pass does not prove
- Only changed lines were mutated. The rest of the code is untested by this check.
- Non-Rust files, and changes with no mutable code (config, comments, test-only edits), produce zero mutants and so pass. Assert a non-zero mutant count in the contract when the task is meant to change logic.
- The same limits as the full run apply: equivalent mutants, and tests that pass for the wrong reason.
- Check the check: break a changed line in a harmless way and confirm the run fails.
