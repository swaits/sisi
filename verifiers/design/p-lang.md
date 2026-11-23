---
id: p-lang
title: P language for communicating state machines
answers: Do my message-passing state machines (services, protocols) reach a bad state under any message ordering, drop or crash?
rung: 1
section: design
languages: any
kinds: state-machine, concurrency
cost: high
detect: p --version
ran_here: no
verified: docs
---

## Use when
- The system is several machines exchanging messages (RPC services, replication, workflows) and the bugs depend on message order, loss, or machine failure.
- You want the model to look like code, with events, states and handlers, and to be the basis for tests of the real system.

## Do not use when
- One machine, few states. Use `tlaplus` or `small-scope-enumeration`.
- You need unbounded proofs. P explores schedules, bounded by search effort.

## Set up
From the P install page: needs the .NET SDK 8.0 (the docs say P currently requires that specific SDK; check with `dotnet --list-sdks`) and Java 11 or newer (the P compiler uses it; check with `java -version`). Then:

    dotnet tool install --global P      # installs `p` into ~/.dotnet/tools; add that to PATH
    dotnet tool update --global P       # to update

There is also a Docker image, `ghcr.io/p-org/p:latest`, with .NET, a JDK and the `p` tool. Not run on this machine: only a .NET runtime and no Java are set up here. A project is a `.pproj` XML file:

    <Project>
      <ProjectName>PingPong</ProjectName>
      <InputFiles><PFile>./PSrc/</PFile><PFile>./PSpec/</PFile><PFile>./PTst/</PFile></InputFiles>
      <OutputDir>./PGenerated/</OutputDir>
    </Project>

## Minimal example
`PSrc/Main.p`: a client sends one `Ping`; a server replies `Pong`. `PSpec/Spec.p`: a monitor asserting every ping is eventually answered. `PTst/Test.p`: the test case. Syntax follows the P tutorial (ClientServer); this snippet itself was not compiled here.
```
// PSrc/Main.p
event Ping: machine;
event Pong;
machine Server { start state Run { on Ping do (c: machine) { send c, Pong; } } }
machine Client {
  var s: machine;
  start state Init { entry { s = new Server(); send s, Ping, this; goto Wait; } }
  state Wait { ignore Pong; }
}
// PSpec/Spec.p
spec PingAnswered observes Ping, Pong {
  start state Idle { on Ping goto Waiting; }
  hot state Waiting { on Pong goto Idle; }
}
// PTst/Test.p
test tcSingleClient [main=Client]: assert PingAnswered in (union { Client }, { Server });
```

## Run
```
p compile
p check -tc tcSingleClient -s 1000
```
`p compile` finds the `.pproj` in the current directory (`-pp path` otherwise) and builds a .NET dll under `PGenerated/`. `p check` finds the dll; with no `-tc` it prints the list of test cases and an error. `-s N` is the number of schedules to explore (the default is one). The tutorial says about 100,000 schedules typically find most easy bugs.

Passing looks like: `..... Found 0 bugs.` and `..... Explored 1000 schedules`. A bug prints `Checker found a bug.`, writes traces under `PCheckerOutput/BugFinding/` (a `.txt`, a `.trace.json` and a `.schedule` file that can be replayed) and ends with `Found 1 bug.`. Exit status, from the checker source (`ExitCode.cs`): 0 no bugs, 1 a bug found, 2 an internal error. The docs do not say that the `p` command passes this through unchanged, so verify with a deliberately broken model.

## As a contract check
```json
{"id": "design-protocol-p", "claim": "No explored schedule of the Ping/Pong machines violates the monitor", "kind": "state-machine", "rung": 1, "cmd": "p compile && p check -tc tcSingleClient -s 1000", "expect": {"exit": 0}, "timeout_s": 1800, "tier": "deep"}
```
The exit codes come from the checker source and were not run here; confirm that a found bug makes the `p check` step exit 1.

## What a pass does not prove
- Schedule exploration is bounded (`-s`), so a pass is strong evidence, not proof; P's default random strategy samples schedules rather than enumerating them all.
- Only the modelled failures (drops, crashes) are covered. Only the scenarios in the test cases are explored.
- The model is not the code.
- Not run here; commands come from the P documentation and source.
