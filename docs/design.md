# How sisi meets SPEC.md

This document describes sisi as it is built. Section numbers in brackets are sections of
`SPEC.md`, which is the standard. Where this document and the specification disagree, the
specification wins. For the dated record of how the rebuild was decided, see
`docs/reconciliation/`.

**sisi** is still improving: this design describes the current system, and the learning loop
in section 8 is how it changes.

## 1. What sisi is

sisi is the operating layer that makes a host AI coding tool behave as the engineering
organization the specification describes, makes that behaviour observable, and improves it from
evidence. The host tool supplies the agent. sisi supplies five things:

1. **An operating policy**: a short rulebook of strategic direction, always loaded. The agent
   works out the tactics.
2. **Records**: the work unit, its verification record, its telemetry and its scorecard.
3. **Gates**: executable checks at the moments a host exposes (session start, prompt, tool
   use, end of turn).
4. **A learning loop**: evidence, learning record, mechanism, validation, promotion,
   monitoring, revert.
5. **An orchestration record**: which workers exist, what they cost, how they performed.

Standing constraints from the owner, which bind every part:

- Python standard library only. No scheduler: anything periodic is a counter checked during
  normal use.
- Works in any host tool, and uses the host's native mechanisms first.
- Nothing in the product names a specific model, price, person or version.
- A behaviour is wanted either as a mechanism or as policy that is measured. Prose that
  nothing checks or measures is removed.
- One of everything. When something is replaced, the old one is deleted in the same change.

## 2. Where things live [12]

| Layer | Path | Holds | Rule |
|---|---|---|---|
| Product | the clone and its stable copy | code, `SPEC.md`, base rulebook, library, default risk table, strategy text | True for every project and every user. Never written at run time. A test scans it for owner-specific names, model ids, prices and home paths. |
| User | `~/.local/share/sisi` (a git repository) | owner statements, `learnings.jsonl`, `findings.jsonl`, `units.jsonl`, `delegations.jsonl`, `worker-notes.json`, the mechanisms promoted from learnings, worker facts | This user, all projects. |
| Project | `<project>/.sisi/` | the open contract, closed unit records, project risk overrides | This project only. Project knowledge itself goes in the project's own docs (handover). |
| Scratch | `~/.local/state/sisi` | session state, caches, logs | May be deleted. Pruned by age during normal use. A release is made from the running launcher's folder. |

`sisi update` on an installed copy runs the migration step for the old store as part of the
update. The specification's "organization-wide" scope is the product. A user's learning reaches the
product only through `sisi promote` / `--export`, scrubbed.

## 3. Risk profiles [5.3, 9, Appendix A]

Ceremony is set by risk, not by the size of a diff. The profiles, lowest first:
`trivial`, `isolated`, `logic`, `integration`, `data`, `critical`, `release`.

`sisi risk [--json]` computes a **floor** from the paths changed since the unit started, using
`canon/risk.json`: glob and keyword patterns mapped to profiles. Defaults: documentation, text
and styling only is `trivial`; one module's behaviour is `isolated`; algorithms, parsing, money
and state machines are `logic`; several top-level packages or a public interface is
`integration`; schema, persistence and migration is `data`; authorization, secrets, crypto,
payments, concurrency primitives, installers and hooks is `critical`. A project may override in `.sisi/risk.json`. The floor is a minimum, not a verdict: it was
measured against independent labels (`measured` in `canon/risk.json`) and agrees about five
times in six, which is why the declared profile sits above it. A learning of mechanism type `policy` may adjust the user's table.
A contract must declare `risk.profile`; it may raise the floor freely and lower it only with
`risk.why`. The record keeps both the floor and the declared profile.

What a profile requires. The gate enforces exactly this table and nothing else:

