---
id: performance-work
title: Performance or resource-use work
applies_to: A change whose goal is to make something faster, smaller or lighter.
---

## Done means
- A measured baseline was taken before the change, on stated hardware, with stated inputs, and the after-numbers are on the same setup.
- The improvement is larger than the noise, shown by repeated runs and a spread, and is the figure the request named (latency, throughput, memory, size).
- Results are identical: the same outputs for every input, including edge cases.
- It holds across the realistic range of inputs (small, large, adversarial), not only the one benchmarked.
- Other costs did not rise unseen (memory, start-up, binary size, tail latency).
- A guard now stops it getting worse again.

## Checks
- Same results: `differential-old-vs-new` (many-inputs), rung 2; `characterization-tests`, `baseline-before-change` (regression).
- Measurement and guard: `perf-regression`, `size-budget`, `ratchet-floor` (regression), rung 3.
- Concurrency effects: `thread-sanitizer`, `stress-repeat` if threads were added.
- Under load: `load-test-k6` (real-world) for a service; `lighthouse-budget` for a web page.
- Tests are real: `mutation-on-diff`; gate: `single-gate-command`.

## Common false finishes
- One timing run, a noisy machine, a 4% change called a win.
- Benchmarked in debug mode, or without optimisations the product ships with.
- The benchmark input is so small that the optimised path is never taken, or the compiler removed the work.
- A cache warmed by the benchmark loop; the cold case is slower than before.
- Speed gained by dropping a check, a copy that was needed, or precision; outputs differ in edge cases.
- Median improved and the 99th percentile got worse.
- Memory use went up as time went down and only time was measured.
- No guard was added, so the gain disappears in the next change.
