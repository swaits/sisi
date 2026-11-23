---
id: licence-notices
title: Generating and checking third-party licence notices
answers: Does the shipped product carry the licence texts and copyright notices its dependencies require?
rung: 3
section: safety
languages: any
kinds: general
cost: medium
detect: command -v cargo-about
ran_here: no
verified: docs
---

Note: cargo-about is not usable here (the mise shim has no version set), so the
script was not run. The cargo-about install command and the `generate` and `init`
flags below were checked against its documentation (EmbarkStudios/cargo-about,
docs/src). The generate-then-compare shape is the one used by a working script in a Rust and Lean 4
project (a `scripts/notices.sh`), which also calls `cargo about generate --locked --all-features --offline`.

## Use when
- You ship a binary, package or image that contains other people's code. MIT, BSD, Apache-2.0 and ISC all require their text to travel with copies.
- A dependency was added, removed or upgraded.
- Before release (see `release-gate`).

## Do not use when
- You only run the code internally and never distribute it.
- The question is "is this licence allowed at all"; that is `dependency-audit-rust` (or the ecosystem's licence checker).

## Set up
Rust: `cargo install --locked --features cli cargo-about` (the `cli` feature is needed), then `cargo about init` for
`about.toml` and `about.hbs`. `about.toml` must carry an `accepted` list of licence ids (in priority order); cargo-about errors on a crate whose licence it cannot satisfy from that list. Other ecosystems: `pip-licenses`,
`license-checker`, or `go-licenses report`. Commit the generated file.

## Minimal example
`scripts/notices.sh` generates `THIRD-PARTY-NOTICES.txt`, or with `--check` fails
if the committed copy is stale:

    #!/usr/bin/env bash
    set -euo pipefail
    tmp=$(mktemp); trap 'rm -f "$tmp"' EXIT
    cargo about generate --locked --all-features --fail about.hbs > "$tmp"
    if [ "${1:-}" = "--check" ]; then
      diff -q "$tmp" THIRD-PARTY-NOTICES.txt >/dev/null \
        || { echo "notices out of date: run scripts/notices.sh" >&2; exit 1; }
    else cp "$tmp" THIRD-PARTY-NOTICES.txt; fi

`--fail` exits non-zero when a crate's licence cannot be determined; without it such crates are skipped. For a workspace add `--workspace`, or point `-m crates/app/Cargo.toml` at the one binary you ship, so the list is what the program contains. `--offline` (never touch the network) makes cargo-about use only the crates' packaged files, losing clarifications that fetch licence text from a repository. `-c about.toml` is the default config path.

The output must not contain dates or absolute paths, or the byte comparison
fails on every machine.

## Run
    scripts/notices.sh --check

Passing looks like: exit 0, no output. Failure prints "notices out of date" and
exits 1; regenerate, read the diff, commit.

## As a contract check
    {"id": "notices-current", "claim": "THIRD-PARTY-NOTICES.txt matches the dependencies", "kind": "general", "rung": 3, "cmd": "scripts/notices.sh --check", "expect": {"exit": 0}, "timeout_s": 300, "tier": "deep"}

## What a pass does not prove
That the file is current, not that it is packaged. Also check the built package
contains it (see `release-gate`). Generators fall back to a licence's standard
text when a crate's own file does not match, which has a placeholder copyright
line; MIT and BSD want the real notice. Bundled fonts and vendored code are
outside the dependency graph and need their own entries.
