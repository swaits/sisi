---
id: isabelle
title: Isabelle/HOL proofs with Sledgehammer
answers: Is this property proved by machine, with automatic proof search to help?
rung: 1
section: prove
languages: any
kinds: general, state-machine
cost: high
detect: isabelle version
ran_here: no
verified: docs
---

## Use when
- Your team already uses Isabelle, or you build on the Archive of Formal Proofs.
- You want strong automation: Sledgehammer calls external provers and returns a proof line to paste in.
- The claim is about algorithms or specifications over lists, sets and numbers.

## Do not use when
- You have no existing Isabelle investment. `lean4-proofs` has better command-line tooling for agents.
- A bounded check is enough (`kani`, `cbmc`).

## Set up
Download the bundle for your platform from isabelle.in.tum.de (current release: Isabelle2026, October 2026; it includes its own Java, ML system and provers). On Linux, unpack it and put its `bin/` on PATH (the install page shows `Isabelle2026/bin/isabelle`). Not installed here, so the example was not run. A session is a directory with a `ROOT` file:
```
session Demo = HOL +
  theories Demo
```

## Minimal example
`Demo.thy`:
```isabelle
theory Demo imports Main begin
theorem rev_rev: "rev (rev xs) = xs"
  by simp
end
```
When a goal resists, write `sledgehammer` in the interactive editor, take the proof it prints (`by (metis ...)`), and replace the call. Do not leave `sledgehammer` or `sorry` in committed files.

## Run
`isabelle build -D .` (`-D DIR` includes a session directory and selects its sessions; `-d DIR` only makes sessions known; `-j N` runs N jobs in parallel; `-v` is verbose).

Passing looks like: exit 0, with the build log reporting the session `Demo` as finished (exact wording is not in the system manual). The manual says the overall return code is the status of the set of selected sessions, so a session that fails to build gives a non-zero exit (conventionally 1) and the log names the failing theory and step. The manuals read here do not say whether a plain `isabelle build` rejects `sorry` or `oops` (or what the `quick_and_dirty` option changes), so do not rely on the build alone: grep the sources for both, as in the contract below.

## As a contract check
```json
{"id": "prove-demo-isabelle", "claim": "The Isabelle session builds and contains no sorry", "kind": "general", "rung": 1, "cmd": "bash -c 'isabelle build -D . && ! grep -R -E \"\\\\b(sorry|oops)\\\\b\" --include=*.thy .'", "expect": {"exit": 0}, "timeout_s": 3600, "tier": "deep"}
```

## What a pass does not prove
- Only the stated theorem about the Isabelle definitions.
- Not run here. `isabelle build -D`, the `ROOT` syntax and the exit-status rule come from the Isabelle system manual; whether the build itself rejects `sorry` is unconfirmed (see Run).
- The grep also flags the word inside comments, which is the safe direction. Check the check: put a `sorry` in a scratch lemma and confirm the contract fails.
