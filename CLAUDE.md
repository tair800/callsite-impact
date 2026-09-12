# CLAUDE.md — callsite-impact

Operating contract for this repository. Read before any work here.

**Parent portfolio rules remain authoritative.** `../../CLAUDE.md` and
`../../PORTFOLIO_MASTER_SPEC.md` govern; this file adds project rules and never relaxes a parent
one. Where they appear to conflict, the parent wins and the conflict is raised, not resolved
quietly.

---

## What this project is

Given two revisions of a public OpenAPI specification and a corpus of client call sites, it reports
which call sites break, which do not, and which the type system cannot decide.

**The answer key is the TypeScript compiler.** See `DECISIONS.md` ADR-001 — the claim, the oracle,
the kill criterion, the baseline and every metric were declared **before implementation**.

---

## Non-negotiable rules

### 1. The compiler is the oracle, and the system never sees it

- Ground truth is `tsc` output: file, line, column, error code. Never a human, never a model.
- The classifier reads the spec diff and the call-site source. It does **not** read compiler output.
  A guard test enforces that the classification package cannot import the oracle package.
- A call site that does not compile clean against revision **A** is **discarded**, never repaired.
  Repairing it would let the author choose what breaks.

### 2. UNKNOWN is a real answer and must not be collapsed

- A change of a class the TypeScript type system cannot express (`maxLength`, `pattern`, `minimum`,
  `format`, enum semantics, auth, rate limits, behaviour, prose) is **UNKNOWN**.
- A clean compile on such a change is **not** evidence of safety and must never be reported as
  UNAFFECTED.
- The abstention rate is published. Suppressing an unanchorable claim counts as an abstention, never
  as a hit.

### 3. Every verdict carries an anchor

- Spec side: change id, operation, path, and the location in the spec document.
- Call-site side: file, line, column, and the source token the verdict is about.
- A verdict that cannot be anchored is suppressed and counted, not emitted unanchored.

### 4. The model never decides ground truth

- AI may explain, rank or draft migration guidance for a verdict **already reached**.
- It may not produce a verdict, override the compiler, or turn UNKNOWN into IMPACTED.
- **Structural, not policy:** the classification path takes no model client, and the verdict type has
  no field a model can write. A guard test walks the evidence schema and fails the build if one
  appears.
- Live AI is optional. The measured claim stands with no model called.

### 5. Never overstate what compilation proves

- It proves a *type-level* incompatibility at a *generated* call site against a *generated* client.
- It does not prove production breakage, runtime behaviour, or that a clean compile is safe.
- The corpus is **synthetic call sites against real vendor specs**. Never call it real production
  code.

### 6. The kill criterion is fixed

≥60 compiler-verified call-site **breakages** across ≥3 vendors, read at its strictest. It is not
lowered, reinterpreted, or replaced with a looser count after results are seen. Both the strict and
the total counts are published.

### 7. Corpus provenance is mandatory

Every labelled example records vendor, spec file, both revisions with commit SHA and date, source
URL, licence, call-site location, language, the change applied, the expected result and the observed
result. A label without provenance is not a label.

### 8. Secrets

Never commit credentials. `.env.example` carries names and placeholders only. The core pipeline needs
no credential of any kind.

### 9. Attribution

Never add `Co-Authored-By`, `Generated with…`, or any similar marker — in code, commits, docs or
repository metadata. Use the Git identity already configured on the machine.

### 10. Honesty

Never describe functionality that does not exist. Every number in the README comes from a committed
script and is reproducible by a reader with `make`.

---

## Layout

```
src/callsite_impact/
  corpus/      vendor acquisition, provenance manifests, spec pair selection
  specdiff/    oasdiff invocation and the typed change model
  generate/    call-site generation from revision A
  oracle/      tsc invocation and label extraction        <- ground truth, quarantined
  classify/    the system under test                       <- must not import oracle
  evaluate/    scorer, baselines, metrics
  api.py       read-only FastAPI over committed artifacts
harness/       the TypeScript workspace tsc runs in
corpus/        vendored specs + manifests (provenance)
artifacts/     committed run outputs the README and UI read
frontend/      Next.js console
```

---

## Key commands

```bash
uv sync --frozen            # install exactly what uv.lock pins
make gate                   # the full local gate, in the order CI runs it
make corpus                 # acquire and verify the vendor corpus
make killtest               # THE MEASUREMENT: oracle + system + baselines
make api                    # serve the read-only API
```

---

## Conventions

- Python 3.12, typed throughout, Pydantic v2 at every boundary, ruff (100 cols), mypy strict.
- TypeScript only inside `harness/` and `frontend/`. `src/` never imports from `harness/`.
- Conventional commits: `feat:`, `fix:`, `test:`, `docs:`, `chore:`, `refactor:`.
