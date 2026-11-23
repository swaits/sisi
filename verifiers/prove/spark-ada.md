---
id: spark-ada
title: SPARK (Ada) proofs with GNATprove
answers: Is this Ada code free of runtime errors and does it meet its contracts, proved?
rung: 1
section: prove
languages: ada
kinds: general
cost: medium
detect: gnatprove --version
ran_here: no
verified: docs
---

## Use when
- The project is in Ada and needs absence of runtime errors (overflow, range, index) or functional contracts proved.
- Safety standards ask for proof evidence.

## Do not use when
- The code is not Ada. Choose the entry for its language.

## Set up
Get GNATprove from Alire (`alr with gnatprove` in an Alire project, then `eval $(alr printenv)`), or install a GNAT toolchain plus GNATprove from AdaCore (see the SPARK user guide, "Installation of GNATprove"). Put `SPARK_Mode` on the code to prove (`pragma SPARK_Mode (On);` in a package spec and body, or `with SPARK_Mode` on declarations) and have a project file. Not installed here, so the example was not run.

`proj.gpr`:

    project Proj is
       for Source_Dirs use (".");
       for Object_Dir use "obj";
    end Proj;

## Minimal example
`bounds.ads`:

    package Bounds with SPARK_Mode is
       function Clamp (Lo, Hi, X : Integer) return Integer
         with Pre  => Lo <= Hi,
              Post => Clamp'Result in Lo .. Hi;
    end Bounds;

`bounds.adb`:

    package body Bounds with SPARK_Mode is
       function Clamp (Lo, Hi, X : Integer) return Integer is
       begin
          if X < Lo then return Lo;
          elsif X > Hi then return Hi;
          else return X;
          end if;
       end Clamp;
    end Bounds;

GNATprove checks the postcondition and every runtime check in the body.

## Run
`gnatprove -P proj.gpr --level=2 --checks-as-errors=on`

`--level` runs from 0 (fast) to 4 (most powerful); level 2 is cvc5, z3 and Alt-Ergo with a 5 second timeout and counterexamples on. Raise the level or `--timeout` when a prover cannot decide.

Passing looks like: exit 0 and a summary table in which every check is "Proved". Failure shows messages such as `medium: postcondition might fail` and, only with `--checks-as-errors=on`, exits non-zero. The SPARK user guide states that GNATprove otherwise "returns with an exit status of zero, even when unproved check messages and warnings are issued". Use `--warnings=error` as well if warnings should fail the run.

## As a contract check
```json
{"id": "prove-clamp-spark", "claim": "Clamp has no runtime errors and satisfies its postcondition", "kind": "general", "rung": 1, "cmd": "gnatprove -P proj.gpr --level=2 --checks-as-errors=on", "expect": {"exit": 0}, "timeout_s": 1800, "tier": "deep"}
```

## What a pass does not prove
- Only code in `SPARK_Mode`; code outside it (`SPARK_Mode => Off`) is assumed. Search for `pragma Assume` and `Annotate`.
- Only contracts as written.
- Without `--checks-as-errors=on` a run with unproved checks still exits 0, so a contract on the exit code alone would pass vacuously. Commands and exit-status behaviour come from the SPARK user guide, not from a run here.