| Profile | Contract | Checks | Requirement model | Risk note | Independent evidence | Retro at close |
|---|---|---|---|---|---|---|
| trivial | no | the diff; a targeted check when one exists | no | no | no | only on an anomaly (two send-backs, or a human correction) |
| isolated | yes | at least one that is not vacuous | no | no | no | yes |
| logic | yes | as isolated, each with `covers` | no | no | no | yes |
| integration | yes | as logic, plus invariants and an `approach` | yes | yes | no | yes |
| data, critical | yes | as integration | yes | yes | yes | yes |
| release | yes | every check (`--all`) | yes | yes | yes | yes |

"Requirement model" is the contract's `requirements` list (section 4); an `approach` is the
contract's `approach` object with `chosen`, `why` and at least one alternative. Text such as `TODO`,
`n/a` or `none` fills no field. The table is held as data in `canon/risk.json` (`requirements`, with
machine keys beside the prose ones) and read by the gate. "Risk note" is
`risk.blast_radius` and `risk.rollback`. "Independent evidence" is an accepted review delegation
in the ledger for this project inside the unit's window with a check stronger than `none`, or a passing check
marked `"independent": true` that names who or what produced it in `"by"`.

## 4. The work unit [10]

The open unit is `.sisi/contract.json`. New fields are optional unless the profile requires them.

```json
{
  "id": "…", "parent": "request or workstream id",
  "goal": "the human's words", "scope": {"in": ["…"], "out": ["…"]},
  "requirements": [
    {"id": "q1", "kind": "explicit|implied|contextual|anticipated|experiential",
     "text": "…", "decision": "now|architect|defer|ignore", "why": "…", "check": "check id or null"}
  ],
  "risk": {"profile": "logic", "why": "…", "blast_radius": "…", "rollback": "…"},
  "checks": [
    {"id": "…", "claim": "…", "cmd": "…", "expect": {"exit": 0}, "rung": 2, "tier": "fast",
     "covers": "the failure this would catch", "when_changed": ["src/parser/**"],
     "mandatory": true, "independent": false}
  ],
  "invariants": [], "assumptions": [], "questions": [],
  "deferred": [{"what": "…", "why": "…", "safe_because": "…"}],
  "limitations": [], "plan": []
}
```

- `sisi contract init` starts a unit. If the previous unit is closed it is replaced. If it is
  still open the command refuses and names `sisi unit close --abandon "<reason>"`, which
  records the disposition [10.3].
- `sisi unit close` archives the unit to `.sisi/units/<id>.json` and appends one summary line
  to the user store's `units.jsonl`. The archived record carries the fourteen items of [10.2]:
  id and parent; outcome and scope; requirements; acceptance checks and invariants; risk
  profile (floor and declared); plan and the workers used; models and budgets; start, end and
  telemetry; changed artifacts; every verification result; deferred checks, limitations and
  open risks; delivery status; the scorecard; the retro findings and the learnings they made.
  It also carries the **policy version**: a hash of the effective rulebook, the enforced checks
  and the risk table, so every unit says which policies were in force [11.6].
- `sisi unit pause "<what it waits for>"` records a wait and lets the turn end with no
  demands. The pause also ends when the tree changes or `sisi verify` runs. Wait time is
  telemetry [6.1].
- `sisi unit show [ID]` prints a record. Nothing is ever overwritten or lost.
- Delivery status is one of `delivered`, `delivered-with-deferred`, `deviation` (a check was
  waived), `unverified` (the gate released after its send-backs ran out), `abandoned`.

## 5. Verification [5.4, 5.5, 5.6, 6.4]

- **Five statuses**: `passed`, `failed`, `skipped`, `not-applicable`, `not-run`, each of the
  last three with a reason. A timeout is `not-run (timed out)`. A check that needs a person is
  `not-run (needs human)`. Nothing that did not run is ever reported as passed.
- **What blocks**: a `failed` check, or a mandatory check that is `not-run` for any reason other
  than a recorded deferral or needing a human. A mandatory check that is `not-applicable` and
  has never passed counts as never run. A unit that closes with deferred or human-pending
  checks is `delivered-with-deferred` and the record lists them. Failed checks keep their
  failure evidence with the result, so a later reader can see what failed without re-running.
