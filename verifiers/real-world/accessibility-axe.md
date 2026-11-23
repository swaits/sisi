---
id: accessibility-axe
title: Automated accessibility checks with axe-core
answers: Does this page have any detectable accessibility violations (contrast, labels, roles)?
rung: 3
section: real-world
languages: javascript, typescript, python
kinds: ui
cost: low
detect: npx playwright --version
ran_here: no
verified: docs
---

## Use when
- You build or change pages and the user said accessibility matters, or you add forms, buttons, images or colours.
- You want a cheap guard against missing labels, low contrast, wrong ARIA roles and bad heading order.

## Do not use when
- You want to claim "accessible". Automated rules catch only a portion of problems; say "no detectable violations".

## Set up
```sh
npm i -D @playwright/test @axe-core/playwright && npx playwright install chromium
```

## Minimal example
```ts
import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
test('home has no detectable a11y violations', async ({ page }) => {
  await page.goto('/');
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);     // prints each violation with the offending element
});
```
Run it on every state that changes the DOM: after opening the menu, the dialog, the error state. Use `.withTags(['wcag2a', 'wcag2aa'])` to pick a standard. Do not disable rules to get green; if a rule must be excluded, `.disableRules([...])` it with a comment saying why and mention it in the report. Take the violation list before your change and show it has not grown.

## Run
`npx playwright test`

Passing looks like: `N passed`. Failure prints the `violations` array: rule id (`color-contrast`), impact, and the HTML node, exit 1.

## As a contract check
```json
{"id": "a11y-axe", "claim": "No axe violations on the covered pages", "kind": "ui", "rung": 3,
 "cmd": "npx playwright test tests/a11y.spec.ts", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 600}
```

## What a pass does not prove
- Roughly a third to a half of accessibility problems can be found by machine; keyboard flow, screen reader wording and sense of the page need a human or a real assistive tool.
- Only pages and states visited. Pixel-level contrast on images is not checked.
- Not run here; the `AxeBuilder({ page }).analyze()` call is from the package README.
- Check the check: add an `<img>` without `alt` and confirm `image-alt` appears.
