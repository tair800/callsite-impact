# Decisions

Architecture decision records. ADR-001 is written **before any implementation** and declares the
claim, the oracle, the kill test, the baseline and every metric. Nothing in it may be weakened after
results are seen; if a number comes out badly, the number is published.

---

## ADR-001 — The claim, the oracle, and the kill test

**Status:** accepted, 2026-09-12, **before implementation**.

### The problem, stated as a developer would hit it

A product team integrates 10–40 third-party APIs. A vendor ships a new API version. Someone runs a
spec differ, gets back *"39 breaking changes"*, and now has to answer the only question that
matters: **which of our call sites actually break?**

A spec differ cannot answer it. It compares two documents and knows nothing about your code. So the
team either upgrades blind, or reads 39 changes against an unknown number of call sites by hand.

### What this repository claims

> **Given two revisions of a public OpenAPI specification and a corpus of client call sites, this
> tool separates the call sites that break from the call sites that do not — and where the change is
> of a class the type system cannot express, it says so instead of guessing.**

Every verdict carries an anchor: the spec change id and location, and the call-site file/line/column.

### The measurement that defines "breaks" — and why it is not us

The answer key is **the TypeScript compiler**, not a human and not a model.

1. Take vendor spec revision **A** and revision **B**, both public, both MIT-licensed.
2. Generate TypeScript types from each with `openapi-typescript` — deterministic, no model.
3. **Generate call sites from revision A**, so that every call site typechecks clean against A *by
   construction*. A call site that does not compile against A is discarded, never repaired.
4. Recompile the identical call sites against revision B. **`tsc` emits the labels** — file, line,
   column, and TypeScript error code.

The system under test never sees the compiler. It predicts from the spec diff and a static read of
the call-site source, and is then graded against what `tsc` said.

**Why call sites are generated rather than hand-written.** A hand-written corpus is a corpus whose
author chose what breaks. Generation from revision A removes that choice: the generator is given the
*before* spec and a seed, never the *after* spec and never the diff. It is a pre-registration device,
not a convenience.

**What the generator is allowed to vary,** declared now so the distribution cannot be tuned to
flatter the result. Each call site uses a **subset** of the operation's surface, because real client
code does; a generator that touched every field would make every removal a breakage and the task
trivial. The seeded choices are:

| Axis | Choices |
|---|---|
| Which operations are called | a seeded sample of the operations in revision A |
| Which request properties are supplied | all required ones, plus a seeded subset of the optional ones |
| Which response properties are read | a seeded subset, at a seeded access depth |
| How a read is **bound** | inferred `const` · `const` annotated with the property's type as revision A declares it · exhaustive `switch` over an enum |
| How a read is **navigated** | `a.b.c` or `a?.b?.c` |

The binding axis is on this list because it is the axis that decides whether a *widening* change —
an enum member added to a response — reaches a call site at all. All three bindings are patterns real
TypeScript clients use. They are fixed here, before any count exists, precisely so that the
proportion of call sites exposed to widening cannot be adjusted once the numbers are in.

**The generator is never shown the diff or revision B.** Its inputs are revision A and an integer.

### The three verdicts, and why the third one exists

The first real finding of this project arrived before a line of it was written. Of the 39 changes
`oasdiff` calls breaking between Adyen Checkout v71 and v72, **26 are `maxLength` changes** — and
`maxLength` does not exist in the TypeScript type system. No call site can be made to fail on it,
and no call site compiling clean is evidence of safety.

So the verdict set is three-valued, and the third value is load-bearing:

| Verdict | Meaning | Evidence required |
|---|---|---|
| **IMPACTED** | this call site breaks under revision B | spec change anchor **and** call-site token anchor |
| **UNAFFECTED** | the change reaches this operation but cannot reach this call site's usage | the same anchors, plus the reason the usage is out of reach |
| **UNKNOWN** | the change class is **not expressible in the type system** | the change anchor and the reason it is inexpressible |

**A compiler-clean result on an UNKNOWN change is not a pass.** It is an abstention, it is counted
as one, and the README publishes the rate. Reporting `maxLength` as a call-site breakage is a false
positive; reporting it as safe is worse.

### Which change classes are ruled on, and what happens to the rest

`oasdiff` v1.29.1 can emit **514** distinct change ids. This repository does not pretend to have
ruled on 514. It classifies **only the ids its own corpus actually produces**, each with a written
justification and a test, and every other id is `UNCLASSIFIED`.

