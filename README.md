# callsite-impact

**A vendor ships a new API version. Your spec differ says "3,383 breaking changes". The only
question that matters is: *which of our call sites actually break?* A differ cannot answer it — it
compares two documents and knows nothing about your code.**

This repository answers it, and then proves the answer against the TypeScript compiler.

---

## The measured result

18 revision pairs from **three vendors** — Adyen, Twilio and Xero, all MIT-licensed public
OpenAPI specifications. **1,338** generated call sites that typecheck clean against revision A.
The compiler breaks **94** of them against revision B. That is the answer key.

| Predictor | **False negatives** | False positives | Precision | Recall | F1 |
|---|---|---|---|---|---|
| **This tool** | **3.2%** | **0.3%** | 0.958 | 0.968 | **0.963** |
| Baseline: *every call site on a changed operation* | 0.0% | 64.4% | 0.105 | 1.000 | 0.190 |
| Baseline: *…restricted to ERR-level changes* | 19.1% | 58.2% | 0.095 | 0.809 | 0.170 |

**Read the naive baseline carefully, because it is not bad at finding breakage — it finds all of
it.** It flags **895** call sites to catch the 94 that break. 801 of those are fine. That is the
number a person has to work through by hand, and it is why "which operations changed?" is not a
useful answer to "what do I have to fix?"

**False negatives lead the table** because a tool that misses breakages manufactures false
confidence and is worse than no tool. Ours misses 3 of 94.

Regenerate with `make corpus && make killtest`. Every number above is written into
[`artifacts/evaluation.json`](artifacts/evaluation.json) by the run that measured it, and CI
re-measures on every push and fails if the committed artifact no longer matches.

### The kill criterion, declared before implementation

[`DECISIONS.md`](DECISIONS.md) ADR-001 was committed **before a line of the pipeline existed**
(`git log` shows the order) and fixed the threshold at **60 compiler-verified call-site breakages
across at least three vendors**.

> **Observed: 94 breakages, 3 vendors. PASSED.**

---

## Why the compiler, and not us

The failure mode for a project like this is obvious: the author writes the code, writes the answers,
and grades themselves. So neither the answers nor the code are written by a person here.

```
vendor spec A ─┬─ openapi-typescript ─→ types A ──┐
               │                                   ├─→ tsc ─→ ADMIT the call sites that compile clean
               └─ generate call sites (seed) ──────┘         (a failure is discarded, never repaired)
                              │
vendor spec B ─── openapi-typescript ─→ types B ──→ tsc ─→ ★ COMPILER LABELS = ground truth
                              │
                              └─→ parse the call-site source (no type checker) ─┐
                                                                                 ├─→ verdicts
vendor spec A + B ─── oasdiff ─→ typed change set ───────────────────────────────┘
```

1. **Call sites are generated from revision A and a seed.** The generator is never shown revision B
   and never shown the diff, so it cannot choose what breaks.
2. **A call site that does not compile against A is discarded, never repaired.** Repairing it would
   let an author who *can* see the diff decide which call sites survive.
3. **The system under test never sees compiler output.** It reads the spec diff and a *parsed* view
   of the call-site source. A guard test fails the build if the classification package imports the
   oracle, or if the fact extractor reaches for `createProgram` or `getTypeChecker`.

---

## The three verdicts, and why the third one is not a cop-out

| Verdict | Meaning |
|---|---|
| **IMPACTED** | this call site breaks under revision B |
| **UNAFFECTED** | the change reaches this operation but cannot reach this call site's usage |
| **UNKNOWN** | the change is of a class the type system **cannot express** |

`oasdiff` calls a decreased `maxLength` a breaking change, and it is one — but `maxLength` does not
exist in the TypeScript type system. No call site can be made to fail on it, and **a clean compile
there is not evidence of safety**. Reporting it as breakage is a false positive; reporting it as safe
is worse. So it abstains, the abstention is counted, and the rate is published: **2.2%**.

The scorer reports two views and the README shows both. **Strict** counts UNKNOWN as a miss;
**abstaining** excludes it and reports it separately. On this corpus they are identical to three
decimal places, because almost nothing abstains.

