---
id: atheris
title: Coverage-guided fuzzing of Python with Atheris
answers: Can any input make this Python code raise an exception it should not, hang, or crash the interpreter?
rung: 2
section: many-inputs
languages: python
kinds: parsing, general
cost: medium
detect: python3 -c "import atheris"
ran_here: yes
verified: ran
---

## Use when

- Python code parses or transforms untrusted input and should raise only its documented exceptions.
- You want libFuzzer's coverage guidance, corpus handling and time budget for Python code, including C extensions.
- Property tests with `hypothesis` have not found anything and you want a search guided by coverage.

## Do not use when

- You need shrinking to a readable counterexample and structured values: `hypothesis`.
- The code is pure and fast to reason about; a property test is less work.

## Set up

    python3 -m venv .venv && .venv/bin/pip install atheris

Atheris builds against clang; wheels exist for common platforms. Use
`@atheris.instrument_func` on your functions or `atheris.instrument_imports()`
around the import of the code under test. Without instrumentation there is no
coverage feedback and the fuzzer finds almost nothing.

## Minimal example (`fuzz_parse.py`)

    import sys
    import atheris

    @atheris.instrument_func
    def parse_pair(s: str):
        a, _, b = s.partition(",")
        x, y = int(a), int(b)                    # ValueError is the documented error
        if s.startswith("42,") and y == 7:
            raise RuntimeError("seeded bug")     # anything else is a finding
        return x, y

    def test_one_input(data: bytes):
        fdp = atheris.FuzzedDataProvider(data)
        s = fdp.ConsumeUnicodeNoSurrogates(16)
        try:
            parse_pair(s)
        except ValueError:
            pass

    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()

## Run

    mkdir -p corpus && .venv/bin/python fuzz_parse.py corpus -max_total_time=60 -timeout=10

Passing looks like: `Done N runs in 60 second(s)`, exit 0.
Failure prints the traceback, writes `crash-<hash>` in the current directory
(`artifact_prefix='./'`) and exits 77. Replay with `.venv/bin/python fuzz_parse.py crash-<hash>`;
commit the file as a regression case.

## As a contract check

    {"id": "fuzz-parse-pair-py", "claim": "parse_pair raises only ValueError on 60 seconds of fuzzed input", "kind": "parsing", "rung": 2, "cmd": ".venv/bin/python fuzz_parse.py corpus -max_total_time=60 -timeout=10", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 300}

## What a pass does not prove

- Only what was found in the time given; the bug in the example took under 60 seconds with instrumentation and was never found in 30 seconds without it.
- Uninstrumented code and code in another process are invisible to the fuzzer.
- Check the check: confirm a planted bug is found, and that the `except` clause only catches the documented error.
