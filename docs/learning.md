# How sisi learns

**There is nothing to schedule. You install it and use your AI; it improves from use.** No cron, no
timers, no daemons, nothing to set up. Every step below happens inside commands and hooks that run
because you used a tool: recording a lesson at the end of a piece of work, starting a session, asking
what "done" means, verifying, or being sent back by the gate.

## The loop in plain words

1. **A lesson is recorded.** At the end of each piece of work the agent answers how it could have gone
   better (`sisi retro`): the aim it fell short of, the concrete moment, why, and the change to sisi
   that would make the next agent do it right without being told. It also names, with `--when` (at
   least five comma-separated words or short phrases, required), the kinds of work the lesson applies
   to in the words a different agent would use, synonyms included — for a CSV lesson: "csv, tsv,
   spreadsheet, tabular data, import, export, parse, delimited file". This matters because word
   overlap alone cannot bridge "CSV" and "spreadsheet": the recording agent, who knows what the lesson
   is about, supplies the bridge vocabulary in advance. Lessons recorded before when-terms existed
   keep working by their own wording and are listed in the cycle brief so a consolidating agent can
   add terms.
2. **It takes effect at once**, in your personal data (the overlay), never in the product files:
   - a verifier or recipe lesson naming an entry is attached to it as a field note straight away;
   - a recipe lesson naming a recipe that does not exist is kept as a draft recipe note;
   - a rule, oracle or brief lesson becomes an active learned note with trigger words taken from its text;
   - a tool lesson (a change to sisi itself) goes on the backlog (`sisi backlog`, most seen first).
     In developer mode, a session started inside the sisi source folder is told the top item.