---

## What the numbers do not say

- **Compilation proves a type-level incompatibility. It does not prove production breakage.** A
  `maxLength` that shrank will reject your requests at runtime with a clean build.
- **The call sites are generated, not harvested.** The specs, the diffs, the compiler and the labels
  are real; the client code is synthetic. This is never called a corpus of production code.
- **One language.** TypeScript, because it has a structural type system and a spec-to-types
  generator that is not ours. Python and Go call sites are out of scope.
- **Adyen contributes 46 of the 94 breakages, and one pair contributes 33.** Per-vendor numbers are
  published for exactly this reason. Xero is the weakest: 18 breakages, recall 0.833.
- **138 of 1,476 generated call sites were discarded** for not compiling against revision A. The
  generator does not handle every schema shape; discarding is the designed response, and the count
  is published rather than hidden.

---

## Two findings worth the reading

**A differ's "breaking change" count says almost nothing about your blast radius.** 3,383 changes;
94 broken call sites. The gap is not the differ being wrong — every change is real. It is that
breakage is a property of *your code*, and the differ has never seen it.

**The abstention rate was 75.7% and the reason was a bug, not a truth about the domain.** A review
found that the prose-shape table read 16 of `oasdiff`'s sentence forms while the expressibility
table ruled on 24 change classes. The eight unread ones carried 2,294 of the 3,383 changes — they
were ruled decidable and then abstained anyway, for want of a parsed property path. Writing the eight
missing patterns moved abstention to 2.2% and false negatives from 5.3% to 3.2%. A high abstention
rate is very comfortable to publish as a limitation; it was a missing table.

---

## Run it

```bash
make install     # uv sync --frozen, then npm ci in harness/
make corpus      # fetch the pinned vendor specs (MIT only)
make killtest    # THE MEASUREMENT: generate, admit, compile, classify, score
```

`make corpus` needs the differ this project consumes rather than reimplements:

```bash
go install github.com/oasdiff/oasdiff@v1.29.1
```

```bash
cd frontend && npm install && npm run dev    # the console on :3000
```

---

## The corpus

| Vendor | Pairs | Services | Licence |
|---|---|---|---|
| Adyen | 9 | checkout, balance-platform, account, bin-lookup | MIT |
| Twilio | 6 | conversations, events, flex, messaging, taskrouter, verify | MIT |
| Xero | 3 | bankfeeds, files, payroll-au | MIT |

The specifications are **not committed** — they are 0.1–1.8 MB each and reproducible from a pin.
[`corpus/manifest.json`](corpus/manifest.json) **is** committed and records, for every revision, the
vendor, the exact commit or version, the source URL, the licence and the **SHA-256 of the bytes used**.
That is what makes a run checkable rather than merely repeatable.

**Stripe was acquired, measured, and removed** — `oasdiff` does not finish on its 8 MB revisions
(still running after 35 CPU-minutes, against seconds for every other pair), so the pair cannot be
re-measured in CI. The reason is recorded in `corpus/acquire.py` rather than quietly deleted.

---

## Where AI is allowed

**Nowhere in the measurement.** No model is called anywhere in this repository. Ground truth is a
file written by `tsc`; verdicts come from a rule table over a parsed syntax tree.

This is structural rather than a policy: the `Finding` type has no free-text field, no confidence
score, and a closed `Literal` set of reasons — **a model cannot express a verdict here because the
type has nowhere to put one.** A guard test walks that schema and fails the build if such a field
appears. A model could reasonably rank or explain findings the compiler already confirmed; that is
not built, and is not claimed.

---

## Documents

| File | Purpose |
|---|---|
| [`DECISIONS.md`](DECISIONS.md) | ADR-001: the claim, the oracle, the kill test and every metric, **declared before implementation** |
| [`CLAUDE.md`](CLAUDE.md) | the operating rules this repository is built under |
| [`docs/deployment.md`](docs/deployment.md) | why the public demo has no backend |
| [`harness/README.md`](harness/README.md) | the compiler harness, and the boundary inside it |
| [`PROJECT_STATUS.md`](PROJECT_STATUS.md) | what exists, what is verified, what is not |
