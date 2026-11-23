# Records: the work unit, verification, telemetry and the scorecard

The open work unit is `.sisi/contract.json`. `sisi contract init` starts one and refuses while
another is open. `sisi unit close` archives it; the commands are `sisi unit close [--abandon
"<reason>"]`, `sisi unit pause "<what it waits for>"`, `sisi unit show [ID]` and
`sisi unit list`. `sisi help` lists them with the rest.

## The record

Closing writes `.sisi/units/<id>.json` in the project and one summary line (id, project,
closed time, risk, delivery status, scorecard) to `units.jsonl` in the user store. The archive is
created whole or not at all and is never replaced: closing twice, starting a new unit, abandoning
and a crash between the archive and the reset each leave every earlier record as it was, and a
second `sisi unit close` after a crash completes the close from the archive. An id already taken
by another unit moves the new one to a fresh id.

It holds the fourteen items of SPEC 10.2, the start and closing commits when the project is a
git repository, the risk floor (from the paths changed since the unit started, by the risk
table) beside the declared profile, the delegations the ledger has for the project in the
unit's window, the retro findings and learnings of the unit, and a hash of the policies in
force (rulebook, risk tables, enforced checks, gate and verify settings; it never contains a
path). Closing offers the unit to the evaluation harness as a benchmark case; a failure there
never stops the close.

Delivery status is one of `delivered`, `delivered-with-deferred`, `deviation` (a check was
waived), `unverified` (the gate released the unit after its send-backs) and `abandoned`. A unit
with a failing check cannot close as delivered. A mandatory check that never ran to a pass, or
whose `when_changed` glob matches no file, makes the unit `delivered-with-deferred`, never
plainly `delivered`. `sisi contract waive` records a deviation; it turns nothing green.

A pause records what the unit waits for. While nothing in the tree changes the gate asks
nothing; a change ends the wait. Waiting time is telemetry.

## Verification

Five statuses: `passed`, `failed`, `skipped`, `not-applicable`, `not-run`; the last three always
carry a reason. A timeout is `not-run (timed out)`; a check a person must judge is `not-run (needs
human)`. A failed check blocks, and so does a mandatory not-run other than a recorded deferral or
needing a human.

- A check with `when_changed` runs only when a changed path matches (`skipped (not affected by
  this change)`); one whose globs match no file is `not-applicable`. `--all` runs everything.
- A check whose command and inputs (the watched files, or the whole tree) are identical to its
  last pass is `skipped (reused: passed at ...)`. A failure is never reused. Files git ignores are
  not seen by the whole-tree fingerprint.
- `sisi contract check` refuses a command that cannot fail (`true`, `:`, `exit 0`, `echo`,
  `test 1 = 1`, any of them in `sh -c`, joined with `;` or `&&`, or after `||`). This is a floor,
  not a proof: no analysis finds every constant.
- Every result stores its duration and whether the check has been seen failing in the unit.
  `sisi verify` prints the slowest checks and the time saved by selection and reuse.

## Telemetry and the scorecard

Every value is `{"value", "class"}` with class `measured`, `inferred`, `estimated` or
`unavailable`; an unavailable value has no value, and is never counted as zero. Tokens by
category and model, question dialogs, human messages and inferred corrections come from the
host's transcript when it has one with usage; cost is estimated only when every model used has a
recorded price. Changed files and lines come from git; delegations from the ledger.

The scorecard has the eight dimensions of SPEC 13.1. `sisi status` prints recent units with
their scorecards and then trends by project, risk profile, model and policy version, with the
median and 95th percentile and "too few" under five units. It prints no single score.
`sisi status --learning` prints the learning report.

## Scratch

Session-state files older than `scratch.session_max_age_days` (30) are removed on the first
session start and every `scratch.prune_every`th (20) after it, with no scheduler. A run is
bounded by `prune_max_delete` files and `prune_budget_s` seconds and the next start continues. A
session is kept while it is the current one or its transcript has been written to within the age.
