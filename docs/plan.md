# Plan: bringing sisi into conformance with SPEC.md

The work list for the reconciliation. `docs/reconciliation/critique.md` says what is wrong,
`docs/target.md` says what replaces it, `docs/spec/conformance.json` holds the status of every
numbered requirement, and this file says in what order it is built and what the owner has
asked for. Section numbers in brackets are sections of `SPEC.md`.

## What done means

Every requirement in `docs/spec/requirements.json` is either met by a named mechanism with a
test that cites its id, or it is on the exceptions list at the end of this file, in plain
words, with the reason and what it would take. A different model family from the one that
built it grades the table against the specification text. The measurements in
`tools/measure.py` are shown before and after.

## Stages

Stages are an order, not a ceiling. Each one lands on the `spec-reconciliation` branch only
with the whole test suite passing.

| # | Stage | Serves | What it delivers |
|---|---|---|---|
| 0 | Standard and baseline | [19] steps 1-4, 6 | The specification saved and protected; its requirements numbered with a completeness test; four audits; a measured baseline. |
| 1 | Cut and sort | [8.2, 12, 17] | Dead commands and developer mode removed; the product scanned by a test for owner-specific and perishable material; a shorter README; `tools/measure.py` and the "before" numbers. |
| 2 | Records | [5.4-5.6, 6.1, 6.4, 10, 13] | The durable work-unit record; the five verification statuses; selection by change and reuse; telemetry with honest classes; the scorecard; `sisi status`; scratch pruning. |
| 3 | Orchestration | [7] | One ledger, worker facts, `route`, the delegation contract, the strategy playbook; nothing in the product names a model. |
| 4 | Conformance table | [19] step 2, [20] | Status of every requirement before the rebuild, then kept current by every stage. |
| 5 | Proportional gate | [5.3, 9, 10.3, 17] | Risk profiles replace line counts; the gate enforces only what the profile requires; retro at close; `unit pause`; subagents pass; hooks add only what a session can act on; recipes found by structured tags. |
| 6 | Learning loop | [11, 12, 14.4, 16] | Learning records per [11.4]; a retro grounded in the unit record; scope earned by evidence; validation before promotion; promotion as a revertible commit; recurrence monitoring; protected rules and owner approval for consequential changes. |
| 7 | Rulebook and documents | [3, 4, 17] | `canon/core.md` rewritten as the operating policy; the documents rewritten around what now exists. |
| 8 | Evaluation harness | [11.5, 11.6, 13.3, 19 step 9, 20.3] | Benchmark cases from real work and from learnings; a replay runner; policy versions compared on historical, held-out and counterexample cases; an independent judge. |
| 9 | Grading | [13.3] | Conformance graded requirement by requirement by a different model family; the exceptions list. |
| 10 | Cutover | [14, 16] | The owner's installation switched, his data migrated, the old orchestrator removed. |

## Cutover checklist

The installed copy is not changed in the middle of a stage.

1. Archive, with a timestamp, the personal data folder, the scratch folder's ledgers, and the
   owner's Claude instructions and settings.
2. Run the data migration on a copy of the real data and compare counts: lessons to
   learnings, owner statements, delegation ledger rows (the old `orch.py` log merged in).
3. Prove `sisi rollback` in a sandbox: release, switch, roll back, compare byte for byte.
4. Check that the new hooks accept state written by sessions that are already running.
5. Release. Run `sisi doctor`. Run the measurements and print the before-and-after table.
6. Remove the hand-written orchestrator section from the owner's Claude instructions and
   retire `orch.py`, in one edit with the backup from step 1. Running sessions get a
   one-time notice through the prompt hook.
7. If anything in steps 5 or 6 fails: `sisi rollback`, restore the archive, stop and report.

## Spending

Builders are the non-Claude workers. Claude workers are used only for short reviews that must
block, at most ten in the whole job. If every non-Claude worker is unavailable, the work stops
at a stage boundary and says so.

## What the owner has said about sisi

These are requirements. Each is quoted as recorded and followed by where it is answered.

- "It is NOT about that one system. This is a CORE STRATEGIC LEVEL BEHAVIOR to be smarter about how you do things. I shouldn't need to specify these menial details. This is a sisi core problem."
  Answer: the rulebook becomes strategic direction with mechanisms behind it (target 1, 10).
