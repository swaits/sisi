---
id: rubric-judge
title: A written rubric scored by an independent model judge
answers: Does the output meet qualities a command cannot measure, such as clarity, tone or fit to the brief?
rung: 5
section: intent
languages: any
kinds: general, ui
cost: medium
detect:
ran_here: no
verified: docs
---

Note: no tool is needed beyond a model CLI or API you already use. The honesty
measures below follow published LLM-as-judge practice; nothing here was run.

## Use when
- The claim is about quality that has no exact answer: a summary, an error message, a design, documentation, a tool description.
- Human review would be the only check otherwise and you want to narrow what the human must read.
- You can write what good looks like as a short list of yes-or-no criteria.

## Do not use when
- A command, test or proof can decide it. A judge is a sample of opinion; it is the weaker rung.
- You are the only model available. A model judging its own work agrees with itself.

## Set up
Write `rubric.md`: 4 to 8 criteria, each a question with a clear pass line and one
example of a pass and a fail. Gather a calibration set from `taste-baseline`.

## Minimal example
`rubric.md` excerpt:

    C1 States what happened in the first sentence. Pass: "The import failed: row 12 has no date." Fail: "An error occurred."
    C2 Says what to do next. C3 Contains no internal jargon. C4 Under 40 words.
    Reply as JSON: {"C1": true|false, "C2": ..., "evidence": {"C1": "<quote>"}}

## Run
Keep the judge honest:
- Blind: give it the output and the rubric only, never the request history, your reasoning or which version is "new".
- A different model family from the one that wrote the work, with temperature 0, and require a quoted line as evidence for every verdict.
- Calibrate first: run the judge on 10 or more outputs the human already judged; require at least 90% agreement. If lower, fix the rubric, not the threshold.
- Run it 3 times and take the majority; a criterion that flips is a vague criterion.
- Treat any false as a failed check, and report the quotes.

Passing looks like: every criterion true in the majority of runs, with quotes
that actually appear in the output, and calibration agreement recorded.

## As a contract check
    {"id": "rubric-judge", "claim": "Independent judge passes all rubric criteria", "kind": "general", "rung": 5, "cmd": "python3 tools/judge.py --rubric rubric.md --input out/summary.txt --min-agree 0.9", "expect": {"exit": 0, "stdout_contains": "ALL PASS"}, "tier": "deep", "timeout_s": 300}

`tools/judge.py` is yours to write; it must exit non-zero on any failed criterion.

## What a pass does not prove
That the human would agree. Judges favour long, confident, polished text and
their own style. Quotes can be checked mechanically (is the quote in the
output?); do that. Check the judge can fail: feed it a deliberately bad output.
A pass at rung 5 does not replace a human check for anything the human cares about.
