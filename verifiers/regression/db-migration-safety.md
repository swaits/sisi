---
id: db-migration-safety
title: Database migration safety (round trip on a copy, squawk, data preservation)
answers: Will this migration run cleanly on real data without losing or corrupting any of it?
rung: 4
section: regression
languages: any
kinds: migration
cost: medium
detect: sqlite3 --version
ran_here: yes
verified: ran
---

## Use when
- You wrote or changed a schema migration (add, drop, rename, retype a column; change constraints).
- You were asked to change a data format that already holds user data.

## Do not use when
- The database is empty and disposable and no migration will ever run on real data.

## Set up
Work on a copy: never run an untested migration on the only copy of the data. Take a copy of a realistic database (a snapshot, an anonymised dump, or a fixture with awkward rows: nulls, long text, duplicates). For PostgreSQL also lint the SQL with `squawk` (`npm install -g squawk-cli` or `pip install squawk-cli`).

## Minimal example
The shape, shown with SQLite: record, migrate up, check the data, migrate down, check equality.
```sh
sqlite3 prod.db .dump | sort > before.sql
cp prod.db work.db
sqlite3 work.db "alter table u add column name text;"                 # the migration up
sqlite3 work.db "select count(*) from u;"                              # row count still 2
sqlite3 work.db "alter table u drop column name;"                      # the migration down
sqlite3 work.db .dump | sort > after.sql
diff before.sql after.sql && echo round-trip-identical
```
Add data-preservation checks that matter to the domain: row counts per table, sums of money columns, a checksum over each preserved column (`select sum(amount) ...`) before and after. For Postgres run `squawk migrations/*.sql` before applying; it flags locks that block writes and unsafe changes such as adding a `NOT NULL` column without a default.

## Run
The commands above, or your migration tool's own up and down commands against the copy.

Passing looks like: `round-trip-identical`, row counts and sums equal, squawk prints no warnings and exits 0. Failure: a diff, differing counts, or squawk exits 1 with rule names.

## As a contract check
```json
{"id": "migration-round-trip", "claim": "Migrating a copy up then down returns identical data", "kind": "migration", "rung": 4,
 "cmd": "sh tests/migration-round-trip.sh", "expect": {"exit": 0, "stdout_contains": "round-trip-identical"}, "tier": "deep", "timeout_s": 300}
```

## What a pass does not prove
- Only the data in your copy. A migration that works on 2 rows may time out or lock on 200 million.
- A reversible migration is not a safe one: a `down` that restores structure may not restore values dropped by `up`.
- SQLite dumps compare text; ordering matters, hence `sort`. Dumps of other databases need `pg_dump --data-only --inserts` or per-table checksums.
- The squawk part was not run (not installed); the install commands are from its README.
- Check the check: make `down` a no-op and confirm the diff appears.
