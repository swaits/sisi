# Plan: bringing sisi into conformance with SPEC.md

The work list for the reconciliation. `docs/reconciliation/critique.md` says what is wrong,
`docs/design.md` says what replaced it, `docs/spec/conformance.json` holds the status of every
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

| # | Stage | Status | Serves | What it delivers |
|---|---|---|---|
| 0 | Standard and baseline | done | [19] steps 1-4, 6 | The specification saved and protected; its requirements numbered with a completeness test; four audits; a measured baseline. |
| 1 | Cut and sort | done | [8.2, 12, 17] | Dead commands and developer mode removed; the product scanned by a test for owner-specific and perishable material; a shorter README; `tools/measure.py` and the "before" numbers. |
| 2 | Records | done | [5.4-5.6, 6.1, 6.4, 10, 13] | The durable work-unit record; the five verification statuses; selection by change and reuse; telemetry with honest classes; the scorecard; `sisi status`; scratch pruning. |
| 3 | Orchestration | done | [7] | One ledger, worker facts, `route`, the delegation contract, the strategy playbook; nothing in the product names a model. |
| 4 | Conformance table | done | [19] step 2, [20] | Status of every requirement before the rebuild, then kept current by every stage. |
| 5 | Proportional gate | done | [5.3, 9, 10.3, 17] | Risk profiles replace line counts; the gate enforces only what the profile requires; retro at close; `unit pause`; subagents pass; hooks add only what a session can act on; recipes found by structured tags. |
| 6 | Learning loop | done | [11, 12, 14.4, 16] | Learning records per [11.4]; a retro grounded in the unit record; scope earned by evidence; validation before promotion; promotion as a revertible commit; recurrence monitoring; protected rules and owner approval for consequential changes. |
| 7 | Rulebook and documents | done | [3, 4, 17] | `canon/core.md` rewritten as the operating policy; the documents rewritten around what now exists. |
| 8 | Evaluation harness | done | [11.5, 11.6, 13.3, 19 step 9, 20.3] | Benchmark cases from real work and from learnings; a replay runner; policy versions compared on historical, held-out and counterexample cases; an independent judge. |
| 9 | Grading | done | [13.3] | Conformance graded requirement by requirement by a different model family; the exceptions list. |
| 10 | Cutover | done | [14, 16] | The owner's installation switched, his data migrated, the old orchestrator removed. |

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

His recorded statements are requirements on this work. Each is quoted, with where it is
answered, in `docs/reconciliation/owner-statements.md`.

## Exceptions

Graded against commit cab81df. One model family judged every requirement against the code and
tests, and a second family re-checked every verdict of "met" and overturned 6 of 68.

| Status | Requirements |
|---|---|
| Met, confirmed by the audit | 62 |
| Partial | 282 |
| Missing | 15 |
| Not applicable | 16 |

By this plan's own definition the work is not done: 297 requirements are not met. Each of them is a row in
`docs/spec/conformance.json`, with what exists (`how`), what is lacking (`gap`) and what would close it
(`fix`). Sorted by what closing them would take. The sorting is a first pass by a cheap worker and was not
checked row by row:

| What it would take | Requirements |
|---|---|
| Judgement: the text asks for a quality of thinking that no code can check; sisi can only ask for it or record it | 109 |
| A small addition to a mechanism that exists | 99 |
| A new mechanism or a substantial change | 51 |
| Only a test: the mechanism does it, and nothing would catch its removal | 17 |
| Boundary: complete, but it can be switched off or waived, or does not run on every host | 9 |
| Wording: a definition or description with nothing to test | 6 |
| Overturned by the audit, not sorted yet | 6 |

### Missing: nothing in the code does it

