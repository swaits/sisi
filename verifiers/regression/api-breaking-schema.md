---
id: api-breaking-schema
title: Breaking-change checks for protobuf, OpenAPI and GraphQL schemas
answers: Did my schema change break existing clients of this API?
rung: 4
section: regression
languages: any
kinds: general, migration
cost: low
detect: buf --version
ran_here: no
verified: docs
---

## Use when
- You edited a `.proto` file, an OpenAPI document or a GraphQL schema that other code or other teams consume.
- You must show a change is additive, not breaking.

## Do not use when
- The schema is internal and changes with all its users in one commit; a compile is enough.
- You need runtime behaviour: see `contract-testing-pact` in `real-world/`.

## Set up
- Protobuf: install `buf` (https://buf.build/docs/installation) and keep a `buf.yaml` at the module root.
- OpenAPI: install `oasdiff` (Go binary or Docker image).
- GraphQL: `npm i -D @graphql-inspector/cli graphql`.
Each tool compares the working tree to a known-good base: a git ref or a saved copy of the old schema.

## Minimal example
```sh
buf breaking --against '.git#branch=main'                       # protobuf, against the main branch
oasdiff breaking --fail-on ERR base/openapi.yaml openapi.yaml    # OpenAPI; first arg is the old spec
graphql-inspector diff base/schema.graphql schema.graphql       # GraphQL; reports breaking, dangerous, safe
```
Get the base BEFORE editing: `git show main:api/openapi.yaml > /tmp/base-openapi.yaml`. Use `--fail-on WARN` with oasdiff to also fail on risky changes. `buf` has rule sets (`FILE`, `PACKAGE`, `WIRE_JSON`, `WIRE`) set under `breaking:` in `buf.yaml`; pick the one that matches how clients are built.

## Run
Any of the commands above.

Passing looks like: no output and exit 0 from `buf breaking`; oasdiff exits 0 with no `error` lines; graphql-inspector says no breaking changes. Failure: buf prints `file:line:col:message` for each break and exits 100; oasdiff with `--fail-on ERR` exits 1 and lists each change with an id; graphql-inspector exits 1 on breaking changes.

## As a contract check
```json
{"id": "api-schema-compat", "claim": "The OpenAPI spec has no breaking changes against main", "kind": "general", "rung": 4,
 "cmd": "git show main:api/openapi.yaml > /tmp/base.yaml && oasdiff breaking --fail-on ERR /tmp/base.yaml api/openapi.yaml", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 120}
```

## What a pass does not prove
- Only the schema, not the server. A server can stop matching its own spec; test that separately (`contract-testing-pact`, schema-validating end-to-end tests).
- Semantics are invisible: renaming meaning without renaming a field passes.
- Not run here (the tools are not installed). `buf breaking --against` and `oasdiff breaking --fail-on ERR` are from their READMEs; the graphql-inspector command and buf's exit code 100 are from memory and should be checked with `--help`.
- Comparing to the wrong base (your own branch) always passes. Check the base is the released one.
- Check the check: remove a field in a scratch copy and confirm it reports a break.
