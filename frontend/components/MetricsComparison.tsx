"use client";

import { useState } from "react";

import { count, ratePercent } from "@/lib/format";
import type { ScopeMetrics, ScoreReport, ViewMetrics } from "@/lib/types";

/**
 * The system against both predeclared baselines, on one corpus and through one scorer.
 *
 * Two things here are requirements rather than layout choices.
 *
 * **Both readings are always reachable.** ADR-001 computes a strict and an abstaining view for
 * every scope and says nothing in the scorer offers a way to publish one without the other. A
 * console that showed only the abstaining view would be publishing the flattering half: a system
 * that abstains on everything it would have got wrong scores perfectly there. The toggle is the
 * whole control, the explanatory sentence is always on screen, and `callsites_excluded_as
 * _abstention` is shown in the abstaining view so the reader can see the denominator it dropped.
 *
 * **Nothing on this table is computed here.** Every cell is a field of `ViewMetrics` or
 * `ScopeMetrics`, formatted. Where the scorer recorded `null` — an empty denominator, which is an
 * absent measurement and not a zero — the cell is an em dash.
 */

type View = "strict" | "abstaining";

const VIEW_NOTE: Record<View, string> = {
  strict:
    "Strict counts an UNKNOWN as a miss wherever the compiler found a breakage: the system did not report a breakage that exists. An UNKNOWN on a clean call site is not counted as a false positive, because a false positive is a call site reported IMPACTED and an abstention is not that.",
  abstaining:
    "Abstaining removes every call site the system abstained on from the confusion matrix entirely. It is the more flattering reading and it is shown with the number of call sites it excluded, because a system that abstains on everything it would have got wrong scores perfectly here.",
};

interface Row {
  key: string;
  label: string;
  note: string;
  report: ScoreReport;
  isSystem: boolean;
}

function scopeOf(report: ScoreReport, scope: string): ScopeMetrics | undefined {
  if (scope === "pooled") {
    return report.pooled;
  }
  return report.by_vendor.find((entry) => entry.scope === scope);
}

function viewOf(metrics: ScopeMetrics | undefined, view: View): ViewMetrics | undefined {
  return metrics?.[view];
}

