---
id: check-the-checker
title: Plant a known bug to confirm the verification pipeline catches it
answers: If the code were wrong, would my whole verification pipeline actually report it?
rung: 2
section: test-quality
languages: any
kinds: general, concurrency, money, parsing
cost: low
detect: git --version
ran_here: yes
verified: ran
---

## Use when
- You wrote a new gate, contract check, CI job or script and want to know it can fail.
- A gate has passed for a long time and you have never seen it red.
- You changed the toolchain, a flag or an environment, and the pass might now be vacuous.

This is a check on another check; mutation testing is the automated form of it for unit tests. A planted bug (a canary) proves one specific path through the pipeline, so it adds rung 2 confidence in that gate.

## Do not use when
- You can run a mutation tool over the area: it plants many bugs and reads the result for you.
- The pipeline touches shared or production systems. Plant the bug only in a local copy.

## Set up
Work in a throwaway branch, worktree or copy so the bug cannot be committed. Choose a canary that the gate is meant to catch: flip a comparison, return a constant, drop a validation, swap two arguments, remove a lock. Keep it small and obvious.

    git worktree add /tmp/canary HEAD && cd /tmp/canary

## Minimal example
Gate: `cargo test price`. Canary: change `qty >= 10` to `qty > 10`.

    sed -i 's/qty >= 10/qty > 10/' src/lib.rs
    cargo test price; echo "exit=$?"      # must be non-zero

Better, keep a permanent canary: a test marked `#[should_panic]` or a script that deliberately feeds a known-bad input into the gate and asserts the gate rejects it (for example, a linter fixture with a known violation, which the lint must flag).

## Run
Run the full gate, not just the unit test, with the bug in place: the same command the contract uses.

Passing looks like: the gate fails, naming the canary (the right test, the right message). Failure of the pipeline: it exits 0 with the bug in place. Then restore the file (`git checkout -- src/lib.rs`, or remove the worktree) and confirm the gate passes again.

## As a contract check
    {"id": "canary", "claim": "The gate fails when a known bug is planted and passes when it is removed", "kind": "general", "rung": 2, "cmd": "sed -i 's/qty >= 10/qty > 10/' src/lib.rs && ! cargo test price; r=$?; git checkout -q -- src/lib.rs; test $r -eq 0 && cargo test price", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 600}

The contract above edits the working tree and restores it with `git checkout`. Do not run it with uncommitted changes in that file.

## What a pass does not prove
- That the gate catches other bugs. One canary shows one path; plant several kinds (value, boundary, state, concurrency).
- A canary that is too blatant is caught by anything. Make it realistic for the change.
- It must fail for the right reason. Read the failure output; a compile error from your sed is not a catch.
- Always revert the canary. A forgotten planted bug is worse than no check.
