---
id: typescript-type-level
title: TypeScript strict mode, branded types, exhaustive never checks, type tests
answers: Does the TypeScript compiler reject misuse of this API: wrong units, unhandled cases, invalid states?
rung: 1
section: prove
languages: typescript
kinds: general, money, state-machine
cost: low
detect: npx --no-install tsc --version
ran_here: yes
verified: ran
---

## Use when
- Values are easy to mix up (cents vs dollars, user id vs order id) and you want the compiler to stop it.
- A union grows over time and every `switch` over it must handle new members.
- You want type-level behaviour tested, so a refactor cannot silently weaken a type.

## Do not use when
- The rule is about runtime values only. A brand does not validate; it needs a smart constructor that does.
- You wrote `as any` or `// @ts-ignore` to get it to compile; the check is then worthless.

## Set up
`npm i -D typescript` (7.0.2 tried; `tsd` 0.33 for dedicated type tests). `tsconfig.json`: `{"compilerOptions": {"strict": true, "noEmit": true, "target": "ES2022", "module": "ES2022", "moduleResolution": "bundler", "types": []}, "include": ["src"]}`.

## Minimal example
`src/brand.ts`:
```ts
declare const brand: unique symbol;
export type Cents = number & { readonly [brand]: "Cents" };
export function cents(n: number): Cents {
  if (!Number.isInteger(n)) throw new RangeError("cents must be an integer");
  return n as Cents;
}
export type Shape = { kind: "circle"; r: number } | { kind: "square"; s: number };
export function area(sh: Shape): number {
  switch (sh.kind) {
    case "circle": return 3 * sh.r * sh.r;
    case "square": return sh.s * sh.s;
    default: { const _x: never = sh; return _x; }   // fails if a case is missing
  }
}
export function pay(_c: Cents): void {}
```
`src/brand.test-d.ts` (type test, type-checked only, never run):
```ts
import { pay, cents } from "./brand";
pay(cents(5));
// @ts-expect-error a plain number is not Cents
pay(5);
```
`@ts-expect-error` itself fails the build if the next line has no error, so the test cannot rot.

## Run
`npx tsc -p .`

Passing looks like: no output, exit 0. Failure: `error TS2345: Argument of type 'number' is not assignable to parameter of type 'Cents'` (removing the `@ts-expect-error` line), or `Type '{ kind: "square"; ... }' is not assignable to type 'never'` after deleting the `square` case; exit 2 or 1 (nonzero). With `tsd`, run `npx tsd` and use `expectError` and `expectType`.

## As a contract check
```json
{"id": "prove-cents-brand", "claim": "A plain number cannot be passed where Cents is required, and area handles every Shape", "kind": "general", "rung": 1, "cmd": "npx tsc -p .", "expect": {"exit": 0}, "tier": "deep", "timeout_s": 300}
```

## What a pass does not prove
- Types are erased at runtime; data arriving from JSON or the network is unchecked unless parsed by a validator (zod and similar) that returns the branded type.
- `any`, `as` casts, `@ts-ignore` and `@ts-expect-error` placed on the wrong line defeat it. Grep for them and add `noImplicitAny` (part of `strict`).
- TypeScript's type system is intentionally unsound in places (array covariance, index access without `noUncheckedIndexedAccess`).
