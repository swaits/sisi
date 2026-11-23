---
id: findings-log
title: A log of every defect found, rejected mutant and false alarm
answers: What has already been found, tried and ruled out, so I do not repeat or reopen it?
rung: 3
section: completeness
languages: any
kinds: general
cost: low
detect:
ran_here: no
verified: docs
---

Note: no tool. Modelled on a reference project, which records what
each proof and mutation run found, and which survivors were equivalent. Not run here.

## Use when
- A verification effort spans more than one session, and the next agent must know what the last one covered.
- A tool reports things that are not bugs (an equivalent mutant, a lint you decided to accept, a flaky test cause). Say so once, with the reason.
- You found a real defect: record its id, what caught it, and the regression test.

## Do not use when
- A single quick check with nothing to carry forward.

## Set up
Create `docs/findings.md` with a table or dated list. One line per finding.
Fields: date, what, how found (technique id), verdict, evidence, follow-up.

## Minimal example
    | 2026-11-09 | Negative amounts accepted by the engine | kani | defect, fixed | test `rejects_negative_line` | none |
    | 2026-11-09 | Mutant `a < b` to `a <= b` in `fees.rs:42` survived | cargo-mutants | equivalent: both branches return the same value when equal | read of lines 40-44 | none |
    | 2026-11-10 | `test_sync` fails 1 in 50 | stress-repeat | defect: shared temp dir; fixed | passes 500 runs | none |

Every "equivalent" or "false alarm" verdict needs the reason, or it is just a
dismissal. Every defect names its regression test.

## Run
    python3 - <<'PY'
    import re,sys
    rows=[l for l in open("docs/findings.md") if l.startswith("|") and "---" not in l]
    bad=[l for l in rows if re.search(r"equivalent|false alarm",l) and len(l.split("|"))<7]
    print("rows:",len(rows)); sys.exit(1 if bad else 0)
    PY

Passing looks like: every row is complete and each defect row names a test that
exists (`grep -rn "rejects_negative_line" tests/`). Before starting, read the log for
the area; do not re-triage a recorded equivalent mutant.

## As a contract check
    {"id": "findings-recorded", "claim": "Every defect found has a regression test and every dismissal has a reason", "kind": "general", "rung": 3, "cmd": "python3 tools/findings_lint.py docs/findings.md", "expect": {"exit": 0}, "timeout_s": 30}

## What a pass does not prove
That the log is complete: only what someone wrote. Keep the real record in the
repository, not the chat. A dismissal can be wrong; give it a date and re-open on a code
change to the area. The log is for the next agent, so write for someone who
saw none of this session.
