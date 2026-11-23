---
id: visual-regression-native-gui
title: Snapshot testing for native GUIs (egui_kittest and the general pattern)
answers: Did my change alter what a desktop GUI draws somewhere I did not mean to?
rung: 4
section: regression
languages: rust, any
kinds: ui
cost: medium
detect: cargo --version
ran_here: no
verified: docs
---

## Use when
- A native GUI (egui, or any toolkit you can drive headless) already looks right and you are about to change layout or styling.
- You need a baseline that works in CI where there is no screen.

## Do not use when
- A web UI: use `visual-regression-web`.
- You cannot render headless and have no way to compare the drawn output.

## Set up
In `Cargo.toml` (a reference project uses this version):
```toml
[dev-dependencies]
egui_kittest = { version = "0.36", features = ["wgpu", "snapshot", "eframe"] }
```
Other toolkits: render offscreen, or dump the draw list or widget tree, to a file and diff it (Qt: `QWidget::grab()`; GTK: widget tree dump; Flutter: `matchesGoldenFile`).

## Minimal example
```rust
use egui_kittest::Harness;
#[test]
fn sidebar_is_unchanged() {
    let mut h = Harness::new_ui(|ui| { ui.heading("Books"); let _ = ui.button("Open"); });
    h.fit_contents();
    h.snapshot("sidebar");          // tests/snapshots/sidebar.png
}
```
Do it in this order: write the test and run it on the unchanged code to create the baseline (`UPDATE_SNAPSHOTS=true cargo test`; `force` also rewrites images within the error margin), commit `tests/snapshots/`, then edit. Scope an intended change by taking one snapshot per region or widget, so only that region's baseline is refreshed.

A pattern that held up in the reference project: pixels differ between renderers (CI software renderer versus a GPU), so compare a hash of the painted shapes everywhere and pixels only on the machine that made them. The baseline stores the hash on line one and the shape text below, so a mismatch says which shape moved. Blessing is an explicit env var (`SIDENAV_BLESS=1`) that is never set to silence a failure.

## Run
`cargo test -p <gui-crate> --test <snapshot-test>`

Passing looks like: `test result: ok`. Failure shows a diff image under `tests/snapshots/` (`*.diff.png`) or the differing shapes, exit 101.

## As a contract check
```json
{"id": "gui-snapshots", "claim": "GUI snapshots match their baselines", "kind": "ui", "rung": 4,
 "cmd": "cargo test -p mygui --test snapshots", "expect": {"exit": 0, "stdout_contains": "test result: ok"}, "tier": "deep", "timeout_s": 900}
```

## What a pass does not prove
- Only the states you built in the harness. Hover, focus, small windows and high-DPI need separate snapshots.
- Not run here (egui_kittest needs a GPU or software renderer); the commands come from the crate docs and the reference project's tests.
- Raising `max_failed_pixels` above about 10 can hide a moved border; the crate docs warn about it.
- Setting the update variable and re-running makes any failure pass. Check `git diff --stat tests/snapshots` shows only the intended files.
- The shapes hash proves painting is the same, not that it looks good.
