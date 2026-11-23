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
- `sisi workers fact WORKER --price-in N --price-out N | --price N | --standing N --source S
  [--date D] [--plan flat|per-use] [--maker M]` — record a price as published (input and output,
  per million tokens), one blended price for a source that publishes only that, or a benchmark
  standing (0–100; `--score` is the old name), each with its source and date, in the user store.
  A fact without a source is refused. Ranking uses one blend of the two prices, by default three
  parts input to one part output (`route.price_blend_input_parts`); `sisi workers` shows both
  prices and the blend, and lists each benchmark standing apart from the accepted rates it prints.
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

Candidates are only workers with a judged record, a known price or a benchmark standing; discovered
catalogue models with none of those are listed but never routed to. On a cold start nobody
qualifies: the pick is then a trial among usable workers, `--explain` says so, and asks for the
result to be judged and facts recorded.

In order: a tier that trains on prompts is never chosen; unavailable and allowance-spent workers
are skipped and named; `avoid` patterns remove a worker unless that leaves nobody; a reviewer
comes from a different maker than the author (a stored `maker` fact, else derived from the model
id). Then the cheapest worker that is capable enough for the kind and difficulty, judged by the
best evidence about each worker, in this order: (a) its judged record for that kind and
difficulty (enough attempts at or above the accepted-rate bar, not later found wrong); (b) the
nearest judged evidence: the same kind at a harder difficulty proves an easier one, then all
kinds at that difficulty or a harder one (the same kind at an easier difficulty is weak evidence,
used only when no usable worker is capable otherwise); (c) benchmark standing as a prior, compared
only with other workers' standing: at least 85 percent of the best usable standing for difficulty
3, 60 percent for difficulty 2, no floor for difficulty 1 (`route.standing_floor` in the config);
(d) nothing known: difficulty 1 only, as an exploration. Above difficulty 1 a benchmark is a reason
to try a worker, not to prefer it to proof: when any usable worker is capable by a judged record for
the kind (a, or b from a harder difficulty of the kind), only those compete; the record across all
kinds counts as proof only when nobody has evidence from the kind; standing decides only when nobody
has a judged record for the request. A thick bad record at this or an easier
difficulty, or a thin one with repeated rejections, keeps a worker off its benchmark. The two
scales never meet: a standing is never compared with an accepted rate. Cheapest first among the
competing workers: flat-rate allowance before per-use prices (blended input and output), unknown prices
last, then standing, `prefer` patterns first, then load balancing across allowances. When no
worker is capable by the evidence, the strongest known usable worker is recommended and `--explain`
says that none is proven. About one difficulty-1 task in ten goes to a cheaper thin-record worker
instead, so cheaper options gather evidence. The choice is deterministic for one fixed record.
`--explain` prints one line for the evidence behind the choice (which of a to d, with the numbers),
one per group of workers passed over as not capable enough, and names an exploration or a fallback.

## Costs and failures

Tokens and cost are captured where the worker's output reports them, and marked `unavailable`
otherwise; when tokens are known but cost is not, cost is estimated from the price fact and
marked `estimated`. Failure is recognised from output text, never the exit status alone: a
limit, login, missing tool or outage is unavailability with a retry time, the brief falls
through to the next choice, and quality is untouched. Poor work is a rejected judgement, which
never marks a worker down. No approval- or sandbox-switching flag is passed unless the config
allows it per tool (`workers.allow_bypass`).

## Stored, and when facts go stale

In the user store: `workers.json` (discovery cache), `delegations.jsonl` (the ledger),
`worker-availability.json`, `worker-prices.json` and `model-strength.json` (worker facts),
`worker-prefs.json` (avoid/prefer), `worker-notes.json` (standing notes) and `worker-drivers.json` (learned drivers). When facts are missing or older than
`workers.facts_max_age_days` (default 30), session start prints one line asking for a fast,
cheap worker to research current prices and benchmark standing and record them — an age check
during normal use, never a scheduler. Settings live under `workers` in the config:
`refresh_after_s`, `timeout_s`, `allow_bypass`, `facts_max_age_days`, `digest_days`,
`host_cross_provider`.

## What this does not do

Prices and benchmark standing are only as fresh as their recorded source and date. A worker
with no judged record, price or prior is listed but never routed to until evidence exists, except a new worker from the section above, which is tried on routine work first.

## Workers that appear later

A worker that did not exist when sisi was installed becomes routable through ordinary use. Nothing is scheduled; each way in runs inside a hook or a command already run. The names of a host's tools and the shape of their data are in `canon/discovery.json` (data, never code).

- **From the host.** The after-tool hook (`sisi watch --after`) recognises the host's capability-listing tool and its delegation tool by the patterns in that file. A listing adds every provider the host says can run a task, each model as the worker `provider/model` exactly as the host names it (a provider the host disables is recorded but never routable). A provider missing from `discovery.drop_after_listings` listings (default 3) is dropped. A delegation seen passing is recorded too. Once per set of new workers the agent gets one line with the count. `sisi route` names the host's delegation tool and the provider and model ids to pass it. A provider listing more than `discovery.catalogue_over` models (default 8) is a catalogue: its models are stored, and only those used, priced or with a standing are candidates. Kept in the scratch folder (`discovery/host-workers.json`); the next listing rebuilds it.
- **From PATH.** At session start the executables in the user-level folders on PATH (under the home folder, never system folders; nothing is run) are compared with the stored list. It is looked at again when a folder changed, after `discovery.path_refresh_s` (6 hours) or `discovery.path_every_starts` (25) session starts. The first run only stores the list. New names are announced once, five at most.
- **A driver, learned as data.** `sisi workers learn NAME` prints a delegation contract for a fast, cheap worker: read the tool's own help, write a small JSON file (the fields of the built-in driver table, plus failure phrases and a token pattern). `--check FILE` validates it; `--record FILE` validates, stores it (`worker-drivers.json`, with who learned it and when) and runs ONE read-only smoke task in a temporary folder, with a time limit and no input. Only a passing driver is used; a failure is classified (login, quota, bad template, no answer, timeout) and the driver stays unusable with the reason (`--verify` tries again). The command is an argument list run without a shell; the brief is one argument. A command with a flag that switches off approvals or a sandbox (patterns in the data file) waits for `sisi approve drv-NAME`, which shows the exact command, and never runs, smoke task included, before. `sisi workers forget NAME` removes one.
- **Earning a place.** Such a worker is unproven until it has `MIN_ATTEMPTS` judged attempts: difficulty 1 only, whatever benchmark it has; a free or flat one gets one routine task in `route.explore_free_one_in` (default 3); `sisi route` and `sisi delegate` say to check its result with at least the tests or a read of the diff. Its plan comes from its driver or from a fact; unknown counts as per-use. The missing-facts line at session start names the new workers (five at most) so the research has a target.
