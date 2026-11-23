---
id: dependency-audit-rust
title: cargo-deny and cargo-audit for advisories, yanked crates, licences and sources
answers: Do my Rust dependencies have known vulnerabilities, yanked versions, disallowed licences or untrusted sources?
rung: 2
section: safety
languages: rust
kinds: general
cost: low
detect: cargo-deny --version
ran_here: yes
verified: ran
---

Ran here with cargo-deny 0.20.2 (licenses, bans, sources and advisories on a
tiny crate). cargo-audit was not installed; its command is from memory.

## Use when
- Any change to `Cargo.toml` or `Cargo.lock`, and on a schedule (new advisories appear without you changing code).
- You must ship under a licence and need to know no dependency conflicts with it.
- Before release, so no yanked crate or unknown git source goes out.

## Do not use when
- The project is not Rust; see `dependency-audit-general`.
- You want proof the dependency code is correct. This reports known problems only.

## Set up
    cargo install cargo-deny --locked
    cargo deny init                      # writes deny.toml; edit it as below

## Minimal example
`deny.toml`:

    [advisories]
    yanked = "deny"
    [licenses]
    allow = ["MIT", "Apache-2.0", "BSD-3-Clause", "ISC", "Unicode-3.0"]
    [bans]
    wildcards = "deny"
    [sources]
    unknown-registry = "deny"
    unknown-git = "deny"

Record every exception beside its reason and a date, never on the command line.

## Run
    cargo deny check advisories licenses bans sources
    cargo audit                           # alternative advisory-only check

Passing looks like: `advisories ok, bans ok, licenses ok, sources ok`, exit 0.
Failure exits non-zero (4 in the run here) with `error[rejected]` or
`error[unlicensed]`. The default `deny init` file allows no licence, so a
fresh crate fails until `allow` is filled in. Advisory checks need network to
fetch the RustSec database.

## As a contract check
    {"id": "cargo-deny", "claim": "No known advisories, yanked crates, disallowed licences or unknown sources", "kind": "general", "rung": 2, "cmd": "cargo deny check advisories licenses bans sources", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 600}

## What a pass does not prove
Only known, reported problems. Today's pass says nothing about tomorrow's
advisory, so schedule it (see `check-tiering`). `ignore` entries and loosened
`allow` lists are how this check gets defeated: read the diff of `deny.toml`.
An unmaintained-crate notice is not a vulnerability; decide that on purpose.
