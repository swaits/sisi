# How sisi learns

**There is nothing to schedule. You install it and use your AI; it improves from use.** No cron, no
timers, no daemons, nothing to set up. Every step below happens inside commands and hooks that run
because you used a tool: recording a lesson at the end of a piece of work, starting a session, asking
what "done" means, verifying, or being sent back by the gate.

## The loop in plain words

1. **A lesson is recorded.** At the end of each piece of work the agent answers how it could have gone
   better (`sisi retro`): the aim it fell short of, the concrete moment, why, and the change to sisi
   that would make the next agent do it right without being told. Every lesson, and every
   `sisi learn` statement, has a tier (`--scope core|user|project` is required; a missing scope is
   refused with a paragraph stating the test). The test is two questions: does it apply to all
   projects where sisi may be used, and would it be useful to every user who installs sisi? Both
   yes is `core`: a change to sisi itself, in force for this user at once through the overlay and
   queued for the product (below, `sisi promote`). Yes then no is `user`: how this owner wants work
   done, kept in the personal store and delivered in all of this user's projects; the owner's
   standing principles (`sisi oracle`) are built from user statements, plus core ones until the
   product carries them. No to the first is `project`: a fact about this one project, which does
   not stay in sisi's store: it moves to that project's
   handover pile (below) and on into the project's own documentation or work list. A project is
   identified by its git remote URL when it has one — normalised, so clones, an ssh or https remote,
   and a renamed folder are the same project — else by its repository root path (a clone or rename
   with no remote is then, unavoidably, a different project). The lesson splits in two: the
   delivered part (`change`, `short`, `--when`; a learn statement) must be universal in the core
   and user tiers, and a structural check (no model call) refuses it when that part names the
   current project — the repository's name, a path or file name that exists in it, or its remote
   URL — saying to rewrite it in general terms or scope it to the project. The tool's own name is
   always exempt: how sisi itself should behave is core, even recorded inside the sisi repository,
   and nothing is project merely for being recorded there (sisi is normally the shell around other
   projects). Its history (`moment`, `cause`, the
   occurrence records with repository, date and tool) is the historical example of where it came
   from and may name the project freely; only the delivered part is checked. Lessons and statements
   recorded before tiers existed (including the old two-way `everywhere`) are not yet tiered: they
   keep being delivered as before until a learning round tiers them (below), and printed headings
   count the short line when present. A lesson also names its pattern (`--pattern`, required): the
   general failure of thinking this incident is an instance of, in one line that would apply to
   unrelated work. A pattern naming the project or merely restating the change is refused by the
   same style of check. `sisi retro patterns` lists the patterns so far and `--pattern-id N`
   reuses one, so near-duplicates start rare and a round merges the rest. Patterns are how lessons
   generalise upward instead of piling up as incident fixes (below).
   `sisi lessons show ID` prints the universal lesson first, then a section headed "Where this came
   from (historical example)" with the moment, cause and occurrences; session start, request-time
   delivery and field notes show only the universal part plus the command that prints the example.
   It also names, with `--when` (at
   least five comma-separated words or short phrases, required), the kinds of work the lesson applies
   to in the words a different agent would use, synonyms included — for a CSV lesson: "csv, tsv,
   spreadsheet, tabular data, import, export, parse, delimited file". This matters because word
   overlap alone cannot bridge "CSV" and "spreadsheet": the recording agent, who knows what the lesson
   is about, supplies the bridge vocabulary in advance. Lessons recorded before when-terms existed
   keep working by their own wording and are listed in the cycle brief so a consolidating agent can
   add terms. A retro may also carry `--short` (one sentence in plain words, at most 140 characters,
   no trailing ellipsis and no newline) and `--topic` (between one and three lower-case words, at
   most 30 characters, such as "releases" or "asking questions"). Both are optional and checked
   only for those limits when given; when either is missing, the retro still succeeds and says
   that the next learning round will write it. Stores written before these fields existed gain
   them on open, losing nothing, and lessons without them keep working.
