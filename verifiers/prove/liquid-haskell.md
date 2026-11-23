---
id: liquid-haskell
title: LiquidHaskell refinement types for Haskell
answers: Do my Haskell functions respect value constraints (non-zero divisors, in-range indexes, length-preserving) for all inputs?
rung: 1
section: prove
languages: haskell
kinds: general
cost: medium
detect: ghc --version
ran_here: no
verified: docs
---

## Use when
- Haskell code where totality and value constraints matter: safe division, bounds, sorted or length-indexed lists.
- You want checks written as comments next to the types, so the code still compiles with plain GHC.

## Do not use when
- The code is not Haskell. See the entries for your language.
- The GHC version you need is newer than the LiquidHaskell release supports: only one GHC version is supported at a time (currently 9.14.1).

## Set up
From the LiquidHaskell README: install Z3 4.15.1 or newer on PATH, then in the project directory

    cabal install --lib liquidhaskell liquid-prelude liquid-vector --package-env . --force-reinstalls

(`--package-env .` writes a `.ghc.environment*` file so only GHC runs started from this directory see the plugin). Put `{-# OPTIONS_GHC -fplugin=LiquidHaskell #-}` at the top of each checked module. LiquidHaskell supports exactly one GHC version at a time: the latest release (v0.9.14.1, May 2026) builds with GHC 9.14.1, and the previous release (v0.9.12.2) is the last one for GHC 9.12.2. Use the LiquidHaskell release that matches your GHC. Not installed here (no Haskell toolchain), so the example was not run.

## Minimal example
```haskell
{-# OPTIONS_GHC -fplugin=LiquidHaskell #-}
module Safe where

{-@ safeDiv :: Int -> {v:Int | v /= 0} -> Int @-}
safeDiv :: Int -> Int -> Int
safeDiv x y = x `div` y

ok :: Int
ok = safeDiv 10 2
-- bad = safeDiv 10 0   -- uncomment: rejected at compile time
```

## Run
`ghc -fplugin=LiquidHaskell Safe.hs` (the README's command), or in a Cabal project add `-fplugin=LiquidHaskell` to `ghc-options` with `liquidhaskell` and `liquid-prelude` in `build-depends` and run `cabal build`. GHC does not rerun the plugin on modules it considers up to date, so after a first pass force a rebuild (`-fforce-recomp`, or touch the file) before trusting a pass.

Passing looks like: the compile succeeds. Failure: a refinement type error from the plugin at the offending call, and a failed compile (non-zero exit as for any GHC error). The exact error wording (older versions printed `Liquid Type Mismatch`; the older `liquid Safe.hs` printed `LIQUID: SAFE`) was not confirmed here.

## As a contract check
```json
{"id": "prove-safediv-liquid", "claim": "safeDiv is never called with a zero divisor", "kind": "general", "rung": 1, "cmd": "ghc -fforce-recomp -fplugin=LiquidHaskell Safe.hs", "expect": {"exit": 0}, "timeout_s": 1800, "tier": "deep"}
```

## What a pass does not prove
- Only annotated specs; `{-@ lazy @-}`, `assume` and `{-@ LIQUID "--no-termination" @-}` weaken or skip checking. Grep for them.
- Modules without the plugin line are not checked at all; make sure the plugin line is on every module that matters.
- Not run here; commands come from the LiquidHaskell README. Check the check: uncomment `bad = safeDiv 10 0` and confirm the compile fails.
