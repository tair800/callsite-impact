import Link from "next/link";

import { LoadFailureNotice, NothingHere } from "@/components/states";
import { count } from "@/lib/format";
import { loadPairIndex } from "@/lib/source";

export const dynamic = "force-dynamic";

/** The pairs the detail artifact carries. One click from here to the two-minute story. */
export default async function PairsPage(): Promise<React.ReactElement> {
  const index = await loadPairIndex();

  return (
    <div className="space-y-4">
      <div className="px-1">
        <h1 className="text-[17px] font-bold tracking-tight text-[var(--color-text)]">
          Spec pairs
        </h1>
        <p className="mt-1 max-w-[86ch] text-[12.5px] text-[var(--color-muted)]">
          Two revisions of one public specification, the changes a differ found between them, and
          the generated call sites the compiler then ruled on.
        </p>
      </div>

      {!index.ok ? (
        <LoadFailureNotice error={index.error} />
      ) : index.data.pairs.length === 0 ? (
        <NothingHere what="spec pairs" />
      ) : (
        <>
          <section className="panel">
            <div className="overflow-x-auto">
              <table className="grid-table">
                <thead>
                  <tr>
                    <th scope="col">Pair</th>
                    <th scope="col">Vendor</th>
                    <th scope="col">Service</th>
                    <th scope="col">Revisions</th>
                    <th scope="col" className="num">
                      Changes
                    </th>
                    <th scope="col" className="num">
                      Admitted
                    </th>
                    <th scope="col" className="num" title="Call sites tsc broke.">
                      Broken
                    </th>
                    <th scope="col" />
                  </tr>
                </thead>
                <tbody>
                  {index.data.pairs.map((pair) => (
                    <tr key={pair.pair_id}>
                      <td className="mono">{pair.pair_id}</td>
                      <td>{pair.vendor}</td>
                      <td className="text-[var(--color-muted)]">{pair.service}</td>
                      <td className="mono text-[11px] text-[var(--color-muted)]">
                        {pair.before_revision} → {pair.after_revision}
                      </td>
                      <td className="num mono">{count(pair.changes_total)}</td>
                      <td className="num mono">{count(pair.callsites_admitted)}</td>
                      <td className="num mono">{count(pair.callsites_broken)}</td>
                      <td className="num">
                        <Link
                          href={`/pairs/${encodeURIComponent(pair.pair_id)}`}
                          className="btn inline-block"
                        >
                          open
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <p className="px-1 text-[11.5px] text-[var(--color-dim)]">{index.data.sampling}</p>
        </>
      )}
    </div>
  );
}