3. **It is shown at the moment it matters**, not only at session start. Session start prints up to
   eight active lessons, strongest first. `sisi done for`, `sisi done ID`, `sisi verifiers for` and
   `sisi contract init` print a two-part block, because the asking agent is a far better matcher than
   word overlap: part one, "likely to apply", holds at most three lessons in full and only on a
   strict test (at least two of the request's own content words inside the when-terms, or one plus
   the lesson's target being the entry being printed); part two lists every remaining loose lesson as
   a one-line heading (best overlap first, within a 1,500-character budget, saying how many were left
   out) for the agent to open with `sisi lessons show ID`. Being printed or listed counts as
   *listed*; opening counts as *read* — the two are reported separately, because "listed many times,
   never read, still recurs" means the heading is bad, and the cycle brief says so. `sisi verifiers
   show` and the gate's send-back message keep the older single strong-match block. Draft recipe notes
   appear in `sisi done for` when their words match. Lesson text is always framed as information to
   weigh, not as commands, and text from a lesson is never executed.
4. **Showings are counted.** Every time a lesson is printed or listed, sisi records which lesson, in
   which session, and where; opening one in full counts separately as read. Promotion needs at least
   two listings or readings since the last promotion. A later sighting of the same problem — a retro recorded with `--same-as`, which
   is also where the "a similar lesson exists" answer sends you — is a recurrence. When sisi itself
   spots the resemblance and refuses a duplicate, that unconfirmed sighting is recorded too (shown by
   `sisi lessons show ID` and in the cycle brief), so it is not lost even if the agent files its lesson
   separately; it counts toward strengthening only once confirmed with `--same-as`. Recurrences after a
   lesson has been shown are the signal that the lesson is not working.
5. **Recurring lessons get stronger.** Each lesson has a strength: 1 (a note), 2 (a candidate rule),
   3 (enforced). A recurrence after at least two showings since the last promotion moves it up one
   step — each step needs its own fresh evidence. A strength-2 lesson
   becomes a real rule only through consolidation (below), because the rulebook has hard budgets of
   120 lines and 7,200 characters and must not grow. A strength-3 lesson needs a check the gate can run; a folded lesson
   shown 20 times with no recurrence is retired from the notes (it stays in history); a lesson that
   still recurs at strength 3 is withdrawn, and the same wording will not be learned again.
6. **Consolidation happens in a cycle**, run by whichever agent is working — see below.

## The cycle (`sisi cycle`)

Consolidation is due when enough lessons have been recorded since the last cycle, or a lesson is
waiting to move up a step, or the learned notes or the loose lessons pass their limits (`sisi cycle
due` states the live reason and its limit) — the loose list stays short
by construction, because the brief's first instruction is to fold lessons into the recipe or entry
for their kind of work, or lift several into one rule, so they leave it. That is a counter check, not a
schedule: it runs at session start, at the end of every turn in the gate, and in the output of
`sisi retro`, `sisi verify` and `sisi done for` — commands agents run in every tool, so the loop works
in tools with no hooks at all. `sisi cycle due` runs the same check by hand. A session that has been
told is not told again until 20 further checks pass or the counter grows.

`sisi cycle` prints a brief the agent can act on without any other context: the lessons with their
counts and measurements, the current rulebook with its line count and budget, and instructions (merge
lessons that say the same thing; lift specific lessons into one general rule; fold a lesson into the
entry it belongs to; say which existing rule text gets shorter so the book does not grow; write checks
for strength-3 lessons). The agent answers with one JSON file:

The brief names the scratch path to write it to, lists every valid rule, recipe and verifier id
(with each recipe's one-line applies-to and the rule number-to-id map), shows full lesson text when
it fits its stated text budget (otherwise it says to run `sisi lessons show ID`), and puts the full
format behind `sisi cycle help`. `sisi cycle check FILE` (or `--dry-run`) validates and prints
exactly what would change, changing nothing.

```json
{"version": 1, "base": "<base version from the brief>", "summary": "one line",
 "rules": [{"id": "rule-id", "title": "Title", "body": "text, ending with Why: ...", "action": "add|replace",
            "shortens": "rule-id: what is removed (required when the book would grow in characters)"}],
 "disable_rules": ["rule-id"],
 "notes": [{"lesson": 3, "action": "merge|fold-into-rule|fold-into-entry|retire|withdraw|keep|set-when|create-entry|keep-as-draft",
            "into": "rule/entry id or [ids]", "merged_into": 4, "note": "split text (optional)",
            "when": "at least 5 terms (optional)", "entry_kind": "recipe|verifier", "entry_text": "full file (create-entry)",
            "reason": "why it stays a draft (keep-as-draft)"}],
 "enforced": [{"lesson": 3, "type": "command", "cmd": "...", "expect": {"exit": 0}, "timeout_s": 30},
              {"lesson": 4, "type": "contract-requirement", "when": "parser",
               "require_kind": "parsing", "max_rung": 2}]}
```

`fold-into-entry` appends a dated field-note bullet (the lesson's change, or `note`) to
`notes/<id>.md` and marks the lesson applied; `into` may be a list, and two notes for one lesson
with different `note` text split a compound lesson. `create-entry` creates a personal recipe or
verifier entry in the overlay, lint-checked; `keep-as-draft` keeps it as a draft with a reason.
`set-when` only sets when-terms. Merge only lessons requesting the same change, into the older or
more general one, which keeps its text and count; the other becomes superseded and needs no action.
Tool lessons cannot be done in a cycle: they stay in `sisi backlog`, except merging a duplicate.
Retire only what is fully folded and quiet (folded, at least 20 listed/read, no recurrences after
first listing); folding in this cycle does not make it quiet. The learned-notes limit counts only
`length(change)` of active strength-1 loose learned notes: folded lessons no longer count, which
is why folding (or merging, retiring, withdrawing, enforcing) reduces it.

`sisi cycle apply FILE` checks the file before writing anything: every lesson id exists, the base
version is still current, changed rules keep their id and their Why, named `sisi` commands and
enforced programs exist, and the resulting rulebook is inside both budgets (120 lines and 7,200
characters) and no longer in characters than before unless `shortens` names what was removed.
Rules are re-wrapped to 100 characters on apply. The base version covers only what a cycle may
change (lesson content and status, rules, notes, enforced checks), not listed/read counters, and
lessons recorded since the brief are left for the next cycle; a stale refusal names exactly what
changed. The base version plus the personal-data lock means two sessions consolidating at once
cannot overwrite each other: the second apply is refused and told to read a fresh brief. A successful apply is one commit in your personal repository, with before-and-after
measurements. `sisi cycle revert` undoes the newest applied cycle exactly (the changed files byte for
byte, and the lesson rows it touched). `sisi cycle status` shows each cycle with what happened since:
deliveries, send-backs each, median time, and recurrences of the lessons it touched. A cycle whose
deliveries got worse after at least 10 of them is flagged, and the next brief says to revert or repair
it first.

Enforced checks live in `overlay/enforced.json` and are checked like the minimum-rung floors: a
contract-requirement fails a contract that touches its subject without a check of the required kind;
a command check runs in the project like a contract check, and only in projects already on the trust
list.

## Is it getting better?

`sisi improve` (and one line of `sisi status`) answers with what is actually counted: lessons recorded,
taking effect, strengthened, retired and withdrawn; the recurrence rate this week against the week
before; send-backs per delivery and median time to delivery, this week against before; and the
rulebook size against its budget. With too little data it says so.

## Safety, and what is not claimed

Changes take effect first and are measured after; there is deliberately no replay testing before a
change ships. Safety comes from narrow scope instead: everything lands in the personal overlay,
every cycle is one commit that can be reverted exactly, the rulebook cannot grow past its budget, and
a change whose measures get worse is flagged and withdrawn. The human is never asked anything by this
loop.

What is measured is counts and times: showings, recurrences, send-backs, delivery times, rulebook
lines. What is not measured is whether the delivered work is what the human meant — that still rests
on contract checks and the human's corrections.

Matching is measured, not asserted — twice over, and correctness no longer rests on it: part one is
deliberately strict, and everything else still reaches the asking agent as a heading it can judge.
The test suite carries two labelled sets, each measured the same way: how often a wrong lesson is
shown in full in part one (precision), and how often the right lesson is reached at all (in part one,
or listed in part two within its budget). The first set (25 should-match pairs, each request
rephrased but sharing vocabulary with its lesson, and 26 should-not) is a regression floor only — one
author wrote both sides, so of course they share words: reach 25/25, part-one wrong 0/26, proving
little beyond "does not regress". The second is harder and is the honest test: 21 pairs whose
requests share *no* content word with the lesson's moment, cause or change text (the test asserts
this), so only the recording agent's when-terms can bridge them, against 24 should-not requests:
reach 21/21 (20 of them already in part one; one — a request sharing a single when-word — reaches
only as a heading, as designed), part-one wrong 0/24. Both sets are small and hand-written; treat
even those figures as evidence about this mechanism on these examples, not as a promise about yours.

Delivery therefore depends on the quality of the when-terms the recording agent writes. Thin or
copy-of-the-text terms leave a lesson findable only by its own wording, exactly the failure they
exist to prevent. What sisi ultimately measures is not match scores but the outcome that matters:
whether the same problem recurs after a lesson has been shown. A lesson that is never found cannot be
shown, which is why the cycle brief lists lessons still missing terms.

At most three lessons are shown as matches, and every showing is on record in `sisi lessons show ID`.
Two display rules differ by surface: at session start (unsolicited), a lesson whose text reads like
an instruction to run something is withheld; when an agent's own query asked (`done for`, gate
send-back and friends), ordinary verbs like "run a property test" are shown — framed as information —
while URLs, shell constructs and outside paths are refused in both places. The task-set experiments
and taste judge in [design.md](design.md) remain unbuilt.
