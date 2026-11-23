---
id: size-budget
title: Binary and bundle size budgets
answers: Did my change make the binary, package or JavaScript bundle bigger than it is allowed to be?
rung: 4
section: regression
languages: any
kinds: general, ui
cost: low
detect:
ran_here: yes
verified: ran
---

## Use when
- You add a dependency, enable a feature or change build settings, and size matters (download size, page weight, embedded targets).
- You were told "keep it small" and need a number that says so.

## Do not use when
- Size is irrelevant to the user. A budget nobody cares about gets bumped without thought.
- You are comparing builds with different compilers or flags; compare like with like.

## Set up
Decide the budget as a number with a reason, and write it in a file under version control, not in the check command. Measure the build output the user receives (the stripped release binary, the gzipped bundle).
Tools: `size-limit` (npm) for bundles, `cargo bloat` for Rust binary attribution, or plain `stat` and `wc`.

## Minimal example
```sh
cargo build --release --locked
size=$(stat -c %s target/release/mytool)        # GNU stat; on macOS use: stat -f %z
budget=$(cat tests/size-budget.txt)             # e.g. 8000000
[ "$size" -le "$budget" ] || { echo "size $size > budget $budget"; exit 1; }
```
For JavaScript: `gzip -c dist/app.js | wc -c`, or `npx size-limit` with limits in `package.json` under `"size-limit"`. Record the size BEFORE the change (`echo $size > /tmp/before`) so a failure can name the growth in bytes, and so you can see how close you already were.

## Run
The script above.

Passing looks like: no output and exit 0. Failure prints `size N > budget M` and exits 1.

## As a contract check
```json
{"id": "size-budget", "claim": "The release binary is within its size budget", "kind": "general", "rung": 4,
 "cmd": "cargo build --release --locked && test $(stat -c %s target/release/mytool) -le $(cat tests/size-budget.txt)", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 900}
```

## What a pass does not prove
- Only the artifact size. It says nothing about start-up time, memory or what was added.
- Raising the number in `tests/size-budget.txt` makes any failure pass. A reviewer should see that file's diff with a reason.
- Different build settings (debug versus release, stripped or not) change size a lot; run the same profile as the budget was set with.
- Check the check: set the budget one byte below the real size and confirm exit 1 (the shell test was run here with exactly this).
