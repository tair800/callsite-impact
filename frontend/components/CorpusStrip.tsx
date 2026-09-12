import { count, formatInstant } from "@/lib/format";
import type { Summary } from "@/lib/types";

/**
 * What the run actually consisted of.
 *
 * `callsites_discarded` is on this strip and not tucked into a footnote for a reason: a call site
 * that did not compile clean against revision A is discarded rather than repaired, and the size of
 * that pile is the reader's check on whether the admitted corpus was selected by the generator or
 * by the author.
 *
 * `total_compiler_labels` sits next to the breakage count on purpose. `tsc` can emit several errors
 * on one call site, so the label count is always the larger and more flattering number, and
 * ADR-001 publishes both so the strict reading cannot quietly be swapped for the loose one.
 */

function Figure({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}): React.ReactElement {
  return (
    <div className="px-3 py-2" title={hint}>
      <div className="kicker">{label}</div>
      <div className="mono mt-0.5 text-[15px] font-bold text-[var(--color-text)]">{value}</div>
    </div>
  );
}

export function CorpusStrip({ summary }: { summary: Summary }): React.ReactElement {
  const { run } = summary;
  return (
    <section className="panel" data-testid="corpus-strip">
      <div className="panel-head flex flex-wrap items-center gap-3 rounded-t-[5px] px-4 py-2">
        <h2 className="kicker">The corpus</h2>
        <span className="ml-auto text-[11px] text-[var(--color-dim)]">
          measured {formatInstant(summary.generated_at)}
        </span>
      </div>

      <div className="grid grid-cols-2 divide-x divide-y divide-[var(--color-line-soft)] sm:grid-cols-3 lg:grid-cols-6">
        <Figure label="Spec pairs" value={count(run.pairs)} />
        <Figure label="Vendors" value={count(run.vendors.length)} hint={run.vendors.join(", ")} />
        <Figure
          label="Call sites admitted"
          value={count(run.callsites_admitted)}
          hint="Generated from revision A and typechecked clean against it before admission."
        />
        <Figure
          label="Call sites discarded"
          value={count(run.callsites_discarded)}
          hint="Did not compile clean against revision A. Discarded, never repaired — repairing would let the author choose what breaks."
        />
        <Figure
          label="Compiler breakages"
          value={count(run.compiler_breakages)}
          hint="Distinct call sites on which tsc errored. The strict kill-criterion count."
        />
        <Figure
          label="Compiler clean"
          value={count(run.compiler_clean)}
          hint="Call sites tsc left alone. Not the same as safe."
        />
      </div>

      <div className="flex flex-wrap gap-x-6 gap-y-1 border-t border-[var(--color-line)] px-4 py-2.5 text-[11.5px] text-[var(--color-muted)]">
        <span>
          vendors: <span className="mono text-[var(--color-text)]">{run.vendors.join(", ") || "—"}</span>
        </span>
        <span title="Generated before admission, including the ones that were discarded.">
          generated: <span className="mono">{count(run.callsites_generated)}</span>
        </span>
        <span title="(call site x change) pairs the predictor considered.">
          candidate findings: <span className="mono">{count(run.candidate_findings)}</span>
        </span>
        <span title="Individual tsc diagnostics. Always at least the breakage count, and never used as the kill-criterion number.">
          compiler labels: <span className="mono">{count(summary.total_compiler_labels)}</span>
        </span>
        <span title="Changes of a class this repository has not ruled on. They fail towards abstention.">
          unclassified changes: <span className="mono">{count(summary.unclassified_changes)}</span>
        </span>
      </div>
    </section>
  );
}
