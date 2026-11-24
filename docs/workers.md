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
- `sisi workers fact WORKER --maker M --class NAME [--released YYYY-MM-DD] --source S` — the maker, class and
  release date researched for a model. `sisi workers` lists each routable worker's recorded maker, class and release date.
- `sisi workers classify [--record FILE [--by WORKER]]` — sisi reads nothing from a model's name. Without
  arguments it prints a short instruction and the ids of routable workers that have no classification; hand
  that to a fast, cheap worker (it takes seconds). The answer is one small JSON object: for each id its maker,
  class and release date (`unknown` where it does not know), and for each maker its classes from most to least
  capable. `--record FILE` validates it (an id that was not asked about refuses the whole answer; `unknown` is
  stored as unknown and changes nothing in routing) and stores the facts with the classifying worker as the
  source; a class order already recorded is never overwritten. Session start names unclassified workers in its
  one facts line, and `sisi route` adds one line only when an unclassified worker is in the running.
- `sisi workers classes MAKER CLASS [CLASS...] --source S` — a maker's classes from most capable to least
  (`--remove` forgets them). A class is the tier word of one line (a "flash" beside the standard model) or,
  for a maker whose lines are the classes, the line's own name; `sisi workers` shows both as the class label.
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
- `sisi delegate --kind K --difficulty N --brief FILE [--worker W] [--review-of W] [--cwd DIR] [--timeout-min N]`
  runs a brief through the worker's own CLI when the host has no delegation of its own. A brief
  lacking outcome, acceptance or the files it may change is refused. `--timeout-min N` (1 to 120)
  sets the time limit of this run in place of `workers.timeout_s` (default 15 minutes).
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

## Newest version of a class, always

Newer versions of a model are almost always better and almost always cheaper, so `sisi route` always uses
the newest version of a given model (the same maker and class) that is usable, and never an older version of
it. This is about versions of one model: a newer release of a different model or class never wins for being
newer. sisi reads
nothing from a model's name: a model's maker, class and release date are facts, researched by a cheap,
fast worker (session start and `sisi route` say when they are missing) and recorded with
`sisi workers fact WORKER --maker M --class C --released YYYY-MM-DD --source S`. A model's identity is its
maker and class; recency is its release date. For a maker whose lines are the classes the class is the
line's own name; for a maker with a "flash" beside its standard model it is `flash` or `standard`. A model
with no recorded maker and class is never compared with another. The same model through two providers is
one model: if its newest version is usable through any provider, older versions do not compete through any
provider, and the existing cost comparison picks the provider. There is no exception for a better old
record or a cheaper old plan. The older version competes again only while the newer is unusable (marked
down, allowance spent, avoided by the user, or limited away) or has no recorded class. A newer model with a
thick bad record is not replaced by its older version either: routing moves to another class or maker by the
usual rules. Different classes are different things and never supersede each other. A bare host alias with a
recorded class and no release date counts as the newest version of its class.

The class order is a prior and nothing more. A worker with no judged proof and no benchmark standing,
whose class is in its maker's recorded order, is capable when the class sits high enough for the
difficulty: `route.class_span` (default routine work 100, ordinary 70, hard 35) is the share of the order,
counted from the most capable class down, that each difficulty reaches. With four classes routine work
reaches all four, ordinary work the top three, hard work the top two; the cheapest capable worker then
wins, so routine work goes to the lowest class and hard work to the upper ones. A judged record or a
benchmark standing always outranks the order; when nobody is proven, the strongest known worker is the
one in the highest class. Classes of different makers are never compared. Until a maker with two or
more classes among the usable workers has an order recorded, `sisi route` adds one line asking for it.

A new version starts from its predecessor's judged record: a model with no thick record of its own
for a kind and difficulty inherits, as evidence, the thick record of the closest older version of
its maker and class (one version back at a time), named in `--explain`. It ranks below the model's
own record and above a benchmark, counts as a judged record for the rule that proof comes before
benchmark, stops once the model has a thick record of its own, and a predecessor's bad record is not
inherited. A discovered model with no data of its own is routable when its predecessor is. Where the
arithmetic falls back to a stable tie-break, the newer version of the same model goes first (never across makers
or classes).

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
worker with a better brief first, then a worker whose evidence is strictly better (`routing.retry_choice`, the
same ladder the capability routing uses). `sisi route --kind K` takes only the ledger's kinds (`impl`, `impl-multi`,
`edit`, `tests`, `debug` build; `read`, `search`, `research`, `review`, `docs` do not; the list is data in
canon/guard.json) and names them when given another; the decision is kept in the session's orchestration meter,
which is also where the contract guard reads it to tell a build delegation from a read.

