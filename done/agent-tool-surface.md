---
id: agent-tool-surface
title: Tools, commands or an interface designed for AI agents
applies_to: An MCP server, a CLI, or a set of functions an AI agent calls, including their names, descriptions, inputs and outputs.
---

## Done means
- Each tool has a clear name and a description that says what it does, when to use it, what it will not do, and what it returns; an agent picks the right tool from the text alone.
- Inputs are validated with clear, fixable error messages, and unsafe or destructive actions need an explicit step.
- Annotations (read-only, destructive, idempotent) match what the tool actually does.
- Outputs are small, stable and structured; they do not overflow an agent's context or leak secrets.
- Real agents, given realistic tasks, complete them through the tools with few wrong calls.
- Dangerous sequences (call order, repeated calls) are safe.

## Checks
- Task success: `agent-surface-evals` (real-world), rung 3 to 5, with tasks, a hidden answer, and a count of wrong or wasted calls.
- Descriptions: `tool-description-lint`, `rubric-judge` (intent) by a different model family.
- Annotations true: `annotation-behaviour-check` (real-world), rung 3; `read-only-guarantee` (regression).
- Bad input and injection: `hostile-input-from-schema` (many-inputs); `threat-model-checklist`, `sensitive-data-leak-test` (safety).
- Surface stability: `api-breaking-schema` (regression); `baseline-before-change`.
- Domain results: `acceptance-examples`, `domain-evidence-report` (intent).

## Common false finishes
- The tool works when called by the test that wrote it; no agent has ever tried it.
- The description was written from the implementation, not tested for how an agent reads it; two tools sound alike and agents pick the wrong one.
- A tool marked read-only writes (a cache, a log, a lock). Check against the file system.
- Output is a wall of text that fills the agent's context; there is no limit or paging.
- Error messages say "invalid input" without saying which field or what would be valid.
- The evals use the same model that wrote the tools, or the author's wording of the tasks.
- A secret appears in an error or log that the agent reads.
- A destructive tool can be called with defaults and no confirmation.
