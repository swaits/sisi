# Verifier library: format and quality bar

The library exists so that an agent, in any tool, can answer two questions
without asking a human: "how do I know this works?" and "how do I know I am
done?". Agents query it with `sisi verifiers for "<claim>"` and `sisi done for
"<kind of work>"`. Every entry must be something an agent can act on in
minutes: a real tool, a real command, and a snippet it can paste into a
contract.

## Technique entries: `verifiers/<section>/<id>.md`

Sections: `design`, `prove`, `many-inputs`, `concurrency`, `test-quality`,
`regression`, `real-world`, `safety`, `intent`, `completeness`.

The file stem equals `id`. Lowercase, hyphens. The file starts with a header
of single-line `key: value` pairs between `---` lines:

```
---
id: cargo-mutants
title: Mutation testing for Rust with cargo-mutants
answers: Would my tests notice if this code were wrong?
rung: 2
section: test-quality
languages: rust
kinds: general, money, parsing
cost: medium
detect: cargo mutants --version
ran_here: no
verified: docs
---
```

- `answers`: the question, in plain words, that a passing run answers. This
  is what the chooser matches on, so write it the way an agent would phrase
  its doubt.
- `rung`: 1 proof, model checking or types; 2 property-based testing, fuzzing,
  differential, mutation; 3 examples; 4 golden files and snapshots;
  5 judged rubric; 6 human.
- `languages`: comma list, or `any`.
- `kinds`: any of general, concurrency, parsing, money, state-machine,
  migration, ui.
- `cost`: low, medium or high. Set-up plus run effort for a first use.
- `detect`: a shell command that exits 0 when the tool is installed. Empty if
  the technique needs no tool.
- `ran_here`: yes only if you ran the minimal example on this machine and it
  behaved as the entry says.
- `verified`: `ran` (you ran it), `docs` (commands and flags checked against
  the tool's current official documentation or its `--help`), or `memory`
  (neither; avoid this, and never use it silently).

Body headings, in this order, all required:

- `## Use when`: the situations and claims it fits. Two to five bullets.
- `## Do not use when`: where it is the wrong tool or a weaker one is enough.
- `## Set up`: install and project set-up commands.
- `## Minimal example`: the smallest complete, correct example. Real code.
- `## Run`: the exact command, and under a `Passing looks like:` line the
  output or exit status that means success. Say how failure shows.
- `## As a contract check`: a JSON object for the `checks` array of
  `.sisi/contract.json`, with `id`, `claim`, `kind`, `rung`, `cmd`, `expect`
  (`exit`, optionally `stdout_contains`) and `timeout_s`. Whenever `timeout_s`
  is over 60, include `"tier": "deep"`: fast checks (the default) may not
  exceed 60 s, because they run in the end-of-turn gate. Deep checks run with
  `sisi verify --deep`, in the background, and never block a turn by being slow.
  Contract-level options: top-level `"parallel": true` makes `sisi verify` and
  the gate run the fast-tier checks at the same time (at most 4; results still
  come in contract order), and `"serial": true` on a check makes it always run
  alone, for checks that share a port, a database or a build directory. Without
  `parallel`, checks run one after another.
- `## What a pass does not prove`: the limits. Bounds, assumptions, things
  that make a pass vacuous, and how to check that the check itself can fail.

Length: 30 to 80 lines. No history of the tool, no selling, no filler.

## Recipes: `done/<id>.md`

Header keys: `id`, `title`, `applies_to` (one line). Body headings, required:

- `## Done means`: the claims that must all be true, in plain words.
- `## Checks`: for each claim, the technique ids from `verifiers/` that can
  show it, strongest first, and the minimum acceptable rung.
- `## Common false finishes`: the ways this kind of work looks done and is
  not.

Length: 25 to 60 lines.

## Quality bar

- Commands and flags must be right. Check each against the tool's official
  documentation or `--help`. A wrong flag costs an agent more than a missing
  entry. If you cannot confirm something, say so in the entry.
- Run the minimal example when the tool is already installed on this machine.
  Work only in a throwaway directory. Do not install toolchains globally and
  do not change anything outside the sisi repository.
- Prefer the technique over the brand. If several tools do the same job in
  different languages, one entry per language is right; two entries for the
  same language and job is not, unless they differ in what they can show.
- Be honest about rung. A technique that samples is rung 2 at best.
- Use plain, direct English. Full sentences. No jargon the entry does not
  explain.
