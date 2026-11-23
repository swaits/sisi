---
id: round-trip
title: Round-trip properties for encode/decode, serialise/parse and do/undo
answers: Does undoing an operation always return exactly what I started with, for every input I can generate?
rung: 2
section: many-inputs
languages: any
kinds: parsing, general, money
cost: low
detect:
ran_here: yes
verified: ran
---

## Use when

- A serialiser and a parser, an encoder and a decoder, a compressor and decompressor, or a do and an undo operation exist.
- Data is saved and reloaded (files, wire formats, journal lines, backups).
- You want a cheap check that loses no information, with no oracle needed.

## Do not use when

- The encoding is lossy by design; test the part that must survive instead.
- Only one direction exists; use `metamorphic` or `algebraic-laws`.

## Set up

Generate values of the in-memory type (not strings of the encoded form), encode,
decode, compare. Also test the other direction where it matters: for any text
the parser accepts, encoding the parsed value gives the canonical text again.

## Minimal example (Python; JSON of integer cents)

    import json
    from hypothesis import given, strategies as st

    entry = st.fixed_dictionaries({
        "memo": st.text(max_size=40),
        "cents": st.integers(-2**63, 2**63 - 1),
        "tags": st.lists(st.text(max_size=8), max_size=5),
    })

    @given(entry)
    def test_value_round_trip(e):
        assert json.loads(json.dumps(e)) == e

    @given(entry)
    def test_text_is_stable(e):
        text = json.dumps(e, sort_keys=True)
        assert json.dumps(json.loads(text), sort_keys=True) == text

## Run

    python3 -m pytest -q test_round_trip.py

Passing looks like: `2 passed`, exit 0.
Failure shows the shrunk value that came back changed, exit 1.

## As a contract check

    {"id": "round-trip-entry", "claim": "entries survive serialise then parse unchanged", "kind": "parsing", "rung": 2, "cmd": "python3 -m pytest -q test_round_trip.py", "expect": {"exit": 0, "stdout_contains": "2 passed"}, "tier": "deep", "timeout_s": 300}

## What a pass does not prove

- It shows no loss, not that the encoding is right: a format that stores the wrong thing round-trips perfectly. Add a golden file or reference parser for the format itself.
- It only covers values the generator makes. Give it the awkward ones: empty, maximum, negative, non-ASCII, a trailing newline, NaN if floats are allowed.
- Equal after the round trip can hide equality that is too loose (`1 == 1.0`, `0 == -0.0`); compare types and canonical text too.
- Check the check: drop a field from the encoder and see the test fail.
