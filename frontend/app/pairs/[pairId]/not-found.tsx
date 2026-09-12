import Link from "next/link";

import { RUN_COMMAND } from "@/lib/loading";

/**
 * A pair id that the artifact does not contain.
 *
 * Segment-scoped rather than left to the root not-found page, because the two cases a reader hits
 * here are specific: a mistyped id, or an artifact from a different run than the link was made
 * against. Both are worth naming.
 */
export default function PairNotFound(): React.ReactElement {
  return (
    <div className="panel px-5 py-6">
      <p className="kicker mb-2">No such spec pair</p>
      <p className="max-w-[78ch] text-[13px] text-[var(--color-text)]">
        The per-call-site artifact in this checkout lists no pair with that id. Either the id is
        mistyped, or the link was made against a different run than the artifact currently committed
        here — pair ids are stable for a given corpus, not across corpora.
      </p>
      <p className="mt-3 text-[12.5px]">
        <Link href="/pairs" className="text-[var(--color-accent)] underline underline-offset-2">
          See the pairs this artifact does contain
        </Link>
      </p>
      <p className="mt-3 text-[11.5px] text-[var(--color-dim)]">
        To regenerate the corpus and its artifacts, run <code className="mono">{RUN_COMMAND}</code>.
      </p>
    </div>
  );
}
