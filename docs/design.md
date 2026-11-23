# sisi: design

Status: this document describes the design of sisi and marks what is built and what is not. The section
"What is built" lists both. Where the text below says "sisi does" something that the list marks as not built,
read it as the intended design.

## Intent

AI coding tools execute well and understand poorly. An agent does not know what success means, so it guesses,
and sometimes it damages work that was already good. Nobody can list every such failure in advance, so the
system has to find them itself.

The end state: a person states a product and gets a verified product. Five objectives, each with the number
that shows it:

| Objective | Shown by |
|---|---|
| Work at a higher level (functions, modules, products) | size of verified work delivered per human message |
| Verifiable outcomes, formal where possible | share of delivered claims backed by a check that ran, by rung |
| Hands off | human minutes and blocking questions per delivered piece of work |
| Delivered sooner, with no weaker check | median time from request to verified result (`sisi time`) |
| Improves itself from use, everywhere | the numbers above, as trends, across all tools |

## The objective

Hard requirements come first: the result is correct, complete, verified at the rung its kind of claim needs,
and what the human meant. Among results that meet them, sisi minimises two things: the time from the request to
a verified result (time to delivery), and the number of times the human is interrupted. Speed is never bought
with a weaker check or a smaller result.

Time to delivery is measured, not guessed. Each time the end-of-turn gate lets a turn end it records one
delivery row: the time since the last message the human actually typed (hook feedback and tool results do not
count), how many times the gate sent the agent back, and how long the checks ran. `sisi time` shows the median
and 90th percentile for the last 7 days against the 7 days before, the share spent in checks, and the five
slowest checks; `sisi status` shows the 7-day median.

A learned change that speeds things up but fails a check is rejected. A learned change that keeps every check
passing but makes median delivery slower is flagged for reversal. (Built: `sisi cycle status` flags a cycle
whose deliveries got worse, and the next cycle brief puts reverting or repairing it first. There is still no
replay testing before a learned change ships; it lands in the personal overlay and is judged after.)

## Why the first design was thrown out

The first version was a rulebook of at most 120 lines, plus advice. It was attacked and found too small, for
these reasons, which still shape the design:

1. **It was advice.** The definition of done was prose in an instruction file. Nothing made an agent write it or
   run it.
2. **It had a low ceiling.** Its only output was one rulebook. The best case was one good instruction file, then
   a plateau.
3. **It ignored the main objective.** Product-level work was a late phase, and "not a new harness" was a stated
   non-goal. Nothing in it could drive hours of work from one sentence.
4. **It treated the human as a cost.** The human can help define success; the first version only tried to ask
   less.
5. **Its measurements were weak.** A classifier's opinion of transcripts, compared before and after with no
   control group. And "fewer corrections, fewer questions" is also what a user who has given up looks like.
6. **It left the best data unused.** Records of delegated work, with outcomes, show that most rejections are
   fixed by a better brief. The hand-off of intent is the largest known source of failure, and the first
   version declared that out of scope.
7. **It ignored competing instructions.** Installed plugins can tell agents to do the opposite of the rulebook
   (for example, forcing a question-and-answer design conversation before any work). The loudest instruction
   wins.
8. **Formal methods were one line of text.** Agents fall back to example tests because the formal tools are not
   installed or set up.
9. **It opened a hole.** Any agent could write "facts about the user" that every agent in every tool would then
   obey. An agent misled by a web page could poison all of them.

## Goals

