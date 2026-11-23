---
id: native-gui-change
title: Changing a native desktop or mobile interface
applies_to: A window, dialog or widget in a desktop or mobile application built with a native or immediate-mode toolkit.
---

## Done means
- The app starts from the built binary, reaches the changed screen through the real controls, and the change works there.
- The screen is captured and compared to a baseline: only the intended pixels changed.
- The view model and the logic behind it are tested without a window, so most of the behaviour needs no display.
- The change respects the data it shows: the UI does not write what it should only read, and every number shown is the engine's.
- Keyboard use, window resizing, high-DPI and long text behave.
- The human has seen the result, or accepted a recorded before-and-after.

## Checks
- Pixels: `visual-regression-native-gui` (regression), rung 4; `pairwise-comparison` (intent) for whether the new one is better.
- Logic: unit and property tests on the view model (`proptest` or `hypothesis`, many-inputs); `derived-view-agreement` (many-inputs) so shown figures match the engine's.
- Read-only: `read-only-guarantee` (regression).
- Structure: `ui-structure-snapshot` (regression) where the toolkit exposes an accessibility tree.
- Install: `packaging-install-upgrade`, `cross-platform-matrix` (real-world).
- Taste: `taste-baseline`, `owner-acceptance-runbook` (intent), rung 6.

## Common false finishes
- Unit tests of the model pass; the window was never opened.
- A screenshot from one platform, theme or scale factor stands for all.
- The baseline image was updated to match the new rendering without a person looking at it.
- Event handlers wired to the wrong widget when several look alike.
- The UI shows a number computed again in the UI code instead of the engine's, and they diverge in an edge case.
- Layout breaks with long text, empty data, or a narrow window.
- It runs on the developer's GPU or font set and fails on a clean machine.
- Closing or killing the app mid-action leaves bad data.
