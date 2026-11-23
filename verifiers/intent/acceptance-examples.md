---
id: acceptance-examples
title: Acceptance examples agreed with the human up front and made executable
answers: Does the program give the exact results the human said they wanted for concrete cases?
rung: 3
section: intent
languages: any
kinds: general, money, parsing
cost: low
detect:
ran_here: no
verified: docs
---

Note: there is no tool. The example runner below is plain test code; it was
not run here as a separate artefact. `verified: docs` reflects that the method
is standard specification by example.

## Use when
- The request is a behaviour in words ("round fees to the nearest cent", "a late invoice gets a reminder"). Words are ambiguous; examples are not.
- The human will not review code but will read a table of inputs and outputs.
- You have to choose between readings of the request and want the human's choice fixed before you build.

## Do not use when
- The claim is "this holds for all inputs". Examples show cases only; use a property or proof (rung 1 or 2).
- The behaviour is visual or tasteful; see `pairwise-comparison`.

## Set up
Write `acceptance/examples.json` and show it to the human once (rule 1, own-the-outcome: one
round of confirmation, with your default stated). Edge cases first: zero,
empty, the largest, a tie, a negative, an invalid input and what it must do.

## Minimal example
`acceptance/examples.json`:

    [
      {"name": "tie rounds to even", "in": {"amount": "2.675", "dp": 2}, "out": "2.68"},
      {"name": "zero", "in": {"amount": "0", "dp": 2}, "out": "0.00"},
      {"name": "negative", "in": {"amount": "-1.005", "dp": 2}, "out": "-1.00"},
      {"name": "bad input", "in": {"amount": "abc", "dp": 2}, "error": "invalid amount"}
    ]

`acceptance/test_examples.py` loops over the file, calls the product through its
public entry point, and fails with the example's `name`.

## Run
    python3 -m unittest discover -s acceptance -v

Passing looks like: one `ok` per example, exit 0. Failure names the example,
the expected and the actual. Never edit an expected value to make a run pass;
a changed expectation goes back to the human as a contract amendment.

## As a contract check
    {"id": "acceptance-examples", "claim": "Every example the human agreed gives the stated result", "kind": "general", "rung": 3, "cmd": "python3 -m unittest discover -s acceptance", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 120}

## What a pass does not prove
Only the cases listed. Check that the examples can fail: change the code on
purpose (swap round-half-even for round-half-up) and see at least one fails.
Examples you wrote and the human skimmed are weak; flag which the human
confirmed. Add a property test for the rule behind them where one exists.
