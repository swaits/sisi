---
id: annotation-behaviour-check
title: Verifying that declared properties (read-only, idempotent) hold in behaviour
answers: Does every tool marked read-only or idempotent really behave that way?
rung: 3
section: real-world
languages: any
kinds: general, state-machine
cost: medium
detect:
ran_here: yes
verified: ran
---

## Use when
- A tool, API method or command declares a property an agent will rely on: MCP `readOnlyHint`, `idempotentHint`, `destructiveHint`, an HTTP `GET` that must be safe, a "dry run" flag.
- You add or change such a tool. A false `readOnlyHint` makes an agent call a destructive tool freely.

## Do not use when
- Nothing relies on the declaration.

## Set up
Build a fixture with data in every table or file the tools can touch. Write a snapshot function for the whole data area (paths, sizes, hashes; see `read-only-guarantee`). Get the tool list and its annotations from the running server (`tools/list` in MCP), and iterate over it so new tools are covered by default.

## Minimal example
```python
# pseudo-code for a test loop; a reference project does this for every tool in tools/list
for tool in server.list_tools():
    for args in sample_arguments(tool):                  # valid calls plus refused ones
        before = snapshot(data_dir)
        result = server.call(tool.name, args)
        after = snapshot(data_dir)
        if tool.annotations.get("readOnlyHint"):
            assert before == after, f"{tool.name} {args} changed data"       # success or refusal
        if tool.annotations.get("idempotentHint") and not result.is_error:
            server.call(tool.name, args)
            assert snapshot(data_dir) == after, f"{tool.name} is not idempotent"
```
Check both outcomes: a refused call must also leave data unchanged. Exclude only files that legitimately change (SQLite `-wal` and `-shm` files change on read; compare database contents by a digest instead). A second assertion belongs here: a tool that does change data must not be marked read-only, so also assert that at least one tool carries `readOnlyHint: false` and that each such tool's sample call changes something; otherwise the loop may be testing nothing.

## Run
Your test command, for example `cargo test --test spec_mcp`.

Passing looks like: all tools pass and the log says how many read-only calls ran and that each changed nothing. Failure names the tool, the arguments and the changed file.

## As a contract check
```json
{"id": "annotations-true", "claim": "Every tool marked read-only leaves data unchanged, success or refusal", "kind": "general", "rung": 3,
 "cmd": "cargo test --test spec_mcp readonly", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 900}
```

## What a pass does not prove
- Only the argument samples used. A tool that writes on a rare path (a cache miss, a quota reset) passes unless the samples reach it.
- A declared property outside the data you snapshot (network calls, email) is not checked. Say which areas are covered.
- The check ran here only in miniature (the snapshot comparison from `read-only-guarantee`); the loop above is the pattern from the reference project, not a tool you can install.
- Check the check: make one read-only tool touch a file and confirm the loop catches it.