- **Selection by change**: a check with `when_changed` runs only when a changed path matches;
  otherwise it is `skipped (not affected by this change)`. A check without it always runs.
  `--all` runs everything. The reason is recorded, which is the justification [5.4] asks for.
- **Reuse**: a check whose inputs (the tree restricted to its `when_changed`, or the whole
  tree) are identical to those of its last pass is `skipped (reused: passed at <time>)`.
- **Vacuous checks are refused**: `sisi contract check` rejects a `cmd` that cannot fail
  (`true`, `:`, `exit 0`, a bare `echo`, and the like).
- **Seen failing**: the record notes for every check whether it has ever been observed to fail
  in this unit (red before green). It does not block; it is reported as evidence quality.
- **Waiver**: `sisi contract waive` no longer makes a unit pass. It records a deviation with
  its reason; the unit's delivery status becomes `deviation` and the completion report must
  say so.
- Slow checks run in the background and block only a `release` change. A command check that
  replay did not validate always waits for the owner before it takes effect.
- **Cost**: every result stores its duration; `sisi verify` prints the slowest checks and
  the time saved by selection and reuse.

## 6. Telemetry and scorecard [6.1, 13]

Every value carries a class: `measured`, `inferred`, `estimated` or `unavailable`. Missing data
is `unavailable`, never zero and never good.

Sources: the hooks (request start, human messages, stops, send-backs, pauses), the host's
transcript where it exposes one (token usage by category and model, question dialogs,
subagent runs), the delegation ledger, git (changed artifacts), and the verification record.

The scorecard has the eight dimensions of [13.1]:

| Dimension | Recorded |
|---|---|
| Intent fulfilment | requirements with a passing check; requirements added after the first verification (surprise); human corrections after delivery (inferred) |
| Correctness and assurance | results by status; techniques used; checks seen failing; independent evidence; deviation or unverified flags |
| Delivery velocity | time to first useful result (first allowed stop after the request); time to validated completion (close); time in checks, in waits, in delegations |
| Resource efficiency | tokens by category and model; cost from known prices (estimated); retries |
| Parallelism | delegations, how many overlapped, worker minutes against wall time |
| Human experience | human messages, question dialogs, corrections (inferred) |
| Lifecycle quality | files and lines changed, tests changed with code, public surface touched |
| Organizational improvement | findings, learnings created, recurrences of known failures in this unit |

`sisi status` is the one report: the last five units with their scorecards, then trends by project,
risk profile, model and policy version, with the median and the 95th percentile, and "too few"
where a segment has fewer than five units. It replaces `improve`, `time`, the old `status`,
`scoreboard`, `lessons digest` and `backlog` as separate reporters. No single score is printed.

## 7. The gate [9, 10.3, 17]

At the end of a turn in which the session changed something:

1. Compute the risk floor. If the profile requires a contract and none is open, say so.
2. Run the selected fast checks. A blocking result sends the agent back with the failures.
3. If the profile's other requirements are missing (requirement model, risk note, independent
   evidence), say which.
4. If everything is green and the unit is not closed, offer the two ways on: record the retro
   (`sisi retro`), which closes the unit; or `sisi unit pause "<what it waits for>"`.
5. A paused or closed unit with no new change passes silently.

In this build the retro is offered once for each state of the tree and a trivial change is asked
nothing (unless the unit shows an anomaly); a recorded retro closes the unit. A session is judged only on
its own edits, so another session's work in the same tree never sends it back. The detail is in
docs/records.md, "The end-of-turn gate".

Send-backs stay bounded; when they run out the unit is released as `unverified` and recorded
as such. A session marked as a subagent is never blocked and never sent back for a retro: a
subagent's last message is its report to its parent and must stay that. The question-dialog
gate stays as it is.

## 8. The learning loop [11, 14.4]

**The retro** runs when a unit closes. It is grounded in the record: `sisi retro` with no
arguments prints the unit's scorecard and what stands out in it. Each finding is recorded with:

