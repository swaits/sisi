---
id: data-migration
title: Migrating data or a schema
applies_to: Changing the shape, location or encoding of stored data, with existing data that must survive.
---

## Done means
- Every record in a realistic copy of production data migrates, and none is lost, duplicated or silently changed.
- Counts, totals, and derived views match before and after, by a check that does not use the migration's own code.
- Old data written by every earlier version still loads.
- The migration is safe to interrupt and to run twice, and a rollback or restore path was tried.
- Application code that reads the new shape works with it, and a mixed period (old and new code) is handled or ruled out.
- It was timed on production-sized data.

## Checks
- Safety and rollback: `db-migration-safety` (regression), rung 3.
- Old data: `old-data-compatibility` (many-inputs), rung 2; `replay-equivalence`, `derived-view-agreement`.
- Equivalence: `differential-old-vs-new` (many-inputs), rung 2, on generated and real records; `round-trip` where a reverse exists.
- Interruption: `fault-injection-storage` (many-inputs), `stress-repeat`.
- Totals and reports: `domain-evidence-report` (intent), `golden-files-hand-verified`.
- Contract: `baseline-before-change`; the human for production data, `owner-acceptance-runbook`.

## Common false finishes
- Tested on a small clean fixture; real data has nulls, odd encodings and duplicates.
- Counts match but values changed (timezone, rounding, trimming); no column-level comparison was made.
- Idempotence was never tried; a second run duplicates rows.
- The rollback exists on paper and has never been run.
- Old code reading new data (during a rolling deploy) fails.
- The migration takes hours in production and locks the table; it was timed on 100 rows.
- Foreign keys, indexes, triggers or permissions were not carried over.
- Backups were not taken or restored before the run.
