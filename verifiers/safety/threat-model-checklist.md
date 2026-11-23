---
id: threat-model-checklist
title: A short written threat model turned into checks
answers: Have I thought about who can attack this change and tested each way in?
rung: 5
section: safety
languages: any
kinds: general
cost: medium
detect:
ran_here: no
verified: docs
---

Note: this technique has no tool; there is nothing to run. `verified: docs`
means the method follows STRIDE as published by Microsoft.

## Use when
- The change crosses a trust boundary: parses data from outside, adds an endpoint, handles credentials, runs a subprocess, reads a user-supplied path, or changes who may do what.
- A security fix: the model says what attack the fix closes and what else is open.
- A new tool surface for agents, where input is untrusted text.

## Do not use when
- The change is internal and touches no boundary. A paragraph of ceremony costs more than it saves.

## Set up
Create `docs/threat-model/<change>.md`. No tool required.

## Minimal example
Five lines, then one check per threat:

    Asset: the invoice PDF a customer uploads and we render.
    Entry points: POST /upload (file, filename), the renderer subprocess.
    Who: any signed-in customer; an attacker with a customer account.
    Threats (STRIDE) and checks:
      T1 Tampering: filename `../../etc/x` writes outside uploads/ -> test_upload_path_traversal
      T2 Denial of service: 2 GB file exhausts disk -> test_upload_size_limit (413)
      T3 Info disclosure: one customer reads another's PDF -> test_cross_tenant_download (404)
      T4 Elevation: renderer runs with the app's environment -> test_renderer_env_is_empty
    Out of scope, stated: DDoS at the network layer.

## Run
    python3 - <<'PY'
    import re,sys; t=open("docs/threat-model/upload.md").read()
    bad=[l for l in t.splitlines() if re.match(r"\s*T\d+ ",l) and "->" not in l]
    sys.exit(1 if bad else 0)
    PY
    pytest -k "traversal or size_limit or cross_tenant or renderer_env"

Passing looks like: every threat line names a check, and each named check
exists and passes. A threat with no check is listed as open, not dropped.

## As a contract check
    {"id": "threat-checks", "claim": "Every threat in the model has a passing check", "kind": "general", "rung": 3, "cmd": "pytest -q -k 'traversal or size_limit or cross_tenant or renderer_env'", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 300}

## What a pass does not prove
Only the threats you thought of. The value is the list, so have an independent
reader (a second model, or the human) add threats before you write checks, and
record disagreements. The rung is 5 for the model itself and 3 for the
executable checks derived from it.
