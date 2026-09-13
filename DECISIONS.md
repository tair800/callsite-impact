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

---

## ADR-003 — What two read-only reviews found, and what it does to the claim

**Status:** accepted, 2026-09-12, **after the first measured result**.

Two independent reviews were run against the measured repository. Both found real defects. This
record exists because three of them change how a number should be read, and a finding that changes
how a number should be read has to sit next to the number.

### The kill criterion is an absolute count, so it scales with a budget nobody pre-registered

`pipeline.py` fixes three constants: `MAX_OPERATIONS = 120`, `CALLSITES_PER_OPERATION = 4`,
`SEED = 20260912`. **ADR-001 does not pre-register any of them.** It pre-registers the *axes* the
generator may vary, not how much to generate. A comment in `pipeline.py` claimed otherwise; that
comment was wrong and has been corrected.

A reviewer re-ran the identical corpus, identical seed and identical specifications at the harness's
own defaults:

| Budget | Admitted call sites | Compiler breakages | Kill criterion |
|---|---|---|---|
| 120 × 4 — published | 1,338 | **94** | PASSED |
| 40 × 3 — `gen-callsites.mjs` defaults | 854 | **52** | **FAILED** |

**What this does not mean.** The accuracy figures are rates and barely moved: F1 0.962 at the
smaller budget against 0.963 published, precision 0.962 against 0.958. The classifier result is not
a function of the budget.

**What it does mean.** *"94 breakages, PASSED"* is a statement about a corpus of a particular size.
The blueprint's criterion — *"fewer than 60 compiler-verified call-site breakage labels across at
least three vendors"* — is best read as a feasibility test: can a corpus of this kind be built at
all, from public specifications, with labels a compiler emits? It can, and 94 is the evidence. But
the threshold is not scale-free, the budget was chosen before any result existed and has not been
changed since, and a reader is entitled to know that a third of the budget would not have cleared
it. Both numbers are published rather than the flattering one.

The budget was **not** raised in response to a result. It has had one value since the first full
run. That is checkable in `git log`.

### The oracle-boundary guard was vacuous, and a reviewer proved it

The guard banned imports of `callsite_impact.oracle` — **a package that did not exist**. A reviewer
planted `import callsite_impact.pipeline` plus a read of `work/<pair>/labels.json` into
`classify/rules.py`, giving the classifier the compiler's raw diagnostics, and all sixteen tests
stayed green.

The boundary was never actually crossed in shipped code — every import under `classify/` was checked
and resolves to `domain`, `specdiff` or the standard library. The defect was in the guard, which is
the worse place for it: a guard nobody can fail is a guard everybody trusts.

Replaced with an **allowlist** of first-party imports plus a ban on the oracle's output filenames,
and both halves were verified by planting the reviewer's own breach and watching them fail.
A ban list only stops the routes somebody thought of.

### Two-thirds of the breakages ride on two bindings that are a sixth of the corpus

| Binding | Call sites | Broken | Rate |
|---|---|---|---|
| inferred `const` | 1,100 | 35 | 3.2% |
| `const pinned: "a" \| "b" = res.x` | 132 | 31 | **23.5%** |
| exhaustive `switch` with a `never` default | 106 | 28 | **26.4%** |

238 call sites — 17.8% of the corpus — carry 59 of the 94 breakages. ADR-001 pre-registers the
binding axis and says plainly that it is what decides whether a widening change can reach a call
site at all; what it does not pre-register is the probability of drawing each one. Both are patterns
real TypeScript clients use, and neither was tuned after a result. But the headline is materially a
statement about that mix, and it is now disclosed rather than left for a reader to discover.

### There is no held-out set

The expressibility table rules on exactly the 24 change ids this corpus emits, so
`unclassified_changes: 0` is tautological and carries no information about generalisation. Worse for
the headline: eight prose patterns were added **after** seeing a score, moving false negatives from
5.3% to 3.2%. That was a genuine bug fix and it is disclosed on the front page — but 3.2% is a
post-selection number on the corpus the rules were fitted to.

