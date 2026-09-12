"use client";

/**
 * The last line of defence.
 *
 * The loaders in `lib/source.ts` turn every expected failure into a described result, so anything
 * that reaches here is unexpected. It still gets a calm panel and a retry rather than a stack
 * trace: `error.message` from a server component is redacted in production by Next, and the digest
 * is what a maintainer needs to find the real one in the logs.
 */
export default function ConsoleError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}): React.ReactElement {
  return (
    <div role="alert" className="panel border-[#63232c] px-5 py-5">
      <p className="kicker mb-2 text-[#ff8f9b]">The console failed to render this screen</p>
      <p className="text-[13px] text-[var(--color-text)]">
        Something outside the expected failure set went wrong. No figure is shown, because a
        partially rendered metrics table reads as a result and would not be one.
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
