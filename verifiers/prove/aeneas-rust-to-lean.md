---
id: aeneas-rust-to-lean
title: Translating Rust to Lean with Charon and Aeneas to prove real code
answers: Can I prove a property of my actual Rust function, not of a hand-written model of it?
rung: 1
section: prove
languages: rust
kinds: general, parsing, money
cost: high
detect: aeneas --help
ran_here: no
verified: docs
---

## Use when
- The Rust is safe, mostly functional code (no heavy trait objects, little unsafe) and you want an unbounded proof about it.
- You need the proof to be about the compiled-from source, so `proof-bridging` is not enough.

## Do not use when
- A bounded proof will do. `kani` is far cheaper.
- The code uses features Charon cannot translate (many closures, async, `dyn` traits). Check what it supports first.

## Set up
Both tools are built from source; there is no package install. From the Aeneas and Charon READMEs (github.com/AeneasVerif/aeneas, .../charon): you need `rustup` (Charon pins its own nightly), OCaml 5 with opam (`opam switch create 5.3.0`, then `opam install src --deps-only --with-test` in the Aeneas checkout), and Lean. In the Aeneas checkout `make setup-charon` builds Charon at the commit in `charon-pin`, and `make` builds `bin/aeneas`. Put `charon` and `aeneas` on PATH. Not installed here, so nothing below was run.

Translate, from inside the crate:
```
charon cargo --preset=aeneas           # writes <crate_name>.llbc
aeneas -backend lean my_crate.llbc -dest lean/
```
`-backend` also takes `fstar`, `coq` and `hol4`. Generated Lean files import the `Aeneas` package, so the Lean project needs it: `lake new`, copy `lean-toolchain` from `backends/lean` in the Aeneas repo, and require it in the lakefile with `[[require]] name = "aeneas" path = "PATH_TO_AENEAS_REPO/backends/lean"` (or `require aeneas from "PATH..."` in a `lakefile.lean`). Aeneas emits definitions in a `Result` monad for panics and overflow. Flags change between releases (both projects publish nightly releases); check `charon --help` and `aeneas --help`.

## Minimal example
A Rust function to prove things about:
```rust
pub fn add_cents(a: u32, b: u32) -> Option<u32> { a.checked_add(b) }
```
Aeneas emits a Lean `add_cents` returning a `Result`. You then write a theorem in a separate Lean file that says: if the result is `ok (some c)` then `c.val = a.val + b.val`, and prove it with the Aeneas tactics `step` (older releases called it `progress`; `step*` repeats it) and `scalar_tac` (arithmetic on bounded integers). The exact names and goal shapes depend on the generated code and library version, so copy the pattern from the Aeneas repository's `tests/lean/Tutorial/` (`Solutions.lean` uses `step as ⟨ ... ⟩` and `scalar_tac`). Not confirmed by running here.

## Run
`lake build --wfail` in the Lean project, after regenerating the Lean files from the current Rust.

Passing looks like: exit 0, and the audit of `lean-axiom-audit` is clean. Failure: Lean errors on the open goal.

## As a contract check
```json
{"id": "prove-add-cents-aeneas", "claim": "add_cents is exact or None, proved on the Lean translation of the Rust", "kind": "money", "rung": 1, "cmd": "bash -c 'charon cargo --preset=aeneas && aeneas -backend lean my_crate.llbc -dest lean/ && cd lean && lake build --wfail'", "expect": {"exit": 0}, "timeout_s": 3600, "tier": "deep"}
```

## What a pass does not prove
- The translation must be regenerated on every Rust change; a stale `lean/` dir proves the old code. The command above regenerates first.
- Aeneas's own semantics are trusted, and the proof assumes the Rust compiler follows them.
- Unsafe code and unsupported features are excluded or axiomatised; read the generated file for `axiom` and `opaque`.
- Not run here: the charon and aeneas invocations, `-dest`, and the tactic names were checked against the READMEs, the Aeneas command-line source and its Lean tutorial, but the example theorem was not compiled.
