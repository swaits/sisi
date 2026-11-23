---
id: concurrent-code
title: Concurrent, parallel or async code
applies_to: Code with threads, tasks, locks, channels, async runtimes, or shared state between processes.
---

## Done means
- The design's key properties (no lost update, no deadlock, ordering where promised, each message handled once) are stated and checked, not assumed.
- Interleavings were explored systematically, not by hoping a test hits the bad one.
- Memory safety and data races are checked by a tool on the real code paths.
- Cancellation, timeout, shutdown and panic in one task leave the rest consistent and release locks and resources.
- Results do not depend on timing: repeated runs under load give the same outcome.
- Throughput claims, if any, are measured.

## Checks
- The design: `tlaplus`, `pluscal`, `quint` or `p-lang` (design), rung 1, for protocols and state machines.
- The code's interleavings: `loom` or `shuttle`, `deterministic-simulation` (concurrency), rung 1 to 2.
- Races and memory: `thread-sanitizer`, `go-race-detector`, `miri`, `address-and-ub-sanitizers`; `unsafe-audit` (safety).
- Correctness of results: `linearizability-checking`, `stateful-model-test` (many-inputs), rung 2.
- Lifecycle: `async-cancellation-safety`, `lock-order-and-deadlock`.
- Flakiness: `stress-repeat`, `flaky-test-detection`, `test-determinism` (test-quality).
- Tests can fail: `mutation-on-diff`, `check-the-checker`.

## Common false finishes
- The tests pass on a fast machine with two threads. Bugs need contention; use a model checker and a stress run with more tasks than cores.
- The sanitiser ran on the tests but the tests do not run the concurrent paths together.
- A `sleep` was added to make a test pass. That is a timing hack, not a fix.
- The model checker explored a model, not the code; the model and the code diverged.
- Loom or Shuttle bounds were set so small that the bad schedule was never reached; a pass with a tiny bound is partial.
- A lock was added and now there is a deadlock under a different order. Check lock order.
- Cancellation was tested at no point other than the start; a drop halfway through leaves state broken.
- "Flaky, re-run" was accepted as a pass.
