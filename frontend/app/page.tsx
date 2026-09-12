import Link from "next/link";

import { CorpusStrip } from "@/components/CorpusStrip";
import { KillCriterionPanel } from "@/components/KillCriterionPanel";
import { MetricsComparison } from "@/components/MetricsComparison";
import { LoadFailureNotice } from "@/components/states";
import { WhatThisProves } from "@/components/WhatThisProves";
import { ratePercent } from "@/lib/format";
import { loadSummary } from "@/lib/source";

/**
 * The result, in the order ADR-001 puts it: the kill criterion, then the comparison, then the
 * corpus, then what the measurement means.
 *
 * Rendered per request rather than baked at build time. The artifact is a committed file that
 * appears when someone runs the measurement, and a page prerendered against its absence would go
 * on showing the empty state after the file arrived.
 */
export const dynamic = "force-dynamic";

export default async function ResultPage(): Promise<React.ReactElement> {
  const summary = await loadSummary();

  if (!summary.ok) {
    return (
      <div className="space-y-4">
        <PageHead />
        <LoadFailureNotice error={summary.error} />
      </div>
    );
  }

  const { data } = summary;

  return (
    <div className="space-y-4">
      <PageHead />

      <KillCriterionPanel criterion={data.kill_criterion} />

      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 px-1">
        <span className="text-[12.5px] text-[var(--color-muted)]">
          Headline false-negative rate (strict, pooled):{" "}
          <strong className="mono text-[14px] font-bold text-[var(--color-text)]">
            {ratePercent(data.headline_false_negative_rate)}
          </strong>
        </span>
        <span className="text-[12.5px] text-[var(--color-muted)]">
          Abstention rate (pair-level):{" "}
          <strong className="mono text-[14px] font-bold text-[var(--color-text)]">
            {ratePercent(data.abstention_rate)}
          </strong>
        </span>
      </div>

      <MetricsComparison
        system={data.system}
        baselineTouches={data.baseline_touches_changed_operation}
        baselineErr={data.baseline_err_level_only}
      />

      <CorpusStrip summary={data} />

      <WhatThisProves />

      <p className="px-1 pt-1 text-[12px] text-[var(--color-muted)]">
        The rows behind these rates — the actual TypeScript, the compiler diagnostics and the change
        each verdict is anchored to — are under{" "}
        <Link href="/pairs" className="text-[var(--color-accent)] underline underline-offset-2">
          spec pairs
        </Link>
        . The bytes every specification was read from are under{" "}
        <Link href="/provenance" className="text-[var(--color-accent)] underline underline-offset-2">
          provenance
        </Link>
        .
      </p>
    </div>
  );
}

function PageHead(): React.ReactElement {
  return (
    <div className="px-1 pb-1">
      <h1 className="text-[17px] font-bold tracking-tight text-[var(--color-text)]">
        Which call sites does this API revision actually break?
      </h1>
      <p className="mt-1 max-w-[86ch] text-[12.5px] text-[var(--color-muted)]">
        A spec differ compares two documents and knows nothing about your code. This measures the
        gap: the compiler says which generated call sites break, and a classifier that never sees
        compiler output has to predict it from the diff and a parsed read of the source.
      </p>
    </div>
  );
}
