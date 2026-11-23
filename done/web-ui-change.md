---
id: web-ui-change
title: Changing a web interface
applies_to: A page, component or flow in a browser-based user interface.
---

## Done means
- The page works in a real browser through the real user journey, not only in a component test.
- It looks right at the sizes users use (phone, tablet, desktop) and nothing else on the page moved unintentionally.
- It is usable by keyboard and screen reader, with sufficient contrast.
- Loading, empty, error and slow-network states exist and are shown correctly.
- The change did not make the page measurably slower or heavier.
- The human has seen it, or the person's verdict on a before-and-after is recorded.

## Checks
- Journey: `e2e-playwright` (real-world), rung 3, running the actual flow with assertions on what the user sees.
- Appearance: `visual-regression-web` (regression), rung 4; `pairwise-comparison` and `taste-baseline` (intent) for whether it is better.
- Structure: `ui-structure-snapshot` (regression) for the accessibility tree.
- Accessibility: `accessibility-axe` (real-world), rung 2 to 3.
- Performance: `lighthouse-budget`, `size-budget`, `perf-regression`.
- Contract with the backend: `contract-testing-pact`. Invariants: `baseline-before-change`.
- Judge: `rubric-judge` (intent) for tone and clarity, rung 5; the human for taste, rung 6.

## Common false finishes
- Screenshots were taken after the change but not compared with before; "looks fine" is a guess.
- The snapshot was regenerated to match the new output, so the diff proves nothing. Look at the images.
- Tested at one viewport and one browser.
- Only the success path was tested; the error and empty states look broken.
- Component tests pass while the page fails to load because of a bundle, route or auth problem.
- Text overflows or truncates with long names, other languages or large font settings.
- A new element is not reachable by keyboard, or steals focus.
- Passing a11y scans taken as proof the page is accessible; they find only a fraction of problems.
- The dev server was tested and the production build was not.
