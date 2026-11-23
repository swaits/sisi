# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

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
