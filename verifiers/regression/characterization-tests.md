---
id: characterization-tests
title: Characterization tests that pin existing behaviour before a refactor
answers: Does the code still do what it did before I restructured it?
rung: 3
section: regression
languages: any
kinds: general, parsing
cost: medium
detect:
ran_here: yes
verified: ran
---

## Use when
- You are refactoring, replacing or optimising code that has few or no tests.
- You do not know exactly what the code does and the spec is missing; you need the behaviour that exists today, bugs included.

## Do not use when
- A real specification exists. Test against the specification, not against current behaviour.
- The behaviour is non-deterministic and you cannot control the source of randomness or time.

## Set up
Pick the entry points the rest of the code calls. List inputs: typical, edge (empty, one, maximum), and the last bug reports. If you have real logs or fixtures, replay them. If the code takes more than a few inputs, generate many and record the outputs (rung 4 style) or compare old and new implementations directly (see `differential` entries in `many-inputs/`).

## Minimal example
Write the test to fail first with a wrong guess, then paste the real output as the expected value. Commit this BEFORE refactoring.
```python
# tests/test_characterize_slug.py  (python3 -m unittest)
import unittest
from textutil import slug
class Pinned(unittest.TestCase):
    def test_current_behaviour(self):
        cases = {"Hello World": "hello-world", "": "", "  a  b ": "a-b", "Ünï": "n"}
        for given, got in cases.items():
            with self.subTest(given=given):
                self.assertEqual(slug(given), got)
```
The `"Ünï": "n"` row looks like a bug. Keep it, add a comment `# BUG? pinned as is`, and tell the human. Do not fix behaviour during the refactor; fix it in a separate commit with the test changed on purpose.

## Run
`python3 -m unittest tests.test_characterize_slug`

Passing looks like: `OK`, exit 0, on the old code (before) and on the new code (after). If it fails on the old code, the test describes behaviour wrong; fix the test, not the code.

## As a contract check
```json
{"id": "characterization", "claim": "Existing behaviour pinned by characterization tests is unchanged", "kind": "general", "rung": 3,
 "cmd": "python3 -m unittest tests.test_characterize_slug", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 120}
```

## What a pass does not prove
- Only the inputs you wrote. A refactor can change behaviour on every input you did not think of.
- It pins bugs as well as features. Review the table for surprises.
- Run `mutation testing` (`test-quality/`) on the pinned function to see whether the cases are strong enough.
- Check the check: introduce a deliberate change in the new code and confirm one case fails.
