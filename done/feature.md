---
id: feature
title: Adding a new capability to an existing product
applies_to: A new capability in a product that already exists and already has users, behaviour and data.
---

## Done means
- The new capability works end to end through the real surface users will use, not only through a new function or endpoint.
- Every requirement is listed with its kind (explicit, implied, contextual, anticipated, experiential) and a decision: implement now, architect for, defer, or ignore, each with a reason.
- Behaviour that already exists is unchanged except where the new capability is meant to change it, shown by invariants with a baseline from before the change.
- Each requirement has an acceptance check, and the checks for the core logic are strong (property, differential or fuzz checks where the input space is broad).
- Empty, large, invalid and repeated use of the new capability behave sensibly, and existing data, settings and workflows still work with it.
- The capability is discoverable and usable in the product's own terms (labels, help, errors), with loading, empty and error states where it has a surface.

## Checks
- Requirements: `requirement-to-check-map` (completeness), `acceptance-examples` (intent), rung 3; every requirement maps to a check or a recorded deferral.
- New logic: `hypothesis`, `proptest` or the language's property tool (many-inputs), rung 2; `differential-reference` where a trusted comparison exists.
- Nothing else broke: `baseline-before-change`, `characterization-tests` (regression), rung 3; invariants from before the first edit.
- Real surface: `e2e-playwright` (real-world) for a web capability, `cli-transcript-tests` for a command, rung 3.
- Hostile and odd input: `hostile-input-from-schema` (many-inputs), rung 2, for any new parser, import or boundary.
- Finished cleanly: `no-stubs-scan`, `single-gate-command` (completeness), rung 3.

## Common false finishes
- The happy path works and the empty, huge, invalid and repeated cases were never tried.
- A requirement nobody stated but everybody needs (undo, export, permissions, existing data) is missing, and the report does not say so.
- Existing behaviour changed silently: no baseline was taken, so nobody can tell what moved.
- The capability exists but users cannot find it, or its errors leave them stuck.
- Anticipated needs were built speculatively, or were dismissed without a recorded defer decision.
- New settings or data have no story for existing users upgrading.
- The new code path is tested only through its internals, never through the surface users touch.
