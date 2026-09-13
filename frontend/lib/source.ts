import "server-only";

import { promises as fs } from "node:fs";
import path from "node:path";

import type { Loaded, LoadFailure, SourceKind } from "@/lib/loading";
import { RUN_COMMAND } from "@/lib/loading";
import type {
  PairDetail,
  PairIndex,
  PairSummary,
  ProvenanceBundle,
  Summary,
} from "@/lib/types";

export type { Loaded, LoadFailure, SourceKind };
export { RUN_COMMAND };

/**
 * The only module that reads `IMPACT_API_BASE_URL`, and the only module that touches the disk.
 *
 * `server-only` is imported above so that importing this from a client component is a build error
 * rather than a base URL quietly compiled into browser JavaScript. Every page that needs data is a
 * server component and calls a loader here; the interactive parts receive the result as props and
 * never learn where it came from.
 *
 * **Disk is the primary path, not the fallback of last resort.** With `IMPACT_API_BASE_URL` unset
 * the console reads the two committed artifacts directly, which is how a fresh checkout and the
 * deployed static demo both work — no API process, no network. The API path exists for local work
 * against `make api` and is strictly optional.
 *
 * Nothing here computes a figure. Each loader returns the bytes the artifact holds, sliced to the
 * shape one screen needs; a number that is not in the file is not available to the console at all.
 */

const REQUEST_TIMEOUT_MS = 8_000;

/** The two file names, fixed by `measure.py` and `write_detail`. */
const EVALUATION_FILE = "evaluation.json";
const DETAIL_FILE = "findings.json";
const HOLDOUT_FILE = "holdout.json";

function apiBase(): string | null {
  const raw = process.env.IMPACT_API_BASE_URL?.trim();
  if (!raw) {
    return null;
  }
  return raw.replace(/\/+$/, "");
}

/**
 * Where the committed artifacts live, tried in order.
 *
 * `<cwd>/artifacts` first so a deployment that copied them next to the app (see
 * `scripts/copy-artifacts.mjs`) wins; `<cwd>/../artifacts` second, which is the repository's own
 * `artifacts/` when the console is run from `frontend/`.
 */
function artifactCandidates(name: string): string[] {
  const cwd = process.cwd();
  return [path.join(cwd, "artifacts", name), path.join(cwd, "..", "artifacts", name)];
}

async function readJsonFile(name: string): Promise<
  { found: true; value: unknown } | { found: false } | { malformed: true; message: string }
