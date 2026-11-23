---
id: old-data-compatibility
title: Compatibility with data written by older and newer versions
answers: Do files written by earlier versions still open to their recorded figures, and is data from a newer version reported as newer rather than corrupt?
rung: 3
section: many-inputs
languages: any
kinds: migration, state-machine, money
cost: medium
detect:
ran_here: yes
verified: ran
---

## Use when

- The program reads files, databases or journals that users keep across upgrades.
- You change a format, a schema or the rules for computing a stored figure.
- An old version may meet newer data (downgrade, shared folder, restored backup).

## Do not use when

- You want sampled inputs: use `round-trip`; this uses fixed fixtures.

## Set up

1. When a format version ships, write real data with that version and commit it
   as `tests/fixtures/<version>/` together with `expected.json`, the figures the
   version itself computed. Never regenerate old fixtures with new code.
2. Keep a newer-format fixture (or fake one with a bumped format field).

## Minimal example (Python)

    import json, pathlib, tempfile

    CURRENT = 2

    def open_book(path):
        data = json.loads(pathlib.Path(path).read_text())    # raises on garbage
        v = data.get("format")
        if v is None or not isinstance(v, int):
            raise ValueError("corrupt: no format")
        if v > CURRENT:
            raise RuntimeError(f"newer: written by format {v}, this reader knows {CURRENT}")
        return {"total": sum(data["cents"])}                 # v1 and v2 both store `cents`

    def test_old_fixture_reopens_to_recorded_figures():
        got = open_book("fixtures/v1/book.json")
        assert got == json.load(open("fixtures/v1/expected.json"))

    def test_newer_is_reported_as_newer_and_left_untouched():
        p = pathlib.Path(tempfile.mkdtemp()) / "b.json"
        p.write_text(json.dumps({"format": 3, "cents": [1]}))
        before = p.read_bytes()
        try:
            open_book(p); assert False
        except RuntimeError as e:
            assert str(e).startswith("newer")
        assert p.read_bytes() == before                      # never repaired or rewritten

    def test_damage_is_still_corrupt():
        p = pathlib.Path(tempfile.mkdtemp()) / "b.json"
        p.write_text("{not json")
        try:
            open_book(p); assert False
        except ValueError: pass

## Run

    python3 -m pytest -q test_compat.py

Passing looks like: `3 passed`, exit 0. Failure shows which fixture gave other figures,
or a newer file reported as corrupt (or the reverse).

## As a contract check

    {"id": "old-data-compat", "claim": "v1 fixtures reopen to recorded figures; newer data is reported newer and untouched; damage stays corrupt", "kind": "migration", "rung": 3, "cmd": "python3 -m pytest -q test_compat.py", "expect": {"exit": 0, "stdout_contains": "3 passed"}, "tier": "deep", "timeout_s": 300}

## What a pass does not prove

- Only the fixtures you have: keep one per released format.
- Expected figures come from the old version; never regenerate them to make a test pass.
- It does not show an upgrade is safe on real data: test the upgrade step on a copy.
- Check the check: edit a fixture's figure and see the test fail; bump a format number and see "newer" appear.