export function MetricsComparison({
  system,
  baselineTouches,
  baselineErr,
}: {
  system: ScoreReport;
  baselineTouches: ScoreReport;
  baselineErr: ScoreReport;
}): React.ReactElement {
  const [view, setView] = useState<View>("strict");
  const [scope, setScope] = useState<string>("pooled");

  const scopes = ["pooled", ...system.by_vendor.map((entry) => entry.scope)];

  const rows: Row[] = [
    {
      key: "system",
      label: "System",
      note: "Predicts from the spec diff and a parsed read of the call-site source. Never sees compiler output.",
      report: system,
      isSystem: true,
    },
    {
      key: "baseline-touches",
      label: "Baseline · touches changed operation",
      note: "Every call site that touches a changed operation is IMPACTED. What a team does today with a spec differ and grep.",
      report: baselineTouches,
      isSystem: false,
    },
    {
      key: "baseline-err",
      label: "Baseline · ERR-level changes only",
      note: "The same move with the differ's own severity filter on.",
      report: baselineErr,
      isSystem: false,
    },
  ];

  return (
    <section className="panel" data-testid="metrics-comparison">
      <div className="panel-head flex flex-wrap items-center gap-3 rounded-t-[5px] px-4 py-2">
        <h2 className="kicker">System versus both predeclared baselines</h2>
        <div
          className="ml-auto flex items-center gap-1"
          role="group"
          aria-label="Scoring view"
        >
          <span className="mr-1 text-[10.5px] uppercase tracking-wider text-[var(--color-dim)]">
            view
          </span>
          <button
            type="button"
            className="btn"
            aria-pressed={view === "strict"}
            onClick={() => setView("strict")}
          >
            strict
          </button>
          <button
            type="button"
            className="btn"
            aria-pressed={view === "abstaining"}
            onClick={() => setView("abstaining")}
          >
            abstaining
          </button>
        </div>
      </div>

      {scopes.length > 1 ? (
        <div className="flex flex-wrap items-center gap-1 border-b border-[var(--color-line-soft)] px-4 py-2">
          <span className="mr-1 text-[10.5px] uppercase tracking-wider text-[var(--color-dim)]">
            scope
          </span>
          {scopes.map((name) => (
            <button
              key={name}
              type="button"
              className="btn"
              aria-pressed={scope === name}
              onClick={() => setScope(name)}
            >
              {name}
            </button>
          ))}
        </div>
      ) : null}

      <div className="overflow-x-auto">
        <table className="grid-table">
          <caption className="sr-only">
            False-negative rate, false-positive rate, precision, recall and F1 for the system and
            both baselines, in the {view} view, scope {scope}.
          </caption>
          <thead>
            <tr>
              <th scope="col">Predictor</th>
              <th scope="col" className="num col-headline" title="The headline metric of ADR-001.">
                FN rate ↓
              </th>
              <th scope="col" className="num">
                FP rate ↓
              </th>
              <th scope="col" className="num">
                Precision
              </th>
              <th scope="col" className="num">
                Recall
              </th>
              <th scope="col" className="num">
                F1
              </th>
              <th scope="col" className="num" title="True positives">
                TP
              </th>
              <th scope="col" className="num" title="False positives">
                FP
              </th>
              <th scope="col" className="num" title="True negatives">
                TN
              </th>
              <th scope="col" className="num" title="False negatives">
                FN
              </th>
              {view === "abstaining" ? (
                <th
                  scope="col"
                  className="num"
                  title="Call sites dropped from this view because the predictor abstained."
                >
                  Excluded
                </th>
              ) : null}
              <th
                scope="col"
                className="num"
                title="(call site x change) pairs returned UNKNOWN, over all candidate pairs. Pair-level, as ADR-001 defines it."
              >
                Abstention
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const metrics = scopeOf(row.report, scope);
              const cells = viewOf(metrics, view);
              if (!cells || !metrics) {
                return (
                  <tr key={row.key} data-testid={`metrics-row-${row.key}`}>
                    <th scope="row" className="text-left font-semibold">
                      {row.label}
                    </th>
                    <td colSpan={view === "abstaining" ? 11 : 10} className="text-[var(--color-dim)]">
                      Not scored for scope <code className="mono">{scope}</code> in this artifact.
                    </td>
                  </tr>
                );
              }
              return (
                <tr
                  key={row.key}
                  className={row.isSystem ? "row-system" : undefined}
                  data-testid={`metrics-row-${row.key}`}
                >
                  <th scope="row" className="max-w-[280px] text-left font-semibold">
                    <span className={row.isSystem ? "text-[var(--color-text)]" : undefined}>
                      {row.label}
                    </span>
                    {/* The note is prose in a numeric table: without a width it runs under the
                        FN RATE column, which is the one number this table is built around. */}
                    <span className="block max-w-[42ch] text-[10.5px] font-normal normal-case tracking-normal text-[var(--color-dim)]">
                      {row.note}
                    </span>
                  </th>
                  <td className="num col-headline font-bold">
                    {ratePercent(cells.false_negative_rate)}
                  </td>
                  <td className="num">{ratePercent(cells.false_positive_rate)}</td>
                  <td className="num">{ratePercent(cells.precision)}</td>
                  <td className="num">{ratePercent(cells.recall)}</td>
                  <td className="num">{ratePercent(cells.f1)}</td>
                  <td className="num mono">{count(cells.counts.true_positives)}</td>
                  <td className="num mono">{count(cells.counts.false_positives)}</td>
                  <td className="num mono">{count(cells.counts.true_negatives)}</td>
                  <td className="num mono">{count(cells.counts.false_negatives)}</td>
                  {view === "abstaining" ? (
                    <td className="num mono">{count(cells.callsites_excluded_as_abstention)}</td>
                  ) : null}
                  <td className="num">{ratePercent(metrics.abstention_rate)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p
        className="border-t border-[var(--color-line-soft)] px-4 py-3 text-[11.5px] leading-snug text-[var(--color-muted)]"
        data-testid="view-note"
      >
        <strong className="font-semibold text-[var(--color-text)]">{view}:</strong>{" "}
        {VIEW_NOTE[view]}
      </p>
    </section>
  );
}
