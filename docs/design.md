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
passing but makes median delivery slower is flagged for reversal. (The measurement exists; the automatic
flagging belongs to the learning loop, which is not built.)

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
the change is larger than a small threshold, the agent is sent back to write one. Small edits pass untouched.
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
The design folds such a ledger and its routing table into the shared store. Today sisi only reads an optional
ledger file, to match delegations with sessions when it builds the task set.

## Part 3: learning that compounds

The data layer of this part is built; the model-driven loop that would act on it is not.

**Signals, strongest first.** The loop learns from outcomes that do not depend on a model's opinion:

1. Check results recorded by `sisi verify`.
2. Survival of work in git: was an agent's change reverted or rewritten within 14 days.
3. Delegation outcomes in a ledger.
4. The human's corrections and the agent's questions, read from transcripts by a classifier. Useful for finding
   causes, weakest as proof.

**Trigger.** Each tool's session-start hook runs `sisi tick`, which returns quickly. The design has it start a
detached background run when there is work and budget, with one lock in the store preventing overlap, so a tick
from any tool processes sessions from all tools. Today `sisi tick` records the session baseline and checks the
wiring; it starts no background run.

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

**Testing a change.** Splitting live sessions between old and new rules proves about one change every three or
four days, which is too slow. The main test is a task set built from the user's own work, re-run in the
background:

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
(`sisi checks` does this today); new models are scored on the task set before routing changes.

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
session records stay in scratch for now and are included in the export. Nothing personal is ever placed in the
product, so the product can be published.

Any agent in any tool reads through the files or the CLI and writes through the CLI:

- `sisi note`: record a failure now (older; `sisi retro` is preferred).
- `sisi propose`: suggest a rule change (older; `sisi retro` is preferred).
- `sisi learn`: record something the human said. The entry is held in quarantine until the harvest finds those
  words in a message the human typed in that session's transcript. An agent cannot invent a preference.

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
- Retrospectives and lessons (`sisi retro`, `sisi lessons`), `sisi learn` with quarantine, time to delivery
  (`sisi time`), `sisi audit`.
- Personal data, the overlay, update, export and import, releases and rollback, promotion of a personal item
  into the product.
- The data layer for learning: harvest of Claude Code transcripts, task set, ground truth, escape candidates,
  check statistics, scoreboard.

Designed, not built:

- The conductor (`sisi build`) and the oracle queue (`sisi inbox`).
- The model-driven learning loop: background runs started from `sisi tick`, experiments on the task set, shipping
  and removal of learned changes, brief templates, playbooks.
- The taste judge and rung 5 judging by a model.
- Blocking gates for tools other than Claude Code.
- Harvest sources other than Claude Code.

## Build order

1. Store, CLI, wiring into each tool, contract format, `sisi verify`, the end-of-turn gate, the first
   verifier-library entries, rulebook version 0, `sisi audit`. Built.
2. Signals and scoreboard: transcript adapters, git survival, and a delegation ledger. Partly built (Claude Code
   transcripts, task set, scoreboard; no git survival signal).
3. The conductor and the oracle queue. Not built.
4. The loop: coach, replay filter, experiments, shipping and removal. Not built.
5. The taste judge and playbooks. Not built.

sisi's own checks: wiring is idempotent and touches no other byte (property tests); the gate cannot be passed
with a failing or unrun check (property test over generated contracts); a rulebook change is visible to every
tool with no further command; `tick` returns quickly; no command writes inside the product at run time; the
learning loop, when built, cannot write outside the personal data folder; a conductor run killed at any step
resumes without redoing closed nodes (to be model-checked, then tested).

## Decisions

1. Delegation tooling is folded into sisi in the design; only the optional ledger read exists today.
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
- Blocking gates outside Claude Code, Muse's instruction path and Codex's hook format are unverified.
- This is several months of building. Each phase is useful on its own.
