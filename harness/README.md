# harness

The TypeScript workspace: small Node scripts, one pinned compiler, no framework. The three documented
below are the spec-to-types generator, the oracle, and the fact extractor.

`src/callsite_impact/` never imports from here; it shells out and reads the JSON these scripts write.

```
npm install
node scripts/gen-types.mjs      <specPath> <outTsPath>
node scripts/run-tsc.mjs        --types <types.ts> --callsites <dir> --out <labels.json>
node scripts/extract-facts.mjs  --callsites <dir> --out <facts.json>
```

---

## The separation this directory exists to enforce

**`run-tsc.mjs` is the oracle.** It is the only thing in this repository that produces ground truth.
It builds a real program and reports every diagnostic the compiler emits. Its output is the answer
key.

**`extract-facts.mjs` is forbidden the type checker.** It may build a syntax tree and walk it. It may
not construct a compilation unit, obtain a type resolver, or ask for type errors. A guard test in the
Python suite greps it for those identifiers and fails the build if one appears.

The reason is the whole point of the project. `extract-facts.mjs` produces the *input* to the
classifier, and the classifier is the system under test. Its score is computed against what the
compiler said. An extractor that could consult the compiler would be handing the system under test
its own answer key, and every number downstream — the false-negative rate above all — would be
measuring nothing at all.

The cost is real and is not hidden: a parser cannot see through a computed property key, a dynamic
index, or a value that crosses a function boundary. Where syntax cannot answer, the extractor records
nothing rather than guessing, and the resulting gap is a limitation of the approach.

---

## scripts/gen-types.mjs

Turns one OpenAPI document into one TypeScript module, by shelling out to the pinned
`openapi-typescript` binary resolved out of `node_modules` — never `npx`, which is free to fetch a
different version.

Deliberately thin. Nothing here decides what a spec means in TypeScript; a third-party deterministic
generator does. If this script grew a transformation of its own, the oracle would be partly ours.

It fails loudly rather than quietly: a zero exit with a missing, empty, or operation-less output file
is treated as a failure, because every later stage indexes into `operations[...]`.

Generated modules export `paths`, `components` and `operations`. Call sites reach a request body as

```ts
NonNullable<operations["post-payments"]["requestBody"]>["content"]["application/json"]
```

The `NonNullable` is required. The `requestBody` member is optional in the generated output, and
without it the compiler reports `TS2339: Property 'content' does not exist`. A response is reached as
`operations[...]["responses"]["200"]["content"]["application/json"]`.

## scripts/run-tsc.mjs

Typechecks a directory of call sites against one revision's types and writes every diagnostic as
data.

- Copies the types module to `<callsites>/spec.ts`, which is where call sites import it from. The
  types are moved to the call sites rather than the other way round so that the file paths in the
  output are the **real** call-site paths — those paths are the anchor every verdict is joined on.
- Writes `<callsites>/tsconfig.json` with the options inlined from `tsconfig.base.json`, so a reader
  who doubts a label can re-derive it by hand with `npx tsc -p <callsites-dir>`.
- Reports diagnostics through the compiler API, not by parsing stdout. Diagnostic messages contain
  newlines: a real chained message from this corpus is three lines. Line-oriented parsing of the text
  output mangles them.
- Reports **every** diagnostic. No first-error stop, no cap. A truncated answer key silently converts
  real breakages into false negatives in the score, which is the one error this project exists to
  measure.
- Refuses a call-site directory containing no call sites, with exit 2. The check is made *before*
  `spec.ts` is copied in, since afterwards the directory is never empty and an empty answer key would
  be indistinguishable from a clean revision.

Output: `{"errors": [{"file", "line", "column", "code", "message"}], "errorCount": n}`, sorted by
file, line, column, code. Line and column are 1-based. A diagnostic with no file (a configuration
error) is kept with a null file rather than dropped.

**Exit code 0 means the harness ran, not that the code compiled.** Type errors are the product. A
non-zero exit means the harness itself failed.

Call sites are expected flat in the directory, since they all import `"./spec"`.

## scripts/extract-facts.mjs

Reads the same directory with a parser and reports what each call site touches.

Identity comes from a marker comment the generator writes immediately above each exported function,
never from anything inferred — the id has to match the one the generator minted or the facts cannot
be joined to the compiler's labels:

```ts
// @callsite id=cs_abc123def456 op=POST /payments key=post-payments
```

Output is a JSON array, one entry per marked exported function, sorted by call-site id then file then
line, with the property arrays sorted by position, so two runs over the same input are comparable
byte for byte. `file` is relative to the call-site directory, matching the oracle's file keys.

```json
{
  "callsiteId": "cs_abc123def456",
  "operationKey": "POST /payments",
  "file": "payments.ts",
  "line": 11,
  "requestProperties": [{ "path": ["billingAddress", "city"], "line": 20, "column": 7,
                          "literalValue": "Amsterdam" }],
  "responseProperties": [{ "path": ["additionalData", "city"], "line": 30, "column": 42,
                           "optionalChained": true }]
}
```

**What it finds, using syntax only.**

- *Request body.* The object literal is identified in three tiers of descending evidence quality,
  and the tiers are separate so the weakness of the last one stays visible: a type annotation whose
  **text** contains `requestBody`; a variable named `body`, `requestBody`, `payload` or `request`
  (override with `--request-var`); or, only when the function contains exactly one top-level object
  literal and nothing to confuse it with, that literal.
- *Request properties.* Every key set, as a nested path. Intermediate keys are recorded as well as
  leaves — `{billingAddress: {city: "x"}}` yields both `["billingAddress"]` and
  `["billingAddress","city"]`, because removing either breaks the call site. Array literals add no
  path segment: `{lineItems: [{id: "1"}]}` yields `["lineItems","id"]`, since the index is a position
  in the client's data, not in the schema. String and numeric literal values are captured;
  anything else leaves `literalValue` null.
- *Response root.* A parameter whose annotation **text** mentions `responses`, or one named
  `response`, `res` or `result` (override with `--response-param`). Local bindings are then followed
  to a fixed point, so `const address = response.billingAddress` makes `address` a root carrying the
  prefix `["billingAddress"]` — without which the binding styles ADR-001 lets the generator vary
  would make those reads invisible here.
- *Response properties.* One entry per link in each access chain, each carrying the position of its
  own token. `response.data.items` yields `["data"]` and `["data","items"]`. Destructuring is walked
  too: `const { pspReference } = response` is the same read as `response.pspReference`.
  `optionalChained` is cumulative up to and including that link, so in `response.a?.b` the entry for
  `["a","b"]` is chained and the entry for `["a"]` is not — which is the distinction the
  *became-optional* change class turns on.

**What it cannot find, stated rather than guessed at.** Computed property keys. Values reaching the
body through a spread or a function call. Reads through reassignment or conditional binding. A
dynamic index makes everything outside it unnameable, though the segments between it and the root are
still recorded. In every one of these cases the extractor emits nothing for the unreadable part.

---

## Versions

`typescript` and `openapi-typescript` are pinned to exact versions in `package.json`, with
`package-lock.json` committed. The compiler version decides what counts as a breakage, so it is not a
range.
