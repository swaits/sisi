---
id: clean-clone-build
title: Build and test from a fresh clone in a clean container
answers: Does this work from a fresh checkout, or only on my working tree?
rung: 3
section: real-world
languages: any
kinds: general
cost: medium
detect: docker --version
ran_here: yes
verified: ran
---

## Use when
- You are about to say "done" on something that builds, packages or deploys.
- You added a file, a generated asset, an environment variable or a tool that your tree may have and the repository does not.
- A path that only exists on your machine (an ignored file, a global tool) could be hiding a break.

## Do not use when
- The change is a comment or documentation only.
- A full build takes hours; then use CI as the clean room and wait for it.

## Set up
Commit (or stage) everything first: a clone sees only committed files. You need `git` and, for a clean machine, Docker or Podman and an image of the target OS.

## Minimal example
```sh
git clone --no-local . /tmp/fresh                     # only committed files come along
docker run --rm -v /tmp/fresh:/work:ro -w /work debian:trixie-slim \
  sh -c 'apt-get update -qq && apt-get install -y -qq make >/dev/null && make test'
```
Without Docker the fresh clone alone catches most problems: `cd /tmp/fresh && make test`. Run the project's real build and test command, with no cache mounts, and on the clean machine install tools only as the README says. If the README's steps are not enough, the README is a bug.
Here a repository with an ignored `generated.txt` passed `make test` in its own directory and failed (`Error 1`) in the fresh clone.

## Run
The commands above. Passing looks like: the same exit 0 and test summary you got on your tree. Failure: missing file, missing tool or failing test in the clean place only, which means the claim "works" was about your tree.

## As a contract check
```json
{"id": "clean-clone", "claim": "A fresh clone builds and passes tests", "kind": "general", "rung": 3,
 "cmd": "rm -rf /tmp/fresh && git clone --no-local . /tmp/fresh && cd /tmp/fresh && make test", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 1800}
```

## What a pass does not prove
- Only the commit you cloned. Uncommitted edits are not tested; commit first.
- A clone on the same machine still inherits your global tools and `~/.cargo`; use a container for the OS and toolchain claim.
- A pinned base image can go stale. Note the image tag.
- Network-fetched dependencies can change between runs; use lockfiles (`--locked`, `npm ci`) so the clean build is repeatable.
- Check the check: delete an ignored-but-needed file and confirm the clone fails.
