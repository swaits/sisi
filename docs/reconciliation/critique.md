# Critique of sisi against SPEC.md

Assessed on 2026-11-23 at commit `ec91e52`, as the specification's reconciliation steps 1 to 4
require [19]: four read-only audits of the code (the learning engine; the path from request
to "done"; installation, wiring and orchestration; and a measured baseline from the owner's
live data), each checked against the others. Numbers in brackets are sections of `SPEC.md`.
This is a dated record. The living status of each requirement is `docs/spec/conformance.json`.

## Verdict

sisi at this commit is a system for circulating prose between agents, with one good gate
attached. It has about 18,000 lines of Python, 41 commands and 160 library files, and after
a day of heavy use it cannot say what any piece of work cost, whether the human accepted it,
or whether anything it learned made later work better. The specification's first milestone is
"observability and control, not sophistication" [19]. sisi built the sophistication first.

What it does well is real and is kept: installation that cannot damage a user's tools, hooks
that fail open, a gate that turns "done" from a claim into an executed check, and a clean
separation of product, personal data and scratch.

## The defects, most serious first

### Flat-out wrong

1. **Learning produces no mechanisms** [11.3, 18]. Of 42 lessons, none became an executable,
   validated mechanism: no lesson has a check attached, none reached the top strength, and no
   enforced-check file exists. All 23 "folded" changes are Markdown. Every path ends as text in
   a later prompt, which the specification lists as a prohibited anti-pattern ("prompt-only
   self-improvement").
2. **Nothing is validated, by stated policy** [11.5, 11.6]. `docs/learning.md` says "there is
   deliberately no replay testing before a change ships". Applying a learning cycle checks
   structure only. Monitoring is one flag comparing send-backs before and after, confounded by
   everything else that changed. A set of 1,627 harvested tasks built for replay has no runner.
3. **It cannot show it is improving** [13, 20.3]. No store holds token counts, cost, human
   attention, acceptance or escaped defects. `sisi improve` counts lessons, showings and
   send-backs. By its own output every failure pattern's recurrence is "not falling". The
   rulebook grew from 98 to 158 lines over five cycles; one cycle was reverted and one is
   flagged worse. The specification says a system "MUST NOT claim to be improving solely
   because it has accumulated more prompts, skills, agents, tools, or learning records".
4. **There is no work-unit record** [10.2]. One `.sisi/contract.json` per project is edited
   by hand for each new task; the previous goal and checks are lost. Check results,
   delivery timings and retros live in three stores that share no id. Of the fourteen items a
   record must hold, the contract has four.
5. **Verification proves exit codes, not claims** [5.1, 5.6]. A check is a command and an
   expected exit status. `{"cmd": "true", "rung": 1, "kind": "money"}` satisfies the floor for
   money code, because the floor compares a self-declared integer. The project's own tests use
   `true` as the model of a good check. Nothing ever requires a check to be seen failing.
6. **The verification record has the wrong vocabulary** [5.6]. Statuses are passed, failed,
   timeout and awaiting-human. There is no skipped, not-applicable or not-run; running out of
   budget is recorded as a timeout; and a check waiting for a human counts as success.
7. **Every gate can be escaped by the agent it gates** [3.2, 10.3]. `sisi contract waive
   "<anything>"` needs no approval and resets the gate. After three send-backs the gate lets
   the turn end.
8. **Ceremony follows the size of a diff, not its risk** [5.3, 9, Appendix A]. Forty changed
   lines or three files demand a six-part design essay; a 39-line change to a money parser
   demands nothing. There is no risk model, no change-impact analysis, no selection of checks
   and no reuse of results [5.4, 6.4].
9. **A retro is demanded at every stop that edited anything** [9, 11.1]. That includes a pause
   to wait for background work and a subagent's hand-back. In the session that produced this
   critique the demand replaced a reviewer's ten-point report with a note about its retro, and
   the report had to be requested again. The gate also sent sessions back 34 times in 87
   deliveries, 9 of them in one session for another worker's edits.
10. **Two orchestrators, and the product's is fiction** [7]. `sisi delegate` has no native run
    on record: its 936 ledger rows were imported once from the owner's hand-written `orch.py`,
    which is what actually runs, loaded into every session from his private instructions.
    sisi's router has no prices and no priors, so "cheapest" is arbitrary among flat-plan
    models; 1,875 catalogue entries flood the candidates; there is no delegation contract [7.5],
    no parallelism [7.4] and no cost capture [7.3]. A new user gets none of what produced the
    owner's results.
11. **Self-modification is ungoverned** [11.7, 14.3, 14.4, 16]. A cycle written by any working
    agent may disable or replace any rule, including the ones that require verification and
    retros, and install command checks, with no human asked. The only guards are a size budget
    and an undo.
12. **One incident becomes a universal rule** [11.6]. Scope is the recording agent's claim,
    checked only for whether the text names the project. 30 of 42 lessons were declared
    universal, almost all on one sighting, and are delivered in every project from that moment.
    Promotion counts "showings" that sisi generates by printing the lesson.
13. **The owner's personal preferences drive a product-wide gate** [12]. The design section
    requires one answer per standing principle, and on this machine those include a Claude
    quota and OpenCode prices. Recording a new statement immediately made the contract invalid
    until it was answered. Any user's installation would work the same way with their own.
14. **The learning store is an instruction channel anyone can write** [16]. Text from lessons is
    injected into every later session in every tool. A delegated worker, or any process running
    as the user, can write it. Contract trust gates commands; nothing gates instruction text.

### Missing

15. **No intent or requirement model** [4.1, 4.2]. Explicit, implied, contextual, anticipated
    and experiential requirements collapse into a free-text list of assumptions. Requirement
    surprise and rework cannot be measured.
16. **No time to first useful result, no stall detection, no budgets** [6.1, 6.3, 6.5]. Only
    the time from request to an allowed stop is measured.
17. **No scorecard** [13.1, 13.4]. None of the eight dimensions is recorded per unit and
    nothing is labelled measured, inferred or unavailable.
18. **No independent evaluation** [13.3]. Scores, scope and recurrence are all judged by the
    agent that did the work.
19. **No confidence, contradiction or staleness handling for knowledge** [12]. Lessons never
    expire; a wrong lesson that is rarely shown lives for ever.

### Overbuilt

20. **Forty-one commands, sixteen of which only manage sisi** [8.2, 17]. A retro alone has a
    twelve-line synopsis of required flags. Four taxonomies sit on one lesson record (aim,
    change kind, pattern, topic); four reporters overlap (`improve`, `status`, `time`,
    `scoreboard`); three writers share one store (`overlay`, `cycle`, `promote`); `note` and
    `propose` are self-declared leftovers.
21. **The prompt hook delivers the wrong thing** [7.6, 12]. For a typo fix, a diagnosis question
    and a feature request it returned the same notice about unfiled handover items, and no
    lesson or recipe. For both of the specification's own example requests it delivers
    nothing. Its matcher is word overlap: "fix the race condition" ranks `security-fix` above
    `concurrent-code`.
22. **The retro manufactures lessons** [11.1]. Because one is demanded every time, agents find
    one every time: 42 lessons in one day, 67% of the evidence from sisi working on sisi, 40 of
    42 seen once. Its duplicate check matched a lesson about subagent hand-backs to one about
    check timeouts and refused to record it.
23. **Whole-document rewriting machinery** (861 lines) exists to keep prose tidy.
24. **Scratch state is unbounded**: 22,651 session files, 177 MB.
25. **Eighteen tool adapters, six of which can block a turn.** The documentation is honest
    about this; the count is not a problem, the unverified ones are simply not evidence.

## What is good and stays

- Installation: everything checked before anything is touched, content-addressed backups,
  edits that never re-serialise a user's configuration, byte-for-byte uninstall (verified in a
  sandbox), and hooks that let the turn end on any sisi error.
