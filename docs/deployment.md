# Deployment

## The shape, and why it is this small

The public demonstration is **one static site on Vercel and nothing else**. No API service, no
database, no cache, no scheduled job.

That is not a corner cut for the demo — it is what this project actually is. The measurement is a
batch job: it clones vendor specifications, generates types with `openapi-typescript`, generates call
sites, runs `tsc` several times per spec pair and writes two JSON files. It takes minutes and it
needs a compiler on disk. The console renders those two files.

So the only question worth asking is where the JSON comes from, and there are two honest answers:

| Option | What it costs | What it buys |
|---|---|---|
| Read the committed artifacts at build time | nothing | the numbers on the site are the numbers CI verified on that commit |
| Run a service that serves them | a free instance that sleeps, ~50 s to wake | the same numbers, later |

The first one wins on every axis, so there is no backend in the deployment. **A service exists in the
repository** — `callsite_impact.api`, a read-only FastAPI over the same two files, runnable with
`make api` — and it is **not deployed**, because deploying it would add a cold start to a page that
does not need one. It is there because the console's data access has to come from somewhere during
development and because the read-only boundary is worth showing in code; it is not there to make the
architecture diagram longer.

There is no database. There is no vector index. There is nothing to connect to, and
`src/callsite_impact/config.py` carries no setting for a connection, so nothing can drift into one.

## The public console

| Layer | Service | Plan | Region |
|---|---|---|---|
| Console | Vercel | Hobby | `fra1` |

**Root directory: `frontend`.** The repository root is a Python project; Vercel must be pointed at
the Next.js app or it will fail to detect a framework.

**Environment variables: none required.** `IMPACT_API_BASE_URL` is read server-side when set, and
when it is unset the console reads `artifacts/evaluation.json` and `artifacts/findings.json` from the
checkout. The deployed site runs on the second path. The variable is deliberately **not** prefixed
`NEXT_PUBLIC_`: it is read in server components and route handlers only, so no API address reaches
the browser.

## What CI guarantees about the numbers on the site

The site renders committed artifacts, so the artifacts have to be trustworthy on their own. CI
re-runs the whole measurement on every push and then does two things:

1. compares the freshly measured artifact against the committed one **field by field, ignoring
   `generated_at`** — a byte comparison would fail on every run, and a check that always fails is a
   check everyone learns to skip;
2. re-checks the predeclared kill criterion and fails the build if it is not met.

So a commit whose code changes the measurement cannot merge while the published numbers still
describe the old code. That is the whole reason the artifact is committed rather than fetched.

## Reproducing the measurement locally

```bash
make install        # uv sync --frozen, then npm ci in harness/
make corpus         # clone/fetch the pinned vendor specs (network; MIT only)
make killtest       # generate, admit, compile, classify, score
```

`make corpus` needs `oasdiff` on `PATH`:

```bash
go install github.com/oasdiff/oasdiff@v1.29.1
```

The corpus is **not committed**. The upstream specifications are MIT-licensed and therefore
redistributable, but they are between 1 MB and 8 MB each and adding ~100 MB of vendor JSON to a
portfolio repository buys nothing a pinned revision plus a checksum does not. `corpus/manifest.json`
**is** committed, and it records for every specification the vendor, the exact revision, the source
URL, the licence and the SHA-256 of the bytes used — which is what makes a run checkable.

## Free-tier limitations, stated rather than hidden

- A static Vercel site has no cold start and no instance to sleep, so the usual free-tier caveat does
  not apply here. That is a consequence of having no backend, not an achievement.
- The measurement does not run in the deployment. It runs in CI and locally. The site is a rendering
  of a result, and the page says so.