- **R-4.2-4** (SHOULD) "Relevant project and user context." Nothing in the code puts relevant project or user context into the intent or requirement model.
- **R-7.3-2** (SHOULD) "The organization SHOULD measure cost per accepted change and cost per unit of verified user value where …" No measure of cost per accepted change or per unit of verified user value exists.
- **R-7.4-4** (SHOULD) "The organization SHOULD measure wall-clock reduction against additional compute and coordination costs." No measure of wall-clock reduction against added compute and coordination cost.
- **R-8.2-1** (SHOULD) "The organization SHOULD minimize accidental complexity." Nothing in the code does it; not even a recorded field or a retro question addresses accidental complexity.
- **R-8.2-2** (MUST NOT) "It MUST NOT equate simplicity with the fewest lines of code, fewest files, shortest implementation, or …" No mechanism detects or refuses the prohibited behaviour; the prohibition exists only in the specification.
- **R-8.3-1** (SHOULD) "The organization SHOULD preserve architectural consistency where it supports comprehension and changeability." No mechanism asks whether a change keeps the existing architecture, conventions or patterns.
- **R-9.2-2** (SHOULD) "It SHOULD prefer targeted evidence gathering over broad, expensive repository analysis." Nothing in the code prefers targeted evidence gathering over broad, expensive analysis.
- **R-9.4-1** (SHOULD) "Agents SHOULD report discoveries that materially affect scope, risk, architecture, or estimates promptly." No mechanism, rule sentence or record covers prompt reporting of discoveries by agents.
- **R-9.8-1** (SHOULD) "A second retrospective SHOULD occur at the end of a multi-unit user request to identify cross-unit …" No second retrospective at the end of a multi-unit request, and no rule sentence asks for one.
- **R-10.1-1** (SHOULD) "The organization SHOULD avoid both extremes: overly large units that hide failures and excessively fragmented …" Nothing in the code steers between oversized and fragmented units.
- **R-11.2-4** (MUST) "What assumptions were wrong, and which were useful?" No mechanism, measure or check for wrong or useful assumptions; rule 8 does not mention them either.
- **R-11.2-5** (MUST) "What decisions were unnecessarily expensive or slow?" No mechanism, measure or check for decisions that were unnecessarily expensive or slow.
- **R-11.2-13** (MUST) "What could have been anticipated or automated?" No mechanism, measure or check.
- **R-12-7** (DEFINITION) "Workstream knowledge: current initiative, plans, interfaces, unresolved decisions, and dependencies across …" There is no workstream layer: nothing stores or retrieves a workstream's plan, interfaces, open decisions or dependencies between units; only the unit's parent …
- **R-13.2-3** (SHOULD) "Rework rate: proportion of work repeated or corrected due to misunderstanding, poor implementation, …" No rework rate is computed from the recorded corrections, send-backs or retries.

### Overturned by the audit

- **R-5.1-4** (MUST) "Implementation correctness: whether the implementation satisfies the specification." Nothing in sisi distinguishes implementation correctness from the other four correctness kinds (grep finds no such term; check kinds are domain labels like money/parsing). Checks are only tied to …
- **R-6.4-4** (SHOULD) "Independent checks SHOULD run concurrently where doing so reduces wall-clock time without causing resource …" Concurrency exists only as an opt-in contract flag `parallel`; nothing sets it, recommends it or judges independence or contention, so sisi does not make concurrent runs happen. The cited test shows …
- **R-7.5-2** (SHOULD) "A clear outcome and bounded scope." Refusal of a thin brief applies only to `sisi delegate`; native host delegations get only non-blocking post-hoc advice (orchestration.py:731). The cited test covers only `delegate check` output, and …
- **R-7.5-6** (SHOULD) "Files, resources, or modules the agent may change." Same gap: the 'Files you may change' requirement is enforced only for `sisi delegate`; a native Agent delegation is only advised afterward. The cited test checks `delegate check` output, not a …
- **R-13.3-2** (SHOULD) "Execution telemetry: timestamps, commands, tool calls, model identity, token counts, costs, retries, test …" The unit record keeps only counts (direct_calls, delegations), not each tool call with its name or the commands run (the shell note says command text is not kept), and the named test covers only …
- **R-13.5-1** (MUST) "An aggregate index MAY be maintained for trend visualization, but decisions MUST also inspect the underlying …" The mechanism is only the absence of an index plus a retro printout; nothing makes a decision inspect scorecard, gate outcomes, confidence and counter-metrics (the cycle brief does not show them), …
