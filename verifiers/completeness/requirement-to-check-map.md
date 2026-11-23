---
id: requirement-to-check-map
title: Mapping each sentence of the request to a contract check, and listing what has none
answers: Does every thing the human asked for have a check, and which asks have none?
rung: 3
section: completeness
languages: any
kinds: general
cost: low
detect: python3 --version
ran_here: no
verified: docs
---

Note: no tool; the map is a small file and a script. The script was not run
here as written, only the traceability idea behind it (`spec-traceability`).

## Use when
- You start non-trivial work from a request in prose and are drafting `.sisi/contract.json` (core rule 1).
- The request is long, or has "and also" clauses that are easy to drop.
- You are about to say "done" and need to show nothing asked for was left out.

## Do not use when
- The request is a one-line change; just run its check.
- A numbered spec already exists; use `spec-traceability`.

## Set up
Copy the request into `.sisi/request.md`, one sentence or clause per line, each
tagged `Q1`, `Q2`, and so on. Number them in the order the human wrote them.

## Minimal example
`.sisi/request.md`:

    Q1 Import the bank CSV into the books.
    Q2 Skip rows that are already there.
    Q3 Show me what was skipped.
    Q4 Keep the old import working.

In the contract, add `"asks": ["Q1"]` to the check that proves each, or list a
sentence under `"unchecked": {"Q3": "needs the human; screen output"}` with the reason.

## Run
    python3 - <<'PY'
    import json,re,sys
    q=set(re.findall(r"^(Q\d+)",open(".sisi/request.md").read(),re.M))
    c=json.load(open(".sisi/contract.json"))
    have={a for k in c["checks"] for a in k.get("asks",[])}|set(c.get("unchecked",{}))
    miss=sorted(q-have); print("no check:",miss or "none"); sys.exit(1 if miss else 0)
    PY

Passing looks like: `no check: none`, exit 0. Failure prints the sentences with no
check, exit 1. Report every `unchecked` entry in the final answer as not verified.

## As a contract check
    {"id": "request-mapped", "claim": "Every sentence of the request maps to a check or a stated reason it has none", "kind": "general", "rung": 3, "cmd": "python3 tools/request_map.py", "expect": {"exit": 0, "stdout_contains": "no check: none"}, "timeout_s": 30}

## What a pass does not prove
That the check is strong; a Q mapped to a weak check passes. Read the map for
the sentences where the check is only "the command runs". Implicit asks (the
human did not write "do not break the old import") are missing: Q4 above must
be added by you, from the invariants in core rule 3. An `unchecked` list is
honest only if it is reported.
