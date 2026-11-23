---
id: baseline-before-change
title: Record what works before you touch it, then compare
answers: Did my change leave everything that already worked exactly as it was?
rung: 4
section: regression
languages: any
kinds: general, ui, migration
cost: low
detect:
ran_here: yes
verified: ran
---

## Use when
- You are about to edit something that already works and the task says "improve", "fix", "refactor" or "tidy".
- Feedback on a change is ambiguous. A baseline lets you show what you changed instead of guessing what was meant.
- No automated test covers the area you are about to touch.

## Do not use when
- The thing is new, so there is nothing to preserve. Use an example test or a property test instead.
- The output is noisy (timestamps, random ids) and you have not yet fixed the noise; the comparison will fail for the wrong reason.

## Set up
1. Before the first edit, run the command that produces the observable output (a test run, a CLI call, a page render, a query).
2. Save the output as files in the repo (`tests/baseline/`) and commit or at least `git add` them. Say in the commit message that the files are the baseline.
3. Write one command that regenerates the output and diffs it against the saved files.

## Minimal example
```sh
mkdir -p tests/baseline
./mytool report --fixture tests/fixtures/small.csv > tests/baseline/report.txt   # BEFORE editing
git add tests/baseline && git commit -m "baseline before change"
# ... edit code ...
./mytool report --fixture tests/fixtures/small.csv | diff -u tests/baseline/report.txt -
```
If the change is meant to alter some of the output, update only those lines, and make the diff show nothing else.

## Run
`./mytool report --fixture tests/fixtures/small.csv | diff -u tests/baseline/report.txt -`

Passing looks like: no output and exit status 0. Failure shows as a unified diff and exit status 1.

## As a contract check
```json
{"id": "baseline-report", "claim": "The report output is unchanged except for the intended lines", "kind": "general", "rung": 4,
 "cmd": "./mytool report --fixture tests/fixtures/small.csv | diff -u tests/baseline/report.txt -",
 "expect": {"exit": 0}, "timeout_s": 60}
```

## What a pass does not prove
- It proves only that the output is the same as before, not that the baseline was right. If the baseline was captured from broken code, the check protects the bug.
- It covers only the inputs you captured. Choose inputs that exercise the parts you will touch.
- A baseline captured after the first edit is worthless. Check `git log` order: the baseline commit must come first.
- To check the check can fail: change one character in the code and see the diff appear.
- This is rung 4 at best. It detects change, it does not judge quality.
