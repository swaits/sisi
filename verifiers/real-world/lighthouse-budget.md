---
id: lighthouse-budget
title: Lighthouse CI budgets and score assertions
answers: Is this page still within its performance, accessibility and best-practice budgets?
rung: 4
section: real-world
languages: javascript, any
kinds: ui
cost: medium
detect: npx lhci --version
ran_here: no
verified: docs
---

## Use when
- Page weight, load time or Lighthouse scores matter and you changed scripts, images, fonts or markup.
- You want a number with a limit, checked on every change.

## Do not use when
- The page needs a login you cannot script around; Lighthouse measures a single loaded page.
- You want a verdict on user experience. Scores are a proxy.

## Set up
```sh
npm i -D @lhci/cli
```
Create `lighthouserc.json`. Run it in an environment you can repeat (a CI container); local laptops give different timings.

## Minimal example
`lighthouserc.json`
```json
{
  "ci": {
    "collect": { "url": ["http://localhost:3000/"], "numberOfRuns": 3, "startServerCommand": "npm run start" },
    "assert": {
      "assertions": {
        "categories:performance": ["error", { "minScore": 0.9 }],
        "categories:accessibility": ["error", { "minScore": 1 }],
        "total-byte-weight": ["error", { "maxNumericValue": 500000 }]
      }
    }
  }
}
```
Several runs and the median handle noise. Prefer hard resource budgets (bytes, request counts), which do not wobble, over timing metrics. Record the current scores BEFORE you edit so you know the margin. `lhci assert --preset=lighthouse:recommended` is available as a starting set and individual assertions can be switched off (`--assertions.uses-webp-images=off`).

## Run
`npx lhci autorun` (collect, assert, upload), or `npx lhci collect && npx lhci assert`.

Passing looks like: all assertions pass and exit 0. Failure prints each failed assertion with expected and actual values and exits nonzero.

## As a contract check
```json
{"id": "lighthouse", "claim": "The home page meets its Lighthouse budgets", "kind": "ui", "rung": 4,
 "cmd": "npx lhci autorun", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 600}
```

## What a pass does not prove
- Lab results on one URL and one machine, not real users' devices and networks.
- Timing scores vary between runs; a pass on three runs is not a guarantee.
- Lowering a threshold to pass is a change to review, as in `ratchet-floor`.
- Not run here (`lhci` is not installed). `lhci assert`, `--preset` and `--assertions` appear in the Lighthouse CI configuration docs; the JSON shape follows those docs.
- Check the check: set `minScore` to 1 on performance and confirm it can fail.
