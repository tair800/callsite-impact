# PROJECT_STATUS — callsite-impact

Resume point for every session. Read after `CLAUDE.md`, then `git status` and recent commits.

**Current status: the claim is measured and the predeclared kill criterion passed.** ADR-001 was
committed before any implementation; the corpus, the oracle, the classifier and both baselines now
run end to end, and CI re-measures on every push.

---

## The measurement

| Predictor | False negatives | False positives | Precision | Recall | F1 |
|---|---|---|---|---|---|
| **System** | **3.2%** | **0.3%** | 0.958 | 0.968 | 0.963 |
| Baseline — every call site on a changed operation | 0.0% | 64.4% | 0.105 | 1.000 | 0.190 |
| Baseline — the same, ERR-level changes only | 19.1% | 58.2% | 0.095 | 0.809 | 0.170 |

Strict view, pooled. Abstention 2.2%. Written by the run that measured it into
`artifacts/evaluation.json`; never hand-typed.

**Kill criterion — declared in ADR-001 before implementation:** ≥60 compiler-verified call-site
breakages across ≥3 vendors. **Observed 94 across 3. PASSED.**

| Corpus | |
|---|---|
| Spec pairs | 18 |
| Vendors | 3 — Adyen (9 pairs), Twilio (6), Xero (3) |
| Call sites generated | 1,476 |
| Call sites admitted (clean against revision A) | 1,338 |
| Call sites discarded | 138 |
| Compiler breakages | 94 |
| Compiler diagnostics | 179 |
| Differ-reported changes | 3,383 across 24 distinct ids, 0 unclassified |

---

## What exists and is verified

| Item | State | Evidence |
|---|---|---|
| Pre-registration | **DONE** | ADR-001 in commit `d3587d9`, before the pipeline commit `0242344` |
| Corpus with provenance | **DONE** | `corpus/manifest.json`: vendor, revision, source URL, licence and SHA-256 per spec; `make corpus` is idempotent on a checksum match |
| Compiler oracle | **DONE** | `harness/scripts/run-tsc.mjs`; labels join to call sites by marker comment, never by the generator's own record |
| Admission | **DONE** | `harness/scripts/admit.mjs`; iterates until clean against revision A, records every discard and why |
| Parser-only extractor | **DONE** | `harness/scripts/extract-facts.mjs`; a guard test fails the build if it reaches for `createProgram`, `getTypeChecker` or `getPreEmitDiagnostics` |
| Classifier | **DONE** | 13 rule functions over 19 change ids; the other 5 of the 24 ruled-on ids are not-type-expressible and never reach a rule — the abstention gate takes them first. Cannot import the oracle package, enforced by an AST-based guard |
| Both baselines | **DONE** | Predeclared in ADR-001, scored by the same scorer over the same candidate pairs |
| AI boundary | **DONE (structural)** | `Finding` has no free-text field, no confidence, and a closed `Literal` reason set; a guard walks the schema |
| Console | **DONE** | Result, spec-pair and provenance screens; 42 Vitest tests; `npm run build` clean |
| Offline suite | **DONE** | 257 tests, no corpus, no network, no node, no credential |
| CI | **GREEN** | Three jobs: offline suite, the full measurement against the real corpus, and the console |

---

## What is deliberately not claimed

| Claim | State | Why |
|---|---|---|
| **Production breakage** | **Not claimed** | A compiler label is a *type-level* incompatibility at a *generated* call site against a *generated* client. A `maxLength` that shrank breaks requests at runtime with a clean build. |
| **A corpus of real client code** | **Not claimed** | The specifications, diffs, compiler and labels are real; the call sites are generated. Said plainly on the front page. |
| **Any live model** | **NOT USED** | No model is called anywhere. Ground truth is a file written by `tsc`; verdicts come from a rule table over a parsed syntax tree. The `Finding` type has nowhere for a model to write a verdict. |
| **Languages other than TypeScript** | **Out of scope** | TypeScript is the oracle because it has a structural type system and a spec-to-types generator that is not ours. |
| **Retrieval / RAG** | **NOT BUILT** | ADR-002. The blueprint specifies pgvector, BM25, RRF and a reranker for this project and the skill matrix counts it as one of exactly three RAG repositories. None of it is built here, and that is an open portfolio coverage gap, recorded rather than absorbed. |
| **Deployment** | **Live** | Console on Vercel, reading the committed artifacts at build time. No backend — see `docs/deployment.md`. |

