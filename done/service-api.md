---
id: service-api
title: Building or changing a service or HTTP API
applies_to: A server whose clients call it over a network: its endpoints, messages, status codes and storage.
---

## Done means
- Each endpoint does what its written contract says for valid, invalid, empty, large and repeated requests, and returns the documented status codes and error bodies.
- Clients that exist still work: the change is backward compatible, or the break is deliberate, versioned and announced.
- Authorisation is enforced on every route, and one user or tenant cannot see or change another's data.
- Retries and concurrent requests do not corrupt state or double-apply an effect.
- It starts from a clean environment, migrates its storage, and answers a health check; after deploy a smoke test passes.
- It holds under expected load and handles dependency failures.

## Checks
- Contract: `contract-testing-pact`, `api-breaking-schema` (regression and real-world), rung 2 to 3.
- Hostile and random requests: `hostile-input-from-schema`, `proptest` or `hypothesis`, `stateful-model-test` (many-inputs), rung 2.
- Isolation: `multi-user-isolation` (real-world), rung 3; concurrency: `stress-repeat`, `deterministic-simulation`, `linearizability-checking`.
- Storage: `db-migration-safety` (regression), `fault-injection-storage`, `old-data-compatibility`.
- Deploy: `smoke-after-deploy`, `load-test-k6`, `runtime-self-check` (real-world).
- Safety: `threat-model-checklist`, `static-analysis-semgrep`, `dependency-audit-general`, `secret-scanning`, `sensitive-data-leak-test`.

## Common false finishes
- Tests call handlers directly and skip authentication, serialisation and middleware.
- Only a single user is tested, so tenant isolation is unknown.
- A new required field breaks existing clients and nobody ran the old client's requests.
- An idempotency or retry case was not tried; a client timeout leads to a double charge.
- Error responses leak stack traces, SQL or other users' ids.
- The migration works on an empty database and fails on real data.
- Passes against a mock of the dependency; the real one behaves differently.
- Load was tested with one repeated request, so caches hid real cost.
