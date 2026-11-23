# Workers: discovery, choice and delegation

sisi finds the agent command-line tools on the machine, keeps a judged record of work given to
them, and recommends the most affordable worker that is good enough. No model, price or ranking
ships in the product: everything specific is discovered here, researched into the user store,
or learned from judged results. The strategy is [canon/orchestration.md](../canon/orchestration.md)
(`sisi delegate guide` prints it); this page is the mechanics.

## The commands

- `sisi workers [--refresh]` — each tool found, the models it lists, whether it is usable now
  and why not, allowance and price where known, runs waiting for a judgement, then the judged
  record as three tables: by task type and difficulty (attempts, accepted, checked well, later
  wrong, median minutes; thin rows marked), what fixed each rejection, and difficulty-guess
  calibration.
- `sisi workers fact WORKER --price N|--score N --source S [--date D] [--plan flat|per-use]
  [--maker M]` — record a price (per million tokens) or a benchmark standing (0–100), each with
  its source and date, in the user store. A fact without a source is refused.
- `sisi workers avoid|prefer PATTERN --why TEXT` — the user's own routing constraints.
- `sisi workers only PROVIDER PATTERN... --why TEXT` — only the matching models of that provider are
  routable; anything else from it (a newly discovered model, say) is passed over with the reason.
  `--remove` deletes the limit.
- `sisi workers note PATTERN "TEXT" --why SOURCE` — a standing operational fact about workers that
  match PATTERN. Shown in `sisi workers` and, for the chosen and passed-over workers it applies to,
  in `sisi route`, as information for the agent. The product ships none; `--remove` deletes one.
- A worker id with no provider prefix is a host-native worker (the host's own subagent model): it
  needs no command-line tool, is usable unless marked down, and `sisi route` says to start it with
  the host's own subagent tool. Everything `sisi workers` and `sisi delegate` write to the user
  store is committed there, one small commit per command.
- `sisi workers down WORKER --reason limit|auth|missing|error [--until DATE-OR-TIME] [--note TEXT]` and
  `sisi workers up WORKER` — availability. Without `--until`, the wait widens on repeat failures.
- `sisi workers import FILE` — merge another ledger file into the delegation ledger, idempotently,
  printing row counts before and after. The source file is only read.
- `sisi route --kind K --difficulty 1|2|3 [--review-of W] [--explain]` — the recommended worker
  and the mechanism to start it with (the host's own subagents, its cross-provider delegation,
  or `sisi delegate`). `--explain` says why, briefly, and why the rest were passed over.
- `sisi delegate brief` prints the delegation-contract template (eight parts);
  `sisi delegate check FILE` lists the parts a brief lacks.
- `sisi delegate --kind K --difficulty N --brief FILE [--worker W] [--review-of W] [--cwd DIR]`
  runs a brief through the worker's own CLI when the host has no delegation of its own. A brief
  lacking outcome, acceptance or the files it may change is refused.
- `sisi delegate judge` is the only way a result enters the ledger: by run id for
  `sisi delegate` runs, or directly (`--worker --type --difficulty`) for work run any other way.
  It carries outcome, the strongest check applied, minutes, tokens, cost, retry-of, and project,
  session and start/end times when known. `sisi delegate amend ID` marks one later proved
  wrong; `sisi delegate recent [-n N] [--project P]` lists judgements to find an id.

## How the choice is made

Candidates are only workers with a judged record, a known price or a benchmark prior; discovered
catalogue models with none of those are listed but never routed to. On a cold start nobody
qualifies: the pick is then a trial among usable workers, `--explain` says so, and asks for the
result to be judged and facts recorded.

In order: a tier that trains on prompts is never chosen; unavailable and allowance-spent workers
are skipped and named; `avoid` patterns remove a worker unless that leaves nobody; a reviewer
comes from a different maker than the author (a stored `maker` fact, else derived from the model
id). Proven workers (enough attempts at or above the accepted-rate bar, not later found wrong)
come first above difficulty 1; proven-bad workers are passed over. Cheapest first within that:
flat-rate allowance before per-use prices, unknown prices last, the benchmark prior ordering a
thin record at equal price, `prefer` patterns first, then load balancing across allowances.
About one difficulty-1 task in ten goes to a cheaper thin-record worker instead, so cheaper
options gather evidence. The choice is deterministic for one fixed record.

## Costs and failures

Tokens and cost are captured where the worker's output reports them, and marked `unavailable`
otherwise; when tokens are known but cost is not, cost is estimated from the price fact and
marked `estimated`. Failure is recognised from output text, never the exit status alone: a
limit, login, missing tool or outage is unavailability with a retry time, the brief falls
through to the next choice, and quality is untouched. Poor work is a rejected judgement, which
never marks a worker down. No approval- or sandbox-switching flag is passed unless the config
allows it per tool (`workers.allow_bypass`).

## Orchestration the hooks enforce

`sisi route` records the session's routing decision (kind, difficulty guess, pick). A delegation started with
the host's own tool is written to the ledger by the hooks as a pending run with that kind and difficulty, and
completed when it returns; `sisi delegate judge ID --outcome O --check C` then needs nothing else. A worker
other than the router's pick is recorded as an override, and `sisi workers` ends with one line on how often
and how they turned out. After a rejection `sisi delegate judge` prints `sisi route --retry-of ID`: the same
worker with a better brief first, a stronger one after a second rejection.

When a worker fails for a reason that is not about its work (a quota, limit, login or connection failure,
arriving as a delegation result or as a host notice), the hooks record it down until the reset time in the
message, mark its pending run `superseded` and hand the agent the router's next worker. The agent is told to
fall back at once with the same brief and neither ask the person nor report it. `sisi delegate` itself says
the same when only host-native workers remain. Models discovery finds that it had not seen are named once at
session start as unproven. Settings under `orchestrate`: `direct_calls`, `direct_chars`, `extension`,
`route_window_min`. Mechanics: [design.md](design.md) section 9.

## Stored, and when facts go stale

In the user store: `workers.json` (discovery cache), `delegations.jsonl` (the ledger),
`worker-availability.json`, `worker-prices.json` and `model-strength.json` (worker facts),
`worker-prefs.json` (avoid/prefer) and `worker-notes.json` (standing notes). When facts are missing or older than
`workers.facts_max_age_days` (default 30), session start prints one line asking for a fast,
cheap worker to research current prices and benchmark standing and record them — an age check
during normal use, never a scheduler. Settings live under `workers` in the config:
`refresh_after_s`, `timeout_s`, `allow_bypass`, `facts_max_age_days`, `digest_days`,
`host_cross_provider`.

## What this does not do

Prices and benchmark standing are only as fresh as their recorded source and date. A worker
with no judged record, price or prior is listed but never routed to until evidence exists.
