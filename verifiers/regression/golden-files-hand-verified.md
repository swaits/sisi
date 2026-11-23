---
id: golden-files-hand-verified
title: Golden outputs recomputed by hand or by an independent method
answers: Is this expected output actually correct, or just whatever my code produced?
rung: 4
section: regression
languages: any
kinds: general, money, parsing
cost: medium
detect:
ran_here: yes
verified: ran
---

## Use when
- You need a fixed expected output for a calculation, report or parser, and a wrong golden file would lock in a bug.
- The numbers matter (money, dates, units). Independent recomputation is what makes the golden trustworthy.

## Do not use when
- You only need to detect change, not correctness. Use `snapshot-insta` or `baseline-before-change`.
- No independent method exists. Say so in the record instead of pretending.

## Set up
Keep each golden next to a provenance file, or a header comment, that records how it was verified. Verification methods, strongest first: a different program (a spreadsheet, `bc`, a second implementation, a published worked example), a hand calculation written out, a regulator's or vendor's published example. "The code printed it and it looked fine" is not a method.

## Minimal example
`tests/golden/invoice-total.expected` is the golden; `tests/golden/invoice-total.PROVENANCE` holds:
```
output: tests/golden/invoice-total.expected
method: independent
how: recomputed with Python's decimal module (or bc, a spreadsheet), not the project's code
command: python3 -c 'from decimal import Decimal as D; print((D("19.99")*3+D("5.00")*D("1.5")+D("0.10")).quantize(D("0.01")))'
result: 67.57
checked_by: agent, 2026-11-22
```
Check both in one command:
```sh
expected=$(python3 -c 'from decimal import Decimal as D; print((D("19.99")*3+D("5.00")*D("1.5")+D("0.10")).quantize(D("0.01")))')
[ "$expected" = "$(cat tests/golden/invoice-total.expected)" ] && ./mytool total tests/fixtures/invoice.json | diff - tests/golden/invoice-total.expected
```

## Run
The line above, as one test script. Passing looks like: no output, exit 0. Failure: a diff, or a nonzero exit when the independent value and the golden disagree (the check fails before it ever runs your code, which is the point).

## As a contract check
```json
{"id": "golden-independent", "claim": "Golden totals match an independently computed value and the tool matches the golden", "kind": "money", "rung": 4,
 "cmd": "sh tests/check-golden.sh", "expect": {"exit": 0}, "timeout_s": 60}
```

## What a pass does not prove
- It shows the golden equals the independent method on these inputs, not that the inputs are representative. Include awkward values (rounding at half cents, zero, negative, very large).
- The independent method can share your misunderstanding. Using the same formula in a second language is not independent; a spreadsheet or a published worked example is better.
- The recorded `method:` is a claim. If it says `independent` but the command only calls your own code, the check is a snapshot at best. A reviewer should read the PROVENANCE file.
- Check the check: edit one digit in the golden and confirm the script fails. Here the unrounded Python result was `67.570`, which also failed a string comparison until it was quantized: compare in the golden's own format.
