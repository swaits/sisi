---
id: mutmut
title: Mutation testing for Python with mutmut
answers: Would my Python tests notice if this function were wrong?
rung: 2
section: test-quality
languages: python
kinds: general, money, parsing
cost: medium
detect: mutmut --version
ran_here: yes
verified: ran
---

## Use when
- You wrote pytest tests and want proof they fail when the code changes.
- Line coverage is 100% but you doubt the assertions (this is common; see `coverage-floor`).
- The code is pure logic in functions. Mutation testing is a check on other checks, giving rung 2 confidence in the tests.

## Do not use when
- The target is module-level code outside functions; mutmut 3 mutates functions. mutmut 2 works differently.
- Windows without WSL: mutmut needs `fork`.
- Tests are slow or depend on network. Fix that first.

## Set up
    uv pip install mutmut pytest         # or: pip install mutmut
    # pyproject.toml
    [tool.mutmut]
    source_paths = ["src/"]
    pytest_add_cli_args_test_selection = ["tests/"]
    [tool.pytest.ini_options]
    pythonpath = ["src"]

Tests must import the code by its package name (`from shop.pricing import price`), not through a path like `src.pricing`; the latter fails with `Failed trampoline hit`. Tool version tried: mutmut 3.8.1. An alternative with a different design is `cosmic-ray` (session file, `cosmic-ray init`, `exec`); I did not run it.

## Minimal example
`src/shop/__init__.py` (empty), `src/shop/pricing.py`:

    def price(qty: int, unit: int) -> int:
        total = qty * unit
        if qty >= 10:
            return total - total // 10
        return total

`tests/test_pricing.py` with only `price(2, 100) == 200` and `price(20, 100) == 1800`.

## Run
    mutmut run
    mutmut results
    mutmut show shop.pricing.x_price__mutmut_3

Passing looks like: `mutmut results` lists no `survived` lines. Failure shows survivors such as `shop.pricing.x_price__mutmut_3: survived`; `mutmut show` prints the diff (here `qty >= 10` became `qty > 10`). Note: `mutmut run` exits 0 even with survivors, so the contract must test the `results` output. Stop and rerun to resume; delete the `mutants/` directory for a fresh run. `# pragma: no mutate` skips a line.

## As a contract check
    {"id": "mutmut-pricing", "claim": "No surviving mutants in the pricing module", "kind": "general", "rung": 2, "cmd": "mutmut run && test -z \"$(mutmut results | grep survived)\"", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 1800}

## What a pass does not prove
- It shows the tests kill small edits, not that behaviour matches the requirement.
- Equivalent mutants cannot be killed; mark them `# pragma: no mutate` with a reason, never silently.
- Only functions are mutated. Check `mutmut results` counts a plausible number of mutants, or the run is vacuous (0 mutants, source_paths wrong).
- In my run, 3 of 7 mutants survived while coverage.py reported 100% line and branch coverage.
