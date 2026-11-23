---
id: derived-view-agreement
title: Every displayed figure recomputed from the core and compared
answers: Does every number a screen, report or export shows equal what the core computes from the same data?
rung: 2
section: many-inputs
languages: any
kinds: ui, money
cost: medium
detect:
ran_here: yes
verified: ran
---

## Use when

- A UI, report, CSV export or API response shows figures that a core library also computes (balances, totals, percentages).
- Formatting, rounding or caching in the display layer could change a value the core got right.
- Two surfaces show the same fact (a dashboard and an exported statement).

## Do not use when

- The view has no figures, only layout: use `ui-screenshot-compare`.
- The view is the only place the figure is computed; compare against an independent reference (`differential-reference`).

## Set up

Give the display layer a seam that returns what it will show as data (not pixels):
a view model, a rendered text, a parsed export. Generate random data, load it
through the core, and for each displayed figure recompute from the core
and compare after normalising only the formatting.

## Minimal example (Python)

    from decimal import Decimal
    from hypothesis import given, strategies as st

    def core_total(entries):                       # the core: integer cents
        return sum(entries)

    def render_report(entries):                    # the display layer under test
        lines = [f"{c / 100:.2f}" for c in entries]        # a float in a money path
        return {"lines": lines, "total": f"{core_total(entries) / 100:.2f}"}

    def parse(text): return int(Decimal(text) * 100)

    @given(st.lists(st.integers(-10**9, 10**9), max_size=30))
    def test_every_figure_matches_core(entries):
        view = render_report(entries)
        assert [parse(x) for x in view["lines"]] == entries           # each line
        assert parse(view["total"]) == core_total(entries)            # the total
        assert sum(parse(x) for x in view["lines"]) == parse(view["total"])  # the page adds up

## Run

    python3 -m pytest -q test_view.py

Passing looks like: `1 passed`, exit 0 (the float formatting is right for these sizes).
With amounts above about 2**53 cents the float version fails and Hypothesis shrinks
to the smallest such figure. Widen the range to see it; a display path that must
handle big amounts should use `Decimal`, not `float`.

## As a contract check

    {"id": "view-matches-core", "claim": "every figure the report displays equals the core's value, and the report adds up", "kind": "money", "rung": 2, "cmd": "python3 -m pytest -q test_view.py", "expect": {"exit": 0, "stdout_contains": "passed"}, "tier": "deep", "timeout_s": 300}

## What a pass does not prove

- It checks the figures you list. Enumerate every displayed number (tests that walk the whole view model help) and add new ones as screens are added.
- Equal to the core only shows the view is faithful; the core can still be wrong (see `algebraic-laws`, `differential-reference`).
- A reference project also scans display source for rounding calls outside the one shared function; a source scan is a cheap extra guard.
- Check the check: change the rounding in the view by one cent and see it fail.
