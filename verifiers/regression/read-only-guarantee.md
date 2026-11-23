---
id: read-only-guarantee
title: Proving a viewer or query path changes nothing
answers: Does this read-only path leave every byte, size and modification time of the data untouched?
rung: 3
section: regression
languages: any
kinds: general, state-machine
cost: low
detect: sha256sum --version
ran_here: yes
verified: ran
---

## Use when
- A viewer, report, query, export or "dry run" must not change stored data, and a user would be harmed if it did.
- You change a read path and want evidence no write sneaked in (a log line, a cache file, a lock, a SQLite `-wal`).

## Do not use when
- The path is allowed to write caches or logs elsewhere. Scope the check to the data directory only.

## Set up
Make a fixture data directory with realistic content, files of several sizes, nested folders. Write a function that snapshots every file's relative path, size, modification time and content hash, so that a changed, added or removed file shows.

## Minimal example
```sh
snap() { (cd "$1" && find . -type f -printf '%p %s %T@ ' -exec sha256sum {} \; | sort); }
snap data > /tmp/before
./mytool view --data data           # the path under test; exercise every page or query
snap data > /tmp/after
cmp /tmp/before /tmp/after && echo unchanged
```
The strongest form also makes the whole tree read-only on disk (`chmod -R a-w data`) and runs the viewer again: it must still work, which proves it never needed to write. In the reference project's test (`crates/ledger-gui/tests/read_only.rs`) the walk records bytes, size and mtime for every file, repeats with read-only and with writable books, and fails if any file appears or goes (for example SQLite's `-wal` and `-shm`).

## Run
The script above.

Passing looks like: `unchanged` and exit 0. Failure: `cmp` prints the first differing line and exits 1; the diff names the file (`diff /tmp/before /tmp/after`).

## As a contract check
```json
{"id": "read-only", "claim": "The viewer changes no byte, size or mtime in the data directory", "kind": "general", "rung": 3,
 "cmd": "sh tests/read-only-check.sh", "expect": {"exit": 0, "stdout_contains": "unchanged"}, "tier": "deep", "timeout_s": 300}
```

## What a pass does not prove
- Only the paths and queries you exercised. A rarely used page may still write.
- Equal mtime resolution: some file systems store coarse times. The content hash covers that for contents.
- It cannot see writes elsewhere (a database server, the network). Add a check on those separately.
- Check the check: append a byte during the run (`echo x >> data/a`) and confirm the check fails (done here: `ro-detects`).
