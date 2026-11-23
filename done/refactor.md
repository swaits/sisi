---
id: refactor
title: Refactoring
applies_to: Changing the structure of code without changing what it does.
---

## Done means
- Behaviour is identical for every input that mattered before: same outputs, same errors, same side effects, same public interface.
- Evidence of that was captured before the first edit, then compared after.
- No behaviour change is hiding in the diff (a "small fix" while there).
- The structure really got better in the way the request named (smaller, fewer dependencies, one place for a rule), and that can be measured.
- Performance and size did not get worse beyond what was agreed.

## Checks
- Same behaviour on many inputs: `differential-old-vs-new` (many-inputs), rung 2, the strongest; run old and new on the same generated inputs.
- Same behaviour on known cases: `baseline-before-change`, `characterization-tests`, `golden-files-hand-verified` (regression), rung 3 to 4. Characterise before you edit.
- Interfaces: `api-semver-rust`, `api-surface-typescript` or `api-breaking-schema` (regression), rung 2.
- The tests can notice a change: `mutation-on-diff` (test-quality), rung 2.
- Structure goal: `architecture-lint` (regression); `ratchet-floor` for a metric that must only improve.
- Speed: `perf-regression`, `size-budget` (regression).
- Gate: `single-gate-command` (completeness), rung 3.

## Common false finishes
- The suite passed, but the code had no tests where you changed it. A passing suite over untested code says nothing; add characterization tests first.
- Existing tests were edited during the refactor. Any test edit is a behaviour change until shown otherwise.
- Error messages, ordering of results, or timing changed, and a caller relied on it.
- A public name was renamed or moved and only in-repo callers were updated.
- Dead code was deleted that was reached by reflection, a config string, or a plugin.
- "Same behaviour" was checked on the happy path only; the error and empty paths differ.
- The refactor and a fix were merged into one diff, so neither can be reviewed. Separate them.
- The new structure is only a rename or a move, with the same coupling.
