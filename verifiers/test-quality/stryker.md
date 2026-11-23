---
id: stryker
title: Mutation testing for JavaScript, TypeScript and C# with Stryker
answers: Would my JS, TS or C# tests notice if this code were wrong?
rung: 2
section: test-quality
languages: javascript, typescript, csharp
kinds: general, money, parsing, ui
cost: medium
detect: npx --no-install stryker --version
ran_here: yes
verified: ran
---

## Use when
- You wrote Vitest, Jest, Mocha or .NET tests and want evidence they can fail.
- You need a numeric gate: Stryker computes a mutation score and exits non-zero below a threshold.
- It is a check on other checks; it gives rung 2 confidence in the tests.

## Do not use when
- The change is a few lines and a full run is slow; mutate only those files or use `--incremental`; see `mutation-on-diff`.
- Tests are mostly snapshots of rendered output; they may kill many mutants without asserting anything meaningful.

## Set up
StrykerJS (ran version 10.1.1):

    npm i -D @stryker-mutator/core @stryker-mutator/vitest-runner vitest
    # stryker.config.mjs
    export default {
      testRunner: 'vitest',
      mutate: ['src/**/*.js'],
      reporters: ['clear-text', 'json'],
      thresholds: { high: 90, low: 80, break: 80 },
    };

Other runners are separate plugins (`@stryker-mutator/jest-runner`, `mocha-runner`). Stryker.NET (docs only, not run here): `dotnet tool install -g dotnet-stryker`, then `dotnet stryker` from the test project directory; options in `stryker-config.json`.

## Minimal example
`src/price.js`:

    export function price(qty, unit) {
      const total = qty * unit;
      if (qty >= 10) return total - Math.floor(total / 10);
      return total;
    }

`test/price.test.js` with `price(2,100) === 200` and `price(20,100) === 1800`.

## Run
    npx stryker run

Passing looks like: the table shows a mutation score at or above `break`, and the log line `Final mutation score of 87.50 is greater than or equal to break threshold 80`, exit 0. Failure: a score below `break` exits 1; survivors are listed with the mutated code (here `qty >= 10` mutated to `qty > 10`). Useful options: `--mutate "src/a.js:10-40"` for line ranges, `--incremental` (state in `reports/stryker-incremental.json`), `--concurrency`, `--timeoutMS`, `coverageAnalysis: 'perTest'` to run only tests that cover a mutant.

## As a contract check
    {"id": "stryker-score", "claim": "Mutation score of src/ is at least 80", "kind": "general", "rung": 2, "cmd": "npx stryker run", "expect": {"exit": 0, "stdout_contains": "Final mutation score"}, "tier": "deep", "timeout_s": 1800}

## What a pass does not prove
- The score is a percentage over sampled mutations; 80 means 20% of changes went unnoticed.
- Survivors may be equivalent; disable with `// Stryker disable next-line <mutator>: reason` and list them.
- `break` must be set or the command always exits 0. Check `thresholds` has all three keys (high, low, break) or none.
- A very high score with a tiny mutant count means little. Confirm the intended files were mutated.
