---
id: taste-baseline
title: Recording the human's past verdicts on before and after pairs
answers: Does this work match what this human has said they prefer, in cases they already judged?
rung: 6
section: intent
languages: any
kinds: general, ui
cost: low
detect:
ran_here: no
verified: docs
---

Note: no tool. The store is plain files; not run here.

## Use when
- The human's judgement is the real test (layout, wording, density, tone) and they have already given verdicts you can reuse.
- You run `rubric-judge` and need cases to calibrate it against.
- The same kind of complaint comes back repeatedly.

## Do not use when
- You have no recorded verdicts. Do not invent them; ask once, or use `pairwise-comparison` with the human.
- A preference was a one-off about a different context.

## Set up
Create `docs/taste/` with one small file per verdict. Record a verdict only when
the human states it (rule 8, close-with-retro: `sisi learn "<their words>"` for lasting
preferences, quoted, never your inference).

## Minimal example
`docs/taste/0007-invoice-email.md`:

    date: 2026-11-09
    pair: before/invoice-email.txt vs after/invoice-email.txt
    verdict: after
    their words: "Better. But keep the amount in the subject line."
    rule it implies: the amount stays in the subject.

## Run
List the verdicts that apply to the area you changed, then re-run the pairs
through the judge or show the human only the cases that differ from past verdicts:

    ls docs/taste/ | head
    python3 tools/taste_check.py --judge-config judge.json --taste docs/taste/

Passing looks like: for every recorded pair in scope, the judge's verdict equals
the human's (agreement at or above the threshold), and no implied rule is violated
(for the example, the subject still has the amount: `grep -q '\$' out/subject.txt`).

## As a contract check
    {"id": "taste-rules", "claim": "Rules implied by the human's past verdicts still hold", "kind": "general", "rung": 6, "cmd": "python3 tools/taste_check.py --taste docs/taste/", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 300}

`tools/taste_check.py` is yours to write; turn each implied rule into a command
where you can, and list the rest as "needs the human".

## What a pass does not prove
Verdicts are about the pairs shown; a new context may need a new verdict. Old
verdicts can be stale: date them and let the human retire them. Your summary of
their words is not their words; keep the quote.
