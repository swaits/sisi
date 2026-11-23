# Orchestration

Objectives, not tactics. Work out the tactics for the tools and models actually
present; nothing here names one. Read on demand: `sisi delegate guide`.

## Who owns what

- The main agent owns the outcome. Delegation never transfers accountability:
  it plans, splits, integrates, verifies, and answers for the whole.
- Workers are specialists and critics. Their reports are evidence to judge,
  not facts to relay.
- Keep the strongest model's context for judgement: intent, design, trade-offs,
  integration, the final call. Raw material belongs in worker reports, judged
  and summarised before it reaches the main thread.

## Delegate, or do it directly

- Delegate reading, searching, bounded implementation, tests, research,
  mechanical change, log triage, and first-pass review.
- Do it directly when delegation costs more than the work: a few lines in a
  file already understood, one short command, a question the current context
  already answers.
- Watch for drift: several quick direct steps in a row on growing work means
  the rest should have been delegated, with what is known so far in the brief.

## Choosing a worker

- Give each task to the least expensive worker that is sufficiently capable,
  counting rework as cost: cheap work that must be redone is expensive.
- Evidence decides, in this order: the judged record for that kind of task and
  difficulty; then price; then benchmark standing. A thin record is a reason
  for care, not a verdict.
- Ask `sisi route --kind K --difficulty N` before delegating; `--explain` says
  why. Difficulty is 1 routine, 2 ordinary, 3 hard. Say the guess out loud;
  the record shows how good the guesses were.
- Use the host's own subagent mechanism first when the worker belongs to the
  host; the host's cross-provider delegation when it has one; otherwise
  `sisi delegate` through the worker's own command line.
- Spread work instead of draining one allowance; every budget runs out.
- Reviews go to a different maker than the author when one is available.
- About one low-stakes task in ten deliberately tries a cheaper worker with a
  thin record, so the record keeps learning. Low-stakes only.
- When the user is waiting, speed can beat the last increment of cheapness.
- Never route work to a tier that trains on its prompts.

## Parallelism

- Run independent work in parallel when it shortens the critical path enough
  to pay for coordination and integration. Useful parallelism is the goal,
  not the number of workers.
- Parallel writers need disjoint files or separate worktrees, clear
  boundaries, and an integration point named in advance.
- Measure it: worker minutes against wall time, from the ledger.

## The brief

- Every delegation carries a contract: outcome and scope; context and sources
  of truth; constraints and interfaces; acceptance; deliverables and report
  format; files the worker may change; verification expected; budget and
  when to escalate. `sisi delegate brief` prints it; `sisi delegate check`
  tests a draft.
- A worker starts cold. Include what is already known and ruled out, the hard
  part if there is one, and what done looks like. Most failures are brief
  failures: retry once with a better brief before blaming the worker.

## Judging

- Judge in proportion to risk: a diff summary for routine work; the tests,
  the hunks themselves, or an independent reviewer for anything touching
  authorisation, data, money, or public interfaces.
- Record every judgement with `sisi delegate judge`: outcome, the strongest
  check actually applied, minutes and tokens where known, and the retry link
  when this attempt follows a rejection. Accepted on a light check is
  recorded as such; the tables keep the two apart.
- When accepted work later proves wrong, amend it. The record is the
  routing policy; an honest record is the whole mechanism.
- Unavailability is temporary and is never a quality judgement: record it
  with `sisi workers down`, use the next worker, and try again when due.
  A rejected result never marks a worker down.

## Keeping the picture current

- What exists, what it costs, and how good it is all change. Discovery is
  `sisi workers`; prices and benchmark standing are worker facts, each with
  a source and a date, recorded with `sisi workers fact`.
- When facts are missing or stale, hand the research itself to a fast, cheap
  worker: find current prices and software-engineering benchmark standing,
  then record them. Treat a newly appeared model as unproven: low-stakes
  tasks first, checked one level more carefully, until its record is thick.
- Orchestration legwork is delegable like any other legwork: discovery,
  price and benchmark research, routing lookups, first-pass review, and
  summarising the record can all go to a fast, cheap worker. The judgement
  about what to do with the result stays with the main agent.

## Objective

All of this serves one objective: the most verified user value per unit of
wall time, cost, and human attention. A choice that saves money by spending
the user's time, or saves time by shipping unverified work, has optimised
the wrong term.
