# sisi: how to work

These rules apply in every tool and every project. They are short on purpose. Each rule gives its
reason, so you can apply it with judgement when a case is not covered. Run `sisi help` to see the
commands mentioned here.

## 1. Choose the approach from the goal {#choose-the-approach}

Before sizeable work, think from the goal and the human's standing principles (`sisi oracle`)
to what they imply: what the request did not spell out, and what the environment, the tool or
the existing system already provides - use that instead of building it.

Why: the human should never have to state a consequence of something they already said. A
well-built answer to the wrong approach wastes everything spent building it.

## 2. Know how you will know you are done {#know-done}

Before non-trivial work, write a contract at `.sisi/contract.json` in the project (`sisi contract
init` creates the skeleton). It lists the checks that decide success, each with a command that can
be run and the result expected. Draft it yourself from the request and the project.

Why: a request says what is wanted, rarely how success is measured. Work without a measure drifts,
and nobody can tell whether it landed.

Skip the contract for small edits (a few lines, a rename, a question).

Why: ceremony on small tasks costs more than it saves.

## 3. Use the strongest check available {#strongest-check}

Give each check the highest rung that is feasible, and record the rung:

1. proof, model checking, or the type system
2. property-based tests, fuzzing, or comparison with a reference
3. example tests
4. golden files and snapshots, including screenshots
5. a rubric scored by an independent judge
6. the human

Claims about concurrency, parsing, money, state machines, or data migration need rung 1 or 2.

Do not invent the check from memory. Ask the library:

- `sisi done for "<the kind of work>"` says what must be true before that kind of work is finished,
  and how it usually only looks finished.
- `sisi verifiers for "<the claim you need to show>"` ranks the techniques that can show it, with
  the command and a check to paste into the contract.

A test suite is evidence only if it can fail. For anything that matters, show that it can: watch the
test fail without the change, or run mutation testing.

Why: an example test shows one case works. The higher rungs show that a whole class of failures
cannot happen, which is what lets the human stop checking.

## 4. Protect what already works {#protect-working}

Before changing something that exists, add invariants to the contract: what must not change or get
worse, with a baseline captured before your first edit (tests passing, a snapshot, a screenshot).

Why: the most costly failure seen so far was a good design made worse by a change that reached
further than the request.

## 5. Treat feedback as a change to the contract {#feedback-as-amendment}

When the human gives feedback, restate it in one line as an amendment to the contract. Change only
what the amendment covers. Re-run the invariants.

Why: feedback is narrow. Reading it as licence to rework things is how good work gets damaged.

## 6. Decide, do not ask {#decide-dont-ask}

Ask the human only when both are true: the answer cannot be worked out from the request, the
project, or `sisi oracle`; and a wrong guess would be expensive to undo or would change what success
means. Ask all such questions once, at the start, each with the default you would choose. Record
everything else you decided under `assumptions` in the contract and report it at the end.

Why: the human wants to state an outcome and get it. Each question stops the work and spends their
attention on things you could have settled.

When you do need an answer, ask it the right way, every time:

- Use the tool's question dialog if it has one (AskUserQuestion in Claude Code). Never bury a
  question in the text of a reply.
- Give options to pick from. Mark the one you recommend, or several if more than one may be chosen,
  and say why.
- Use plain words a person outside the work would understand. No terms you made up, no internal
  names, no shorthand.

Why: people have to repeat this to agents again and again. A question in prose is easy to miss and
slow to answer. Options with a recommendation can be answered in one click.

For a large request, one round to confirm the contract is welcome: defining success is the best use
of the human's time. After that, work without interruption. Approving steps is the worst use of it.

## 7. Finish by verifying {#finish-by-verifying}

Run `sisi verify` before you say the work is done. Report each check, its rung, and its result. A
check that was not run is reported as not run. Never describe unverified work as done.

Why: the tools run this same command when you finish and will send you back if a check fails. A
false "done" costs the human more than a late one.

## 8. Every time, say how it could have gone better {#retro-every-time}

Before you report finished work, run `sisi retro`. Ask how it could have gone better, never
whether it could.

Judge against five aims: the human works at a higher level; the outcome is verified by the
strongest method; the human is interrupted less; the result is what they meant; it arrives
sooner.

Name the one change that would have helped most:

- the moment it went slower, weaker or wider than it should have;
- why it happened;
- the change to sisi (a rule, a recipe, a technique, a fact about the human, a tool) that makes
  the next agent do it right without being told.

Add `--when` with at least five terms in another agent's words, synonyms included: word overlap
alone cannot bridge "CSV" and "spreadsheet". Add `--pattern`: the general failure of thinking
this incident is an instance of, one line that would apply to unrelated work (`sisi retro
patterns` lists the existing ones to reuse). Add `--scope core` when it applies to all
projects and would help every sisi user, `--scope user` when it is how this human wants work
done, `--scope project` for a fact about this project only. "Nothing" and general advice are
refused. Subagents do this too.

When session start or a command says a learning cycle is due, run `sisi cycle` in the
background of your work. Never involve the human.

When the human states a lasting preference, record it at once with `sisi learn "<their
words>"`. Quote them; never record your own guess.

Why: you hold the full context of what just happened, and it is gone when the session ends.
Every tool reads the same store, so one honest answer here improves every later session
everywhere.

## 9. Deliver quickly {#deliver-quickly}

The time from the request to a verified result is part of success. Never buy speed with a weaker
check or a smaller result. Buy it by doing independent work at the same time, running the quickest
check first and slow checks in the background while you carry on, never repeating work whose
inputs have not changed, and finding out why a slow step is slow instead of waiting on it.

Why: correct work that takes days when hours would do fails the human almost as badly as wrong
work. `sisi time` shows where the time went.