```
sisi retro --finding "<what happened, with the evidence>" --cause "<root cause>"
           --impact value|correctness|time|cost|attention
           --disposition promote|record|drop
   promote: --change "<the exact improvement>" --mechanism policy|orchestration|skill|tool|infrastructure|verification|knowledge|benchmark
            --scope organization|user|project|task-class --expect "<observable effect>" --validate "<how it will be tested>"
   record:  --limits "<where it applies and where it does not>"
   drop:    --why-not "<why it is not worth promoting>"
   [--same-as ID]
```

At least one finding per closed unit; generic findings are refused as now. Search terms,
topics and short lines are derived by the tool, not demanded. A finding that resembles an
existing learning is attached to it as a recurrence candidate instead of being refused.

**The learning record** follows [11.4]: id, title, source unit, observation (evidence,
impact), root cause, proposed change (description, mechanism type, scope, target), expected
effect, validation (method, benchmark), status, version, provenance (every unit and project it
was seen in), confidence. Status moves through `observed`, `analyzed`, `proposed`,
`implemented`, `validated`, `promoted`, `monitored`, and may end `revised`, `reverted` or
`rejected`.

**Scope is earned.** A learning is in force in the project it came from at once. It is
delivered in other projects only when its provenance has at least two units in at least two
projects, or it is an owner statement. One incident never becomes a universal rule [11.6].
Learnings recorded by a subagent are held as candidates until the parent's retro includes them.
`sisi learn --withdraw` takes an owner statement recorded by mistake out of delivery while
keeping it in history.

**Promotion** is the cycle, due by a counter. A cycle turns proposed learnings into
mechanisms in the user store: an enforced contract requirement, an enforced command check, a
library entry, a risk-table or routing adjustment, a benchmark case, or rule text. Changes to
sisi's own code are `tool` learnings: they go to the backlog and the contribution export.
`sisi cycle apply`:

- **validates before promoting**. A command check is replayed on the commits of the unit it
  came from where they are known (must fail before the fix, pass after). What cannot be
  replayed is promoted as `unvalidated` and reported as such; it is never called validated.
- **commits** each change to the user store; revert is exact, as now.
- **refuses** to touch protected rules (`canon/protected.json`: the non-negotiable
  constraints, verification before done, truthful reporting, this governance). Disabling a
  rule, widening a scope to everything, or adding a command that runs in every project is
  consequential: it is stored as pending and takes effect only after the owner's decision
  (`sisi approve ID --yes|--no`, asked through the host's question dialog). `sisi approve`
  refuses a decision made without a terminal unless a config setting allows relayed approval.
- **must act on flagged learnings**: see monitoring.

**Monitoring.** A recurrence after promotion counts against the learning. Two recurrences flag
it "not working"; the next cycle must revise or revert it. `sisi status --learning` shows, per
promoted learning, units since, recurrences and a verdict, and the realization rate
(promoted learnings holding with no recurrence over at least five relevant units).
Being shown is not evidence: showings never promote anything.

## 9. Orchestration [7]

The product gives direction and keeps the record. It names no model.

**Direction** (one rule in the rulebook, a longer playbook on demand in `canon/orchestration.md`):
the main agent owns the outcome; give each task to the least expensive worker that is
sufficiently capable, counting rework as cost; use the host's own delegation first; run
independent work in parallel when it shortens the critical path; write a delegation contract;
judge what comes back in proportion to risk and record the judgement; treat an unavailable
worker as temporary; keep finding out what exists, what it costs and how good it is; keep the
strongest model for judgement and hand the legwork down, including the legwork of orchestration
itself (discovery, price and benchmark research, first-pass review can go to a fast cheap
worker).

**The record** (user store):

- `sisi workers`: the tools and models found on this machine, what is usable now, and the
  judged record as three tables: by task type and difficulty; what fixed each rejection (a
  better brief, a stronger worker, nothing); how good the difficulty guesses were.
- **Worker facts**: prices and benchmark standing, each with a source and a date, written by
  `sisi workers fact …`. When facts are missing or old, session start says so in one line and
  asks for a cheap worker to research them. Nothing is hard-coded.
- Routing treats a worker id with no provider prefix as the host's own subagent.
  `sisi workers note` records a standing fact about matching workers and `sisi workers only`
  restricts routing to matching models of one provider; both are honoured by `sisi route`.
  `sisi workers down --until` accepts a date or a time, after which the worker is usable again.
- `sisi route --kind K --difficulty N [--explain]`: the recommendation. Candidates are only
  workers with a judged record, a known price or a benchmark prior. With a thin record it
  ranks by price and prior instead of arbitrarily, and about one low-stakes task in ten goes
  to a cheaper worker with a thin record. `sisi workers avoid|prefer PATTERN --why` holds the
  user's own constraints.
- `sisi delegate judge …` is the only way a result enters the ledger (type, difficulty, worker,
  outcome, strongest check applied, minutes, tokens, retry-of). `amend` marks one that later
  proved wrong. `down`/`up` record availability. The ledger is where a unit's delegation
  telemetry and the parallelism measure come from.
- **Delegation contract** [7.5]: `sisi delegate brief` prints the template (outcome and scope,
  context and sources of truth, constraints and interfaces, acceptance, deliverables and
  report format, files it may change, verification expected, budget, when to escalate);
  `sisi delegate check FILE` says which parts a brief lacks.
- `sisi delegate --brief FILE …` still runs a worker through its own CLI when the host has no
  delegation of its own.

The owner's hand-written orchestrator (`orch.py`, its ledger, and the section of his Claude
instructions) is replaced by this. Its ledger is merged into the user store with a row count
check, then it is removed.

