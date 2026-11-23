---
id: packaging-install-upgrade
title: Install and upgrade real packages in containers across distributions
answers: Can a user install this package, open their data, upgrade, and still have their data intact?
rung: 3
section: real-world
languages: any
kinds: general, migration
cost: high
detect: docker --version
ran_here: no
verified: docs
---

## Use when
- You ship `.deb`, `.rpm`, Arch packages, installers or a self-update path.
- Version N+1 changes a file format or a data directory, and users have data from version N.

## Do not use when
- You ship only a container image or a library; test the image directly or use `clean-clone-build`.

## Set up
Build the old and the new package. For each target distribution, start a clean container (Debian, Fedora, Arch images are enough) with the package directory mounted read-only. Create an ordinary user in the container: installs run as root, data belongs to a user.

## Minimal example
The pattern, as used in a reference project (`deploy/packaging/test-linux-packages.sh`), per distribution:
```sh
docker run --rm -v "$PWD/target/packages:/packages:ro" debian:trixie-slim bash -c '
  set -euo pipefail
  useradd -m tester
  apt-get install -y /packages/mytool_0.1.0_amd64.deb
  su tester -c "mytool setup && mytool create demo"
  before=$(su tester -c "mytool list")
  apt-get install -y /packages/mytool_0.1.1_amd64.deb       # the upgrade
  after=$(su tester -c "mytool list")
  [ "$before" = "$after" ]'
```
Check things that break in practice: the data's head or checksum is unchanged, a long-running process restarts onto the new binary (`readlink /proc/$pid/exe` must not say `(deleted)`), the self-updater refuses when a package manager owns the install, and uninstall leaves user data alone. Repeat with `fedora:latest` (`dnf install`) and `archlinux:latest` (`pacman -U`).

## Run
Your script, once per distribution. Passing looks like: exit 0 in every container and the same data summary before and after. Failure: a nonzero exit with the failed assertion; keep the container logs.

## As a contract check
```json
{"id": "pkg-upgrade", "claim": "Install, open data, upgrade: data is unchanged on Debian, Fedora and Arch", "kind": "general", "rung": 3,
 "cmd": "sh deploy/test-packages.sh", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 3600}
```

## What a pass does not prove
- Only the distributions and versions tested. Other package managers and init systems differ.
- Real user data is richer than your demo data; use an anonymised copy from an old version when you can.
- Docker's default seccomp and missing systemd can change behaviour; services that need them need `--privileged` or a VM, which weakens isolation.
- Not run here (no packages to build). The shape comes from the reference project's script; Docker and the base images are installed on this machine.
- Check the check: corrupt the data in the new package's migration and see the comparison fail.