- The executable contract and the blocking gate with bounded send-backs. It is the one place
  where "done" is evidence and not a sentence.
- The check runner (process-group kill on timeout, parallel cap) and the deep tier
  (fingerprint freshness, detached runs).
- The trust allowlist for running a project's commands.
- Delivery timing measured from the last message the human typed.
- The product, personal and scratch split; personal data as its own git repository; cycles
  that revert exactly.
- Handover of project facts into the project's own documents.
- The transcript evidence layer (`harvest`, `groundtruth`).
- Honesty: `doctor` says "unknown", `sisi rule` says "not enforced", `improve` says "not
  measured", library entries say "what a pass does not prove".
- The test suite: fast, green and sandboxed.
- Routing as pure arithmetic over a judged record, with the reviewer drawn from a different
  maker than the author.

## Verdict for every module

| Module | Lines | Verdict | Why |
|---|---|---|---|
| `cycle.py` | 2052 | Replace the core | Keep exact revert, the base-version lock and enforced checks; add validation, governance and monitoring; remove showing-driven promotion. |
| `retro.py` | 1899 | Replace | Record per [11.4]; a retro grounded in the unit's record; no strength ladder, no lesson list, no mandatory taxonomies. |
| `adapters.py` | 1626 | Keep | Works and is tested; unverified tools are already labelled. |
| `workers.py` | 1053 | Replace the core | One ledger, worker facts, a delegation contract, candidate cap. Keep discovery and failure classification. |
| `gate.py` | 989 | Rebuild | Around risk profiles; retro only at close; pause; subagents pass. |
| `documents.py` | 861 | Simplify | Keep structure checks; drop the trace regime. |
| `wiring.py` | 757 | Keep | Safe install. |
| `overlay.py` | 729 | Keep | The real promotion mechanism; trim its public commands. |
| `release.py` | 665 | Simplify | Keep release, rollback and scrubbed promote; retire developer mode. |
| `verifiers.py` | 616 | Keep, replace the matcher | Match by the structured tags entries already carry. |
| `hookjson.py` | 551 | Keep | The cost of never rewriting a user's JSON. |
| `harvest.py` | 541 | Keep | Evidence source; add token usage. |
| `cli.py` | 532 | Simplify | Fewer commands. |
| `lifecycle.py` | 445 | Keep | Fold `migrate` into `update`. |
| `scope.py` | 273 | Replace the logic | Scope earned by evidence, not claimed. |
| `routing.py` | 261 | Keep the arithmetic | Feed it facts; remove the vendor table. |
| `design.py` | 257 | Retire | Replaced by a requirement model and a risk note where the risk warrants. |
| `taskset.py` | 255 | Keep for the evaluation harness | Built and never run; it is the source of benchmark cases. |
| `prompt.py` | 255 | Simplify | Relevance only. |
| `hookio.py` | 249 | Keep | |
| `groundtruth.py` | 242 | Keep | Validation by replay needs its commits. |
| `contract.py` | 238 | Extend | The work-unit schema. |
| `delivery.py` | 235 | Keep | Becomes unit telemetry. |
| `verify.py` | 230 | Keep, extend | Five statuses, selection, reuse. |
| `handover.py` | 222 | Keep | Remove the per-prompt notice. |
| `deep.py` | 216 | Keep | |
| `store.py` | 211 | Keep | Add pruning. |
| `rulecmd.py` | 210 | Keep | |
| `pdata.py` | 195 | Keep | |
| `watch.py` | 192 | Keep | |
| `tick.py` | 167 | Simplify | Only what the session can act on. |
| `learn_cli.py` | 162 | Merge | Into the one report. |
| `paths.py` | 143 | Keep | |
| `gitutil.py` | 123 | Keep | |
| `audit.py` | 119 | Retire | Counts lines, judges nothing. |
| `principles.py` | 113 | Merge | One path for owner statements. |
| `scoreboard.py` | 100 | Merge | Into the scorecard, labelled inferred. |
| `escapes.py` | 89 | Merge | Into the scorecard. |
| `trust.py` | 46 | Keep | |
| `__init__.py`, `__main__.py` | 5 | Keep | One source for the version. |
| `done/` (20 recipes) | 626 | Keep | Good checklists; fix how they are found. |
| `verifiers/` (140 entries) | 8596 | Keep | Rank entries that ran here above documentation-only ones. |
| `canon/core.md` | 154 | Rewrite | As the operating policy, in the order work happens. |
| `canon/floors.json` | 7 | Replace | Floors by risk profile and technique, not a self-declared number. |