2. **It takes effect at once**, in your personal data (the overlay), never in the product files:
   - a verifier or recipe lesson naming an entry is attached to it as a field note straight away.
     When the lesson has a short line, the bullet reads "- YYYY-MM-DD: <short> (seen N times;
     lesson ID; full text: sisi lessons show ID)" in place of the long change text; an explicit
     note text given by a later fold still wins over the short line;
   - a recipe lesson naming a recipe that does not exist is kept as a draft recipe note;
   - a rule, oracle or brief lesson becomes an active learned note with trigger words taken from its text;
   - a tool lesson (a change to sisi itself) goes on the backlog (`sisi backlog`, most seen first).
     A session started inside the sisi source folder is told the top item.
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
   show` and the gate's send-back message keep the older single strong-match block. The same strict
   part-one test also runs at the moment the human's request arrives: where the tool documents a
   prompt-submission event with a context channel, `sisi prompt` injects the best-matching recipe's
   "done means" list in short form plus the matching lessons' short lines, each with the command
   that prints it in full (`sisi done ID`, `sisi lessons show ID`), within a 2,000-character cap.
   A recipe counts only when at least two distinct non-generic request words hit its title,
   applies-to or id, at least one of them in its title (matched on stems, so "tag" meets
   "tagging") — the same strict floor lessons use. A message that is a question to the agent and
   names no work (no fix, build, change or the like), trivial messages (a bare yes or no, a slash
   command, a short question) and unmatched requests inject nothing at all. These
   showings count as *listed* at place `prompt`. The hook never blocks a turn: any error exits
   silently. Draft recipe notes
   appear in `sisi done for` when their words match. Lesson text is always framed as information to
   weigh, not as commands, and text from a lesson is never executed. One-line headings — the
   other-lessons list, session-start notes, `sisi backlog` and `sisi lessons` — use the short
   line when one is present; without one they cut the change at a word boundary and end with
   "…", never mid-word. Printed-heading budgets count the short line when present, because that
   is what is printed.
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
   becomes a real rule only through consolidation (below), because the rulebook has hard budgets in
   lines and characters (`sisi doctor` prints them), and must not grow without shortening. A strength-3 lesson needs a check the gate can run; a folded lesson
   shown 20 times with no recurrence is retired from the notes (it stays in history); a lesson that
   still recurs at strength 3 is withdrawn, and the same wording will not be learned again.
6. **Consolidation happens in a cycle**, run by whichever agent is working — see below.

## Project facts are handed over, not kept (`sisi handover`)

Project-specific details might be recorded, with where the lesson came from as a historical
example — but they might not live in the global store: sisi is used across many projects, so
everything it leaves behind is at the broad or meta level, and project facts belong in that
project's own work list and design documentation. Scoping an item `project` (at `sisi retro` /
`sisi learn` time, or in a learning round) moves it out of the delivered global data into a
per-project handover pile in the personal store, kept only until filed. At session start inside
that project (and in request-time delivery there) sisi says, in plain words, how many items
belong to this project and asks the agent to file each in the project's own design documentation
or work list — wherever the project keeps them; if it has neither, a short section in its main
agent instructions file or a docs file — and then confirm with `sisi handover done ID --where
PATH`. `sisi handover` lists the waiting items in full, including the owner's quoted words and
the date, so nothing is lost in the move. The confirmation checks that the named file exists
inside the project and contains the item's key text (or a quoted fragment passed with `--quote`)
before removing it from the pile, and records where it went (id, project, path, date) in a small
filed log. After confirmation the item is gone from every global listing, digest and delivery;
the digest shows only a count per project of items still waiting to be filed. History stays in
the personal store's git history. The end-of-turn check is not involved: this is a
start-of-session notice that repeats until filed.

## The cycle (`sisi cycle`)

Consolidation is due when enough lessons have been recorded since the last cycle, or a lesson is
waiting to move up a step, or the learned notes or the loose lessons pass their limits (`sisi cycle
due` states the live reason and its limit). The due test counts only what a round can act on:
tool lessons (changes to sisi itself, which a round cannot fold) and project-scoped items (handed
over to their project) do not count toward it; tool lessons are shown by `sisi backlog` under
their own separate heading cap, and a tool lesson whose change has been built is closed with
`sisi lessons set ID --status applied`, which takes it off the backlog and stops the digest
calling it "not built yet". The loose list stays short
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
format behind `sisi cycle help`. It also lists every active lesson lacking a short line or topic,
lists the topics already in use so the agent reuses one instead of inventing a near-duplicate,
states the short and topic limits, and requires a `set-short` entry for each listed lesson:
`sisi cycle check FILE` (or `--dry-run`) refuses a file that omits one, naming the lesson, and
prints exactly what would change, changing nothing. A round can be started on demand even when
none is due: `sisi cycle --now` (or plain `sisi cycle`) prints the brief either way.

The brief also lists every not-yet-tiered lesson and `sisi learn` statement, with the repository
each was recorded in where known, and requires a tier for each: a note
`{"lesson": A, "action": "set-scope", "scope": "core|user|project", "project": "<id, when
project>"}` for a lesson, and the equivalent `{"text": "<the exact statement>", "action":
"set-scope", ...}` in a top-level `"learn"` list for a statement (the full format is behind
`sisi cycle help`). The brief states the two questions with generic examples of each tier.
Scoping to a project moves the item to that project's handover pile, and `sisi cycle check`
refuses to fold a project-scoped item into the rulebook or the general recipe/technique notes.
The brief likewise lists patterns with the lessons under each, and requires the round to assign
a pattern to every lesson lacking one (`set-pattern`, reusing a listed pattern before naming a
new one), merge near-duplicate patterns (a top-level `patterns` merge), and — for any pattern
explaining at least three lessons and at least six incidents (two constants in the code) — write
or update its statement in the rulebook as one strategic behaviour, traced like any folded
lesson. These three pressures are what keep patterns few: reuse is listed before invention is
allowed, exact duplicates merge themselves, and anything left over is merged or promoted each
round. The brief also lists core items waiting for the product; run from the clone it says
to run `sisi promote` after folding, otherwise to export. A file containing only the required
set-short/set-scope/set-pattern entries is acceptable when nothing else is ready to fold — a
cleanup-only round, startable at once with `sisi cycle --now`. Reading lessons during a round cannot stale it: automatic retirement (a
folded lesson shown 20 times) is deferred while a round is open, so `sisi lessons show` during
the round leaves its base current. `sisi cycle apply` prints the rulebook's lines and characters
before and after, matching what `sisi cycle check` predicted.

```json
{"version": 1, "base": "<base version from the brief>", "summary": "one line",
 "rules": [{"id": "rule-id", "title": "Title", "body": "text, ending with Why: ...", "action": "add|replace",
            "shortens": "rule-id: what is removed (required when the book would grow in characters)"}],
 "disable_rules": ["rule-id"],
 "notes": [{"lesson": 3, "action": "merge|fold-into-rule|fold-into-entry|retire|withdraw|keep|set-when|create-entry|keep-as-draft|set-short|set-scope|set-pattern",
            "into": "rule/entry id or [ids]", "merged_into": 4, "note": "split text (optional)",
            "when": "at least 5 terms (optional)", "short": "one plain sentence (set-short)", "topic": "topic words (set-short)",
            "entry_kind": "recipe|verifier", "entry_text": "full file (create-entry)", "scope": "core|user|project (set-scope)", "project": "id (set-scope)", "pattern": "one line (set-pattern)", "pattern_id": 1,
            "reason": "why it stays a draft (keep-as-draft)"}],
 "learn": [{"text": "the exact learn statement", "action": "set-scope", "scope": "core|user|project", "project": "id, when project"}],
 "patterns": [{"pattern": 1, "action": "merge|set-statement|fold-into-rule|keep", "into": 2, "statement": "sharpened one line"}],
 "documents": [{"doc": "recipe:<id>", "action": "rewrite", "text": "<full new text>",
                "trace": [{"lesson": 3, "fragment": "the exact sentence in the new text that carries it"}]},
               {"doc": "verifier:<id>", "action": "reviewed", "reason": "why its structure is already right"}],
 "rule_order": ["every rule id exactly once, in reading order"],
 "enforced": [{"lesson": 3, "type": "command", "cmd": "...", "expect": {"exit": 0}, "timeout_s": 30},
              {"lesson": 4, "type": "contract-requirement", "when": "parser",
               "require_kind": "parsing", "max_rung": 2}]}
