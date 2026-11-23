---
id: contract-testing-pact
title: Consumer-driven contract tests between services (Pact)
answers: Does the service I changed still satisfy what each of its consumers expects?
rung: 3
section: real-world
languages: javascript, typescript, python, java, go, rust
kinds: general
cost: high
detect:
ran_here: no
verified: docs
---

## Use when
- Two services talk over HTTP or messages, owned by different people, and integration tests are slow or flaky.
- You change a provider's response, or a consumer's request, and need to know who breaks.

## Do not use when
- One codebase owns both sides and a type checker covers the interface. A shared schema check (`api-breaking-schema`) is cheaper.
- You only need one end-to-end flow; use `e2e-playwright` or `smoke-after-deploy`.

## Set up
JavaScript/TypeScript (pact-js, current release 17.x; needs Node 16 or newer): `npm install --save-dev @pact-foundation/pact`. Other languages: `pip install pact-python` (4.x), and the Pact libraries for Java, Go and Rust (see docs.pact.io). The Python, Go and Rust APIs differ from the JavaScript one below; use the library's own README. Decide where contracts are stored: a Pact Broker, or a committed `pacts/` directory.

## Minimal example
Consumer side: describe one interaction in a test, run it against Pact's mock server, which writes a contract file to `pacts/` when the test passes. Provider side: replay every consumer's contract against the real provider. From the pact-js README (the `PactV3` and `MatchersV3` classes are the current consumer API):
```ts
import { PactV3, MatchersV3 } from '@pact-foundation/pact';
import path from 'path';

const provider = new PactV3({
  dir: path.resolve(process.cwd(), 'pacts'),
  consumer: 'MyConsumer',
  provider: 'MyProvider',
});

it('returns user 1', () => {
  provider
    .given('user 1 exists')
    .uponReceiving('a request for user 1')
    .withRequest({ method: 'GET', path: '/users/1' })
    .willRespondWith({
      status: 200,
      headers: { 'Content-Type': 'application/json' },
      body: { id: MatchersV3.integer(1), name: MatchersV3.like('Ada') },
    });
  return provider.executeTest(async (mockserver) => {
    const res = await fetch(`${mockserver.url}/users/1`);   // replace with your real client
    expect((await res.json()).name).toBe('Ada');
  });
});
```
Provider verification (also from the README; `Verifier` is the provider interface):
```ts
import { Verifier } from '@pact-foundation/pact';
await new Verifier({
  providerBaseUrl: 'http://localhost:8081',                      // your provider, already running
  pactUrls: [path.resolve(process.cwd(), 'pacts/MyConsumer-MyProvider.json')],
  stateHandlers: { 'user 1 exists': async () => { /* insert user 1 */ } },
}).verifyProvider();
```
Use `like()`-style matchers instead of exact values so only the structure is pinned. Run verification on the provider before merging a provider change.

## Run
Consumer: your normal test command (it writes the contract). Provider: the test file above, run by your test runner (`npm run test:pact:provider`, a script you define). Passing looks like: every interaction verified and the test passes (exit 0). Failure: `verifyProvider()` rejects, so the test fails with the interaction and mismatched field in the output. A state name missing from `stateHandlers` is a provider setup gap to fix, not a pass. With a Broker, `publishVerificationResult` should be on only in CI.

## As a contract check
```json
{"id": "pact-provider", "claim": "The provider satisfies all consumer contracts", "kind": "general", "rung": 3,
 "cmd": "npm run test:pact:provider", "expect": {"exit": 0}, "timeout_s": 900, "tier": "deep"}
```

## What a pass does not prove
- Only interactions consumers wrote down. A consumer using a field it never put in a contract is not protected.
- Matching structure is not matching meaning.
- Not run here (no Pact libraries installed); the snippets follow the pact-js README and docs (docs/consumer.md, docs/provider.md). The API changes between major versions, so confirm names against the installed version.
- Pending pacts (`enablePending: true`) make a new contract not fail the provider build; do not enable them in a gating check.
- Provider states that set up fake data can hide real-data issues.
- Check the check: remove a field from the provider response in a scratch copy and see the verification fail.
