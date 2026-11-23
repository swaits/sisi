---
id: perf-regression
title: Performance regression checks with an explicit budget (criterion, hyperfine, iai-callgrind)
answers: Did my change make this code or command measurably slower than before?
rung: 4
section: regression
languages: rust, any
kinds: general
cost: medium
detect: hyperfine --version
ran_here: no
verified: docs
---

## Use when
- You changed a hot path or are asked to "optimise", and need evidence of faster or not slower.
- A command's run time has a limit users depend on.

## Do not use when
- Timing noise exceeds the effect you care about and you cannot reduce it (shared CI runners). Count instructions instead (iai-callgrind) or measure memory or allocations.
- The claim is about correctness; speed says nothing about that.

## Set up
- Rust micro-benchmarks: `cargo add --dev criterion`, add `[[bench]] name = "b" harness = false`, put the benchmark in `benches/b.rs`.
- Whole commands: `hyperfine` (https://github.com/sharkdp/hyperfine).
- Low-noise Rust: `iai-callgrind` counts instructions with valgrind (Linux, needs valgrind installed).

## Minimal example
Baseline BEFORE editing, compare after, on the same machine, with nothing else running.
```sh
cargo bench --bench b -- --save-baseline main      # before the change
cargo bench --bench b -- --baseline main           # after: prints "change: [...]" and a verdict
hyperfine --warmup 3 --runs 20 --export-json after.json './mytool big.csv'
```
A budget is an explicit number. Criterion and hyperfine do not fail on a regression, so read the numbers: with `jq` take `.results[0].mean` (seconds) from the hyperfine JSON and fail if it exceeds the budget.
```sh
jq -e '.results[0].mean < 0.50' after.json     # exit 1 when the mean is not under 0.5 s
```
Handle noise: warm-up runs, at least 10 runs, compare the median or min rather than the mean, repeat a failing run once, and record the machine. For a Rust gate that does not depend on timing, iai-callgrind can fail on an instruction-count increase (its regression option, see its README; not run here).

## Run
The commands above.

Passing looks like: criterion ends `No change in performance detected.` (here: `change: [-1.2% -0.3% +0.5%] (p = 0.53 > 0.05)`), and `jq -e` exits 0. A real slowdown prints `Performance has regressed.`; criterion still exits 0, so a contract must parse it or use the `jq` budget.

## As a contract check
```json
{"id": "perf-budget", "claim": "mytool processes big.csv in under 0.5 s mean", "kind": "general", "rung": 4,
 "cmd": "hyperfine --warmup 3 --runs 20 --export-json /tmp/h.json './mytool big.csv' && jq -e '.results[0].mean < 0.50' /tmp/h.json", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 300}
```

## What a pass does not prove
- Timing depends on the machine; a budget set on a laptop may fail on CI. Record where it was set.
- A benchmark measures the inputs you chose, not production load. Optimised-away work (`black_box` missing) gives fake speed.
- Criterion `--save-baseline`/`--baseline` ran here (exit 0 and `No change` confirmed). hyperfine and iai-callgrind were not installed: `--warmup` and `--runs` are in the hyperfine README; `--export-json` is from memory, check `hyperfine --help`.
- Check the check: add a sleep and confirm the budget fails.
