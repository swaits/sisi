---
id: illegal-states-unrepresentable
title: Making illegal states unrepresentable with types, checked by a compile-fail test
answers: Is it impossible, not just unlikely, for callers to build an invalid value or call an operation in the wrong state?
rung: 1
section: prove
languages: rust, typescript
kinds: general, state-machine, money
cost: low
detect: cargo --version
ran_here: yes
verified: ran
---

## Use when
- A value has a validity rule (a percentage 0 to 100, a non-empty list, a validated email) that is currently checked in many places.
- An object has phases (closed then open, draft then posted) and calls are only legal in some of them.
- You want the compiler to reject misuse, and a test that proves it does.

## Do not use when
- The rule depends on runtime data the type cannot hold (a balance across accounts). Use a runtime check plus `kani` or tests.
- A quick enum or `Option` already forces the case. Do not add types for show.

## Set up
Rust: nothing extra. Make fields private and expose a constructor that validates (parse, don't validate: return `Option`/`Result` once at the edge, then pass the type everywhere). Use enums and exhaustive `match` with no `_` arm; use the typestate pattern with a type parameter for phases. For compile-fail tests use `compile_fail` doctests, or the `trybuild` crate (add under `[dev-dependencies]`) to compare compiler output.
TypeScript: see `typescript-type-level`.

## Minimal example
```rust
pub struct Percent(u8);                        // private field
impl Percent {
    pub fn new(v: u8) -> Option<Percent> { (v <= 100).then_some(Percent(v)) }
    pub fn get(self) -> u8 { self.0 }
}

pub struct Conn<S>(std::marker::PhantomData<S>);
pub struct Open; pub struct Closed;
impl Conn<Closed> { pub fn open(self) -> Conn<Open> { Conn(std::marker::PhantomData) } }
impl Conn<Open>   { pub fn send(&self, _b: &[u8]) {} }

/// ```compile_fail
/// use ise::Percent;
/// let p = Percent(250); // private field: must not compile
/// ```
///
/// ```compile_fail
/// use ise::Conn;
/// Conn::new().send(b"x"); // a closed connection has no `send`
/// ```
pub struct CompileFailTests;
```
(Add `Conn::new() -> Conn<Closed>`.) The crate is named `ise` in the doctests.

## Run
`cargo test --doc`

Passing looks like: exit 0 and `test src/lib.rs - CompileFailTests (line N) - compile fail ... ok`. Failure: a `compile_fail` test whose code does compile shows `Test compiled successfully, but it's marked 'compile_fail'.` and exits 101. With `trybuild`, `cargo test` compares the real compiler message with a stored `.stderr` file.

## As a contract check
```json
{"id": "prove-percent-unrepresentable", "claim": "A Percent above 100 and a send on a closed connection cannot be written: both fail to compile", "kind": "general", "rung": 1, "cmd": "cargo test --doc", "expect": {"exit": 0, "stdout_contains": "compile fail"}, "tier": "deep", "timeout_s": 600}
```

## What a pass does not prove
- A `compile_fail` test passes on any compile error, including a typo. Observed: adding an error code like `compile_fail,E0451` is not enforced on stable (a wrong code still passed). Use `trybuild`, which pins the message, for tests that must fail for the right reason.
- Rules the type cannot express remain open; construction inside the defining module bypasses private-field checks. Keep the smart constructor the only way in, and review `unsafe` and `Default`/`Deserialize` impls that could build invalid values.
