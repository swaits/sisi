---
id: api-surface-typescript
title: Public API report diffs for TypeScript with API Extractor
answers: Did the exported types and functions of this TypeScript package change, and was that intended?
rung: 4
section: regression
languages: typescript
kinds: general
cost: medium
detect: npx --no-install api-extractor --help
ran_here: yes
verified: ran
---

## Use when
- You maintain a TypeScript library or package whose exported types others import.
- You want any change to the public surface to show up as a reviewable diff in a committed file.

## Do not use when
- The code is an application, not a library; nobody imports it.
- You only want type checking; `tsc --noEmit` is enough (see `zero-warnings`).

## Set up
```sh
npm i -D @microsoft/api-extractor typescript
mkdir -p config etc             # init writes to config/ only if it exists; --local needs etc/ to exist
npx api-extractor init          # creates config/api-extractor.json (else ./api-extractor.json)
npm run build                   # api-extractor reads the emitted .d.ts files
```
`tsconfig.json` needs `"declaration": true`. Set `mainEntryPointFilePath` (template default `<projectFolder>/lib/index.d.ts`) to your built `.d.ts`; it should match `typings` in `package.json`. `apiReport.enabled` is `true` in the template. The report is written to `etc/<unscopedPackageName>.api.md` and must be committed. Every export needs a release tag (`/** @public */`), or the `ae-missing-release-tag` warning fails the non-local run.

## Minimal example
```sh
npm run build
npx api-extractor run --local     # writes or updates etc/pkg.api.md; use only when you intend to change the API
git diff etc/pkg.api.md           # review: every line here is a public change
npx api-extractor run --print-api-report-diff   # CI mode: fails if the report differs from the committed one, and prints the diff
```
Take the report BEFORE editing: run `api-extractor run --local`, commit, then edit. After editing, run it without `--local`; a nonzero exit means the surface changed. Then decide: revert the change, or update the report in the same commit and say why.

## Run
`npm run build && npx api-extractor run`

Passing looks like: `API Extractor completed successfully`, exit 0. Failure: the warning `You have changed the API signature for this project. Please copy the file "temp/pkg.api.md" to "etc/pkg.api.md", or perform a local build`, then `API Extractor completed with warnings` and exit 1. A missing report file fails the same way (`The API report file is missing`). In non-local mode any warning, not only the report diff, makes the run fail.

## As a contract check
```json
{"id": "ts-api-report", "claim": "The exported API matches the committed API report", "kind": "general", "rung": 4,
 "cmd": "npm run build && npx api-extractor run", "expect": {"exit": 0}, "timeout_s": 300, "tier": "deep"}
```

## What a pass does not prove
- Only the exported names and types, not behaviour.
- Running with `--local` rewrites the report and passes anything. In an agent's contract, use the non-local command.
- Ran here with @microsoft/api-extractor 7.60.1 and TypeScript 6.0.3: `--local` wrote the report, a plain run passed on an unchanged API, and a plain run after adding an export exited 1 with the diff. TypeScript 6 also needs `rootDir` in `tsconfig.json`.
- Types that are exported but marked `@internal` are filtered out of some reports by configuration.
- Check the check: add an `export` and confirm the run fails until the report is updated.
