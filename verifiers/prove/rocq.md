---
id: rocq
title: Rocq (formerly Coq) proofs, and when to pick it over Lean
answers: Is this property proved by machine, in a prover with a large existing library of verified programs?
rung: 1
section: prove
languages: any
kinds: general, state-machine
cost: high
detect: rocq --version
ran_here: no
verified: docs
---

## Use when
- You depend on an existing Rocq development (CompCert, Iris, VST, Fiat Crypto, MathComp) or the team already knows it.
- You need extraction of verified code to OCaml or Haskell.
- The proof is about C via VST, or concurrent separation logic via Iris.

## Do not use when
- You are starting fresh and have no reason to prefer it. Prefer `lean4-proofs`: faster builds, better agent tooling, and `lake build` as one oracle.
- A bounded check will do (`kani`, `cbmc`).

## Set up
Install through opam (version 2.1 or newer). Rocq packages are not in the default opam repository, so add theirs first:

    opam repo add rocq-released https://rocq-prover.org/opam/released
    opam install rocq-prover
    rocq -v

The package is `rocq-prover` (the old name was `coq`); the binary is `rocq`, and the batch compiler is `rocq compile` (alias `rocq c`). The current reference manual documents only `rocq`-prefixed commands and does not mention `coqc`, so on a modern install use `rocq compile`; an older `coq` install has `coqc`. Not installed here, so nothing was run.

For a Dune build (the manual calls Dune support experimental), `dune-project` has a `(lang dune 3.x)` line and `(using rocq 0.14)` (Dune docs, Dune 3.25; the Rocq language version is not the Rocq version), and a `dune` file has `(rocq.theory (name Demo))`. Without Dune: `rocq makefile -f _CoqProject -o CoqMakefile`, then `make -f CoqMakefile`.

## Minimal example
`Demo.v`:
```coq
Theorem add_zero_r : forall n : nat, n + 0 = n.
Proof. intros n. induction n; simpl; auto. Qed.
Print Assumptions add_zero_r.
```

## Run
`dune build` (or `rocq compile Demo.v` for one file; name the logical path with `-Q . Demo` when needed; the file name must be a valid identifier, so `to-to.v` fails).

Passing looks like: exit 0 (the manual does not document `rocq compile` exit codes; a Rocq error such as an unsolved goal fails the compile and Dune reports it). `Print Assumptions add_zero_r.` prints `Closed under the global context` when no axioms are used; any listed axiom, or `Admitted.` in the source, means the proof is incomplete. Dune normally hides the output of successful rules, so to see the `Print Assumptions` line compile the file directly with `rocq compile`, and grep the sources as well.

## As a contract check
```json
{"id": "prove-demo-rocq", "claim": "The Rocq development builds with no Admitted lemmas", "kind": "general", "rung": 1, "cmd": "bash -c 'dune build && ! grep -R -E \"Admitted|admit\\.\" --include=*.v .'", "expect": {"exit": 0}, "timeout_s": 3600, "tier": "deep"}
```

## What a pass does not prove
- Only the stated theorem about the Rocq definitions; the link to real code is a separate problem (`proof-bridging`).
- `Admitted` and `Axiom` pass the build; the grep and `Print Assumptions` catch them.
- Not run here. The opam commands, `rocq compile` and the Dune stanzas come from the Rocq install page, refman and Dune docs; the exit status of `rocq compile` is not documented in them.