**`UNCLASSIFIED` fails towards abstention** — it is treated as not-type-expressible and yields
UNKNOWN. The alternative default is the dangerous one: an unruled change class silently treated as
expressible would let a clean compile be scored as a correct UNAFFECTED, manufacturing accuracy out
of ignorance. The count of changes that landed in `UNCLASSIFIED` is published beside the results.

### The kill criterion — predeclared, not to be lowered

Inherited verbatim from `portfolio-control/PORTFOLIO_BLUEPRINT.md` §3:

> **Fewer than 60 compiler-verified call-site breakage labels across at least three vendors.**

Read at its strictest: **60 call sites on which `tsc` emits an error attributable to the spec
change**, not 60 (call site × change) pairs and not 60 clean compilations. Across **≥3 distinct
vendors**. Both the strict count and the looser total-label count are published so the reading cannot
be quietly swapped later.

If the corpus cannot reach 60 honestly, the claim is not proven and this repository says so on its
front page.

### The baseline — chosen now, before any result exists

> **Naive baseline: every call site that touches a changed operation is IMPACTED.**

This is what a team does today with a spec differ and `grep`. It should score near-perfect recall and
poor precision. A second baseline is also declared now: **every call site touching an operation with
an `oasdiff` ERR-level change is IMPACTED** — the same move with the differ's own severity filter on.

### The metrics — declared now, computed later

Denominator for every rate is the compiler's label set for a spec pair.

| Metric | Definition |
|---|---|
| **False-negative rate** — *the headline* | compiler-labelled breakages the system failed to report ÷ all compiler-labelled breakages |
| False-positive rate | call sites reported IMPACTED that the compiler left clean ÷ all clean call sites |
| Precision / recall / F1 | on the IMPACTED class |
| **Abstention rate** | (call site × change) pairs returned UNKNOWN ÷ all candidate pairs |
| Baseline deltas | both baselines scored on the identical corpus with the identical scorer |

**False negatives lead** because a tool that misses breakages manufactures false confidence and is
worse than no tool. A suppressed unanchorable claim counts as an abstention, never as a hit.

### Where AI is allowed, and where it cannot reach

**Allowed:** explaining a verdict the compiler already reached, ranking verified findings, drafting
migration guidance.

**Forbidden, structurally.** Ground truth is a file written by `tsc`. The AI boundary is not a policy
sentence — the classification path takes no model client, and the evidence type carries no field a
model can write into. A model cannot turn UNKNOWN into IMPACTED because nothing in the pipeline reads
a model to decide a verdict. A guard test enforces the shape.

**Live AI is optional and must not block the core.** The measured claim stands with no model called.

### Consequences, including the ones against us

- The corpus is **synthetic call sites against real vendor specs**. The specs, the diffs and the
  compiler are real; the client code is generated. This repository never calls it a corpus of real
  production code.
- `maxLength`, `pattern`, `minimum`, `format`, enum *semantics*, auth, rate limits and behavioural
  changes are all UNKNOWN. That is a large abstention class and it is published, not hidden.
- One language. TypeScript is the oracle because it has a structural type system and a
  spec-to-types generator that is not ours. Python or Go call sites are out of scope, stated as such.

---

## ADR-002 — Retrieval is not built in this increment, and the gap is recorded

**Status:** accepted, 2026-09-12, **before implementation**.

`PORTFOLIO_BLUEPRINT.md` §3 specifies pgvector HNSW, BM25 over `tsvector`, Reciprocal Rank Fusion and
a cross-encoder reranker, and `SKILL_MATRIX.md` counts this project as one of exactly three carrying
*"RAG end-to-end through citation and measured retrieval evaluation"*.

**None of that is built here.** This increment builds the compiler-grounded core only.

The reason is a scope instruction from the owner that post-dates the blueprint — a 1–2 day
fast-track, *"do not introduce PostgreSQL if the project can remain file/artifact based"*, and a
required final report whose eighteen fields are all corpus, compiler, baseline and verdict figures
with no retrieval metric among them. The core proof and the retrieval layer are separable, and the
core is the one the kill criterion tests.

**The consequence is a real portfolio coverage gap, and pretending otherwise is the failure mode this
ADR exists to prevent:** the mandated *"≥3 projects with RAG through citation and measured retrieval
evaluation"* is met by projects 3, 7 and 8 with no slack. Until retrieval lands here, the portfolio
has two. This is recorded in `portfolio-control/PORTFOLIO_PROGRESS.md` as an open item against
project 3, not silently absorbed.

Nothing in this repository claims semantic retrieval, hybrid search, reranking or a vector index.
