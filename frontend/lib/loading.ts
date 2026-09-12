/**
 * The vocabulary for "the data did not arrive", kept out of `lib/source.ts`.
 *
 * `source.ts` imports `server-only`, so anything that module owns is unimportable from a client
 * component — including its types, which a bundler is not obliged to erase before it evaluates the
 * import. The failure *shape* has to cross that line, because the components that render a missing
 * artifact are interactive and the server passes them the failure as a prop. So the shape lives
 * here, where both sides may have it, and the base URL stays where only the server can reach it.
 */

export type SourceKind = "api" | "disk";

export type LoadFailure =
  | { kind: "missing_evaluation"; message: string }
  | { kind: "missing_detail"; message: string }
  | { kind: "not_found"; message: string }
  | { kind: "unreachable"; message: string }
  | { kind: "timeout"; message: string }
  | { kind: "upstream"; message: string }
  | { kind: "malformed"; message: string };

export type Loaded<T> =
  | { ok: true; data: T; source: SourceKind }
  | { ok: false; error: LoadFailure };

/**
 * What a reader has to run to make a missing artifact exist.
 *
 * Quoted verbatim on every empty state. "No data" tells someone looking at a fresh checkout
 * nothing they can act on; this is the command, and it is the same command the API's own 503 hint
 * gives, so the two sources cannot tell a reader different things.
 */
export const RUN_COMMAND = "make corpus && make killtest";

/** A missing artifact is an empty state. Everything else is an error state. */
export function isMissingArtifact(error: LoadFailure): boolean {
  return error.kind === "missing_evaluation" || error.kind === "missing_detail";
}