Closing this properly means reserving a vendor the rules have never seen and reporting it
separately. It is **not done**, it is the largest open weakness in the measurement, and it is
recorded here rather than left implicit.

### Smaller corrections

- The differ's `--version` reports `oasdiff version main` for a binary installed from tag `v1.29.1`,
  because the version is injected at link time. The manifest recorded that string, contradicting
  every instruction in the repository. Now read from the Go module stamp, which cannot drift.
- Compiler diagnostics were attributed to call sites by line number without checking the filename.
  Harmless today — the oracle typechecks one file — and silently wrong the day it is not.
- `README.md` opened by attributing the corpus-wide total of 3,383 changes to a single vendor
  upgrade. The largest single pair is 797 and the median is about 130.

---

## ADR-004 — A confirmatory slice, and what the budget evidence actually supports

**Status:** accepted, 2026-09-13, **before the slice was measured**.

ADR-003 left two things open. This record closes one of them with evidence, closes the other with a
measurement, and is committed **before either result exists** so the order is checkable.

### What the history proves about the generation budget, stated exactly

| Question | Answer from `git log` |
|---|---|
| When was the canonical budget introduced? | `0242344`, the commit that introduced `pipeline.py` |
| Has it ever changed? | **No.** Two commits have touched `pipeline.py`; the second changed a comment. `MAX_OPERATIONS = 120`, `CALLSITES_PER_OPERATION = 4`, `SEED = 20260912` are the only values the file has ever held. |
| Was it fixed before the first score was *observed*? | **The repository does not prove this.** `0242344` also introduced `artifacts/evaluation.json` — the first committed measurement. Both landed together. |
| Does ADR-001 pre-register it? | **No.** Grepping the pre-registration commit `d3587d9` for a budget returns nothing. |
| Harness default | `40 × 3`, in `gen-callsites.mjs`, unchanged since its first commit |

**So the honest claim is narrower than "pre-registered", and narrower than what ADR-003 said.**
ADR-003 stated *"the budget was not raised in response to a result … that is checkable in git log"*.
What `git log` actually shows is that the budget never changed **after the first committed score**.
The first full run happened in a working tree before that commit, so the history cannot separate
"chosen before the first score" from "chosen while the first score was visible". That correction is
made here rather than left standing.

The word **pre-registered** is therefore not used of the budget anywhere. It is used only of what
ADR-001 actually fixed before implementation: the claim, the oracle, the three verdicts, the kill
threshold, the two baselines and the metric list.

### The kill criterion is unchanged, and its sensitivity is published

The criterion stays exactly as the blueprint set it: **≥60 compiler-verified call-site breakage
labels across ≥3 vendors.** It is not lowered, rewritten or reinterpreted.

It is an **absolute count**, so it scales with how much code the generator writes. The canonical
release corpus and the harness default are both measured and both published, so a reader can see
which claims scale with corpus volume and which do not. The sweep lives in
`artifacts/budget_sweep.json`, written by `scripts/budget_sweep.py`.

### The confirmatory slice

`corpus/holdout.py` names fifteen spec pairs — six Adyen services, six Twilio products, three Xero
APIs — **none of them in the development corpus**, chosen by service name before any of their
content was inspected. It is a **data** hold-out, not a vendor hold-out: it tests whether the rule
logic generalises to call sites and changes nobody tuned against, and it does not independently test
the expressibility table, because the same three vendors will largely produce ids already ruled on.
An unruled id abstains, which costs the strict score rather than hiding in it.

**The commitment, made here before the number exists: whatever it scores is published, and no rule,
pattern or table is changed afterwards.** If the slice scores worse than the development corpus,
that gap is the finding.

A pair is excluded **only** if the toolchain cannot process it, never because of its result, and
every exclusion is counted and published.