## Verdict for every command

| Command | Verdict |
|---|---|
| `contract` (init, check, waive, trust, untrust) | Keep; `waive` records a deviation instead of passing |
| `verify` | Keep, extend |
| `gate`, `tick`, `prompt`, `watch` | Keep (hooks); rebuilt as above |
| `rule` | Keep |
| `install`, `uninstall`, `doctor` | Keep |
| `release`, `rollback` | Keep |
| `dev` | Retire |
| `promote` | Keep, simplify |
| `migrate` | Fold into `update` |
| `update`, `export`, `import` | Keep |
| `build-canon`, `canon cost` | Internal; size shown by `doctor` |
| `overlay` | Internal except `revert` |
| `audit` | Retire |
| `retro` | Replace |
| `lessons` | Keep, smaller |
| `backlog`, `improve`, `time`, `scoreboard`, `lessons digest` | Merge into `status` |
| `cycle` | Keep, rebuilt |
| `note`, `propose` | Retire |
| `learn`, `oracle` | Keep |
| `design` | Retire |
| `handover` | Keep |
| `status` | Replace with the one report |
| `verifiers`, `done` | Keep |
| `workers`, `route`, `delegate` | Replace the core |
| `harvest`, `tasks`, `escapes`, `checks` | Internal to the evaluation harness |
| `version`, `help` | Keep |
| New: `unit`, `risk`, `approve` | See `docs/target.md` |
