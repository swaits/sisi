---
id: owner-acceptance-runbook
title: A scripted acceptance walked through using only the product's public surface
answers: Can the owner, or an agent acting as the owner, do the real job end to end using only what the product exposes?
rung: 6
section: intent
languages: any
kinds: general, ui
cost: medium
detect:
ran_here: no
verified: docs
---

Note: modelled on a runbook in a reference project (a re-audit done
through the product's tools alone, with a test mirroring it). Not run here.

## Use when
- The product is finished, or a large part is, and the question is "does it do what the owner wanted?" not "do the units pass?".
- Several features must work together, and unit tests passed each on its own.
- The human wants to run a short script and see for themselves.

## Do not use when
- The change is small or internal; a runbook costs more than it finds.
- Nobody, human or agent, can run the product in its real environment.

## Set up
Write `docs/runbooks/acceptance.md`. Each step: what to do, using only the CLI,
the UI, the API or the agent tools the product ships (never the database, a
debugger or a source file); what to expect; what to do on a mismatch. Say who
acts: the owner, or an agent with no access to the source.

## Minimal example
    1. Start the product on an empty data directory: `product serve --data /tmp/acc`.
       Expect: "listening on 127.0.0.1:8080", exit when stopped with code 0.
    2. Create a customer via the public API (curl in the runbook). Expect: 201 and an id.
    3. Issue an invoice for $100 and fetch the statement. Expect: balance 100.00.
    4. Restart the product on the same directory. Expect: the same balance.
    5. If any expectation fails, stop. The runbook or the product is wrong; say which.

## Run
An agent walks the runbook, copying each command and its real output into
`acceptance-report.md`. The owner reads the report, or walks it themselves.
Every step records pass, fail or not run.

Passing looks like: every step passed with real output pasted, nothing skipped,
and the report names who ran it and on what version. A runbook step that needed a
workaround is a failure of the product, even if the workaround worked.

## As a contract check
    {"id": "acceptance-runbook", "claim": "The acceptance runbook passes end to end through the public surface", "kind": "general", "rung": 6, "cmd": "python3 tools/walk_runbook.py docs/runbooks/acceptance.md", "expect": {"exit": 0, "stdout_contains": "ALL STEPS PASSED"}, "tier": "deep", "timeout_s": 900}

`tools/walk_runbook.py` is yours to write; where steps are human-only, the contract
check is the owner's recorded verdict, not a command.

## What a pass does not prove
Only the journeys written down. An agent that can read the source may use it, so
state what it may not read. Steps that depend on data from a previous run give
false passes; start clean. The owner's own pass is the only one that counts as rung 6.
