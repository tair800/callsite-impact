import type { LoadFailure } from "@/lib/loading";
import { isMissingArtifact, RUN_COMMAND } from "@/lib/loading";

/**
 * The three things a screen can show instead of data.
 *
 * The empty state is the one with a rule attached to it. A console that answers a missing artifact
 * with "no data" has told a reader standing in a fresh checkout nothing — the artifacts are
 * *produced*, by a command, and the command is the only useful thing to say. So every empty state
 * here prints `make corpus && make killtest` and says which file is absent.
 */

export function Panel({
  title,
  children,
  right,
}: {
  title: string;
  children: React.ReactNode;
  right?: React.ReactNode;
}): React.ReactElement {
  return (
    <section className="panel">
      <div className="panel-head flex items-center gap-3 rounded-t-[5px] px-4 py-2">
        <h2 className="kicker">{title}</h2>
        {right ? <div className="ml-auto">{right}</div> : null}
      </div>
      <div className="px-4 py-3">{children}</div>
    </section>
  );
}

/** A missing artifact. Names the file and the command, in that order. */
export function ArtifactEmptyState({
  error,
}: {
  error: Extract<LoadFailure, { kind: "missing_evaluation" | "missing_detail" }>;
}): React.ReactElement {
  const file = error.kind === "missing_evaluation" ? "artifacts/evaluation.json" : "artifacts/findings.json";
  return (
    <div
      role="status"
      className="panel px-5 py-6"
      data-testid="artifact-empty-state"
    >
      <p className="kicker mb-2">No measurement in this checkout</p>
      <p className="text-[13px] text-[var(--color-text)]">
        <code className="mono text-[var(--color-accent)]">{file}</code> is not present. The console
        renders committed artifacts and never invents one, so there is nothing to show until the
        measurement has been run.
      </p>
      <p className="mt-3 text-[12px] text-[var(--color-muted)]">Run, from the repository root:</p>
      <pre className="source mt-1.5 inline-block">{RUN_COMMAND}</pre>
      <p className="mt-3 text-[11.5px] text-[var(--color-dim)]">
        The run shells out to <code className="mono">tsc</code> and takes minutes. Commit{" "}
        <code className="mono">artifacts/</code> when it finishes. Alternatively, start the
        read-only API with <code className="mono">make api</code> and point the console at it with{" "}
        <code className="mono">IMPACT_API_BASE_URL</code>.
      </p>
    </div>
  );
}

/** Anything that is not a missing artifact: an unreachable API, a bad status, unparseable bytes. */
export function ErrorPanel({ error }: { error: LoadFailure }): React.ReactElement {
  return (
    <div role="alert" className="panel border-[#63232c] px-5 py-5" data-testid="error-panel">
      <p className="kicker mb-2 text-[#ff8f9b]">Could not load</p>
      <p className="text-[13px] text-[var(--color-text)]">{error.message}</p>
      <p className="mt-3 text-[11.5px] text-[var(--color-dim)]">
        Failure class <code className="mono">{error.kind}</code>. The console shows nothing rather
        than a partial figure: a metrics table missing a row reads as a result, and it is not one.
      </p>
    </div>
  );
}

/** One switch, so no screen can handle a missing artifact and an outage the same way by accident. */
export function LoadFailureNotice({ error }: { error: LoadFailure }): React.ReactElement {
  if (isMissingArtifact(error)) {
    return (
      <ArtifactEmptyState
        error={error as Extract<LoadFailure, { kind: "missing_evaluation" | "missing_detail" }>}
      />
    );
  }
  return <ErrorPanel error={error} />;
}

/** A present-but-empty collection. Distinct from a missing artifact and must stay distinct. */
export function NothingHere({ what }: { what: string }): React.ReactElement {
  return (
    <p role="status" className="px-1 py-6 text-[12.5px] text-[var(--color-muted)]">
      The artifact was read and contains no {what}.
    </p>
  );
}

export function SkeletonRows({ rows = 5 }: { rows?: number }): React.ReactElement {
  return (
    <div role="status" aria-label="Loading" className="space-y-2 py-2">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="skeleton h-5 w-full" />
      ))}
      <span className="sr-only">Loading</span>
    </div>
  );
}

export function LoadingScreen({ label }: { label: string }): React.ReactElement {
  return (
    <div role="status" aria-live="polite" className="space-y-4">
      <div className="skeleton h-24 w-full" />
      <div className="panel px-4 py-4">
        <p className="kicker mb-3">{label}</p>
        <SkeletonRows rows={6} />
      </div>
    </div>
  );
}