---

## What two read-only reviews found

Both reviews were adversarial and read-only, and both found real defects. The three that change how
a number should be read are in `DECISIONS.md` ADR-003 and on the README's front page; summarised:

**The oracle-boundary guard was vacuous.** It banned imports of `callsite_impact.oracle` — a package
that did not exist. A reviewer planted `import callsite_impact.pipeline` plus a read of
`work/<pair>/labels.json` into the classifier and all sixteen tests stayed green. The boundary was
never crossed in shipped code; the defect was in the guard, which is the worse place for it. Replaced
with an allowlist of first-party imports plus a ban on the oracle's output filenames, and verified by
planting the reviewer's own breach and watching both halves fail.

**The kill criterion scales with an unregistered budget.** At the harness's own default generation
budget the identical corpus yields **52** breakages, below the threshold of 60. The published 94 is
at a budget fixed in `pipeline.py` that ADR-001 never pre-registered — and a comment there claimed
it had. The accuracy rates are unaffected (F1 0.962 against 0.963). Both numbers are now published.

**Two-thirds of the breakages ride on a sixth of the corpus** — the 238 call sites that pin a narrow
type, at a 24% breakage rate against 3.2% for an inferred `const`.

**The differ's self-reported version was wrong in the manifest.** `go install …@v1.29.1` produces a
binary that reports `oasdiff version main`, because the version is injected at link time. The
manifest recorded that, contradicting every instruction in the repository. Now read from the Go
module stamp.

**The README attributed a corpus-wide total to one upgrade** — "3,383 breaking changes" is the sum
across 18 pairs; the largest single pair is 797 and the median about 130. Rewritten around a real
single pair.

---

## Known issues and findings

**The abstention rate was 75.7% and the cause was a missing table, not the domain.** The prose-shape
table in `specdiff/oasdiff.py` read 16 of `oasdiff`'s sentence forms while the expressibility table
ruled on 24 change classes. The eight unread ones carried **2,294 of 3,383 changes** —
`response-property-became-nullable` alone was 2,087. Those changes were ruled decidable and then
abstained anyway, because the property path is the only thing that joins a change to a call site and
there was nothing to produce one. Found by a read-only review, not by a test. Writing the eight
patterns moved abstention to 2.2% and false negatives from 5.3% to 3.2%. The lesson worth keeping: a
high abstention rate is *comfortable* to publish as an honest limitation, which is exactly why it
needs checking rather than accepting.

**The oracle could fabricate a clean answer key.** `run-tsc.mjs` installed the types module into the
call-site directory *before* counting the files in it, so its empty-directory guard was unreachable.
An empty directory typechecked `spec.ts` against itself and reported `errorCount: 0` with exit 0 —
indistinguishable from a revision where nothing broke. Found by a read-only review. Fixed by counting
call-site files before installing the types, excluding `spec.ts`.

**The operation "sample" was not sampling.** `operations.filter(() => chance(rand, 1))` is always
true, so the generator took the first N operations in sorted path order. On a large specification
that means every call site lands in the alphabetical head of the API and coverage depends on a
path's first letter. Replaced with a seeded shuffle.

**Five documentation claims were false and were corrected rather than kept.** A module docstring said
the table ruled on 16 ids when it held 24, and that a change class was abstained on when the table
ruled it expressible — a reader was being told the opposite of what the code does. Others cited
Stripe figures after Stripe had been removed from the corpus. Prose is not type-checked, and this is
the second project in a row where the only defence that worked was a reviewer reading it.

**Stripe was acquired, measured and removed.** `oasdiff` does not finish on its two 8 MB revisions —
still running after 35 CPU-minutes, against seconds for every other pair — so the pair cannot be
re-measured in CI, and a measurement nobody can re-run is the one thing this project cannot ship. A
separate probe over an even wider Stripe pair (8,922 differ-reported changes, 434 admitted call
sites) produced **zero** compiler breakages, so removing it moved the kill criterion in neither
direction. Recorded in `corpus/acquire.py` rather than deleted.

**Xero is the weakest vendor and the per-vendor table says so.** 64 admitted call sites, 18
breakages, recall 0.833 against 1.000 for Adyen and Twilio. Three of its six candidate services are
excluded because `oasdiff` rejects their published specifications outright — duplicate endpoints and
YAML unmarshal failures — which is a defect in the specs, not the differ.
