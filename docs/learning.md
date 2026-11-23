# The learning loop

How sisi turns what happened in one work unit into a mechanism that helps the next.
The rule throughout: a behaviour is wanted either as a mechanism or as policy that is
measured. Prose that nothing checks or measures is not learning.

## The record

One store: `learnings.jsonl` in the user store (`~/.local/share/sisi`), one JSON object
per learning, committed to that folder's git repository — git is the history. Retro
findings live in `findings.jsonl`. There is no second copy and no database mirror.

A learning record carries: id, title, source unit, observation (evidence and impact),
root cause, the proposed change (description, mechanism type, scope, target), expected
effect, validation (method, benchmark, result), status, version, provenance (every unit
and project it was seen in) and confidence. Status moves through `observed`, `analyzed`,
`proposed`, `implemented`, `validated`, `promoted`, `monitored`, and may end `revised`,
`reverted` or `rejected`. Showings are never recorded: being printed is not evidence.

## The retro

`sisi retro` with no arguments prints the unit's record and what stands out — it reads
`sisi.unit.summary_for_retro(project)` when that module is present, otherwise the open
contract and the verification results on record. Each finding is then recorded with a
disposition, and only the fields that disposition needs:

```
sisi retro --finding "<what happened, with the evidence>" --cause "<root cause>"
           --impact value|correctness|time|cost|attention
           --disposition promote|record|drop
  promote: --change "<exact improvement>" --mechanism policy|orchestration|skill|tool|
           infrastructure|verification|knowledge|benchmark --scope ... (optional)
           --expect "<observable effect>" --validate "<how it will be tested>"
  record:  --limits "<where it applies and where it does not>"
  drop:    --why-not "<why it is not worth promoting>"
  [--same-as ID]
```

At least one finding per closed unit; generic findings ("be more careful") are refused.
Search terms, topics and short lines are derived by the tool, never demanded. A finding
that resembles an existing learning is attached to it as a recurrence candidate — it is
recorded, not refused. Learnings recorded in a subagent session are held as candidates
until a parent retro adopts them (`--same-as`).

## Scope is earned

A learning is in force in the project it came from at once. It is delivered in other
projects only when its provenance holds at least two units in at least two projects, or
it is an owner statement. One incident never becomes a universal rule. Text delivered
into a prompt is framed as background information to weigh, never as an instruction,
and only learnings that entered through sisi's own commands (`retro`, `learn`, `cycle`,
migration) are ever delivered. Silence is the default.

## The cycle

Promotion is the cycle, due by a counter checked during normal use (no scheduler):
`sisi cycle` prints the brief for a cheap worker, which writes one JSON cycle file
(`sisi cycle help` is the format). Mechanism kinds a cycle can install in the user
store: an enforced contract requirement, an enforced command check (both in
`overlay/enforced.json`), a library entry (recipe or verifier), rule text, a risk-table
adjustment (`overlay/risk-adjustments.json`), a routing adjustment
(`overlay/routing-adjustments.json`), or a benchmark case
(`overlay/benchmarks/<name>.json`). `tool` learnings — changes to sisi's own code — are
refused by the cycle; they go to the backlog shown in the learning report and to the
contribution export.

`sisi cycle apply FILE` treats the file as untrusted input and validates everything
before changing anything — a refusal applies nothing:

- **Replay before promotion.** A command check is run in a temporary git worktree at
  the before-commit and the after-commit of the unit it came from; it must fail before
  the fix and pass after. Only then is the learning `validated`. What cannot be
  replayed is promoted as `unvalidated` and always reported as such. A replay that
  fails refuses the whole cycle. Replay never touches the user's working tree.
- **Protected rules** (`canon/protected.json`: verification before done, truthful
  reporting, this governance) cannot be replaced or disabled by a cycle at all.
- **Consequential changes wait for the owner**: disabling any other rule, widening a
  scope to all projects, or a command check for every project is stored as pending and
  takes effect only after `sisi approve ID --yes|--no`. Session start prints one line
  while a decision is waiting.
- **Flagged learnings must be acted on** (below); a cycle that ignores one is refused.
- Each change is its own commit in the user store, and the cycle records the
  before/after commits, so `sisi cycle revert [ID]` restores the store exactly.

## Monitoring

A recurrence after promotion counts against the learning. Two flag it "not working";
the next cycle must revise or revert it. `sisi status --learning` prints
`learning.learning_report()`: per promoted learning the units since promotion, the
recurrences, whether it is validated or unvalidated, and the verdict, plus the
realization rate (promoted learnings holding with no recurrence over at least five
relevant units) — or "too few" when the numbers are small. No claim of improvement is
printed from counts of records.

## Owner statements

One path: `sisi learn "<what you want>"` writes an owner statement into the same
learning store, live at once and delivered in every project; `sisi oracle` prints them.
The old `learn.jsonl` / `oracle.md` stores were merged into it by migration.

## Migration

`sisi update` (and `sisi migrate`) runs the learning migration once, with a backup
first and idempotently: old lesson rows become learning records with honest statuses (a
lesson folded into prose is `implemented`, always unvalidated; nothing becomes
`validated`), occurrences become provenance, impressions — sisi's own showings — are
dropped, and owner statements join the same store. A store with only the old sqlite
database is read from the database itself. Learnings whose provenance does not meet
the two-units-two-projects rule are delivered only in their origin project, whatever
scope they once claimed.

## Seams for other parts of sisi

- `learning.findings_for_unit(project, unit_id)` — the findings a unit record stores.
- `learning.learning_report()` — the text `sisi status --learning` prints. It replaces
  `sisi improve`, `sisi backlog` and `sisi lessons digest`, which are deleted.
- `cycle.enforced_results(contract, project, ...)` — what `sisi verify` runs.
- `cycle.due_notice()` — the one session-start line (cycle due, decision waiting).
- `retro.satisfied(repo, since, fp)` and `retro.TEMPLATE` — what the gate asks.
- `learning.delivery_text(project, query)` — what the prompt hook may add.
