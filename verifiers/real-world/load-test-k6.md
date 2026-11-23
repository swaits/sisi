---
id: load-test-k6
title: Load tests with pass/fail thresholds (k6)
answers: Does the service stay fast and correct under the load it must handle?
rung: 3
section: real-world
languages: any
kinds: general
cost: medium
detect: k6 version
ran_here: no
verified: docs
---

## Use when
- You changed a query, cache, index, lock or request path and need to show it holds under concurrency.
- A latency or error-rate promise exists (a service level objective).

## Do not use when
- The service has no stated target; invent none. Ask for one, or compare before and after instead.
- You would point it at a production system or one you do not own. Test a copy.

## Set up
Install k6 (https://grafana.com/docs/k6/latest/set-up/install-k6/). Run the system under test locally or in a staging copy with realistic data volume.

## Minimal example
`load.js`
```js
import http from 'k6/http';
import { check } from 'k6';
export const options = {
  vus: 20, duration: '30s',
  thresholds: {
    http_req_failed:   ['rate<0.01'],        // under 1 % errors
    http_req_duration: ['p(95)<300'],        // 95 % of requests under 300 ms
  },
};
export default function () {
  const res = http.get('http://localhost:3000/api/items');
  check(res, { 'status is 200': (r) => r.status === 200, 'has items': (r) => r.json().length > 0 });
}
```
Thresholds are what make this a check: if any is crossed, k6 exits nonzero. Checks (`check`) alone only count and do not fail the run, so also put `checks: ['rate>0.99']` in `thresholds`. Run once against the unchanged system first and record the numbers.

## Run
`k6 run load.js`

Passing looks like: every threshold line marked with a tick (`✓`) and exit 0. Failure marks the threshold `✗` and exits with code 99.

## As a contract check
```json
{"id": "load", "claim": "p95 latency under 300 ms and under 1% errors at 20 users", "kind": "general", "rung": 3,
 "cmd": "k6 run load.js", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 300}
```

## What a pass does not prove
- Only the traffic mix you scripted. Real users behave differently.
- The load generator and the system share a machine in a local test; results are optimistic. Record where it ran.
- Not run here (`k6` is not installed). Thresholds and their behaviour come from the k6 documentation; the exit code 99 is from memory.
- Passing latency does not show the responses were right; keep the `check` calls and a threshold on them.
- Check the check: set `p(95)<1` and confirm the run fails.
