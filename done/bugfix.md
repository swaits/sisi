---
id: bugfix
title: Fixing a bug
applies_to: A reported defect in existing behaviour, where the aim is to make it right and leave everything else alone.
---

## Done means
- The bug is reproduced first by an automated test that fails on the unfixed code, for the reason in the report.
- The same test passes after the fix, and it is kept as a permanent regression test.
- The cause is found, not just the symptom: the fix is at the point that was wrong, and siblings of the bug (same pattern elsewhere) were looked for.
- Nothing that worked before changed: the whole existing suite passes, and a baseline taken before the first edit matches afterwards.
- The diff touches only what the fix needs; no drive-by refactors.
- The report says what the bug was, why it happened, and what was not fixed.

## Checks
- Fails before, passes after: `red-before-green` (test-quality), rung 3; for a bug in logic over many inputs, a property or differential check that fails on the old code (`proptest`, `hypothesis`, `differential-old-vs-new` in many-inputs), rung 2.
- Nothing else changed: `baseline-before-change`, `characterization-tests` (regression), rung 3; `feedback-as-amendment` (intent) for the scope check on the diff.
- The test can fail: `vacuity-check`, `mutation-on-diff` (test-quality), rung 2.
- Same mistake elsewhere: `static-analysis-semgrep` (safety) with a rule for the pattern; log it in `findings-log` (completeness).
- Finished cleanly: `no-stubs-scan`, `single-gate-command` (completeness), rung 3.
- If the bug was a crash or hostile input: the input is added as a seed (`regression-seed-hygiene`, many-inputs).

## Common false finishes
- The new test passes but was never run against the unfixed code. It may never have failed; run it with the fix reverted.
- The test asserts the new behaviour on the exact reported input only. A different input with the same cause still fails; vary it.
- The symptom is hidden: an error is caught and ignored, a value is clamped, the failing case is special-cased. The cause remains.
- An old test was changed or deleted to make the suite green. Read the test diff first.
- A flaky failure "went away" after the change. A bug seen once is not fixed by one clean run; see `stress-repeat` (concurrency).
- The fix is in the wrong layer (UI hides what the engine gets wrong).
- The reproduction used test fixtures that cannot occur in real data, so the real case is untested.
- The change reaches further than the bug and nobody ran the invariants.
- "Cannot reproduce" is reported as fixed. Say it is unreproduced and not fixed.
