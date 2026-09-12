# callsite-impact console

A read-only operator console over the two committed artifacts. It exists so that a visitor can see,
in under two minutes, that the compiler and the predictor are two different things and that the
naive baseline over-reports.

```bash
npm install
npm run dev            # http://localhost:3000
npm run typecheck      # tsc --noEmit
npm test               # vitest run
npm run build
```

## Where the data comes from

Two sources, in this order:

1. **`IMPACT_API_BASE_URL` is set** — the console reads the read-only API (`make api` in the
   repository root) through `/api/v1/summary`, `/api/v1/provenance`, `/api/v1/pairs` and
   `/api/v1/pairs/{id}`.
2. **It is unset** — the console reads the committed artifacts directly from
   `artifacts/evaluation.json` and `artifacts/findings.json`, looking in `./artifacts` first and
   then `../artifacts`.

The second is the **primary path**, not a degraded one: it is how a fresh checkout works and how the
deployed demo works, with no API process and no network. Nothing about the console requires the API
to exist.

If neither source has an artifact, every screen renders an empty state naming the absent file and
the command that produces it — `make corpus && make killtest`. The console never falls back to
sample data; a fabricated result on a page whose whole subject is measurement would be the worst
thing it could do.

## The API base URL is server-side only

`IMPACT_API_BASE_URL` is read in exactly one module, `lib/source.ts`, which imports `server-only`.
Every page that loads data is a server component; the interactive components receive the result as
props and never learn where it came from.

It must never be renamed to `NEXT_PUBLIC_*` and must never be listed under `env` in
`next.config.ts` — either would inline the address into the browser bundle. `lib/loading.ts` exists
so that the *failure shape* can cross into client components without dragging `server-only` with it.

`frontend/.env.example` names that one variable and nothing else. It is not a credential; the core
pipeline needs none.

## Screens

| Route | What it shows |
|---|---|
| `/` | The kill criterion (PASSED/FAILED), the system against both predeclared baselines in the strict and abstaining views, the corpus counts, and what compiler verification does and does not prove. |
| `/pairs` | The spec pairs the detail artifact carries. |
| `/pairs/[pairId]` | One pair: provenance, the changes the differ reported with their expressibility, and every sampled call site with the compiler's verdict beside the system's and the baseline's. Filterable to the rows where a predictor disagrees with the compiler. |
| `/provenance` | Every specification with both revisions, both dates and both sha256 digests, in full, so a reader can verify the bytes. |

## Rules this console is built to

- **UNKNOWN is a first-class verdict.** It means the TypeScript type system cannot express the
  change class, so no call site could be made to fail on it and a clean compile is not evidence of
  safety. It has its own colour — neither red nor green, and deliberately not amber — and a tooltip
  on every instance saying it is not a miss and not a soft IMPACTED.
- **Both scoring views are always reachable.** ADR-001 computes a strict and an abstaining reading
  for every scope and offers no way to publish one without the other. The toggle is the primary
  control on the comparison table, the sentence explaining the difference is on screen in both, and
  the abstaining view discloses how many call sites it excluded to get its better numbers.
- **No figure is computed in the browser.** Every number rendered is a field of a committed
  artifact, formatted. A rate the scorer recorded as `null` — an empty denominator, which is an
  absent measurement and not a zero — renders as an em dash. A metric that does not exist in the
  artifact does not exist here; it belongs in `evaluate/scorer.py`.
- **A failed kill test is the loudest thing on the page.** `passed` is read from the artifact, not
  re-derived.

## Deployment

The build root is `frontend/`, which is above the repository's `artifacts/` directory, so
`npm run artifacts` copies the two JSON files next to the app before `next build`. `vercel.json`
chains them. The copy is a no-op when the artifacts are absent — a checkout without a measurement
still produces a console, one that shows the empty state.

`frontend/artifacts/` is git-ignored: the committed copy lives at the repository root and a second
one would be a second source of truth.

## Tests

`vitest run`, jsdom, Testing Library. The suite covers the verdict chip in all three states, the
disagreement filter (including that an abstention on a clean call site is *not* a disagreement,
mirroring `scorer._view`), the strict/abstaining toggle, the kill-criterion panel in both outcomes,
and the missing-artifact empty state. Fixtures live in `tests/fixtures.ts`, are clearly marked as
invented, and are imported by nothing outside `tests/`.
