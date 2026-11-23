---
id: docs-change
title: Changing documentation
applies_to: README files, guides, API docs, comments meant to be read, and runbooks.
---

## Done means
- Every command, snippet and path in the text runs or exists as written, on a clean machine.
- Every link and cross-reference resolves.
- The text matches what the code does now; claims about behaviour were checked against the code or a run.
- It answers the question its reader brings, in the order they need, and says what it does not cover.
- Nothing else changed: no code or contract edit rode along.
- Examples contain no real secrets, and no private names.

## Checks
- Runs and links: `doc-tests-and-links` (real-world), rung 3; `cli-transcript-tests` for shown output.
- True to the code: `acceptance-examples` (intent) for stated behaviour; `golden-files-hand-verified` for output shown.
- Quality: `rubric-judge` (intent), rung 5, with a different model family; `pairwise-comparison` against the old text.
- Scope: `feedback-as-amendment` (intent) for the diff.
- Safety: `secret-scanning`, `shellcheck` for shell snippets (safety).
- Complete: `no-stubs-scan` for TODO and "coming soon", `requirement-to-check-map` if the doc has a spec (completeness).

## Common false finishes
- Snippets were written, not run; one has a typo or a removed flag.
- The docs describe the plan or the old behaviour, not the code.
- Links were checked before files were renamed.
- A new feature is documented in one place; two older pages still say the opposite.
- Output shown was typed, not copied from a run.
- The docs are accurate for the author's machine; a path or tool is not there elsewhere.
- Placeholder text ("TBD", "lorem") remains.
- The human asked for a fix to one section and the whole page was rewritten.