- Success is an executable artefact, enforced by the tools, not requested.
- One sentence can start work that runs to a verified result.
- The human's time goes to defining success, without blocking the work.
- What accumulates is capability (checks, verifiers, a calibrated judge of the human's taste, playbooks), not
  only rules.
- One shared store for everything, used by every tool.

## Non-goals

- No cron, timers, daemons, or third-party Python packages. Everything runs because a tool was used or a
  command was started.
- No new chat UI. sisi drives the existing command-line tools.
- No per-project tuning. The store is global. Contracts are per piece of work.

## Anti-goals

- An agent that asks nothing and delivers something wrong.
- Ceremony on small tasks.
- Changes nobody can see or undo.
- Scores that go up while the delivered work gets worse.

## Part 1: contracts that are enforced

A **contract** is a file that says how this piece of work will be known to be done. The agent writes it from the
request and the project. It holds:

- **checks**: each has the claim it supports, the command that tests it, the expected result, and its rung on
  the ladder
- **invariants**: for existing work, what must not change or get worse, with a baseline captured before the
  first edit
- **assumptions**: what the agent decided to fill gaps
- **open questions**: only those where the answer cannot be worked out and a wrong guess is expensive, each with
  a default
- **design** (sizeable work): how the approach was chosen — what the goal and the owner's standing
  principles imply that the request did not spell out; what the environment, host tool or existing
  system already provides that should be used instead of built, with evidence it exists; at least two
  other approaches with cost and risk; the chosen one and why it is what the owner would pick; for
  each standing principle, the objection the owner would raise and how the design answers it (or why
  it does not apply); and an independent challenge by a different model or a subagent playing the
  owner, with what changed in response. Validation is structural and aimed at filler (named existing
  things are checked where checkable, a command on PATH or a file in the repository). That the
  challenge predates the first edit is honestly not checkable: edit attribution records paths, not a
  first-edit time, so a parseable recording time is all that is required

The ladder, highest first:

1. Proof, model checking, the type system
2. Property-based tests, fuzzing, comparison with a reference
3. Example tests
4. Golden files and snapshots, including screenshots
5. A rubric scored by a judge model whose agreement with the human is measured
6. The human

`sisi verify` runs the contract and records every result in the shared store. A contract with top-level
`"parallel": true` runs its fast-tier checks at the same time (at most 4); a check with `"serial": true` always
runs alone. Results are reported in contract order either way.

**Enforcement.** The tool's end-of-turn hook calls `sisi verify`. If a contract exists and a check fails or was
not run, the agent is sent back with the failures and cannot report the work as done. If no contract exists and
the change is larger than a small threshold, the agent is sent back to write one; a change that size
with a contract whose design section is missing or fails validation is sent back to fill it. Small
edits and subagents pass untouched, and the same send-back budget bounds every send-back, so no
session is trapped. Request-time delivery hands the standing principles and the design instruction
over when a request reads as design or build work, and `sisi design` prints them before a contract
exists.
Claude Code supports a blocking stop hook. The equivalent in OpenCode, Codex and Muse is not verified; where it
does not exist, verification is meant to run at the next session start and failures to be reported then (that
fallback is a design intention, not built).

**Floors.** Some kinds of claim have a minimum rung. Concurrency, parsing, money, state machines and data
migration may not rest on example tests alone. The floors are in `canon/floors.json`.

**Formal tooling is provisioned.** sisi keeps a verifier library: for each language and kind of claim, the
tool, a working template and a worked example (Kani and Verus for Rust, TLA+ or Quint and Alloy for designs,
property testing per language, screenshot comparison for UI). Each time a check was hard to set up, the set-up
is meant to be saved, so the next use is cheap.

**Feedback.** Feedback from the human becomes an amendment to the contract, restated in one line. Only what the
amendment covers may change, and the invariants are re-run. A UI that was good stays good unless the amendment
says otherwise.

## Part 2: the conductor (not built)

`sisi build "<what I want>"` would turn a statement into verified work. It can be started from a terminal or by
an agent inside any tool. It is a plain program that drives the installed command-line tools in headless mode.
Its state is on disk in the shared store, so a run survives the session that started it and can be resumed from
any tool. None of this exists yet; there is no `sisi build` and no `sisi inbox` command.

1. **Frame.** A strong model writes the product contract: acceptance checks for the whole, and for the core
   logic a formal model where one applies. It fills everything it can from the oracle profile.
2. **One oracle round.** The human sees the contract and the few open questions, once, and corrects it. This is
   the human defining success, and it is the highest-value minute in the run.
3. **Split.** The contract becomes a tree. Each node has its own contract and a brief generated from it, so a
   brief always carries the success checks.
4. **Dispatch.** Nodes go to workers chosen from a routing record, in parallel where they do not share files.
5. **Close.** A node closes only when `sisi verify` passes on it. A failure is retried with the failing output,
   then escalated to a stronger worker. Parents are re-verified when children land.
6. **Report.** What was built, every check and its rung, every assumption.

**The oracle queue.** A question that arises mid-run does not stop the run. It goes into a queue with the
default the agent is proceeding on. Work that does not depend on it continues. `sisi inbox` would show the
queue. An answer that differs from the default re-opens only the nodes that used it.

**Delegation records.** A person who already delegates work to cheaper models may keep a ledger of outcomes.
The design folds such a ledger and its routing table into the shared store. Built: the worker layer
([workers.md](workers.md)) discovers the agent tools and models installed on the machine, imports such a
ledger once into the shared store, and routes work by pure arithmetic over the judged record — the most
affordable usable worker that is good enough, with load spread in proportion to the allowance each plan has
left and reviews sent to a different maker. `sisi delegate` runs one brief unattended through a per-tool
driver and leaves the run waiting for a judgement. No model is preferred in code, and nothing refreshes on a
schedule: discovery is re-read during normal use when the stored copy is old or after a failure. What is not
built on top of it is the conductor above: framing, splitting and closing a tree of work.

## Part 3: learning that compounds

The agent-run loop over retro lessons is built: lessons take effect at once, are delivered at matching
moments, are measured per lesson, climb a strength ladder, and are consolidated by `sisi cycle`
([learning.md](learning.md)). The heavier machinery designed below — background runs, replay experiments on a
task set before shipping, the taste judge — is not built; the built loop ships to the personal overlay first
and judges by measured deliveries, with exact revert and withdrawal as the safety net.

**Signals, strongest first.** The loop learns from outcomes that do not depend on a model's opinion:

1. Check results recorded by `sisi verify`.
2. Survival of work in git: was an agent's change reverted or rewritten within 14 days.
3. Delegation outcomes in a ledger.
4. The human's corrections and the agent's questions, read from transcripts by a classifier. Useful for finding
   causes, weakest as proof.

**Trigger.** There is no scheduler and no background run. Whether consolidation is due is a counter check made
during normal use: the session-start hook (`sisi tick`), the end-of-turn gate on an otherwise-clean stop, and
the output of `sisi retro`, `sisi verify` and `sisi done for` — so tools without hooks are covered by commands
agents run anyway. A session is told at most once until 20 further checks pass or the counter grows. Two
sessions consolidating at once are kept apart by the personal-data lock and a base version in the cycle file:
the second apply is refused and re-reads a fresh brief. (The earlier design of tick starting detached
background runs on a budget was dropped for this simpler trigger.)

**What the loop would produce.**

- **Rules.** One change at a time, each with its reason and evidence. The always-loaded core stays under 120
  lines; the rest loads on demand.
- **The oracle profile.** What the human wants, so a thing is asked once ever.
- **A taste judge.** Every time the human judges an outcome ("this is worse"), the before, the after and the
  verdict are saved. A judge is tuned on these and its agreement with the human on held-back verdicts is
  measured. It may stand in for the human on rung 5 only for kinds of work where agreement is above 85%. This is
  how taste becomes checkable.
- **The verifier library**, described in part 1.
- **Playbooks.** Runs that closed cleanly are mined too. The decomposition and checks that worked for a kind of
  product are saved for the next one.
- **Brief templates**, from what the ledger shows fixed rejected work.

**Testing a change.** (Not built; the built loop takes the opposite order by decision — a change lands in the
personal overlay at once and is judged by measured deliveries, because waiting for replay evidence left every
lesson inert. What follows is the replay design that may still be added.) Splitting live sessions between old
and new rules proves about one change every three or four days, which is too slow. The main test is a task set
built from the user's own work, re-run in the background:

- **Human tasks.** A project as it was when a session began, the request the human typed, and what they ended up
  accepting. In a census of one user's history, only a fraction of sessions were usable as tasks and a smaller
  fraction had ground truth that could be fully trusted. From the day sisi is installed, every session is
  recorded with its exact starting commit, so the set grows with use.
- **Brief tasks.** Records of delegated work, each an instruction, the work done, and whether it was accepted.
  These test how instructions are written and which model suits which job.

A candidate change is run against a sample of tasks next to the current version, in separate copies of the
project. It is scored on: the accepted version's tests passing, closeness to what the human accepted, questions
asked, and whether its checks would have caught the failure that really happened. It ships only if it passes
every check and scores higher on tasks it was not written from; a change that is faster but fails a check is
rejected, however quick. Live sessions then confirm or reverse it, and a change that keeps the checks passing
but makes median time to delivery slower than before is flagged for reversal. The spend is capped by a budget
that favours flat-rate plans first, then the cheaper models.

Other things the loop would improve, besides rules: recipes are tightened whenever a bug gets past a passing
set of checks; techniques are ranked by how often they catch real failures; checks that never fail are flagged
(`sisi checks` does this); new models are scored on the task set before routing changes.

**Owning the instruction surface.** `sisi audit` lists every source of instructions each tool loads
(instruction files, plugins, skills) and reports where they contradict the rulebook. Contradictions the loop
cannot remove itself would be put in the oracle queue.

## One shared store

One rulebook, one oracle profile, one set of contracts and results, one verifier library, one scoreboard. Tools
are connected by reference (an import line or a symlink), never by copy, so a change is live everywhere at the
next session. Every write to personal data is a git commit. Private session text and results live in scratch
(`~/.local/state/sisi/`) and are not committed. The layout as built is in `docs/personal-data.md`.

### Product and personal data are separate

sisi is two things on disk, and an update to one must never cost the other.

- **The product**: what a person clones. Code, the base rulebook, the base library of techniques and recipes,
  defaults. sisi never writes into it at run time. `sisi update` replaces it.
- **Personal data**: everything sisi has learned for this person. It lives in one folder outside the clone
  (`~/.local/share/sisi/`), with its own local git history so any change can be undone, and it is never touched
  by an update. It holds the profile of what the person wants, the lessons, learned changes to the rulebook,
  field notes, added or replaced techniques and recipes, the task set, results, settings and trusted projects.
- **Scratch**: things that can be rebuilt (the transcript index, locks, logs) stay in `~/.local/state/sisi/`.

Learned changes are stored as an overlay, not as edits to the product. Every base rule, technique and recipe
has a stable id. The overlay can add an item, replace one by id, or switch one off. What agents load is the
result of applying the overlay to the base, generated into the personal folder; the tools point at that
generated file.

On update the overlay is applied again to the new base. If the product changed an item the person's overlay
replaced, the person's version stays and the item is queued for re-testing against the new base version.
Personal data carries a format version, and `sisi update` migrates it after taking a backup.

One folder means one thing to back up or copy to another machine (`sisi export`, `sisi import`). Results and
session records stay in scratch and are included in the export. Nothing personal is ever placed in the
product, so the product can be published.

Any agent in any tool reads through the files or the CLI and writes through the CLI:

- `sisi note`: record a failure now (older; `sisi retro` is preferred).
- `sisi propose`: suggest a rule change (older; `sisi retro` is preferred).
- `sisi learn`: record something the human said, in their words. It takes effect at once: user-tier
  statements are the owner's standing principles (`sisi oracle`), core statements are queued for the
  product, project statements are handed over to their project. Tiers follow the owner's two questions:
  does it apply to all projects where sisi may be used, and would it help every user who installs
  sisi? Both yes is a product change (`core`, in force at once through the overlay, written into the
  source tree by `sisi promote` on a developer install once folded, the personal copy dropped when
  the product contains it; on an ordinary install `sisi promote --export` writes a contribution file
  and nothing is ever sent automatically). The tool's own name never makes an item project-bound: how
  sisi itself should behave is core, wherever it was recorded.

Models used by the loop run with no tools and return text. sisi's own code checks and writes that text, and
writes only inside the personal data folder (as overlay changes; see `docs/personal-data.md`), never into the
product. Text inside transcripts that the human did not type is data, never instruction.

## Scoreboard

`sisi scoreboard` shows weekly and per-repository trends computed from harvested sessions; `sisi status` shows
verification statistics. The design adds, per tool: verified work per human message; share of claims by rung;
blocking questions and human minutes per piece of work; share of agent changes surviving 14 days; taste-judge
agreement. The last two are not built.

## What is built

Built and covered by tests:

- The CLI and the shared store; contracts (`sisi contract`), `sisi verify` with fast and deep tiers and trust
  for contracts that run commands.
- The end-of-turn gate (`sisi gate`) and session-start hook (`sisi tick`), wired into Claude Code with a
  blocking hook; wiring (`sisi install`, `uninstall`, `doctor`) also points Codex and OpenCode at the rulebook,
  where nothing blocks.
- The rulebook (`canon/core.md`), the minimum-rung floors, the verifier library and the recipes.
- Retrospectives and lessons (`sisi retro`, `sisi lessons`), `sisi learn` live at once, time to delivery
  (`sisi time`), `sisi audit`.
- Choosing the approach as a checked step: the contract design section, `sisi design`, the gate's
  design send-back on large changes, and request-time delivery of the standing principles for design
  or build requests. The rulebook's first rule states it and `sisi rule` reports its enforcement.
- Patterns: each retro names the general failure of thinking behind the incident; patterns are
  first-class, merged in rounds, and promoted into the rulebook as strategic behaviours past a
  threshold; the digest and `sisi improve` show them first. Three tiers (`core`, `user`, `project`)
  replace the two-way scope, with older universal items tiered by the next round, and `sisi promote`
  listing, writing (developer installs) or exporting core items.
- The lesson loop: immediate effects in the overlay (field notes, draft recipes, learned notes, `sisi backlog`),
  moment-of-use delivery with recorded showings, per-lesson measurement, the strength ladder with enforced
  checks, `sisi cycle` (due counter, brief, validated apply under lock and base version, exact revert, status
  with worse-cycle flagging) and `sisi improve`.
- Personal data, the overlay, update, export and import, releases and rollback, promotion of a personal item
  into the product.
- The data layer for learning: harvest of Claude Code transcripts, task set, ground truth, escape candidates,
  check statistics, scoreboard.
- The worker layer: discovery of the installed agent tools and their models (`sisi workers`), the delegation
  ledger in the shared store with a one-time lossless import of the earlier hand-kept ledger, unavailability
  kept apart from judged quality, choice by measured results (`sisi route`), and unattended runs with
  judgement (`sisi delegate`). The session's model is kept from hook payloads, strength comes from the record
  plus a stored prior with source and date (no ranking shipped in code), and session start says whether the
  session should plan and delegate or work itself. Stored price and strength tables are ready for a later
  research refresh; that refresh, and any driver for a host with its own delegation interface, are not built.

Designed, not built:

- The conductor (`sisi build`) and the oracle queue (`sisi inbox`).
- Replay experiments on the task set before a learned change ships, brief templates, playbooks. (Shipping and
  removal of learned changes exist in the simpler ship-first-measure-after form described in Part 3.)
- The taste judge and rung 5 judging by a model.
- A blocked turn proven end to end in each tool. Gates are built for the tools whose hooks allow one
  (see [harnesses.md](harnesses.md)); most are tested against the documented hook format only.
- Harvest sources other than Claude Code.

## Build order

1. Store, CLI, wiring into each tool, contract format, `sisi verify`, the end-of-turn gate, the first
   verifier-library entries, rulebook version 0, `sisi audit`. Built.
2. Signals and scoreboard: transcript adapters, git survival, and a delegation ledger. Partly built (Claude Code
   transcripts, task set, scoreboard; no git survival signal).
3. The conductor and the oracle queue. Not built.
4. The loop: coach, replay filter, experiments, shipping and removal. Partly built (the lesson loop ships,
   measures and removes; the coach as a separate model run, the replay filter and experiments are not built).
5. The taste judge and playbooks. Not built.

sisi's own checks: wiring is idempotent and touches no other byte (property tests); the gate cannot be passed
with a failing or unrun check (property test over generated contracts); a rulebook change is visible to every
tool with no further command; `tick` returns quickly; no command writes inside the product at run time; the
learning loop, when built, cannot write outside the personal data folder; a conductor run killed at any step
resumes without redoing closed nodes (to be model-checked, then tested).

## Decisions

1. Delegation tooling is folded into sisi: discovery, the ledger, the choice rule and unattended runs are
   built (see [workers.md](workers.md)); the conductor that frames and splits whole products is not.
2. The end-of-turn gate is on by default. Each check has a time limit, and after three send-backs in a row the
   agent is let through with the result marked unverified. One setting turns the gate off.
3. Session text may be read by any provider the user already uses as a worker, never by a model whose id marks it
   as training on prompts. This is a user setting, not something sisi decides for them.
4. Background spend has a default budget (a number of cheap calls and test runs a day). Not built, since no
   background runs exist yet.

## Known limits

- Whether an agent understood cannot be proved. Survival in git and check results are evidence, with delay.
- A contract can be wrong. Passing checks prove the checks, so the product contract gets the one oracle round.
- Experiments at this volume detect large effects only.
- The taste judge is worthless until the human has given enough verdicts, and it is trusted per kind of work,
  not globally.
- Outside Claude Code and Copilot CLI, a blocked turn has not been run end to end; Muse has no confirmed
  instruction path or end-of-turn hook, and OpenCode's plugin events are unproven.
- The end-of-turn gate attributes edits per session. Edit-tool calls are read from the session's own
  transcript (incrementally, from a per-session offset), including the transcripts of subagents it
  started natively. Shell commands are not judged from their text where the tool has before/after tool
  hooks (Claude Code, Codex, Gemini, Copilot and Cursor have them wired): `sisi watch` takes a stat-only
  tree snapshot (file sizes and modification times, `.gitignore` honoured, `.git` never included) before
  and after the command and attributes exactly the paths that changed to that session, and the session
  answers for a failing check only when a path changed since the last passing state is attributed to
  it. That measurement has honest limits: another agent changing the tree inside this session's command
  window is attributed to this session (it errs strict, the safe side); a change that keeps a file's
  size and mtime, a write to a git-ignored file, and a write between the last complete transcript line
  and a crash are invisible; `git commit` changes only `.git` and so is never an edit; sisi's own
  commands write only personal data and state (except `sisi contract init/waive/trust`) and never count,
  so `sisi retro` cannot create the need for another retro. Where a tool has no before/after tool events
  (Qwen, Pi, OpenCode), shell commands are still judged by the older command-text classifier, which
  over-attributes interpreters and test runners. A missing or unreadable transcript, a corrupt line, an
  unparseable shell command, a shell command whose after-record never arrives, and an unread transcript
  tail over 64 MB are all treated as "this session edited" — strict — never as "someone else did it".
  Attribution decides who is sent back and who owes a retrospective; it never turns a failing check into
  a pass — a stop allowed over another session's failing tree is recorded unverified, once per tree state.
- This is several months of building. Each phase is useful on its own.