When a worker fails for a reason that is not about its work (a quota, limit, login or connection failure,
arriving as a delegation result or as a host notice), the hooks record it down until the reset time in the
message, mark its pending run `superseded` and hand the agent the router's next worker. The agent is told to
fall back at once with the same brief and neither ask the person nor report it. `sisi delegate` itself says
the same when only host-native workers remain. A failure is read from the end of what a worker printed, never
from everything it read: `workers.failure_text` returns the last 1,500 characters of each stream, and nothing
when the run exited 0 and printed more than 4,000 (it did its work; a short exit-0 message such as a limit
notice is still read). Every classifier (a run, a model listing, a smoke run of a learned tool, a provider's
own phrases, a learned tool's phrases, the hooks on a host delegation result) reads that text. The shell hook
acts only on a command that really runs `sisi delegate` and only on a line that begins with a worker id and
` is unavailable (`, the last one. Models discovery finds that it had not seen are named once at
session start as unproven. Settings under `orchestrate`: `direct_calls`, `direct_chars`, `extension`,
`route_window_min`. Mechanics: [design.md](design.md) section 9.

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

A worker that did not exist when sisi was installed becomes routable through ordinary use; nothing is scheduled. Host tool names are data (`canon/orchestration-tools.json`, shared with the orchestration meter), never code.

- **From the host.** The after-tool hook reads the host's capability listing and delegation calls. Each provider the host says can run a task, and each model, is the worker `provider/model`; a provider the host disables is stored, never routable, and one missing from `discovery.drop_after_listings` listings (3) is dropped. A listing over `discovery.catalogue_over` models (8) is a catalogue: only models used, priced or with a standing are candidates. `sisi route` names the delegation tool and the ids to pass it. Your own `only` limit still decides what is routable.
- **From PATH.** Session start compares the executables in the user-level folders on PATH (nothing is run) with the stored list and names new ones once, five at most (`discovery.path_refresh_s`, `discovery.path_every_starts`).
- **A tool, learned as data.** `sisi workers learn NAME` prints the brief for a cheap worker to read the tool's help and write a small JSON driver; `--check FILE` validates, `--record FILE` stores it (`worker-drivers.json`) and runs one smoke task, `--verify` retries, `sisi workers forget NAME` removes it. The command is an argument list, never a shell. A name that collides with a built-in driver is refused. A command with a flag that switches off approvals or a sandbox runs nothing until the owner decides.
- **Earning a place.** Such a worker is unproven until it has `MIN_ATTEMPTS` judged attempts: difficulty 1 only, a free or flat one gets one routine task in `route.explore_free_one_in` (3), and `sisi route`/`sisi delegate` say to check its result. Unknown plan counts as per-use.
- **Providers.** A tool can carry several providers (the part of an id before the first slash), each with facts of its own that never reach another: `sisi workers plan PROVIDER flat|free|per-use --source S`; `sisi workers allowance PROVIDER --url|--command ...` (a probe: the key comes from a named command at probe time, goes in one request, and is never stored or printed; the smallest remaining window decides, the provider is down until every spent window resets; a failed probe changes nothing); `sisi workers signature PROVIDER --match TEXT --class auth|limit|missing|error` (the provider's own failure phrases, before the built-in ones). A limit marks that provider down until the time the error names, else the probe's reset.
- **Vouching.** `sisi workers vouch WORKER --up-to 1|2|3 --why "OWNER'S WORDS"`: capable up to that difficulty on the owner's word, ranked with judged proof, shown by `--explain` as its own evidence; a thick bad record overrides it and its own thick record replaces it. Words not found in a message the owner typed count only to difficulty 2.
- **The owner's decisions.** Learned drivers that switch off approvals (`drv-NAME`) and allowance probes (`probe-PROVIDER`) are decided with learning changes by one command, `sisi approve`: it lists all three kinds in full, and a decision needs the random word it prints typed at the controlling terminal. An agent's shell command is refused, whatever the id.