> {
  for (const candidate of artifactCandidates(name)) {
    let text: string;
    try {
      text = await fs.readFile(candidate, "utf8");
    } catch {
      continue;
    }
    try {
      return { found: true, value: JSON.parse(text) as unknown };
    } catch {
      return { malformed: true, message: `${candidate} is not valid JSON.` };
    }
  }
  return { found: false };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * A shallow presence check, not a schema validator.
 *
 * Its job is to turn a truncated or half-written artifact into a described failure rather than a
 * page that renders `undefined` where a rate belongs. Validating every leaf would duplicate the
 * Pydantic models in a second language, which is the kind of duplication that drifts.
 */
function hasKeys(value: unknown, keys: string[]): value is Record<string, unknown> {
  return isRecord(value) && keys.every((key) => key in value);
}

const MISSING_EVALUATION: LoadFailure = {
  kind: "missing_evaluation",
  message: `No evaluation artifact. Run \`${RUN_COMMAND}\` and commit artifacts/.`,
};

const MISSING_DETAIL: LoadFailure = {
  kind: "missing_detail",
  message: `No per-call-site artifact. Run \`${RUN_COMMAND}\` and commit artifacts/.`,
};

// ------------------------------------------------------------------------------------- API path

async function fetchApi(
  base: string,
  route: string,
  missing: LoadFailure,
): Promise<{ ok: true; value: unknown } | { ok: false; error: LoadFailure }> {
  let response: Response;
  try {
    response = await fetch(`${base}${route}`, {
      cache: "no-store",
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (cause) {
    const timedOut = cause instanceof DOMException && cause.name === "TimeoutError";
    return {
      ok: false,
      error: timedOut
        ? {
            kind: "timeout",
            message: `The API did not answer within ${REQUEST_TIMEOUT_MS / 1000} seconds.`,
          }
        : { kind: "unreachable", message: "The API is not reachable from the console." },
    };
  }

  // 503 is how the API says "the artifact is not there", and it means the same thing to a reader
  // as an absent file: run the measurement. It is mapped onto the same empty state, not onto a
  // generic outage banner that would send them looking at the network instead.
  if (response.status === 503) {
    return { ok: false, error: missing };
  }
  if (response.status === 404) {
    return { ok: false, error: { kind: "not_found", message: "The API has no such pair." } };
  }
  if (!response.ok) {
    return {
      ok: false,
      error: { kind: "upstream", message: `The API answered ${response.status}.` },
    };
  }

  try {
    return { ok: true, value: (await response.json()) as unknown };
  } catch {
    return {
      ok: false,
      error: { kind: "malformed", message: "The API answered with something that is not JSON." },
    };
  }
}

// ------------------------------------------------------------------------------------- loaders

const SUMMARY_KEYS = [
  "generated_at",
  "run",
  "kill_criterion",
  "system",
  "baseline_touches_changed_operation",
  "baseline_err_level_only",
];

/** The front page's block: corpus counts, the kill criterion, the system and both baselines. */
export async function loadSummary(): Promise<Loaded<Summary>> {
  const base = apiBase();
  if (base !== null) {
    const result = await fetchApi(base, "/api/v1/summary", MISSING_EVALUATION);
    if (!result.ok) {
      return { ok: false, error: result.error };
    }
    if (!hasKeys(result.value, SUMMARY_KEYS)) {
      return {
        ok: false,
        error: { kind: "malformed", message: "The API's summary is missing required fields." },
      };
    }
    return { ok: true, data: result.value as unknown as Summary, source: "api" };
  }

  const file = await readJsonFile(EVALUATION_FILE);
  if ("malformed" in file) {
    return { ok: false, error: { kind: "malformed", message: file.message } };
  }
  if (!file.found) {
    return { ok: false, error: MISSING_EVALUATION };
  }
  if (!hasKeys(file.value, [...SUMMARY_KEYS, "total_compiler_labels", "unclassified_changes"])) {
    return {
      ok: false,
      error: { kind: "malformed", message: `${EVALUATION_FILE} is missing required fields.` },
    };
  }
  return { ok: true, data: file.value as unknown as Summary, source: "disk" };
}

/**
 * The confirmatory slice, when one has been measured.
 *
 * Read from disk only, and optional. It is a second scored corpus rather than a view of the first,
 * so the API — which serves one artifact — has nothing to return for it. Absent is a legitimate
 * state: a checkout that has not run the slice still renders a console, it just does not claim a
 * generalisation estimate it does not have.
 */
export async function loadHoldout(): Promise<Summary | null> {
  const file = await readJsonFile(HOLDOUT_FILE);
  if ("malformed" in file || !file.found) {
    return null;
  }
  if (!hasKeys(file.value, [...SUMMARY_KEYS])) {
    return null;
  }
  return file.value as unknown as Summary;
}

/** Every spec, with the checksums a reader can verify the bytes against. */
export async function loadProvenance(): Promise<Loaded<ProvenanceBundle>> {
  const base = apiBase();
  if (base !== null) {
    const result = await fetchApi(base, "/api/v1/provenance", MISSING_EVALUATION);
    if (!result.ok) {
      return { ok: false, error: result.error };
    }
    if (!hasKeys(result.value, ["pairs", "per_pair"])) {
      return {
        ok: false,
        error: { kind: "malformed", message: "The API's provenance is missing required fields." },
      };
    }
    return { ok: true, data: result.value as unknown as ProvenanceBundle, source: "api" };
  }

  const file = await readJsonFile(EVALUATION_FILE);
  if ("malformed" in file) {
    return { ok: false, error: { kind: "malformed", message: file.message } };
  }
  if (!file.found) {
    return { ok: false, error: MISSING_EVALUATION };
  }
  if (!hasKeys(file.value, ["provenance", "per_pair"])) {
    return {
      ok: false,
      error: { kind: "malformed", message: `${EVALUATION_FILE} is missing its provenance block.` },
    };
  }
  return {
    ok: true,
    data: {
      pairs: file.value["provenance"] as PairProvenanceList,
      per_pair: file.value["per_pair"] as ProvenanceBundle["per_pair"],
    },
    source: "disk",
  };
}

type PairProvenanceList = ProvenanceBundle["pairs"];

const PAIR_HEAVY_KEYS = new Set(["callsites", "changes_shown"]);

function stripHeavy(pair: Record<string, unknown>): PairSummary {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(pair)) {
    if (!PAIR_HEAVY_KEYS.has(key)) {
      out[key] = value;
    }
  }
  return out as unknown as PairSummary;
}

/** The pair index, plus the artifact's own sentence about how its call sites were sampled. */
export async function loadPairIndex(): Promise<Loaded<PairIndex>> {
  const base = apiBase();
  if (base !== null) {
    const result = await fetchApi(base, "/api/v1/pairs", MISSING_DETAIL);
    if (!result.ok) {
      return { ok: false, error: result.error };
    }
    if (!hasKeys(result.value, ["sampling", "pairs"])) {
      return {
        ok: false,
        error: { kind: "malformed", message: "The API's pair index is missing required fields." },
      };
    }
    return { ok: true, data: result.value as unknown as PairIndex, source: "api" };
  }

  const file = await readJsonFile(DETAIL_FILE);
  if ("malformed" in file) {
    return { ok: false, error: { kind: "malformed", message: file.message } };
  }
  if (!file.found) {
    return { ok: false, error: MISSING_DETAIL };
  }
  if (!hasKeys(file.value, ["sampling", "pairs"]) || !Array.isArray(file.value["pairs"])) {
    return {
      ok: false,
      error: { kind: "malformed", message: `${DETAIL_FILE} is missing required fields.` },
    };
  }
  return {
    ok: true,
    data: {
      sampling: String(file.value["sampling"]),
      pairs: (file.value["pairs"] as unknown[]).filter(isRecord).map(stripHeavy),
    },
    source: "disk",
  };
}

/** One pair in full: its changes, its call sites, and every side of the question about each. */
export async function loadPairDetail(pairId: string): Promise<Loaded<PairDetail>> {
  const base = apiBase();
  if (base !== null) {
    const result = await fetchApi(
      base,
      `/api/v1/pairs/${encodeURIComponent(pairId)}`,
      MISSING_DETAIL,
    );
    if (!result.ok) {
      return { ok: false, error: result.error };
    }
    if (!hasKeys(result.value, ["pair_id", "callsites", "changes_shown"])) {
      return {
        ok: false,
        error: { kind: "malformed", message: "The API's pair detail is missing required fields." },
      };
    }
    return { ok: true, data: result.value as unknown as PairDetail, source: "api" };
  }

  const file = await readJsonFile(DETAIL_FILE);
  if ("malformed" in file) {
    return { ok: false, error: { kind: "malformed", message: file.message } };
  }
  if (!file.found) {
    return { ok: false, error: MISSING_DETAIL };
  }
  if (!hasKeys(file.value, ["pairs"]) || !Array.isArray(file.value["pairs"])) {
    return {
      ok: false,
      error: { kind: "malformed", message: `${DETAIL_FILE} is missing required fields.` },
    };
  }
  for (const entry of file.value["pairs"] as unknown[]) {
    if (isRecord(entry) && entry["pair_id"] === pairId) {
      return { ok: true, data: entry as unknown as PairDetail, source: "disk" };
    }
  }
  return {
    ok: false,
    error: { kind: "not_found", message: `No pair \`${pairId}\` in ${DETAIL_FILE}.` },
  };
}

/** Which pairs exist, for `generateStaticParams`. Absent artifacts yield an empty list. */
export async function knownPairIds(): Promise<string[]> {
  const index = await loadPairIndex();
  return index.ok ? index.data.pairs.map((pair) => pair.pair_id) : [];
}
