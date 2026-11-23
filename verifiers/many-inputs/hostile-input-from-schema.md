---
id: hostile-input-from-schema
title: Hostile arguments generated from an API or tool schema
answers: Does every call my API or tool accepts survive wrong, missing, huge and strange arguments with a clean error and no crash?
rung: 2
section: many-inputs
languages: any
kinds: parsing, general
cost: medium
detect: python3 -c "import hypothesis_jsonschema"
ran_here: yes
verified: ran
---

## Use when

- A server, CLI or agent tool publishes a schema (JSON Schema, OpenAPI, MCP `tools/list`) for its inputs.
- A panic or internal error reachable by one request is a denial of service or loses data.
- You need to show that after hostile calls the server still serves and its data still reopens.

## Do not use when

- There is no schema; write one, or fuzz the raw handler with `cargo-fuzz` or `atheris`.
- You only care about valid calls: use ordinary tests.

## Set up

    pip install hypothesis hypothesis-jsonschema pytest

For each operation, generate valid arguments from its schema, then make them
hostile: wrong types, missing and extra fields, empty and huge strings, negative,
fractional and maximum numbers, control characters, absurd dates.

## Minimal example

    from hypothesis import given, settings, strategies as st
    from hypothesis_jsonschema import from_schema

    SCHEMA = {"type": "object", "required": ["cents", "memo"], "properties": {
        "cents": {"type": "integer", "minimum": 0}, "memo": {"type": "string"}}}

    def handle(args):                    # the thing under test: result or clean refusal
        if not isinstance(args, dict) or not isinstance(args.get("cents"), int) \
                or isinstance(args.get("cents"), bool) or args["cents"] < 0:
            return {"error": "invalid_arguments"}
        return {"ok": len(str(args.get("memo", "")))}

    hostile = st.one_of(
        from_schema(SCHEMA),
        st.recursive(st.none() | st.booleans() | st.integers() | st.floats() | st.text(),
                     lambda c: st.lists(c, max_size=3) | st.dictionaries(st.text(max_size=5), c, max_size=3)))

    @settings(max_examples=300)
    @given(hostile)
    def test_no_crash_clean_error(args):
        out = handle(args)               # any exception here is a failure
        assert "ok" in out or out.get("error")
        assert handle({"cents": 1, "memo": "x"}) == {"ok": 1}   # still serving afterwards

## Run

    python3 -m pytest -q test_hostile.py

Passing looks like: `1 passed`, exit 0. Failure shows the shrunk argument that raised or
got no clean answer.

## As a contract check

    {"id": "hostile-args", "claim": "no generated or mangled argument crashes the handler; each gets a result or a clean error", "kind": "parsing", "rung": 2, "cmd": "python3 -m pytest -q test_hostile.py", "expect": {"exit": 0, "stdout_contains": "passed"}, "tier": "deep", "timeout_s": 600}

## What a pass does not prove

- Only the shapes generated. A server whose crash needs a particular combination across fields or calls needs a stateful sequence (`stateful-model-test`).
- "Clean error" is whatever your assert accepts; define it (error code, no stack trace, no data change).
- Check after the hostile calls that the server still answers and the stored data reopens. One reference project's suite does both: every tool is called with hostile arguments, then a restarted server must still read the books.
- Check the check: add a deliberate crash on one input class (`cents` above 2**63) and see it found.
