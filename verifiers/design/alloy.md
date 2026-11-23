---
id: alloy
title: Alloy 6 for structural and relational designs
answers: Does my data model or permission scheme allow a state that breaks a rule I care about?
rung: 1
section: design
languages: any
kinds: general
cost: medium
detect: test -f alloy.jar && java -version
ran_here: yes
verified: ran
---

## Use when
- The design is about relations: who owns what, who may read what, tree and graph shapes, uniqueness and reference rules.
- You want a counterexample drawn for you when a rule can be broken.
- Alloy 6 also has `var` signatures and temporal operators, so small state machines work too.

## Do not use when
- The state space is large and numeric. Use `tlaplus` or `z3-smt`.
- You need a result for unbounded sizes. Alloy checks up to a scope.

## Set up
Download `org.alloytools.alloy.dist.jar` from github.com/AlloyTools/org.alloytools.alloy/releases (6.2.0 tried) and save it as `alloy.jar`. Needs Java 17.

## Minimal example
`perm.als`:
```
sig User {}
sig Doc { owner: one User, readers: set User }
fact OwnerCanRead { all d: Doc | d.owner in d.readers }
assert OwnerAlwaysReads { all d: Doc | d.owner in d.readers }
check OwnerAlwaysReads for 5
```

## Run
`java -jar alloy.jar exec -f perm.als`

Passing looks like: the table line `check OwnerAlwaysReads ... UNSAT` (no counterexample within scope 5). Failure looks like `... SAT` on a `check` line. The exit status is 0 in both cases (observed), so a contract must test the text. The table goes to stderr, so redirect with `2>&1` before grepping. Without the `fact` the same run printed `SAT`. Solutions are written to a folder named after the file (`perm/`), including `receipt.json`; `-f` replaces it.

## As a contract check
```json
{"id": "design-permissions-alloy", "claim": "Within scope 5 every document owner can read their document", "kind": "general", "rung": 1, "cmd": "bash -c \"java -jar alloy.jar exec -f perm.als 2>&1 | grep -E '^[0-9]+\\. check .* UNSAT$'\"", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 300}
```

## What a pass does not prove
- Only instances up to the scope (here 5 per signature). Small scopes catch most design bugs but not all.
- A `fact` that is too strong can make the model empty, so every check passes. Add a `run` for a realistic case and confirm it is SAT.
- The assertion above restates the fact, so it is trivial; in practice assert a consequence of the rules, not the rule.
