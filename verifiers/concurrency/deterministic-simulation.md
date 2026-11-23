---
id: deterministic-simulation
title: Deterministic simulation of async and distributed systems (turmoil, madsim)
answers: Does my networked or async system keep working under reordering, delays, partitions and crashes, reproducibly from a seed?
rung: 2
section: concurrency
languages: rust, any
kinds: concurrency, state-machine
cost: high
detect: cargo --version
ran_here: yes
verified: ran
---

## Use when
- The system has several nodes or tasks talking over a network, uses timeouts, retries, leases or elections.
- You need fault tests (partition, delay, restart) that are repeatable, not flaky.
- A bug appeared once in the field and you want to replay it from a seed.

## Do not use when
- The code is one thread with no I/O; use plain tests.
- You must exercise the real kernel, real sockets or real disks. Simulation replaces them.
- Code under test calls the wall clock or OS randomness directly and cannot be routed through the simulator; it will not be deterministic.

## Set up
The pattern: all time, network, disk and randomness go through a simulated layer driven by one seed; the same seed gives the same run. Rust options:
- `turmoil` (Tokio hosts, simulated TCP and UDP, partitions): `cargo add turmoil` plus `tokio` with `rt,macros,time`.
- `madsim` (also simulates disk and RPC; swap in `madsim-tokio`; build with `RUSTFLAGS="--cfg madsim"`). Its seed environment variables were not confirmed here; check docs.rs/madsim.
In other languages, copy the pattern: inject a clock, a network and a random source, then run many seeds.

## Minimal example
`src/main.rs` with turmoil 0.7:

    use std::time::Duration;
    use turmoil::{net::{TcpListener, TcpStream}, Builder};
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    fn run(seed: u64) -> turmoil::Result {
        let mut sim = Builder::new().rng_seed(seed).simulation_duration(Duration::from_secs(60)).build();
        sim.host("server", || async {
            let l = TcpListener::bind("0.0.0.0:9000").await?;
            loop { let (mut s, _) = l.accept().await?; let mut b = [0u8; 4]; s.read_exact(&mut b).await?; s.write_all(&b).await?; }
        });
        sim.client("client", async {
            let mut s = TcpStream::connect("server:9000").await?;
            s.write_all(b"ping").await?; let mut b = [0u8; 4]; s.read_exact(&mut b).await?;
            assert_eq!(&b, b"ping");
            turmoil::partition("client", "server");
            let r = tokio::time::timeout(Duration::from_secs(5), TcpStream::connect("server:9000")).await;
            assert!(!matches!(r, Ok(Ok(_))), "connect must fail across a partition");
            turmoil::repair("client", "server");
            Ok(())
        });
        sim.run()
    }
    fn main() { for seed in 0..20 { run(seed).unwrap_or_else(|e| panic!("seed {seed}: {e}")); } println!("20 seeds ok"); }

## Run
    cargo run

Passing looks like: `20 seeds ok`, exit 0. Failure panics with the failing seed, exit 101. Re-run just that seed to debug.

## As a contract check
    {"id": "sim-seeds", "claim": "Protocol invariants hold across 20 simulated seeds with a partition", "kind": "concurrency", "rung": 2, "cmd": "cargo run", "expect": {"exit": 0, "stdout_contains": "seeds ok"}, "tier": "deep", "timeout_s": 600}

## What a pass does not prove
- It samples seeds and faults; rung 2. More seeds and more fault types find more.
- It tests your logic against the simulator's model of the network, not the real one. Simulator gaps (partial writes, clock drift) hide bugs.
- Anything outside the simulated layer is not controlled. If the same seed gives different outcomes, determinism is broken; run one seed twice and compare.
- Check the check: inject a known bug (drop the retry) and confirm some seed fails.
