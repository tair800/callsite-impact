import Link from "next/link";

import { LoadFailureNotice, NothingHere } from "@/components/states";
import { count, formatDate } from "@/lib/format";
import { loadProvenance } from "@/lib/source";

export const dynamic = "force-dynamic";

/**
 * Every specification this repository read, with the checksum of the bytes it read.
 *
 * CLAUDE.md rule 7 makes provenance mandatory: a label without it is not a label. This screen is
 * where that is cashed out for a reader — vendor, service, both revisions, both dates, both
 * sha256 digests, the source URL and the licence, per pair. The digests are shown in full rather
 * than truncated, because a checksum a reader cannot copy is a checksum a reader cannot check.
 */
export default async function ProvenancePage(): Promise<React.ReactElement> {
  const provenance = await loadProvenance();

  return (
    <div className="space-y-4">
      <div className="px-1">
        <h1 className="text-[17px] font-bold tracking-tight text-[var(--color-text)]">
          Provenance
        </h1>
        <p className="mt-1 max-w-[86ch] text-[12.5px] text-[var(--color-muted)]">
          The specifications are public and the digests below are over the exact bytes the
          measurement ran against. Fetch a file from its source, hash it, and compare — a corpus
          that cannot prove which bytes it read is a corpus whose numbers cannot be checked.
        </p>
      </div>

      {!provenance.ok ? (
        <LoadFailureNotice error={provenance.error} />
      ) : provenance.data.pairs.length === 0 ? (
        <NothingHere what="specifications" />
      ) : (
        <>
          {provenance.data.pairs.map((pair) => {
            const counts = provenance.data.per_pair.find(
              (entry) => entry.pair_id === pair.pair_id,
            );
            return (
              <section key={pair.pair_id} className="panel" data-testid="provenance-pair">
                <div className="panel-head flex flex-wrap items-center gap-3 rounded-t-[5px] px-4 py-2">
                  <h2 className="text-[12.5px] font-bold text-[var(--color-text)]">
                    {pair.vendor} · {pair.service}
                  </h2>
                  <code className="mono text-[11px] text-[var(--color-dim)]">{pair.pair_id}</code>
                  <Link
                    href={`/pairs/${encodeURIComponent(pair.pair_id)}`}
                    className="btn ml-auto inline-block"
                  >
                    call sites
                  </Link>
                </div>

                <div className="overflow-x-auto">
                  <table className="grid-table">
                    <thead>
                      <tr>
                        <th scope="col">Revision</th>
                        <th scope="col">Identifier</th>
                        <th scope="col">Date</th>
                        <th scope="col">sha256</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td className="text-[var(--color-muted)]">before</td>
                        <td className="mono">{pair.before_revision}</td>
                        <td className="mono text-[var(--color-dim)]">
                          {formatDate(pair.before_date)}
                        </td>
                        <td className="mono break-all text-[10.5px]">{pair.before_sha256}</td>
                      </tr>
                      <tr>
                        <td className="text-[var(--color-muted)]">after</td>
                        <td className="mono">{pair.after_revision}</td>
                        <td className="mono text-[var(--color-dim)]">
                          {formatDate(pair.after_date)}
                        </td>
                        <td className="mono break-all text-[10.5px]">{pair.after_sha256}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                <div className="flex flex-wrap gap-x-6 gap-y-1 border-t border-[var(--color-line)] px-4 py-2.5 text-[11.5px] text-[var(--color-muted)]">
                  <span>
                    licence: <span className="mono text-[var(--color-text)]">{pair.licence}</span>
                  </span>
                  <span className="break-all">
                    source:{" "}
                    <a
                      href={pair.source_url}
                      rel="noreferrer noopener"
                      target="_blank"
                      className="mono text-[var(--color-accent)] underline underline-offset-2"
                    >
                      {pair.source_url}
                    </a>
                  </span>
                  {counts ? (
                    <>
                      <span title="Call sites admitted for this pair.">
                        admitted: <span className="mono">{count(counts.callsites_admitted)}</span>
                      </span>
                      <span title="Call sites tsc errored on. The strict kill-criterion count for this pair.">
                        breakages: <span className="mono">{count(counts.breakage_callsites)}</span>
                      </span>
                      <span title="Individual tsc diagnostics. Never used as the kill-criterion count.">
                        labels: <span className="mono">{count(counts.compiler_labels)}</span>
                      </span>
                      <span title="(call site x change) pairs the system considered.">
                        candidate pairs:{" "}
                        <span className="mono">{count(counts.candidate_pairs)}</span>
                      </span>
                    </>
                  ) : null}
                </div>
              </section>
            );
          })}
        </>
      )}
    </div>
  );
}
