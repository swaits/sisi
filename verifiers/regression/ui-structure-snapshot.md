---
id: ui-structure-snapshot
title: Accessibility-tree and DOM-structure snapshots
answers: Is the page's structure (headings, buttons, labels, order) the same as before, regardless of pixels?
rung: 4
section: regression
languages: javascript, typescript, python
kinds: ui
cost: low
detect: npx playwright --version
ran_here: yes
verified: ran
---

## Use when
- You want a UI check that does not break on fonts, antialiasing or colour shifts.
- You are refactoring markup or components and the screen must keep the same elements and labels.
- You want a companion to `visual-regression-web`: structure first, pixels second.

## Do not use when
- The claim is about appearance (spacing, colour, alignment). Structure snapshots cannot see it.
- You have not decided what the structure should be; you would just record whatever exists.

## Set up
```sh
npm i -D @playwright/test && npx playwright install chromium
```
Python has the same API: `expect(locator).to_match_aria_snapshot("...")` in `pytest-playwright`.

## Minimal example
```ts
import { test, expect } from '@playwright/test';
test('main structure', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('main')).toMatchAriaSnapshot(`
    - heading "Shop" [level=1]
    - paragraph
    - button "Buy"
    - navigation "Main":
      - link "Home"
  `);
});
```
Take the snapshot BEFORE editing. Scope the locator to the region you are touching, and keep a second snapshot of the rest of the page, so only the intended region may change. Use `npx playwright test --update-snapshots` to write the expectations into the test file or `.aria.yml` files when you mean to change them (flag `--update-source-method` picks patch or overwrite).

## Run
`npx playwright test`

Passing looks like: `N passed`, exit 0. Failure shows a diff such as `- button "Buy"` against `+ button "Buy now"` and exit 1.

## As a contract check
```json
{"id": "ui-structure", "claim": "The accessibility tree of the main regions is unchanged", "kind": "ui", "rung": 4,
 "cmd": "npx playwright test tests/aria.spec.ts", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 300}
```

## What a pass does not prove
- Nothing about appearance. A button can keep its label and become invisible.
- Matching is partial by default: extra elements not listed may exist. Write the whole subtree you care about, or check the Playwright aria-snapshot docs for the `/children` setting (not run here).
- Accessible names come from text, so copy changes fail it; that is often the signal you want.
- Check the check: edit a label and see the diff appear (done here with Playwright 1.57).
- Other tools (Testing Library `getByRole`, Cypress snapshots) give the same kind of check; the claim is the same, the rung is 4.
