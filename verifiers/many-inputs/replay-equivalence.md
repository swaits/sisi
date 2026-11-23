---
id: replay-equivalence
title: Replay equivalence for event-sourced and journalled state
answers: Is the live state exactly what you get by replaying the log from scratch, and does a refused command leave no trace?
rung: 2
section: many-inputs
languages: any
kinds: state-machine, money
cost: medium
detect:
ran_here: yes
verified: ran
---

## Use when

- State is built from a log of events or journal lines (event sourcing, write-ahead logs, ledgers, undo stacks).
- Restart, backup restore and replication rebuild state by replay, so any drift between live and replayed state is data loss waiting to happen.
- Commands can be refused (validation, closed period, limits).

## Do not use when

- State is stored directly and no log exists. Use `fault-injection-storage` and `round-trip`.

## Set up

Expose two things: a way to apply a command (which may append to the log and
change live state) and a way to build state from the log alone. Drive both with
random command sequences, including commands that must be refused.

## Minimal example (Python)

    from hypothesis import given, strategies as st

    class Store:
        def __init__(self): self.log, self.balance = [], 0
        @staticmethod
        def fold(log):                                  # state from the log alone
            b = 0
            for kind, n in log:
                b += n if kind == "dep" else -n
            return b
        def command(self, kind, n):
            if n <= 0 or (kind == "wd" and n > self.balance):
                return "refused"
            self.log.append((kind, n))
            self.balance += n if kind == "dep" else -n
            return "ok"

    cmds = st.lists(st.tuples(st.sampled_from(["dep", "wd"]), st.integers(-3, 50)), max_size=40)

    @given(cmds)
    def test_live_equals_replay_and_refusals_leave_no_trace(commands):
        s = Store()
        for kind, n in commands:
            log_before, state_before = list(s.log), s.balance
            if s.command(kind, n) == "refused":
                assert s.log == log_before             # nothing written
                assert s.balance == state_before       # nothing changed
            assert s.balance == Store.fold(s.log)      # live == replay, after every command

## Run

    python3 -m pytest -q test_replay.py

Passing looks like: `1 passed`, exit 0. Failure shows the shortest command list where live
and replayed state differ, or where a refusal wrote something.

## As a contract check

    {"id": "replay-equivalence", "claim": "live state equals state replayed from the log after any command sequence, and refused commands change nothing", "kind": "state-machine", "rung": 2, "cmd": "python3 -m pytest -q test_replay.py", "expect": {"exit": 0, "stdout_contains": "passed"}, "tier": "deep", "timeout_s": 300}

## What a pass does not prove

- Replay may use the same code as the live path, and then agrees trivially. Make replay a separate, simpler fold, or replay through the persisted bytes (write the log, reopen, compare).
- Compare everything observable (balances, indexes, derived reports), not one number; a field left out hides drift.
- Include refused commands in the generator, or the "no trace" half is never tested. Count how many were refused.
- Check the check: make a refused command append to the log, or make replay skip one event type, and see it fail.