```

`fold-into-entry` appends a dated field-note bullet (the lesson's change, or `note`) to
`notes/<id>.md` and marks the lesson applied; `into` may be a list, and two notes for one lesson
with different `note` text split a compound lesson. `create-entry` creates a personal recipe or
verifier entry in the overlay, lint-checked; `keep-as-draft` keeps it as a draft with a reason.
`set-when` only sets when-terms. `set-short` writes the short line and topic, and may be combined
with other actions on the same lesson; when it lands on a lesson already folded into an entry, the
entry's existing default bullets are rewritten to the short form. A bullet is treated as a default
bullet only when its text equals the lesson's full change with whitespace normalised; any other
text came from an explicit `note` and is left alone. Merge only lessons requesting the same change,
into the older or more general one, which keeps its text and count; the other becomes superseded
and needs no action. Tool lessons cannot be done in a cycle: they stay in `sisi backlog`, except
merging a duplicate (and a `set-short` for one, so the digest can show it).
Retire only what is fully folded and quiet (folded, at least 20 listed/read, no recurrences after
first listing); folding in this cycle does not make it quiet. The learned-notes limit counts only
`length(change)` of active strength-1 loose learned notes — it counts the change, not the short
line, because it is about content not yet folded — while printed headings count the short line
when present: folded lessons no longer count toward the learned-notes limit, which is why folding
(or merging, retiring, withdrawing, enforcing) reduces it.

`sisi cycle apply FILE` checks the file before writing anything: every lesson id exists, the base
version is still current, changed rules keep their id and their Why, named `sisi` commands and
enforced programs exist, and the resulting rulebook is inside both budgets (lines and
characters, printed by `sisi doctor`) and no longer in characters than before
unless `shortens` names what was removed.
Rules are re-wrapped to 100 characters on apply. The base version covers only what a cycle may
change (lesson content and status, short lines and topics, rules, notes, enforced checks), not
listed/read counters, and
lessons recorded since the brief are left for the next cycle; a stale refusal names exactly what
changed. The base version plus the personal-data lock means two sessions consolidating at once
cannot overwrite each other: the second apply is refused and told to read a fresh brief. A successful apply is one commit in your personal repository, with before-and-after
measurements. `sisi cycle revert` undoes the newest applied cycle exactly (the changed files byte for
byte, and the lesson rows it touched). `sisi cycle status` shows each cycle with what happened since:
deliveries, send-backs each, median time, and recurrences of the lessons it touched. A cycle whose
deliveries got worse after at least 10 of them is flagged, and the next brief says to revert or repair
it first.

Every round ends with a whole-document edit. The things agents read are documents — the
rulebook, the oracle (the owner's standing principles, one plain line per principle followed by
his quoted words and the date), each "what done means" recipe, each technique entry — and a
folded lesson belongs in
the document's own text, in the section where it fits (in a recipe: Done means, Checks, or
Common false finishes), in the document's voice, not as one more dated bullet in a journal.
The brief prints, for every document that has appended field notes, was folded into, has a
personal copy whose product text has since changed, or has had no whole-document review for
the configured number of rounds, its full current text and the lessons folded into it
(universal part only), together with a short editorial standard: one instruction per bullet or
sentence; most important and most often violated first; related instructions grouped under
one heading; no duplicates; imperative, concrete, plain words; each rule keeps its reason;
exceptions beside the instruction they qualify; no history or narrative. The cycle file then
needs, for each listed document, a rewrite (the full new text) or a `reviewed` entry with a
one-line reason; `sisi cycle check` refuses a file that skips one. The personal version of a
recipe or technique lives in the overlay and shadows the product's, with the product hash it
was derived from on record; when the product later changes, the next brief lists the document
as needing a re-merge rather than silently keeping the stale copy. Field-note files from
before this existed are listed the same way and keep being shown until rewritten.

For the oracle the same tracing applies to statements: a rewrite traces every statement to the
line that carries it, and until a round integrates one, `sisi oracle` prints it under its own
heading so a new statement is in force at once and never parked unread.

Nothing folded may be lost in a rewrite. For each lesson folded into a document the file gives
the exact sentence or bullet in the new text that carries it, or an explicit disposition:
moved to another named document (with its fragment there), merged with another lesson (both
ids point at the same fragment), or retired under the usual retirement rule. A rewrite that
leaves any lesson without one of these is refused. For the rulebook the same holds for rule
ids: each survives or is merged into another id, and each keeps its Why. The trace map is
stored beside the document, outside the text agents load; `sisi lessons show ID`,
`sisi rule N` and `sisi done ID --trace` print where a lesson lives. Structure is checked
mechanically: the rulebook budgets, rule headings with ids, Why paragraphs and the generated
pointer lines, the library lint for recipes and techniques, the house width after wrapping,
run-on bullets, and dated journal-style bullets. A round may also reorder the rulebook
(`rule_order`): ids stay stable, numbers follow the order, and stored data refers to rules by
id. Each rewrite is recorded on its cycle, so `sisi cycle status` shows recurrences of the
rewritten document's lessons before and after it, and flags a rewrite followed by more.
Reverting a round restores documents, order and trace maps along with everything else.

Enforced checks live in `overlay/enforced.json` and are checked like the minimum-rung floors: a
contract-requirement fails a contract that touches its subject without a check of the required kind;
a command check runs in the project like a contract check, and only in projects already on the trust
list.

## Every rule points at its own detail (`sisi rule`)

The generated rulebook ends each rule with one generated line — `More: sisi rule N` — so a rule an
agent is reading names the command that explains it. `sisi rule` with no argument tables every rule
in the effective rulebook with how it is enforced, in plain words, derived from what the code does
(which hooks are wired, whether the floors and the gate checks exist): a rule with no mechanism
says so ("not enforced: depends on the agent") instead of implying otherwise. `sisi rule N` (or
`sisi rule ID`) prints the rule in full with its reasons, how it is enforced, whether the text is
base or overlay, which learning rounds changed it, and the lessons folded into it, each with
`sisi lessons show ID`. One rule gained a mechanism this way: where the tool has a question dialog
and a readable transcript (Claude Code; Qwen Code is wired the same way but its transcript shape is
unconfirmed, so the check may find nothing to read there), the end-of-turn gate sends the agent back
once when its final message ends by asking the human a question in reply text and no dialog was
used in that turn — the last sentence ending in a question mark outside code blocks, quotes and
known rhetorical forms. Subagents and dialog-less tools are exempt, and the same message is never
sent back twice.

## What has been learned, in plain words

`sisi lessons digest` is for the human, not for agents. Its first line says how much has been
learned in one sentence, and its last line says how to see a lesson in full (`sisi lessons show
ID`), with the lesson number on every line. Patterns come first: the handful of strategic
behaviours, each with how many incidents it explains and whether its recurrence is falling.
Then the tiers: "In sisi itself, for every user" holds core items, each marked in the product
or waiting to be promoted; "How you want work done" holds user items; items waiting to be
filed in their projects appear only as a count per project (run `sisi handover` inside that
project to see them). Statements not yet tiered appear in the person's own words under "What
you said" when any are stored. The remaining short lines are grouped
under their topic headings, ordered by how much each topic holds, most first. After every line
comes its state in plain words — in the rulebook; attached to a kind of work (named by the
entry's human title, never its internal id); a loose note; a change to sisi itself, not built
yet, or built once closed with `sisi lessons set ID --status applied` — plus "seen N times" only
when a lesson has been seen more than once. Lessons without a short line go last, under "Not yet
summarized", cut at a word boundary. Retired, withdrawn and superseded lessons are left out
unless `--all` is given. `sisi rule N` lists the lessons behind a rule the same split way as
`sisi lessons show ID`: the lesson line, then its historical example.

## Is it getting better?

`sisi improve` (and one line of `sisi status`) answers with what is actually counted: patterns first
(each with its incidents and recurrence trend), then lessons recorded,
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

Two more labelled sets guard the newer checks, measured the same way in `tests/test_scope.py`
and `tests/test_prompt.py`: lesson texts labelled universal or project-bound (including
universal lessons that merely mention common file names such as README or CHANGELOG, which
pass, and universal changes whose moment names a project, which also pass because only the
delivered part is checked), and long real-style multi-part requests plus plain questions for
request-time recipe delivery (a hit is the expected recipe; any other recipe is a false match).
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
