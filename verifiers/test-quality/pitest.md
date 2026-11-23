---
id: pitest
title: Mutation testing for the JVM with PIT (pitest)
answers: Would my Java or Kotlin tests notice if this code were wrong?
rung: 2
section: test-quality
languages: java, kotlin
kinds: general, money, parsing
cost: medium
detect: mvn --version
ran_here: no
verified: docs
---

## Use when
- A Maven or Gradle JVM project has JUnit tests and you want evidence they can fail.
- You want a pass/fail gate on mutation score in CI.
- It is a check on other checks; it gives rung 2 confidence in the tests.

## Do not use when
- The build is not on Maven, Gradle or an IDE that PIT supports.
- Tests are slow integration tests; scope `targetTests` tightly.

## Set up
Not run here (no JDK configured on this machine); taken from pitest.org's Maven quickstart. Add to `pom.xml`:

    <plugin>
      <groupId>org.pitest</groupId>
      <artifactId>pitest-maven</artifactId>
      <version>LATEST</version>   <!-- pin a real version in your project -->
      <configuration>
        <targetClasses><param>com.example.pricing*</param></targetClasses>
        <targetTests><param>com.example.pricing*</param></targetTests>
        <mutationThreshold>80</mutationThreshold>
        <withHistory>true</withHistory>
      </configuration>
    </plugin>

For JUnit 5, also add the `pitest-junit5-plugin` as a plugin dependency (from memory of the PIT docs; confirm in your version). Gradle uses the separate `info.solidsoft.pitest` plugin (`gradle pitest`; not checked here).

## Minimal example
`Pricing.java`:

    public class Pricing {
      public static int price(int qty, int unit) {
        int total = qty * unit;
        return qty >= 10 ? total - total / 10 : total;
      }
    }

With a JUnit test for `price(2,100)` and `price(20,100)` only, PIT reports a survivor for the boundary `>=` changed to `>`.

## Run
    mvn test-compile org.pitest:pitest-maven:mutationCoverage

Passing looks like: the build succeeds and the console shows a mutation score at or above `mutationThreshold`; the HTML report is in `target/pit-reports/`. Failure: the build fails with a score below the threshold, and the report lists `SURVIVED` mutations with the line. `withHistory` stores results to speed up reruns. To check only changed code PIT has an SCM goal (`scmMutationCoverage`); I could not confirm its options from the docs I read, so read the PIT docs before relying on it.

## As a contract check
    {"id": "pitest-score", "claim": "Mutation score of the pricing package is at least 80", "kind": "general", "rung": 2, "cmd": "mvn -q test-compile org.pitest:pitest-maven:mutationCoverage", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 3600}

## What a pass does not prove
- Only the classes matched by `targetClasses` are mutated; a too-narrow glob yields a vacuous pass. Check the report names your classes.
- Surviving mutants may be equivalent; exclude with `excludedMethods` or `avoidCallsTo` and say why.
- A score is a ratio of sampled changes, not correctness.
- With no `mutationThreshold`, the build passes whatever the score. Check it is set.
