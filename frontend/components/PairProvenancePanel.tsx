import { formatDate, shortSha } from "@/lib/format";
import { RUN_COMMAND } from "@/lib/loading";
import type { PairDetail, PairProvenance } from "@/lib/types";

/**
 * Where this pair's two specifications came from.
 *
 * Split across the two artifacts by design, and this component shows the seam honestly rather than
 * hiding it: `findings.json` carries the vendor, the service, the two revisions and the source URL,
 * while the checksums, the revision dates and the licence live only in `evaluation.json`. When the
 * second file is absent the fields it owns say so and name the command, instead of rendering an
 * em dash that a reader could mistake for "this specification has no checksum".
 */
export function PairProvenancePanel({
  pair,
  provenance,
}: {
  pair: PairDetail;
  provenance: PairProvenance | null;
}): React.ReactElement {
  return (
    <section className="panel" data-testid="pair-provenance">
      <div className="panel-head rounded-t-[5px] px-4 py-2">
        <h2 className="kicker">Provenance</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="grid-table">
          <tbody>
            <Row label="Vendor" value={pair.vendor} />
            <Row label="Service" value={pair.service} />
            <Row
              label="Before revision"
              value={pair.before_revision}
              extra={provenance ? formatDate(provenance.before_date) : undefined}
            />
            <Row
              label="After revision"
              value={pair.after_revision}
              extra={provenance ? formatDate(provenance.after_date) : undefined}
            />
            <tr>
              <th scope="row" className="w-[180px] text-left">
                Before sha256
              </th>
              <td className="mono break-all">
                {provenance ? (
                  <span title={provenance.before_sha256}>{shortSha(provenance.before_sha256)}</span>
                ) : (
                  <Absent />
                )}
              </td>
            </tr>
            <tr>
              <th scope="row" className="text-left">
                After sha256
              </th>
              <td className="mono break-all">
                {provenance ? (
                  <span title={provenance.after_sha256}>{shortSha(provenance.after_sha256)}</span>
                ) : (
                  <Absent />
                )}
              </td>
            </tr>
            <tr>
              <th scope="row" className="text-left">
                Source
              </th>
              <td className="mono break-all">
                <a
                  href={pair.source_url}
                  rel="noreferrer noopener"
                  target="_blank"
                  className="text-[var(--color-accent)] underline underline-offset-2"
                >
                  {pair.source_url}
                </a>
              </td>
            </tr>
            <tr>
              <th scope="row" className="text-left">
                Licence
              </th>
              <td className="mono">{provenance ? provenance.licence : <Absent />}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Row({
  label,
  value,
  extra,
}: {
  label: string;
  value: string;
  extra?: string;
}): React.ReactElement {
  return (
    <tr>
      <th scope="row" className="w-[180px] text-left">
        {label}
      </th>
      <td className="mono break-all">
        {value}
        {extra && extra !== "—" ? (
          <span className="ml-2 text-[var(--color-dim)]">{extra}</span>
        ) : null}
      </td>
    </tr>
  );
}

function Absent(): React.ReactElement {
  return (
    <span className="text-[var(--color-dim)]">
      in <code className="mono">artifacts/evaluation.json</code>, which is not present — run{" "}
      <code className="mono">{RUN_COMMAND}</code>
    </span>
  );
}
