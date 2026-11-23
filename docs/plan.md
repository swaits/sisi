# Plan: bringing sisi into conformance with SPEC.md

The work list for the reconciliation. `docs/reconciliation/critique.md` says what is wrong,
`docs/design.md` says what replaced it, `docs/spec/conformance.json` holds the status of every
numbered requirement, and this file says in what order it is built and what the owner has
asked for. Section numbers in brackets are sections of `SPEC.md`.

## What done means

Every requirement in `docs/spec/requirements.json` is either met by a named mechanism with a
test that cites its id, or it is on the exceptions list at the end of this file, in plain
words, with the reason and what it would take. A different model family from the one that
built it grades the table against the specification text. The measurements in
`tools/measure.py` are shown before and after.

## Stages

Stages are an order, not a ceiling. Each one lands on the `spec-reconciliation` branch only
with the whole test suite passing.

| # | Stage | Status | Serves | What it delivers |
|---|---|---|---|
| 0 | Standard and baseline | done | [19] steps 1-4, 6 | The specification saved and protected; its requirements numbered with a completeness test; four audits; a measured baseline. |
| 1 | Cut and sort | done | [8.2, 12, 17] | Dead commands and developer mode removed; the product scanned by a test for owner-specific and perishable material; a shorter README; `tools/measure.py` and the "before" numbers. |
| 2 | Records | done | [5.4-5.6, 6.1, 6.4, 10, 13] | The durable work-unit record; the five verification statuses; selection by change and reuse; telemetry with honest classes; the scorecard; `sisi status`; scratch pruning. |
| 3 | Orchestration | done | [7] | One ledger, worker facts, `route`, the delegation contract, the strategy playbook; nothing in the product names a model. |
| 4 | Conformance table | done | [19] step 2, [20] | Status of every requirement before the rebuild, then kept current by every stage. |
| 5 | Proportional gate | done | [5.3, 9, 10.3, 17] | Risk profiles replace line counts; the gate enforces only what the profile requires; retro at close; `unit pause`; subagents pass; hooks add only what a session can act on; recipes found by structured tags. |
| 6 | Learning loop | done | [11, 12, 14.4, 16] | Learning records per [11.4]; a retro grounded in the unit record; scope earned by evidence; validation before promotion; promotion as a revertible commit; recurrence monitoring; protected rules and owner approval for consequential changes. |
| 7 | Rulebook and documents | done | [3, 4, 17] | `canon/core.md` rewritten as the operating policy; the documents rewritten around what now exists. |
| 8 | Evaluation harness | done | [11.5, 11.6, 13.3, 19 step 9, 20.3] | Benchmark cases from real work and from learnings; a replay runner; policy versions compared on historical, held-out and counterexample cases; an independent judge. |
| 9 | Grading | not done | [13.3] | Conformance graded requirement by requirement by a different model family; the exceptions list. |
| 10 | Cutover | not done | [14, 16] | The owner's installation switched, his data migrated, the old orchestrator removed. |

## Cutover checklist

The installed copy is not changed in the middle of a stage.

1. Archive, with a timestamp, the personal data folder, the scratch folder's ledgers, and the
   owner's Claude instructions and settings.
2. Run the data migration on a copy of the real data and compare counts: lessons to
   learnings, owner statements, delegation ledger rows (the old `orch.py` log merged in).
3. Prove `sisi rollback` in a sandbox: release, switch, roll back, compare byte for byte.
4. Check that the new hooks accept state written by sessions that are already running.
5. Release. Run `sisi doctor`. Run the measurements and print the before-and-after table.
6. Remove the hand-written orchestrator section from the owner's Claude instructions and
   retire `orch.py`, in one edit with the backup from step 1. Running sessions get a
   one-time notice through the prompt hook.
7. If anything in steps 5 or 6 fails: `sisi rollback`, restore the archive, stop and report.

## Spending

Builders are the non-Claude workers. Claude workers are used only for short reviews that must
block, at most ten in the whole job. If every non-Claude worker is unavailable, the work stops
at a stage boundary and says so.

## What the owner has said about sisi

His recorded statements are requirements on this work. Each is quoted, with where it is
answered, in `docs/reconciliation/owner-statements.md`.

## Exceptions

Requirements that are not met when the work is reported, in plain words. To be filled by the lead.