## 10. The rulebook

`canon/core.md` is rewritten as the organization's operating policy, in the order work happens.
Each rule states the behaviour, the reason, and what enforces or measures it.

1. Own the outcome: intent, the five kinds of requirement, when to ask [4].
2. Size the work by risk [5.3, 9].
3. Define done before building: checks that can fail; invariants for what exists [5.1, 10].
4. Verify with the minimum sufficient evidence, and report it honestly [5.4, 5.6].
5. Deliver fast: first useful result early, parallel work, reassess when stalled [6].
6. Orchestrate: cheapest adequate worker, delegation contract, judge and record [7].
7. Report plainly and in proportion [17].
8. Close with a retro grounded in the record [11].
9. Stay inside the lines: authorization, security, privacy, data as data, truth [3.2 tier 0, 14, 16].

Owner statements (`sisi learn`, printed by `sisi oracle`) are user data. They are loaded as
"what this user wants" and never drive a product-wide gate.

## 11. What a session is given [7.6, 12, 17]

- **Always**: the rulebook and the user's statements.
- **Session start**: nothing unless this session can act on it: broken wiring, a cycle that is
  due, a decision waiting for the owner, stale worker facts, handover items for this project
  (once per session). No lesson lists, no backlog.
- **Each prompt**: at most 2,000 characters, and only what matches the request: the recipe
  chosen by structured tags, and learnings in scope. Silence is the default.
- **End of turn**: only what section 7 says.

## 12. Commands by reader

`sisi help` lists every command and `sisi help COMMAND` explains one in full. Commands group
by who uses them. For the owner: `sisi install`, `sisi uninstall`, `sisi doctor`,
`sisi update`, `sisi status`, `sisi rollback`, `sisi approve`, `sisi oracle`, `sisi export`
and `sisi import`. For the agent at work: `sisi contract`, `sisi unit`, `sisi risk`,
`sisi verify`, `sisi retro`, `sisi learn`, `sisi route`, `sisi delegate`, `sisi workers`,
`sisi verifiers`, `sisi done`, `sisi rule`, `sisi handover` and `sisi lessons`. For hooks:
`sisi tick`, `sisi prompt`, `sisi gate` and `sisi watch`. For maintaining sisi itself:
`sisi release`, `sisi promote`, `sisi cycle`, `sisi version` and `sisi help`.

## 13. Evaluation

Evaluation replays real work under different policies and compares the records. Cases come
from closed units, runs stay isolated from the live stores, and an independent judge scores
the outcome. A comparison is a sample of past work, not a proof about future work. See
`docs/evaluation.md`.
