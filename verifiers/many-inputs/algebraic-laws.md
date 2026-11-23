---
id: algebraic-laws
title: Domain laws as properties (conservation, idempotence, commutativity, monotonicity)
answers: Do the rules my domain guarantees, such as debits equal credits, hold after any generated sequence of operations?
rung: 2
section: many-inputs
languages: any
kinds: money, state-machine, general
cost: low
detect:
ran_here: yes
verified: ran
---

## Use when

- The domain has laws that must always hold: debits equal credits, totals are conserved by transfers, applying an operation twice equals once, order of independent operations does not matter, a counter never goes down.
- Money, inventory, permissions, scheduling, any ledger-like state.
- You can name each law in one sentence. Each becomes one test, named for the law.

## Do not use when

- The law is only true for a subset of states you cannot generate; generate valid states first.
- You want to compare with another implementation: `differential-reference`.

## Set up

Write a generator for operations (or for valid starting states), apply them with
the real code, then check the law on the result. Keep money in integer cents.

## Minimal example (Python; a transfer ledger)

    from hypothesis import given, strategies as st

    def apply(balances, a, b, cents):              # under test
        out = dict(balances)
        if cents <= 0 or out.get(a, 0) < cents:
            return out                             # refused: nothing changes
        out[a] -= cents
        out[b] = out.get(b, 0) + cents
        return out

    names = st.sampled_from("abc")
    state = st.dictionaries(names, st.integers(0, 10**6))
    transfers = st.lists(st.tuples(names, names, st.integers(-5, 10**6)), max_size=30)

    @given(state, transfers)
    def test_conservation(s, ts):
        total = sum(s.values())
        for a, b, c in ts:
            s = apply(s, a, b, c)
            assert sum(s.values()) == total        # nothing created or destroyed
            assert all(v >= 0 for v in s.values()) # nobody goes negative

    @given(state, names, names, st.integers(1, 10**6))
    def test_refused_transfer_is_idempotent_noop(s, a, b, c):
        once = apply(s, a, b, c)
        assert apply(once, a, b, 10**9) == once    # an impossible transfer changes nothing

## Run

    python3 -m pytest -q test_laws.py

Passing looks like: `2 passed`, exit 0. Failure shows the shortest violating sequence.

## As a contract check

    {"id": "law-conservation", "claim": "transfers conserve the total and never overdraw", "kind": "money", "rung": 2, "cmd": "python3 -m pytest -q test_laws.py", "expect": {"exit": 0, "stdout_contains": "2 passed"}, "tier": "deep", "timeout_s": 300}

## What a pass does not prove

- Laws that hold are necessary, not sufficient: an implementation that does nothing conserves the total. Pair with `stateful-model-test` for what should have happened.
- The check holds only for generated states. If the generator never makes an overdrawn account or `a == b`, those cases are untested.
- Check the check: break the code (skip the debit, or credit twice) and see the right law fail.
