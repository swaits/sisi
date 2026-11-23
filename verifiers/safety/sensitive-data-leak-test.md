---
id: sensitive-data-leak-test
title: Tests that a secret value never appears in files, logs, free text or errors
answers: Can the secret value (a tax id, a token, a password) appear anywhere it should not?
rung: 3
section: safety
languages: any
kinds: general
cost: low
detect:
ran_here: yes
verified: ran
---

## Use when
- The code handles a value that must be stored in one place only (a vault) or never stored: tax ids, tokens, card numbers, health data.
- A bug report says a secret showed up in a log line, an exception message, a backup, an export or free-text notes.
- You changed logging, error formatting, serialisation or export code near such a value.

## Do not use when
- You are checking committed files for keys; use `secret-scanning`.
- The value can legitimately appear in output (the user's own page). Test a masked form instead.

## Set up
No tool. Pick one unmistakable canary value per secret (a real-shaped but fake
tax id such as `123-45-6789`) and list its variants: with and without
separators, reversed, URL-encoded, base64 if the code encodes it.

## Minimal example
Python, standard library (`test_leak.py`). Run every surface the program can write to
and assert the canary is in none:

    SECRET = "123-45-6789"
    VARIANTS = {SECRET, SECRET.replace("-", ""), SECRET[::-1]}
    # ... call save_vendor(name, SECRET, outdir, log) and a failing call ...
    surfaces = {f.name: f.read_text() for f in Path(d).rglob("*") if f.is_file()}
    surfaces["logs"] = "\n".join(captured_log_lines)
    surfaces["error"] = str(exc_info.exception)
    for where, text in surfaces.items():
        for v in VARIANTS:
            assert v not in text, f"{v!r} leaked into {where}"

Add a test that the check can fail: assert the canary is found in a string you
build to contain it. Also exercise the failure paths (bad input, crash): leaks
live in error messages and tracebacks.

## Run
    python3 -m unittest -q test_leak

Passing looks like: `OK`. Failure shows `AssertionError: '123-45-6789' leaked
into logs`. Scan the whole data directory, temp files and any export, not only
the files you expect.

## As a contract check
    {"id": "no-secret-leak", "claim": "The secret canary appears in no file, log or error message", "kind": "general", "rung": 3, "cmd": "python3 -m unittest -q test_leak", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 120}

## What a pass does not prove
Only the surfaces and variants you listed. A secret transformed in a way you did
not list (hashed with a weak hash, split across lines) is not caught. Memory,
swap, crash dumps and third-party services are outside it. Rung 3 is honest:
it is examples, not a proof that no path leaks.
