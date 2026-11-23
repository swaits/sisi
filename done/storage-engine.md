---
id: storage-engine
title: A storage engine, database layer or persistent format
applies_to: Code that writes data to disk or a database and must read it back correctly after crashes, upgrades and concurrency.
---

## Done means
- What is written is what is read back, for all value shapes, including the empty, the largest and the unusual.
- A crash or power loss at any point leaves the store either as before or as after, never in between, and recovery works.
- Concurrent readers and writers see consistent states, with the isolation the documentation promises.
- Files written by every earlier version still open; the new version's files are rejected or migrated safely by older ones.
- Corruption is detected and reported, not silently returned.
- Disk full, permission denied and a failed write are handled without damaging existing data.
- Performance and size on realistic volume are measured.

## Checks
- Round trip and model: `stateful-model-test`, `round-trip`, `model-test-from-spec` (many-inputs), rung 2.
- Crash and failure: `fault-injection-storage`, `deterministic-simulation` (concurrency), rung 2.
- Consistency: `linearizability-checking`, `loom` or `shuttle`, `stress-repeat`.
- Old data: `old-data-compatibility`, `replay-equivalence`, `derived-view-agreement`; migration: `db-migration-safety`.
- Hostile files: `cargo-fuzz`, `structure-aware-fuzzing`.
- Design: `tlaplus` or `quint` for recovery protocols (design), rung 1.
- Read-only paths: `read-only-guarantee`. Speed: `perf-regression`.

## Common false finishes
- Tests never kill the process mid-write; the write-then-rename or log protocol was not exercised.
- `fsync` was not called (or the directory was not synced), and the test machine's cache hid it.
- The store was tested in memory or on tmpfs, not on a real disk.
- One thread only; a second writer breaks it.
- The test reopened the store in the same process, which kept caches alive. Restart a fresh process.
- An old file from the previous release was never opened.
- Corrupted bytes are returned as valid data because there is no checksum.
- A lock file is left behind after a crash and blocks the next start.
