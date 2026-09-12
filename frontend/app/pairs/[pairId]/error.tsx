"use client";

export default function PairError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}): React.ReactElement {
  return (
    <div role="alert" className="panel border-[#63232c] px-5 py-5">
      <p className="kicker mb-2 text-[#ff8f9b]">This pair could not be rendered</p>
      <p className="text-[13px] text-[var(--color-text)]">
        Something outside the expected failure set went wrong while reading the per-call-site
        artifact. Nothing partial is shown.
      </p>
      {error.digest ? (
        <p className="mt-2 text-[11.5px] text-[var(--color-dim)]">
          digest <code className="mono">{error.digest}</code>
        </p>
      ) : null}
      <button type="button" className="btn mt-4" onClick={reset}>
        Try again
      </button>
    </div>
  );
}
