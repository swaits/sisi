---
id: multi-user-isolation
title: Proving one account cannot read another's data
answers: Can user B see, change or guess user A's data through any door the product offers?
rung: 3
section: real-world
languages: any
kinds: general
cost: medium
detect:
ran_here: no
verified: docs
---

## Use when
- The product has accounts, tenants, workspaces or roles, and a leak between them would be serious.
- You added an endpoint, a query, an export, a search index, a cache or a background job that touches stored data.

## Do not use when
- A single-user tool with no sharing. Use `read-only-guarantee` if the concern is accidental writes.

## Set up
Two layers, as a Rust project did them in a CI workflow (`two-user.yml`) and an integration test (`two_user.rs`):

1. Operating-system layer. A system account `appsvc` runs the server and owns the data root; the root is created mode `0700` (`sudo install -d -o appsvc -g appsvc -m 0700 /srv/appdata`). The test runs as a different account (the CI runner) and must be refused.
2. Network layer. The server listens only on loopback (`--http 127.0.0.1:PORT`) with `--isolation enforced`; each book has its own bearer token, minted by the server (`token create --book acme --name ci`, stored in a 0600 file under the root). The test reaches the data only through that door, with the token.

For a product with accounts rather than OS users, the same idea: create accounts A and B with distinctive data (`ALPHA-SECRET-1`) and make every request as B using only B's credentials.

## Minimal example
What the reference test asserts as the agent account, in Rust: `std::fs::read_dir(tenant_root)` and `File::open(tenant_root/books/<book>/journal.jsonl)` must both fail with `ErrorKind::PermissionDenied` (the test checks the error kind, so a missing path does not pass as "refused"); then `books.start` over HTTP with the token must report `isolation` equal to `service_user (enforced)`, and a read, a write, an upload and an export must still work through that door (the account is shut out of the files, not out of the product). Separate tests check that `--http` rejects non-loopback addresses and that books moved to the server keep their head hash.

A generic web-API version of the cross-account cases (not from the reference project):
```sh
# As user B, ask for A's record by every route: direct id, list, search, export, attachment URL.
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN_B" "$BASE/api/records/$A_RECORD_ID"      # expect 403 or 404
curl -s -H "Authorization: Bearer $TOKEN_B" "$BASE/api/records?q=ALPHA-SECRET" | grep -c ALPHA-SECRET || true     # expect 0
```
Also test: no credentials at all (401), a tampered or expired token, writing to A's record as B (must change nothing; check A's record afterwards), and listing endpoints returning only B's rows. Write every case with a distinctive value and assert its absence from every response body, not only the status code.

## Run
The reference job builds the server, creates the accounts and directories, starts two servers, then runs, as the agent account, with the deployment given in `TWO_USER_TEST=1`, `APP_TENANT_ROOT`, `APP_SERVER_URL`, `APP_BOOK`, `APP_TOKEN` and related variables:

    cargo test -p app-cli --test two_user -- --nocapture --test-threads=1

Passing looks like: both tests ran and passed. Without `TWO_USER_TEST` each test prints `SKIPPED ...` and returns, which cargo counts as a pass, so a laptop run proves nothing: require that the output contains no `SKIPPED`. Failure: a panic such as "this account can read the tenant root". For a web API, your own script: every forbidden access returns 403, 404 or 401, the secret strings appear in no response, and A's data is byte-identical afterwards.

## As a contract check
```json
{"id": "isolation", "claim": "Account B cannot read or modify account A's data through the API", "kind": "general", "rung": 3,
 "cmd": "sh tests/isolation.sh", "expect": {"exit": 0}, "timeout_s": 300, "tier": "deep"}
```
For the reference-style OS check, make the script fail on a `SKIPPED` line in the cargo output.

## What a pass does not prove
- Only the doors you tried. Enumerate every endpoint from the route list or the tool list, and test each as B.
- Insecure direct object references hide in ids that are guessable; also try other users' ids from a list you did not get from the API.
- Not run here. `verified: docs` means this entry was checked against the reference project's workflow file and test source, which it describes accurately; the generic curl cases are not taken from it, and the project's two-user test does not try one account's token against another account's book.
- A shared cache or search index can leak even when the database is separate. Include them.
- Check the check: temporarily remove the authorisation check and confirm the test fails.
