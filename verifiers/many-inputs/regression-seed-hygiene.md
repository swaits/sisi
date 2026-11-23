---
id: regression-seed-hygiene
title: Keeping failing seeds checked in, replayed and never orphaned
answers: Once a random test or fuzzer found a bug, is that exact input still replayed on every run so the bug cannot return?
rung: 2
section: many-inputs
languages: any
kinds: general, parsing, state-machine
cost: low
detect:
ran_here: yes
verified: ran
---

## Use when

- You use proptest, Hypothesis, fast-check, a fuzzer or rapid, and a failure has been found, or will be.
- A random test went red once and green on re-run, and nobody recorded why.
- You are finishing a bug fix found by a random or fuzz test.

## Do not use when

- The suite has only fixed example tests; those already replay.

## Set up

Know where each tool keeps failures, and commit those:

- proptest: `proptest-regressions/*.txt` (or `*.proptest-regressions` beside the test file); the path is printed on failure.
- cargo-fuzz: `fuzz/artifacts/<target>/crash-*`; copy fixed cases to `fuzz/seeds/<target>/`.
- Go native fuzzing: `testdata/fuzz/FuzzName/<hash>`; plain `go test` replays them.
- Hypothesis: `.hypothesis/` is local; pin the minimal case with `@example(...)` in the test.
- fast-check: pass `{ seed, path }` to reproduce, or add `examples: [[...]]` to keep it.

## Minimal example (Hypothesis: pin the shrunk failure)

    from hypothesis import given, example, strategies as st

    def parse_amount(s):
        return int(s.replace(",", ""))     # fixed: used to reject "1,000"

    @given(st.integers(0, 10**9).map(lambda n: f"{n:,}"))
    @example("1,000")                      # the case the fuzzer found; stays forever
    def test_parse_amount(text):
        assert parse_amount(text) == int(text.replace(",", ""))

A cheap guard that none are orphaned (a deleted test leaves its seed file behind):

    # check_seeds.sh: every seed file maps to an existing test file
    for f in proptest-regressions/*.txt; do
      t=$(basename "$f" .txt); [ -e "src/$t.rs" ] || [ -e "tests/$t.rs" ] || { echo "orphaned: $f"; exit 1; }
    done

## Run

    python3 -m pytest -q test_amount.py
    sh check_seeds.sh

Passing looks like: `1 passed`, exit 0, and no `orphaned:` line. A removed pin makes
the pinned case vanish silently, so review diffs of `@example` and seed files.

## As a contract check

    {"id": "seeds-replayed", "claim": "every saved failing input is replayed and no seed file is orphaned", "kind": "general", "rung": 2, "cmd": "python3 -m pytest -q test_amount.py && sh check_seeds.sh", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 300}

## What a pass does not prove

- Replay proves the old bug is not back, not that the area is clean.
- A seed recorded for an old test shape may no longer reach the same code after a refactor (proptest seeds depend on the strategy); for important bugs also add a plain named example test.
- Check the check: revert the fix and confirm the pinned or saved case fails by itself, with random generation turned off (`derandomize=True`, or a replay of only the seed file).
