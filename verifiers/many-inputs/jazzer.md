---
id: jazzer
title: Fuzzing the JVM and JavaScript with Jazzer and Jazzer.js
answers: Can any input make this Java, Kotlin or Node code throw an unexpected exception, hang or hit a known bug pattern?
rung: 2
section: many-inputs
languages: java, kotlin, javascript, typescript
kinds: parsing, general
cost: medium
detect: jazzer --help
ran_here: no
verified: docs
---

## Use when

- JVM or Node code parses or processes untrusted input and should throw only documented errors.
- You want fuzz tests that run as ordinary unit tests (replaying saved crashes) in CI and as a long fuzz job on demand.
- You want built-in detectors for common problems (injection sinks, unsafe deserialisation).

## Do not use when

- You want shrinking and structured values: `jqwik` or `fast-check`.
- The code is Python (`atheris`) or Go (`go-fuzz`).

## Set up

JVM (JUnit 5): add `com.code-intelligence:jazzer-junit` as a test dependency
(Maven Central; use the current version). A standalone `jazzer` binary is on the
project's GitHub releases page.
Node: `npm install --save-dev @jazzer.js/core` (and `@jazzer.js/jest-runner` for Jest).

## Minimal example (JVM, `ParserFuzzTest.java`)

    import com.code_intelligence.jazzer.junit.FuzzTest;

    class ParserFuzzTest {
        @FuzzTest
        void parsePairNeverCrashes(String input) {
            try {
                Parser.parsePair(input);
            } catch (IllegalArgumentException expected) {
                // the documented error; any other exception is a finding
            }
        }
    }

Node equivalent (`fuzz.js`): `module.exports.fuzz = function (data /* Buffer */) { parsePair(data.toString()); };`

## Run

    JAZZER_FUZZ=1 mvn test -Dtest=ParserFuzzTest      # fuzzing mode
    mvn test                                          # regression mode: replays saved crashes only
    npx jazzer fuzz                                   # Node; see `npx jazzer --help` for corpus and time flags

Without `JAZZER_FUZZ=1` the JUnit tests only replay saved inputs, so a plain test run
is quick and never fuzzes. Passing looks like: tests pass, exit 0. Failure reports the
stack trace and writes the crashing input under
`src/test/resources/<package>/<Class>Inputs/<method>/`; commit it so regression
mode replays it. A time budget for the JVM and Node jobs is a libFuzzer flag
(`-max_total_time=60`); I could not confirm from the docs how each wrapper passes it.

## As a contract check

    {"id": "fuzz-parser-jvm", "claim": "parsePair throws only IllegalArgumentException and all saved crashing inputs still pass", "kind": "parsing", "rung": 2, "cmd": "mvn -q test -Dtest=ParserFuzzTest", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 600}

This replays the saved inputs; a fuzzing-mode job is a separate scheduled run.

## What a pass does not prove

- In regression mode it only re-checks saved inputs; it does not search.
- A fuzzing run finding nothing is not a proof; budget and seed corpus matter.
- Not run here (no JDK is set on this machine). `@FuzzTest`, `JAZZER_FUZZ`, the artifact location and the Node install and signature are from the project READMEs; Node corpus and time flags were not confirmed. Check the check: plant a crash and see it found.
