---
id: e2e-playwright
title: End-to-end browser tests against the running app (Playwright)
answers: Can a user actually do this task in the real running app in a real browser?
rung: 3
section: real-world
languages: javascript, typescript, python
kinds: ui, general
cost: medium
detect: npx playwright --version
ran_here: yes
verified: ran
---

## Use when
- A claim is about a user flow: sign in, add to cart, save a form, see the result.
- Unit tests pass but you have not seen the pieces work together through the real UI.

## Do not use when
- The claim is about a calculation or a rule; a unit or property test is faster and more precise.
- The flow depends on third-party services you cannot fake; stub them at the network layer (`page.route`) and say you did.

## Set up
```sh
npm i -D @playwright/test && npx playwright install chromium
```
Let Playwright start the app so the test never runs against a stale server: in `playwright.config.ts` set `webServer: { command: 'npm run start', url: 'http://localhost:3000', reuseExistingServer: false }` and `use: { baseURL: 'http://localhost:3000' }`. Use a fresh test database or fixture each run.

## Minimal example
```ts
import { test, expect } from '@playwright/test';
test('a visitor can add a note', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('textbox', { name: 'Note' }).fill('buy milk');
  await page.getByRole('button', { name: 'Add' }).click();
  await expect(page.getByRole('listitem')).toHaveText('buy milk');   // asserts the result, not just that the click worked
});
```
Locate by role and accessible name, not CSS classes, so the test survives restyling. Assert on what the user sees after the action. For a bug fix, write the test so it fails on the old code first.

## Run
`npx playwright test`

Passing looks like: `N passed`, exit 0. Failure shows the failing step, a trace (`--trace on` then `npx playwright show-trace`), and exit 1. A web server that fails to start makes the run fail, not pass. (Run here against a static page served by `python3 -m http.server`.)

## As a contract check
```json
{"id": "e2e", "claim": "The add-note flow works in a real browser", "kind": "ui", "rung": 3,
 "cmd": "npx playwright test", "expect": {"exit": 0, "stdout_contains": "passed"}, "tier": "deep", "timeout_s": 600}
```

## What a pass does not prove
- Only the paths you scripted, in one browser. Add projects for Firefox and WebKit when it matters.
- Flaky tests tempt retries. A test that passes only on retry is failing sometimes; fix the wait (assert on a visible state) instead of adding `retries`.
- `expect(...).toBeVisible()` alone proves little; assert the content or effect.
- Check the check: break the feature (remove the handler) and confirm the test fails.
