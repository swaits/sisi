---
id: agent-surface-evals
title: Scripted agent transcripts played against the real tool server
answers: Can an agent finish the job by following only what the tool itself tells it to do next?
rung: 3
section: real-world
languages: any
kinds: general, state-machine
cost: high
detect:
ran_here: no
verified: docs
---

## Use when
- You build or change a tool that AI agents call: an MCP server, a CLI an agent drives, an API with guidance in its responses.
- The tool's responses carry guidance ("next steps", error hints) and you want it proved to be enough, with no model involved.

## Do not use when
- The tool is only used by humans. Use `cli-transcript-tests`.
- You want to measure a particular model's skill; this check uses no model and proves only that a path exists.

## Set up
Write transcripts as data files (JSON), one per journey. A transcript is `{ "description", "settings", "setup": [...], "steps": [...] }`. `setup` calls are made directly (the chart and the books an agent finds on arrival; they are not the agent's moves) and may save values with `"save": {"x": "/pointer"}`. Write a small runner that starts the real server (a temporary data directory, a real socket or stdio), plays the steps, and fails when a step's tool is not in the previous result's next steps. The reference project does exactly this in `crates/app-cli/tests/agent_evals.rs`, with six transcripts in `crates/app-cli/tests/agent_evals/*.json`; the test asserts the exact list of transcript names, so a deleted transcript fails.

## Minimal example
Trimmed from the reference project's `onboarding_to_first_post.json`:
```json
{ "description": "A new book: onboarding to the first account, following only next_steps.",
  "steps": [
    { "call": "books.start", "args": { "agent": { "model": "scripted", "reasoning_effort": "none", "harness": "agent_evals" } } },
    { "expect": { "/state": "needs_onboarding" } },
    { "expect_next_steps_contains": "books.set_setting" },
    { "follow": "books.set_setting", "with": { "changes": [{ "key": "company.name", "value": "Eval Co" }], "decided_by": "Avery Quill" } },
    { "expect_next_steps_contains": "books.add_account" },
    { "follow": "books.add_account", "with": { "code": "1000", "name": "Cash", "account_type": "asset" } } ] }
```
The step forms in the reference runner: `call` (first step only, and only `books.start`), `follow` (the previous result's `next_steps` must name that tool; its `args` are used with `with` laid over them, so `with` supplies only what an agent decides: an amount, a date), `follow_prompt` (the previous result must name that prompt), `expect_next_steps_contains` and `expect` (JSON-pointer equality on the previous result). The runner panics on any other step. The tool names above belong to that project's server; use your own server's.
Add the cases agents get wrong: a refused call must say what to do instead, and the transcript then follows that advice.

## Run
Your test command; the reference project's is `cargo test -p app-cli --test agent_evals`. The test function plays every file, and asserts that each transcript called at least one tool after the start.

Passing looks like: `test result: ok` for `agent_evals_follow_only_next_steps`. Failure names the step, for example `"onboarding step 3: books.add_account is not in the previous result's next_steps: [...]"`, or `was refused` when the call itself errored.

## As a contract check
```json
{"id": "agent-evals", "claim": "An agent can complete each journey by following the tool's own next steps", "kind": "general", "rung": 3,
 "cmd": "cargo test -p app-cli --test agent_evals", "expect": {"exit": 0, "stdout_contains": "test result: ok"}, "timeout_s": 900, "tier": "deep"}
```

## What a pass does not prove
- That a model will actually choose those steps; it proves they exist and are enough.
- Only the journeys scripted. Add one for each reported agent failure.
- Not run here. `verified: docs` means checked against the reference project's runner source and transcripts (this entry describes that pattern; the runner is specific to its server).
- The reference runner has no explicit "end state" step: a transcript ends where its last `expect` lines say, so give every transcript a final `expect` on the result that proves the journey finished.
- A transcript with no `expect` lines proves only that calls did not error. Assert on content.
- Check the check: edit the server's next steps to name a wrong tool and see a transcript fail.
