---
id: parser-or-codec
title: Parsing, formatting or encoding code
applies_to: Code that turns bytes or text into structured data or back, including file formats, protocols and serialisers.
---

## Done means
- Valid input of every form the format allows parses to the right value, checked against an independent source (the specification's examples, a reference implementation).
- Encoding then decoding returns the original, and decoding then encoding returns the canonical form.
- Invalid and hostile input gives an error, never a crash, hang, huge allocation or wrong answer; there are bounds on size and nesting.
- Behaviour on the strange cases is decided and written down: duplicates, trailing data, byte order marks, case, whitespace, overlong encodings.
- Files written by it can be read by other tools, and the reverse.

## Checks
- Round trip: `round-trip` (many-inputs), rung 2, with a generator that makes valid structures.
- Agreement with another implementation: `differential-reference`, `differential-executable-spec` (many-inputs), rung 2.
- Crashes and hangs: `cargo-fuzz`, `atheris`, `jazzer` or `go-fuzz`, with `structure-aware-fuzzing`, rung 2; run longer than a smoke test.
- Schema-based attack: `hostile-input-from-schema`. Seeds kept: `regression-seed-hygiene`.
- Known good files: `golden-files-hand-verified` (regression), `old-data-compatibility`.
- Grammar properties: `metamorphic`, `algebraic-laws`; small domains: `exhaustive-small-domain` (prove).
- Tests are real: `mutation-on-diff`.

## Common false finishes
- Round trip passes only because the generator makes values the parser already handles; the strange values are never made.
- Fuzzing ran for a minute from an empty corpus, found nothing, and was called clean.
- Both directions share a bug (the same wrong table) so the round trip is symmetric and wrong. Compare to an independent oracle.
- Errors are tested by "it returns an error", not that the position and message are right.
- The decoder accepts input the specification forbids ("be liberal"), and other tools then disagree.
- Recursion depth, length prefixes, and decompression ratios are unbounded.
- Locale, endianness or Unicode normalisation differs on another machine.
