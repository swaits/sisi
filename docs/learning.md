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
`proposed`, `pending-approval` (a decision waits for the owner), `backlog` (a change to sisi
itself), `implemented`, `validated`, `promoted`, `monitored`, and may end `revised`, `reverted`,
`rejected` or `merged` (into another learning). Showings are never recorded: being printed is not evidence.

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

At least one finding per closed unit. A finding that is only generic advice is refused wherever
the filler appears ("be more careful when writing tests in future"); a short specific one is
accepted ("Tests flaked on CI: 3 of 10 runs"). Things that look like keys, tokens or passwords are
replaced by `<redacted>` before a finding or a learning is stored. Search terms, topics and short
lines are derived by the tool, never demanded.

A finding that resembles a learning **in force in this project** is attached to it as a recurrence,
and the match is printed; `--new` records the finding as a learning of its own instead. Resemblance
searches nothing else. `--same-as ID` names the learning it repeats; for a learning from another
project the finding must plainly be the same thing, and it is that project's own evidence (a unit
there) that adds the provenance, never the resemblance. A unit is counted once for a learning, so
repeating a retro in one unit inflates nothing.

Recorded by a subagent means what the hooks recorded: tick marks a session that started as a
subagent, and the watch hook records, for each shell command, whether its hook payload came from
a subagent (an agent id or a subagent transcript path). `sisi retro` reads that session record; no
environment variable decides it. A subagent's learning is held as a candidate and attaches to nothing;
the parent adopts it with `sisi retro --adopt ID`, never by resemblance. `--target ID` names the rule,
recipe or technique a learning concerns, so `sisi rule`, `sisi done` and `sisi verifiers show` can
list the learnings behind it.

## Scope is earned

A learning is in force in the project it came from at once. It is delivered in other projects only
when its provenance holds at least two units in at least two projects (`organization` scope), or it is
an owner statement made at user scope; a project-scoped statement is delivered only in its project. One
incident never becomes a universal rule. Text delivered into a prompt is framed as background
information to weigh, never as an instruction. Relevance is scored against the learning's own terms, so
a long prompt does not dilute a real match; silence is the default.

Only rows that sisi's own commands wrote, as they wrote them, are delivered or acted on. Each such
command appends the id and content digest of what it wrote to `learnings-ledger.jsonl`, in the same
commit as the row; a row added by hand, or edited by hand, has no matching entry and is never delivered
(`sisi lessons` and the learning report name it). A later sisi write does not launder it.

## The cycle

Promotion is the cycle, due by a counter checked during normal use (no scheduler): five learnings a cycle
can act on arrived since the last cycle, or, fourteen days after it, five still waiting. `sisi cycle` prints
the brief for a cheap worker that has nothing else to read: the complete file format with one filled example
per action, every enumerated value, what happens to each kind of action (takes effect, held for the owner,
refused), and at most eight learnings (flagged first, then the most recurrent, then the oldest), each with its
statement, origin project, source unit and whether commits are recorded, in at most 6,000 characters; what does
not fit waits for the next cycle. The worker writes one JSON cycle file. `sisi cycle check FILE` runs nothing
and lists every problem in the file at once, each with how to fix it; `sisi cycle apply FILE` prints what took
effect, what waits and what was refused in at most fifteen lines. Mechanism kinds a cycle can install in the
user store: an enforced contract requirement (`when` is a risk profile or a path glob: something the code
evaluates), an enforced command check (both in `overlay/enforced.json`), a library entry (recipe or verifier;
it is linted when the file is checked), `rule-add` (one or two sentences added to a named rule before its
`Why:`, naming what the addition shortens or saying nothing can be; the applied message prints the loaded
rulebook size before and after), `rule-replace` (the whole rule; always the owner's), a risk-table adjustment
(`overlay/risk-adjustments.json`), a routing adjustment (`overlay/routing-adjustments.json`), or a benchmark case
(`overlay/benchmarks/<name>.json`). A learning that should not be promoted is `reject`ed with a specific reason
(a generic one is refused) or `merge`d into the learning it repeats. `tool` learnings are never in a brief or in
"due": they have the status `backlog` from the moment they are recorded and go to the tool list in the learning
report and to the contribution export (`sisi promote --export`).

`sisi cycle apply FILE` treats the file as untrusted input and plans everything before writing anything —
the budget and every other check run first, and a refusal applies nothing. If applying then fails part-way
(a full disk), every file the cycle wrote is restored.

- **A mechanism reaches only what its learning earned.** Each entry written carries the learning id,
  the scope the learning has earned (`learning.earned_scope`: its origin project unless it earned more)
  and the origin project. Enforced checks, risk and routing adjustments are filtered by project when read.
  A scope or `every_project` flag in the cycle file is a request for more, never the gate.
- **Replay before promotion** (`evaluate.validate_command`, the one replay implementation). `check` never
  executes anything from the file. `apply` replays a command check only between the two commits the learning's
  own record holds (the start and closing commits of the unit it was found in, from the unit record, or the
  commits stored with the finding; commits named in the file are ignored), in the learning's origin project, on
  the trust list. Each run is in an exported copy of that commit's tree with no `.git` directory (the command
  cannot read history), an environment of PATH, HOME (an empty directory) and LANG only, a time limit, and
  the copy is deleted afterwards. The command must name a path that differs between the two trees, or it is
  refused as vacuous. It is `validated` only if it **ran and failed** at the start (not exit 126/127, not a
  timeout, not killed by a signal; its program, and a script given to an interpreter, must exist at *both*
  commits) and ran and passed at the end, and `before` is an ancestor of `after`; a learning with no recorded
  commits, or any other reason it cannot be shown, leaves it `unvalidated` and waiting for the owner. A replay
  that ran and behaved wrongly refuses the whole cycle. Replay never touches the working tree.
