---
id: pairwise-comparison
title: Before and after shown side by side instead of scored in the absolute
answers: Is the new version better than the old one for the thing the human cares about?
rung: 5
section: intent
languages: any
kinds: general, ui
cost: low
detect:
ran_here: no
verified: docs
---

Note: no tool; the procedure is the technique. Not run here.

## Use when
- You changed something that already worked (a layout, a message, a report, a prompt) and the risk is that it got worse.
- "Is this good?" has no stable answer but "which is better?" does.
- You have a before capture from `baseline-before-change`.

## Do not use when
- There is an exact correct output; test it.
- There is no earlier version. Use `rubric-judge` or `acceptance-examples`.

## Set up
Capture the old output before your first edit and the new output after, from
identical inputs. Strip anything that gives away which is new (dates, version
strings, file names). Randomise which is shown as A and B.

## Minimal example
For a judge or the human, a two-column card:

    Task: the invoice email, same data.
    A: <output 1>          B: <output 2>
    Question: which is clearer for a customer who owes money? Answer A, B or tie, and quote the line that decided it.

Run each pair twice with the sides swapped. A verdict that changes with the
order is "tie".

## Run
    python3 tools/pair.py --before out/before.txt --after out/after.txt --judge other-family --swap

Passing looks like: "after" wins or ties on both orders for every case, and no case
is a loss. Report wins, ties and losses, with the quote for each loss. For a
human, show images or text side by side and record the verdict with
`sisi learn` only if the human states a lasting preference.

## As a contract check
    {"id": "pairwise-not-worse", "claim": "The new output is never judged worse than the old", "kind": "general", "rung": 5, "cmd": "python3 tools/pair.py --before out/before.txt --after out/after.txt --swap --fail-on-loss", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 300}

`tools/pair.py` is yours to write; it must exit non-zero on a loss.

## What a pass does not prove
That the new version is good, only that it is not worse on the cases shown.
Small samples hide rare losses; include the cases that were hard. A judge that
shares the author's model family leans toward the author's style. Position bias
is why you swap. For anything the human cares about, they decide.
