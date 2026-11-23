---
id: python-stdlib-property
title: Property-style tests with only the Python standard library
answers: Can I check a law over many generated inputs when I may not install any package?
rung: 2
section: many-inputs
languages: python
kinds: general, parsing, money
cost: low
detect: python3 --version
ran_here: yes
verified: ran
---

## Use when

- No third-party packages are allowed or available.
- The law is simple (round trip, ordering, agreement with a reference) and a bounded, seeded random loop is enough.
- You need a quick sample before deciding whether to bring in `hypothesis`.

## Do not use when

- Packages are allowed: `hypothesis` shrinks failures and remembers them; this does not.
- The input has structure that blind random bytes rarely satisfy (valid JSON, balanced entries). Write a structured generator or use `structure-aware-fuzzing`.

## Set up

Nothing to install. Put the test in `tests/test_props.py` and run it with `unittest`.

## Minimal example

    import os, random, unittest

    def encode(b): return b.hex()
    def decode(s): return bytes.fromhex(s)

    class Props(unittest.TestCase):
        def test_round_trip(self):
            fixed = [0, 1, 2]                                  # always run: reproducible
            fresh = [random.randrange(2**32) for _ in range(3)]  # new ground each run
            extra = [int(s) for s in os.environ.get("SEEDS", "").split(",") if s]
            for seed in fixed + fresh + extra:
                rng = random.Random(seed)
                for _ in range(500):
                    data = bytes(rng.randrange(256) for _ in range(rng.randrange(64)))
                    with self.subTest(seed=seed, data=data):
                        self.assertEqual(decode(encode(data)), data)

    if __name__ == "__main__":
        unittest.main()

## Run

    python3 -m unittest discover -s tests

Passing looks like: `Ran 1 test` then `OK`, exit 0.
Failure shows `FAIL: test_round_trip (seed=..., data=...)` with the seed and input
in the subTest label, exit 1. Reproduce a failing fresh seed with
`SEEDS=<seed> python3 -m unittest discover -s tests`, then copy it into `fixed`.

## As a contract check

    {"id": "prop-round-trip-stdlib", "claim": "decode(encode(x)) == x over seeded random inputs", "kind": "parsing", "rung": 2, "cmd": "python3 -m unittest discover -s tests", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 120}

## What a pass does not prove

- There is no shrinking: the failing input may be large. Print it, then reduce by hand.
- Uniform random bytes seldom hit edge cases (empty, maximum, boundary values). Add them to the generator explicitly.
- The checker only sees what the generator makes. Test the check by breaking the code on purpose and seeing it fail.
