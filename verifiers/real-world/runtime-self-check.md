---
id: runtime-self-check
title: Give the product its own verify or doctor command and run it as a check
answers: Does the product's own data pass its own integrity checks (hash chain, control totals, invariants)?
rung: 3
section: real-world
languages: any
kinds: money, state-machine, general
cost: medium
detect:
ran_here: yes
verified: ran
---

## Use when
- The product holds data whose consistency can be checked from the data alone: a journal with a hash chain, ledgers whose debits equal credits, counters that must add up to a stored total, foreign keys that must resolve.
- You want the same check to run in tests, after a migration, after a restore, in CI and in production.

## Do not use when
- There is no invariant to check. A `verify` command that always prints OK is worse than none.

## Set up
Add a command, for example `mytool verify [--data DIR]`, that reads the data and checks invariants without writing anything (see `read-only-guarantee`). Make it exit 0 when all hold and nonzero with a specific message for each broken one. Typical checks: each record's hash includes the previous hash; sum of debits equals sum of credits; row counts match a stored control total; no orphan references; every file referenced exists.

## Minimal example
A hash-chained log, with `verify` as a few lines of shell:
```sh
# each line: <prev-hash> <payload>; the next line's prev-hash must be sha256 of the whole previous line
prev=GENESIS
while IFS= read -r line; do
  [ "${line%% *}" = "$prev" ] || { echo "chain broken at: $line"; exit 1; }
  prev=$(printf '%s' "$line" | sha256sum | cut -d' ' -f1)
done < journal.log
echo "chain ok"
```
Run it on good data, then edit one payload byte in a copy and confirm it fails (done here: a tampered line printed `chain broken at:` and exited 1). Then use it as a check wherever data changes: after a migration (`db-migration-safety`), after an upgrade (`packaging-install-upgrade`), after a restore. The owner's reference project exposes this as a `verify` tool and runs it in migration and hostile-input tests, asserting the books still verify afterwards.

## Run
`mytool verify --data data/` or the script above.

Passing looks like: `chain ok` (or the product's own summary) and exit 0. Failure: a message naming the first broken record, exit 1.

## As a contract check
```json
{"id": "self-verify", "claim": "The data directory passes the product's own integrity check", "kind": "general", "rung": 3,
 "cmd": "mytool verify --data tests/fixtures/books", "expect": {"exit": 0, "stdout_contains": "ok"}, "tier": "deep", "timeout_s": 120}
```

## What a pass does not prove
- Only the invariants coded into `verify`. If a bug writes data that satisfies the checker, the checker passes. Keep the invariants independent from the write path.
- A hash chain shows tampering or corruption after the fact; it does not show the entries were correct.
- A verify that runs on an empty fixture proves nothing; use data with every kind of record.
- Check the check: corrupt one record in a copy and confirm failure.
