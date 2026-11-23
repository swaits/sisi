---
id: visual-regression-web
title: Screenshot comparison for web UI with Playwright
answers: Did my change alter how the page looks anywhere I did not mean to change?
rung: 4
section: regression
languages: javascript, typescript, python
kinds: ui
cost: medium
detect: npx playwright --version
ran_here: yes
verified: ran
---

## Use when
- A page already looks right and you are about to edit its CSS, markup or components.
- You were asked to change one region (a button, a header) and must show nothing else moved.
- The user has approved a design and wants it pinned.

## Do not use when
- The page is still being designed; screenshots will fail on every edit. Use a structure snapshot (`ui-structure-snapshot`) first.
- The content is live data you cannot fix or mask.

## Set up
```sh
npm i -D @playwright/test && npx playwright install chromium   # once
```
In `playwright.config.ts` fix the viewport, disable animations and allow no drift: `expect: { toHaveScreenshot: { maxDiffPixels: 0, animations: 'disabled' } }`, `use: { viewport: { width: 800, height: 600 } }`. Run on one OS only (the CI image); font rendering differs between OSes.

## Minimal example
`tests/home.spec.ts`
```ts
import { test, expect } from '@playwright/test';
test('home looks the same', async ({ page }) => {
  await page.goto('/');
  // Dynamic regions are masked: a changing clock must not fail the test.
  await expect(page).toHaveScreenshot('home.png', { mask: [page.locator('#clock')] });
});
// Per-region scope: every region except the intended one gets its own baseline.
test('header is untouched', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#hdr')).toHaveScreenshot('header.png');
});
```
Order of work: (1) BEFORE the first edit run `npx playwright test --update-snapshots` and commit the PNGs. (2) Edit. (3) Run `npx playwright test`. (4) The intended region may differ. Re-baseline only that region's test (`npx playwright test -g "buy button" --update-snapshots`) and keep the whole-page test failing only on that region by masking it: `mask: [page.locator('#buy')]`. Every other test must pass untouched. Read the diff images in `test-results/` before re-baselining.

## Run
`npx playwright test`

Passing looks like: `N passed`, exit 0. Failure prints `N pixels (ratio ...) are different` and writes `-actual.png` and `-diff.png` into `test-results/`. Missing baselines are written on first run and the run still reports them; treat that as not yet checked.

## As a contract check
```json
{"id": "ui-visual-regression", "claim": "No unintended visual change on the pages covered by baselines", "kind": "ui", "rung": 4,
 "cmd": "npx playwright test", "expect": {"exit": 0, "stdout_contains": "passed"}, "tier": "deep", "timeout_s": 300}
```

## What a pass does not prove
- Only that pixels match the baseline. If you re-baseline to make a failure go away you have proved nothing; re-baseline only the region you meant to change.
- A mask hides a region completely: do not mask the thing you changed in the other tests.
- It does not show the design is good or that feedback was understood. That needs rung 5 or 6.
- Only the viewports, pages and states you captured are covered (hover, error and empty states need their own tests).
- Check the check: change a colour and see it fail. In a run here, changing the masked clock text still passed while a changed button label failed.
