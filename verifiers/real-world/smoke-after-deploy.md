---
id: smoke-after-deploy
title: Post-deploy smoke checks and health endpoints
answers: Is the thing I just deployed actually up and serving correct responses?
rung: 3
section: real-world
languages: any
kinds: general
cost: low
detect: curl --version
ran_here: yes
verified: ran
---

## Use when
- You deployed, released or restarted a service and are about to say it is live.
- You want a small set of fast checks that run after every deploy and after rollback.

## Do not use when
- You need deep correctness; smoke checks only show it is alive and wired.
- You cannot reach the deployed URL; then say what you could not check.

## Set up
Have a health endpoint (for example `/healthz`) that checks real dependencies (database reachable, migrations applied), not just that the process is up. Know the version string the deploy should now report, so you can tell the new build from the old one.

## Minimal example
```sh
BASE=https://app.example.com
expected=$(git rev-parse --short HEAD)
curl -fsS --max-time 10 --retry 5 --retry-delay 3 --retry-connrefused "$BASE/healthz" | tee /tmp/health.json
curl -fsS "$BASE/version" | grep -q "$expected"                  # the new build is the one answering
curl -fsS -o /dev/null -w '%{http_code}\n' "$BASE/" | grep -qx 200
curl -fsS "$BASE/api/items?limit=1" | python3 -c 'import json,sys; json.load(sys.stdin)'   # one real read that parses
```
`-f` makes curl fail on HTTP errors (4xx, 5xx), which is what turns the check into an exit code. `--retry` gives a starting service time. Add one write-and-read round trip against a test account if the service has state. Keep the smoke set under a minute.

## Run
The commands above, as a script with `set -e`. Passing looks like: exit 0, the health JSON shows each dependency `ok`, and the version matches. Failure: curl exits 22 (HTTP error), 28 (timeout) or 7 (connection refused); `grep` exits 1 when the version is old.

## As a contract check
```json
{"id": "smoke", "claim": "The deployed service is healthy and serving the new build", "kind": "general", "rung": 3,
 "cmd": "sh scripts/smoke.sh https://app.example.com", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 120}
```

## What a pass does not prove
- Only the endpoints probed. A healthy `/healthz` can sit in front of a broken checkout page.
- A load balancer may send you to one healthy instance while another is bad; probe more than once.
- A cached or CDN-served response can mask a failed deploy. The version check is what shows the new build is live.
- Check the check: point it at a wrong path (`/nope`) and confirm `curl -f` exits 22 (run here against a local server: 22 for the missing path, 7 for a refused connection; the full script was not run against a real deployment).