- **Protected rules** (`canon/protected.json`) cannot be replaced or disabled by a cycle or by
  `sisi overlay`. If the file cannot be read, no rule can be changed.
- **Consequential changes wait for the owner**: more scope than the learning earned; an enforced command
  not proven by replay (or that would run outside its origin project); a risk pattern that lowers a
  profile; any whole-rule replacement or disabling of a rule; a sentence added to a rule, or a library entry,
  from a learning confined to one project; a mechanism for a project that no longer exists on disk;
  `sisi overlay replace-rule` and `disable-rule`. They are stored as pending and take effect only after
  `sisi approve ID --yes|--no`. While a decision waits, its learning is `pending-approval`; promoting it
  again is refused, and so is a second change to a rule that has one waiting. If the owner refuses, the
  learning is rejected, not proposed again.
- **`sisi approve`** with no arguments lists every waiting change in full: the command, the pattern and
  profile, the rule text as a diff, why it needs the owner, and the replay result. A decision needs the word
  `sisi approve ID --yes|--no` prints typed back at the controlling terminal device (never standard input), and
  the before-tool hook refuses any shell command of an agent that invokes it; a process with no controlling
  terminal is refused unless the user config sets `learning.agent_relayed_approval`. Every decision, and every
  refused attempt, is recorded in `approvals.jsonl` (when, session, terminal or not, `relayed by an agent`).
  Session start prints one line while a decision is waiting, telling the agent to ask the owner through
  the host's question dialog and to give him the command to run himself. SECURITY.md says what this does and
  does not guarantee.
- **Flagged learnings must be acted on** (below); a cycle that ignores one is refused.
- Each change is its own commit in the user store, and each cycle (and each approval) is recorded with the
  files and learning fields it changed. `sisi cycle revert [ID]` undoes exactly those: statements, findings
  and recurrences recorded after the cycle survive, and a revert is refused if a later change touched the
  same file.
- A learning that was validated but waits for the owner is `pending-approval` with its validation result kept;
  once promoted and a unit in its scope has closed, or it has recurred, `monitored`.
- An origin project is always the main repository's key, never a linked worktree's path; `sisi update` repairs
  records and mechanisms written before that (and statuses: tool learnings to `backlog`, learnings with a
  decision waiting to `pending-approval`).

## Monitoring

A recurrence after promotion counts against the learning (once per unit). Two flag it "not working";
the next cycle must revise or revert it. `sisi status --learning` prints only
`learning.learning_report()`: per promoted learning the units in its own scope since promotion
(read from `units.jsonl` in the user store, one JSON object per line with `id`, `project`, `closed_at`,
`risk`; the file may not exist yet, which counts as none), the recurrences, whether it is validated or
unvalidated, and the verdict, plus the realization rate (promoted learnings holding with no recurrence over
at least five units in their scope) — or "too few" when the numbers are small. A project-scoped learning
counts only its project's units. No claim of improvement is printed from counts of records.

## Owner statements

One path: `sisi learn "<what you want>"` writes an owner statement into the same learning store, live
at once; `sisi oracle` prints the ones in force in the current project. A user-scope statement is
delivered everywhere, a project-scoped one only in its project. The record says whether the quoted words
appear in a human-typed message of the session transcript (`typed by the owner`) or not, or no transcript is
available (`relayed by an agent`); it is never blocked, and `sisi oracle` shows the relayed ones as such.
`sisi learn --withdraw ID --reason "..."` withdraws a statement recorded by mistake: kept in its history,
never delivered again.

## Migration

`sisi update` (and `sisi learn`/`sisi oracle`) run the learning migration whenever the
old store exists and the `learnings-migrated.json` marker does not: a backup first, merged by legacy id
(a lesson already carried over is not carried twice; a learning recorded before the first migration does
not stop it). Old lesson rows become learning records with honest statuses (a lesson folded into prose
is `implemented`, always unvalidated; nothing becomes `validated`); occurrences become provenance with the
old `repo` values normalised to the project key new code uses, and only occurrences that attach to a
lesson are counted; impressions, sightings and pattern rows are not carried (the backup keeps them);
owner statements join the same store with their scope, duplicates dropped. Malformed lines are counted and
reported, not hidden. A migrated learning is earned beyond its project only under the same
two-units-two-projects rule as a new one. The sqlite store is read too.

## The product

`sisi promote --export` writes the contribution file for `tool` learnings and for learnings that earned
organization scope (scrubbed: no history, no user or project names); `sisi promote L-NNNN [--apply]`
writes the rule or recipe such a learning was folded into into the source folder and marks the learning
`in_product`. `sisi handover` lists the project-scope learnings and statements waiting to be filed in
their own project's documents. `sisi rule ID`, `sisi done ID` and `sisi verifiers show ID` list the
learnings in scope that target that entry.

## Seams for other parts of sisi

- `learning.findings_for_unit(project, unit_id)` — the findings a unit record stores.
- `learning.learning_report()` — the text `sisi status --learning` prints, the one learning report.
- `cycle.enforced_results(contract, project, ...)` — what `sisi verify` runs, filtered by project.
- `cycle.risk_patterns(cwd)` — the learned risk patterns that apply in a project (`risk.load_patterns`).
- `cycle.routing_adjustments(project)` — the learned routing adjustments that apply in a project.
- `cycle.due_notice()` — the session-start lines (cycle due, decision waiting).
- `learning.delivery_text(project, query, targets=())` — what the prompt hook may add.
- `evaluate.validate_command(repo, before, after, cmd)` — the replay.

## What this does not do

Replay validation needs commits and a trusted project; without them a check stays
unvalidated and waits for the owner. Being shown is never evidence, and one incident never
earns wider scope on its own.
