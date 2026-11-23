# Workers: discovery, choice and delegation

sisi finds the agent command-line tools on the machine, keeps a judged record of work given to
them, and chooses the most affordable worker that is good enough for each new piece of work. No
list of preferred models is shipped in code, and nothing is scheduled: information refreshes when
a command runs and the stored copy is old, or after a failure.

## The commands

- `sisi workers` prints, in plain words, each tool found on `PATH`, the models it lists, whether
  it is usable now and why not (not logged in, limit reached until a stated time), the allowance
  left where the tool itself reports one, and the price where one is known. A tool with no model
  listing command is shown as "models learned by use": the record names its models as they are
  used. `sisi workers --refresh` reads the tools again instead of using the stored copy.
- `sisi route --kind K --difficulty N [--review-of W] [--explain]` prints the worker the record
  chooses for a kind of task (such as `search`, `impl`, `tests`, `review`) at a difficulty of 1, 2
  or 3. It is plain arithmetic over the record; no model is called. `--explain` also prints why
  each other candidate was passed over. `--review-of W` chooses a reviewer from a different maker
  than the author `W`, peer review style.
- `sisi delegate --kind K --difficulty N --brief FILE [--worker W] [--review-of W] [--cwd DIR]`
  runs the brief unattended on the chosen worker in the given folder, writes the full transcript
  to a file under the state folder, and prints only the worker's final report, the transcript path
  and the command that records the judgement.
- `sisi delegate judge ID --outcome accepted|rejected --check none|diffstat|tests|read|review
  [--minutes N]` records how a run turned out and how strongly it was checked. That judgement is
  what later choices learn from. A run nobody judged is listed by `sisi workers` and named at
  session start.
- `sisi delegate amend ID` marks a judged result that later proved wrong, so it stops counting as
  a success.

## How the choice is made

In order: a model whose id contains "contributor" is never chosen, because those tiers train on
prompts. A worker marked unavailable is skipped until its retry time, as is a flat-rate plan whose
allowance is known to be spent. For a review, the author's maker is skipped while another maker
is available.

A worker counts as proven for a kind and difficulty after enough judged attempts (one threshold
constant in code) with an accepted rate at or above the bar, where accepted means accepted and not
later found wrong. Above the lowest difficulty, proven workers come first. At the lowest
difficulty, workers with a thin record stay in the pool, so low-stakes work is what gathers their
first attempts. A worker with enough attempts and a rate below the bar is passed over while
anything else remains.

Cheapest means: a flat-rate plan with allowance left and no recent failure comes before anything
billed per use, because one more task on it costs nothing extra. Per-use workers order by their
known price. An unknown price is treated as the most expensive of its class until it is learned;
`--explain` says so rather than inventing a number.

Work is then spread, not drained: within one price tier and price, the worker that has taken the
least work relative to the allowance it has left goes first. Every delegation is recorded, so the
choice rotates as work is done, yet is deterministic for one fixed record. Ties break on the
worker id.

On a fresh install the record is empty and no prices are known, so every worker is thin and
unpriced: the first usable worker in id order is chosen, with flat-rate allowance winning where a
tool reports it. Each judgement then shapes the next choice. That is the whole bootstrap; there is
no shipped roster to fall back on.

## Failures that are not bad work

Some tools report a limit or a missing login with a success exit status, so failure is recognised
from the output text, never from the exit status alone. A limit, login, missing tool or outage is
recorded as unavailability, with a retry time that grows on repeat failures, and the same brief is
tried on the next choice at once. Unavailability never counts against a worker's quality. A worker
that ran and did poor work is a different thing: that is a rejected judgement.

sisi never passes a flag that switches off a tool's approvals or sandbox unless the config
explicitly allows it for that tool (`workers.allow_bypass`). When a run times out, the message
says it may be stalled on such a decision and names that setting.

## The main thread

Hook payloads carry the session's model; sisi keeps it with the session record. Model strength
comes from the judged record where it is thick enough, otherwise from a stored prior table in
which every figure carries its source and date. No ranking ships in code: with no prior and no
record, the strength of a model is stated as unknown.

At session start, one plain line follows from that: a session whose model is among the strongest
available on the machine is told to plan, delegate with `sisi delegate` and judge; a weaker one is
told to do the work itself, and told once which stronger models are available. A session another
agent started (a subagent, or a worker run by `sisi delegate`) is told nothing about delegating.

## What is stored, and the seams left open

In the personal data folder: `workers.json` (discovery, with the time it was read),
`delegations.jsonl` (the ledger: runs, judged attempts, amendments), `worker-availability.json`
(unavailable workers and retry times), and two tables that start empty:

- `worker-prices.json`: `{"models": {"<model or worker>": {"plan": "flat" or "per-use",
  "cost_per_million_tokens": number, "maker": name, "source": text, "date": "YYYY-MM-DD"}},
  "tools": {"<tool>": entries of the same shape}}`.
- `model-strength.json`: `{"models": {"<model or worker>": {"score": number from 0 to 100,
  "source": text, "date": "YYYY-MM-DD"}}}`.

A ledger kept by the earlier hand-written orchestrator is imported once, without changing the
original, when its path is named by the `ledger` config key or the `SISI_LEDGER` environment
variable; `sisi workers` reports how many rows came in.

Settings live under a `workers` key in the config: `refresh_after_s` (how old discovery may get
before a command refreshes it), `timeout_s` (how long one delegated run may take), and
`allow_bypass` (per tool, whether approval- or sandbox-switching flags may be passed; off unless
named).

Deliberately not built in this slice, with the tables above ready for them: refreshing prices and
published benchmark scores by web research into those tables; using a cheap fast model to classify
tasks, match lessons or draft review plans; a driver for hosts that delegate through their own
interface rather than a command line; and removing the prose orchestrator this replaces.
