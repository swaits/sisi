# Evaluation

The harness that answers "is sisi getting better?" with evidence instead of claims. A
learning cycle changes the policy (rules, checks, routing, guidance); this replays
representative past work under the old and the new policy and puts the results side by side.
Section numbers in brackets are sections of `SPEC.md`.

## Concepts

- A **case** is one replayable piece of real work, stored as JSON in the user store under
  `benchmarks/<id>.json`. The product ships no cases from any real project.
- A **replay** runs a case in a temporary checkout of the case's repository and records
  what happened. Nothing replays in the user's working tree, and the temporary copy is
  removed afterwards whatever the outcome.
- A **policy version** is a hash of the effective policy: the product rulebook plus the
  store's generated rulebook, overlay and config. A run may also be labelled by hand
  (`--policy NAME`); the hash is then kept beside the label.
- **Results** live in the user store as `eval-results.jsonl`: one row per run with the
  case, split, policy version, worker, outcome, minutes, tokens and cost, every value
  carrying its class (measured, estimated, unavailable) [13.4].

## The case format

```json
{"id": "case-name", "kind": "check",
 "source": {"unit": "the work unit it came from", "learning": "or the learning"},
 "project": {"repo": "path or remote", "start_commit": "before the work",
             "fix_commit": "after the work"},
 "request": "the human's own words",
 "checks": [{"id": "tests", "cmd": "the check command", "expect": {"exit": 0}}],
 "tags": ["task class"], "split": "dev", "added": "<date>"}
```

Two kinds and three splits:

- `check`: the command must **fail at `start_commit` and pass at `fix_commit`**. That is
  what "validated" means for a promoted command check [11.5]. Passing at both is
  `failed-to-fail` (the check proves nothing); failing at both is `failed-to-pass`.
- `task`: starting from `start_commit`, a worker given `request` under the policy under
  test must produce a tree on which the checks pass.
- `dev` cases are for tuning. `holdout` cases are held out: a tuning run (`--split dev`)
  and a shadow evaluation must never include them, and they run only when named.
  `counterexample` cases must **still pass**: they are the guard against overfitting a
  rule to the incident it came from [11.6].

## How cases accumulate

- From finished work: `sisi.evaluate.capture_case(unit_record)` is called when a unit
  closes. A unit with a repository, a start commit and command checks becomes a case;
  its id and dev/holdout split are deterministic, so re-capturing changes nothing.
- From the harvested task set: `sisi eval import` converts the replayable harvested tasks
  (graded A or B, with a test command) into cases. Their split is the same deterministic
  hash as the task's. The old hidden `sisi tasks` and `sisi checks` commands are served
  by this module now; `sisi harvest` itself is unchanged.
- By hand: `sisi eval add case.json`, or `sisi eval add --id ... --check ...`.

## Replay and cost

`sisi eval run` with no arguments replays only `check` cases: that needs no AI tool and
spends nothing. `task` cases spend real money, so they run only with an explicit
`--tasks N`. Before any task replay the command prints the estimated cost, worked out
from the median cost of recorded task runs, or the word `unknown` when nothing has been
recorded. A per-invocation hard cap can be set in the personal config
(`{"eval": {"max_cost_per_run": VALUE, "timeout_s": SECONDS, "worker_timeout_s": SECONDS}}`);
a known estimate above the cap refuses the run, and the cap also stops further task
cases once the known spend reaches it.

A task replay hands the request to a worker through the existing delegate runner, with a
brief that carries the policy under test, then runs the case's checks on the result. A
run that cannot happen (repository gone, commit missing, timed out, no worker) is
recorded as `not-run` with its reason, never as a pass [13.4].

## Comparing policies

`sisi eval compare A B` treats A as the baseline and B as the candidate, over the cases
**both** ran: pass rate, median and 95th-percentile minutes, and cost, each beside its
counter-metric (a speed or cost figure is meaningless without the pass rate next to it),
plus the same break-down per task class [13.5]. Under five common cases it says "too
few" and claims nothing. Cases only one side ran are listed, not ignored, and
unavailable cost is never counted as zero. A candidate that fails cases the baseline
passed is called "not an improvement" in so many words, however much faster or cheaper
it is. There is deliberately no single score.

`sisi eval shadow DIR` does the same for a candidate policy that exists only as a copy of
the user store (a learning cycle applied to the copy, not to the real store): it runs a
sample of dev cases plus every counterexample under the current policy and the candidate
and prints the comparison, before anyone is asked to approve the change [11.6]. The
learning loop calls the same code as `sisi.evaluate.compare_for_candidate(dir, sample)`,
and calls `sisi.evaluate.validate_check(case)` before promoting a command check.

## Independent judging

`sisi eval judge RESULT_ID` asks a worker from a **different maker** than the one that
did the run (chosen through the routing module's reviewer selection) to read the request,
the diff and the check results and answer met or not met for each acceptance item, with
one line of reason [13.3]. The judgement is stored with the result as `judged_by`. A
judge from the same maker is refused: a worker's own assessment is never recorded as
independent evidence.

## Honest limits

- A replay is a **sample**, not the original work: the worker, its context and the state
  of the world have all moved on. Outcomes are comparable between policies run the same
  way; they are not a rerun of history.
- A pass rate over a handful of cases says little, which is why the comparison refuses to
  claim improvement under five common cases and splits figures by task class instead of
  hiding a bad one behind a good one.
- Holdout cases exist to catch tuning that overfits the cases it was tuned on. Using them
  to tune a rule quietly converts them into dev cases and destroys their value: run them
  to check, never to adjust.
- A check case that passes at both commits may still be a useful check; it is only a bad
  *benchmark case*, because it cannot distinguish a fixed tree from a broken one.
- Cost and token figures are as good as what the worker tools report. Where nothing is
  reported they stay "unavailable", and the harness will not invent precision to fill
  the gap.
