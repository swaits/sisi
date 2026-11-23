# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## Unreleased

### Added

- Lessons gain an optional short line (one plain sentence, at most 140 characters) and topic
  (between one and three lower-case words, at most 30 characters), written at `sisi retro` with
  `--short` and `--topic` or by a learning round with a `set-short` note action. The cycle brief
  lists every active lesson lacking either field and the topics already in use, and
  `sisi cycle check` refuses a file that omits one. `sisi cycle --now` starts a round on demand
  when none is due, field-note bullets and agent-facing headings use the short line when present,
  and `sisi lessons digest` prints a plain-language summary grouped by topic for the human.

### Changed

- The end-of-turn gate now attributes edits to the session that made them. Edit-tool calls are read
  incrementally from the session's own transcript (a per-session offset; native subagents' transcripts
  under the session count too), and shell commands are measured, not guessed: where the tool has
  before/after tool hooks (Claude Code, Codex, Gemini, Copilot, Cursor), `sisi watch` snapshots the
  tree (sizes and mtimes only) before and after the command and attributes the changed paths to the
  session. A retrospective is required only when this session, or a subagent it started, edited files
  since its last retrospective. When checks fail and no path changed since the last passing state is
  attributed to this session, the stop is allowed once per distinct tree state with a note that the
  contract is not satisfied and the work must not be reported as done, recorded unverified; otherwise
  the session is sent back as before. `git commit` and sisi's own commands (except `contract
  init/waive/trust`) never count as edits; another agent's write inside this session's command window
  is attributed to this session (strict, documented); tools without before/after tool events keep the
  command-text classifier. See the known limits in [docs/design.md](docs/design.md).

## [0.2.0] - 2026-11-23

### Added

- Lessons take effect on their first occurrence: verifier and recipe lessons attach as field notes at once,
  recipe lessons naming a missing recipe become draft recipe notes shown by `sisi done for`, rule, oracle and
  brief lessons become learned notes with trigger words, and tool lessons form a backlog (`sisi backlog`).
- Lessons are delivered at the moment they match — in `sisi done for`, `sisi verifiers for`,
  `sisi verifiers show`, `sisi contract init` and the gate's send-back message, at most three in 600
  characters — and every showing is recorded. Session start shows the strongest lessons first.
- A strength ladder (1 note, 2 candidate rule, 3 enforced): a recurrence after at least two showings moves a
  lesson up; folded lessons shown 20 times without a recurrence retire; lessons that keep recurring at
  strength 3 are withdrawn and not re-learned in the same form.
- `sisi cycle` (`due`, brief, `apply`, `revert`, `status`): agent-run consolidation under a base version and
  the personal-data lock, one commit per cycle, exact revert, and flagging of cycles whose deliveries got
  worse. Due-ness is a counter checked at session start, at the end of each turn, and in `sisi retro`,
  `sisi verify` and `sisi done for`; there is no scheduler, and a session is told at most once until 20
  further checks pass or the counter grows.
- Enforced lessons (`overlay/enforced.json`), checked like floors; command checks run only in trusted projects.
- `sisi improve` and a learning line in `sisi status`; [docs/learning.md](docs/learning.md).
- Matching measured on labelled corpora in the test suite (distinctive-word weighting), matched lessons on
  `sisi done ID`, unconfirmed duplicate sightings recorded on the retro refusal path, promotions that
  require two showings since the previous promotion, and required `--when` terms on `sisi retro` (the bridge
  vocabulary a later agent with different words needs).
- A two-part delivery block in `sisi done for`, `sisi done ID`, `sisi verifiers for` and
  `sisi contract init`: strict "likely to apply" lessons in full (two of the request's own content words
  inside the when-terms, or one plus the printed entry as target), then every loose lesson as a heading
  within a 1,500-character budget for the asking agent to judge. Listings and readings are counted
  separately, and more than 30 loose lessons (or headings over budget) makes a cycle due.
- Retro refusals are structural only (presence, length, enums, when-term count, moment differs from
  change, five exact empty answers), each naming its check and quoting the text. The earlier
  phrase-matching rules are gone: one of them refused a true lesson whose moment spelled its number out.
- Wiring for every major harness, one adapter per tool (`sisi/adapters.py`) with per-tool hook translation
  in `sisi/hookio.py` (`sisi tick --tool NAME`, `sisi gate --tool NAME`): blocking session-start and
  end-of-turn hooks for Codex CLI (with its one-time `/hooks` trust step called out in install and doctor),
  Gemini CLI, GitHub Copilot CLI, Qwen Code and Pi; a follow-up gate for Cursor; an OpenCode plugin whose
  enforcement is unproven on v2.3.2; rulebook-only links for Windsurf (pointer file), Cline, Kiro, Zed,
  Goose, Amp, Grok CLI, Crush and Aider; truthful `sisi doctor` rows for Muse Code (rulebook via foreign
  context, no native gate), Antigravity, and the T3 Code / Orca hosts. See [docs/harnesses.md](docs/harnesses.md).

### Changed

- Verifier and recipe field notes are written on a lesson's first occurrence (previously the second, from a
  second session). Existing personal data migrates on open without loss.

## [0.1.0] - 2026-11-22

First public release.

### Added

- A rulebook (`canon/core.md`, at most 120 lines) shared by every tool, plus minimum-rung floors for kinds of
  claim that may not rest on example tests alone (`canon/floors.json`).
- Contracts: `sisi contract init | check | waive | trust | untrust`, and `sisi verify` with fast and deep tiers,
  parallel checks, per-check time limits and a record of every result.
- An end-of-turn gate (`sisi gate`) that sends an agent back when a check fails or was not run, and a
  session-start hook (`sisi tick`). The gate blocks in Claude Code only.
- Wiring by reference for Claude Code, Codex and OpenCode: `sisi install`, `uninstall`, `doctor`, `audit`.
- A verifier library of 140 techniques across ten sections, and 20 "what done means" recipes, with
  `sisi verifiers` (list, show, for, doctor, lint) and `sisi done`.
- Retrospectives and shared lessons (`sisi retro`, `sisi lessons`), human-stated preferences held in quarantine
  (`sisi learn`), and time to delivery (`sisi time`, `sisi status`).
- Product and personal data kept apart: a personal folder with its own git history, an overlay of learned changes
  to rules, verifiers and recipes, `sisi update`, `export`, `import`, `migrate`.
- Releases for people who both use and develop sisi (`sisi release`, `rollback`, `dev`, `promote`).
- A data layer for learning from past sessions: harvest of Claude Code transcripts, a task set, escape
  candidates, check statistics and a weekly scoreboard.
- `sisi --version` and `sisi version`.

### Not included

- The build conductor (`sisi build`, `sisi inbox`) and the model-driven learning loop are designed in
  `docs/design.md` and not built.