- "sisi should also optimize for minimize(time to delivery) for each task. Just about anything I ask it to do can take HOURS, and sometimes it can take DAYS. I don't want to give up the autonomy or completeness or correctness! But I want both. I want all that AND I want it delivered quickly. So this needs to be part of the sisi core objective optimization function."
  Answer: time to first useful result and to validated completion are measured per unit and reported with their percentiles; selection and reuse of checks; pauses and waits measured (target 5, 6; stage 2).
- "The pushed README still says 'Version 0.1.0, an early release.' under Status. This is the problem with this kind of text, hardcoded to specific versions or numbers or whatever. Also I'm pretty sure the whole README could be reduced by 25-50%."
  Answer: stage 1 rewrites the README without versions or counts, and a test scans the product for perishable material.
- "For price and benchmarking, I'm totally fine with sisi doing web research on that, and updating it every now and then. Generally sisi is built for SWE tasks, so those kinds of benchmarks are what's most useful, and if they do well there they probably do well in other places too, with a few exceptions like specialized software security models."
  Answer: worker facts with source and date, researched by a cheap worker when stale (target 9; stage 3).
- "the brand and title is always **sisi** is still improving. Lowercase, and emph on sisi if it is available."
  Answer: stage 1 and stage 7 documents.
- "Make sure they do a cleanup and backfill to get that garbage out of my global disk data. Stuff like the keymap for phrp belong in that project's work list and design documentation!!! (on project-specific items stored in sisi's global data; lessons must be universally applicable, project details allowed only as the historical example of where a lesson came from)"
  Answer: scope is earned by evidence and a learning is in force only in its own project until then; the migration in stage 6 re-scopes the existing lessons and hands project items to their projects (target 8; cutover step 2).
- "As part of the orchestrator incorporation into sisi, make sure you delete the old version so my sessions aren't running two orchestrators. Also we will need to let current running sessions know about the changes or else I need to restart them."
  Answer: cutover steps 4 and 6.
- "Subagent performance history goes in the user sisi store, not sisi core. And sisi needs to work in t3 or Claude or Hermes or anything else out there. It should always choose the native subagent delegation mechanism!!!!!"
  Answer: the ledger and worker facts live in the user store; `sisi route` names the host's own mechanism first (target 2, 9).
- "I feel like I'm really still having to lead you around by the nose. With sisi I thought you were going to be getting smarter, seeing around corners, anticipating and building what I need before I realize it????"
  Answer: the requirement model with implied, contextual, anticipated and experiential requirements, required where the risk warrants; requirement surprise measured per unit (target 3, 4, 6).
- "The question you have to ask is whether something applies to ALL projects where sisi may be in play AND if it would be universally useful to ALL USERS who install and use sisi. If so it goes in sisi core! If not it's either a user-preference or project-specific and it goes in my user sisi data store. Working on the sisi project itself is the exception -- we'll normally just have sisi as our shell while we work on a wide variety of different projects."
  Answer: the four layers and the universality test (target 2; stage 1).
- "OBTW part of this is deprecating the whole standalone orch.py thing to make that a core part of sisi. But it should be GENERIC and STRATEGIC in direction, so the agent works out the tactics on the fly. IOW, it shouldn't explicitly say use THIS EXACT MODEL or whatever. It sets out OBJECTIVES about how to discover models, discover pricing, discover benchmarking, measure performance, and dispatch and orchestrate DYNAMICALLY and INTELLIGENTLY. And it can leverage subagents with specific orchestration tasks like assessing, routing decisions, whatever. That could be a Haiku/Ember level model sometimes too! This should play DIRECTLY into the main system's objective function, especially around wall time, cost, efficiency."
  Answer: target 9; stage 3; delegation time, tokens and overlap feed the scorecard (target 6).
- "Ok get to work. Also note that I'm totally fine with GROSS change. Rearchitecting is okay. The ONLY thing that matters is that we implement the spec (plus orchestration layer) PERFECTLY."
  Answer: backward compatibility with the old design is not a goal; what is replaced is deleted.

## Exceptions

Requirements that are not met when the work is reported, in plain words. Filled in at stage 9.
