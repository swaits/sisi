---
id: differential-old-vs-new
title: Differential testing of new code against the previous version
answers: Did my refactor or rewrite keep the behaviour of the old code on inputs I did not think of?
rung: 2
section: many-inputs
languages: any
kinds: general, parsing, money, migration
cost: medium
detect:
ran_here: yes
verified: ran
---

## Use when

- You are refactoring, optimising or rewriting code whose behaviour must not change.
- The old version is trusted by its users, even if not proved.
- You can keep both versions side by side for the length of the change (old copy in the test tree, a tagged release, or a git worktree of the old commit).

## Do not use when

- The behaviour is meant to change. Then compare only the parts that must not change, or use `metamorphic`.
- The old version has known bugs you do not want to keep; agreement would preserve them. Record the known differences explicitly.

## Set up

Freeze the old implementation as a module the test can import (copy it as
`old_impl.py`, or build the old commit in a worktree and call it as a program).
Delete the copy when the change is merged and its job is done.

## Minimal example (Python; a faster word counter against the original)

    from collections import Counter
    from hypothesis import given, strategies as st

    def old_count(text):                           # frozen original
        counts = {}
        for w in text.split():
            counts[w] = counts.get(w, 0) + 1
        return counts

    def new_count(text):                           # rewrite under test
        return dict(Counter(text.split()))

    @given(st.text(alphabet=" \n\tab é", max_size=200))
    def test_new_matches_old(text):
        assert new_count(text) == old_count(text)

## Run

    python3 -m pytest -q test_old_vs_new.py

Passing looks like: `1 passed`, exit 0.
Failure prints the shrunk input and both outputs, exit 1.

## As a contract check

    {"id": "refactor-same-behaviour", "claim": "new_count returns what the old implementation returned on generated text", "kind": "general", "rung": 2, "cmd": "python3 -m pytest -q test_old_vs_new.py", "expect": {"exit": 0, "stdout_contains": "passed"}, "tier": "deep", "timeout_s": 300}

## What a pass does not prove

- It compares outputs on generated inputs only. Side effects (files, logs, timing) are not compared unless you read them back.
- The alphabet decides what is tried: include the awkward characters, empty input and very large ones. In the example, a non-breaking space is the kind of case that separates `split()` rewrites.
- Errors count too: compare raised exceptions and messages, not only returned values.
- Check the check: change the new code by one character and confirm the test fails.
