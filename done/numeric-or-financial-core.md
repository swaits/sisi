---
id: numeric-or-financial-core
title: Numeric or financial calculation code
applies_to: Code that computes with money, quantities, rates or any number where a wrong digit is a wrong answer, such as ledgers, tax, interest, pricing.
---

## Done means
- Numbers are exact: money is integers or decimals, never binary floating point, with rounding rules named and applied in one place.
- Conservation laws hold for every input: debits equal credits, parts sum to the total, a reversal nets to zero, allocations lose no cent.
- Boundaries are decided and tested: zero, negative, the largest value, overflow, many decimal places, ties in rounding, currency conversion.
- Period, year and timezone boundaries behave; leap days and month ends are covered.
- Results agree with an independent source: a hand calculation, a reference implementation, a published example.
- The domain's own reports (trial balance, statements) foot and the human or an expert has read them.

## Checks
- Laws for all inputs: `lean4-proofs`, `kani`, `verus`, `creusot` or `exhaustive-small-domain` (prove), rung 1, for the core invariants; else `proptest` or `hypothesis`, `algebraic-laws` (many-inputs), rung 2.
- Overflow and panics: `kani`, `cargo-fuzz`, `illegal-states-unrepresentable`.
- Independent answer: `differential-reference`, `differential-executable-spec`, `metamorphic`, `model-test-from-spec`.
- Rules traced: `spec-traceability` (completeness).
- Evidence for the human: `domain-evidence-report`, `golden-files-hand-verified`.
- Tests are real: `cargo-mutants`, `mutation-on-diff`; `rust-lints-strict` denying lossy casts (safety).
- Leaks: `sensitive-data-leak-test` for tax ids.

## Common false finishes
- Example tests with round numbers pass; the cent that disappears on a three-way split is never tried.
- `float` or `double` is used somewhere in the path, even once.
- Rounding happens at each step instead of at the end, or at the end instead of each step, against the stated rule.
- A property test generates only small positive amounts, so negatives and huge values never occur.
- The proof covers a simplified model; the shipped code uses a different type or rounding.
- A report foots because both sides come from the same wrong figure.
- A reversal, a late entry, or a closed period was never tried.
- A surviving mutant in the arithmetic was written off without a reason in the `findings-log`.
