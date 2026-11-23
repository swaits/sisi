# Contributing

Thanks for looking. sisi is small on purpose; this page says how to change it safely.

## Run the tests

    python3 tests/run_parallel.py        # every test file in its own process, side by side
    python3 -W ignore::ResourceWarning -m unittest discover -s tests    # the same tests, one at a time
    bin/sisi verifiers lint
    bin/sisi verify          # runs sisi's own contract (.sisi/contract.json)

Tests never touch your real home folder: they point `SISI_HOME` and `SISI_STATE`
at temporary directories, and a test fails at once if a path resolves outside them. Set `SISI_TEST_ITERS=10` to
run the property tests with more iterations.

A pull request should pass all three. If you fix a bug, add a test that fails without the fix.

## Rules for the code

- Standard library only. No third-party packages, no build step, no install step beyond cloning. This is what
  lets the tool run unchanged in any tool's hook, on any machine with Python.
- Python 3.9 or newer. Do not use syntax or library calls that need a newer version. The minimum
  was set by reading the code, not by running old interpreters: every Python file parses with
  `ast.parse(..., feature_version=(3, 8))`, and there are no `match` statements, `X | Y` types or
  walrus operators. The newest standard library features in use, `shutil.copytree(...,
  dirs_exist_ok=True)` and `sys.pycache_prefix`, were added in 3.8; the stated minimum is 3.9
  because 3.8 is end of life and the CI runners in use do not offer it. Which versions and systems
  CI proves is stated in `.github/workflows/ci.yml`; read that file rather than trusting a list
  here.
- Hooks (`sisi tick`, `sisi gate`) must stay fast and must fail open: anything that goes wrong inside sisi lets
  the agent through and is logged.
- sisi never writes into the product folder at run time. Anything it writes goes to the personal data folder or
  scratch. A test enforces this.
- Do not add personal paths, names or email addresses to any file. `tests/test_public.py` fails if a home path or an
  address appears.
- The rulebook, `canon/core.md`, has a hard budget of 120 lines. Change it only to improve a rule; to add one,
  shorten or merge another. Each rule says why it exists.

## Verifier and recipe entries

The library in `verifiers/` (techniques) and `done/` (what done means for a kind of work) is the part most
worth contributing to. The exact format, the quality bar and the meaning of each field are in
[docs/verifier-format.md](docs/verifier-format.md). In short: a real tool, a minimal example you ran, the exact
command, what passing looks like, and a JSON check that can be pasted into a contract. Say honestly in the
header whether you ran it (`ran`), checked it against the tool's documentation (`docs`) or neither. Run
`bin/sisi verifiers lint` before sending it.

## Product or personal overlay

The product is what every user gets. Your personal overlay is what sisi learned about you.

- Belongs in the product: a general rule, a technique or recipe that helps anyone, a bug fix, documentation.
- Belongs in your overlay: your preferences, your project names and paths, a rule that is right for you only, a
  technique that depends on a private setup.

If something started in your overlay and is general, `sisi promote <id>` shows what it would write into the source
folder after removing your paths, user name and email addresses (dry run unless `--apply`). Read the result
before you commit it. See [docs/developing.md](docs/developing.md) and [docs/personal-data.md](docs/personal-data.md).

## Reporting problems

Bugs and ideas go in GitHub issues. Security problems do not: see [SECURITY.md](SECURITY.md).

By contributing you agree that your contribution is licensed under the MIT licence of the project.
