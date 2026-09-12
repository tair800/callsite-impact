"use client";

import { useMemo, useState } from "react";

import { VerdictChip, VerdictTriple } from "@/components/chips";
import { count } from "@/lib/format";
import type { CallsiteDetail } from "@/lib/types";
import { disagreesWithCompiler } from "@/lib/verdicts";

/**
 * The call sites, with all three answers side by side and a way to get to the ones that differ.
 *
 * The rows where the compiler and a predictor disagree are the entire point of the project, and a
 * reader should not have to scroll a hundred agreeing rows to find them — so the filters are the
 * primary control here, not a refinement. `disagreesWithCompiler` mirrors the strict confusion
 * matrix in `scorer.py` exactly, so "system ≠ compiler" selects precisely the rows that the
 * published false-negative and false-positive counts were computed over.
 *
 * Abstentions get a filter of their own. An UNKNOWN is not a wrong answer and does not belong in
 * the disagreement bucket by default; a reader who wants to see what the type system could not
 * decide asks for it directly.
 */

type Filter = "all" | "breakages" | "system-disagrees" | "baseline-disagrees" | "system-unknown";

const FILTERS: { key: Filter; label: string; title: string }[] = [
  { key: "all", label: "all", title: "Every call site in the sample." },
  {
    key: "breakages",
    label: "compiler breakages",
    title: "Call sites on which tsc emitted at least one error. Truth, not a prediction.",
  },
  {
    key: "system-disagrees",
    label: "system ≠ compiler",
    title:
      "The compiler broke it and the system did not say IMPACTED, or the compiler left it clean and the system said IMPACTED. The strict reading, matching the published counts.",
  },
  {
    key: "baseline-disagrees",
    label: "baseline ≠ compiler",
    title: "The same test applied to the naive baseline. This is where the over-reporting shows.",
  },
  {
    key: "system-unknown",
    label: "system abstained",
    title:
      "The system returned UNKNOWN: the change is of a class the type system cannot express. Not a miss and not a soft IMPACTED.",
  },
];

function matches(filter: Filter, row: CallsiteDetail): boolean {
  switch (filter) {
    case "all":
      return true;
    case "breakages":
      return row.truth === "impacted";
    case "system-disagrees":
      return disagreesWithCompiler(row.truth, row.system);
    case "baseline-disagrees":
      return disagreesWithCompiler(row.truth, row.baseline);
    case "system-unknown":
      return row.system === "unknown";
  }
}

export function CallsiteTable({
  callsites,
  cleanOmitted,
  sampling,
}: {
  callsites: CallsiteDetail[];
  cleanOmitted: number;
  sampling: string;
}): React.ReactElement {
  const [filter, setFilter] = useState<Filter>("all");
  const [expanded, setExpanded] = useState<string | null>(null);

  const rows = useMemo(
    () => callsites.filter((row) => matches(filter, row)),
    [callsites, filter],
  );

  return (
    <section className="panel" data-testid="callsite-table">
      <div className="panel-head flex flex-wrap items-center gap-3 rounded-t-[5px] px-4 py-2">
        <h2 className="kicker">Call sites</h2>
        <div className="ml-auto flex flex-wrap items-center gap-1" role="group" aria-label="Filter call sites">
          {FILTERS.map((entry) => (
            <button
              key={entry.key}
              type="button"
              className="btn"
              title={entry.title}
              aria-pressed={filter === entry.key}
              onClick={() => setFilter(entry.key)}
            >
              {entry.label}
            </button>
          ))}
        </div>
      </div>

      <p className="border-b border-[var(--color-line-soft)] px-4 py-2 text-[11.5px] text-[var(--color-muted)]">
        <span data-testid="row-count">
          Showing {count(rows.length)} of {count(callsites.length)} sampled call sites.
        </span>{" "}
        <span className="text-[var(--color-dim)]">{sampling}</span>{" "}
        <span data-testid="clean-omitted" className="text-[var(--color-dim)]">
          {cleanOmitted > 0
            ? `${count(cleanOmitted)} clean call sites from this pair are not shown.`
            : "No clean call sites from this pair were omitted."}
        </span>
      </p>

      {rows.length === 0 ? (
        <p role="status" className="px-4 py-6 text-[12.5px] text-[var(--color-muted)]">
          No call site in this sample matches that filter. The artifact was read; this is a filter
          result, not missing data.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="grid-table">
            <thead>
              <tr>
                <th scope="col">Operation</th>
                <th scope="col" className="num">
                  Line
                </th>
                <th scope="col">Compiler · System · Baseline</th>
                <th scope="col" aria-label="Expand" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const open = expanded === row.callsite_id;
                return (
                  <CallsiteRow
                    key={row.callsite_id}
                    row={row}
                    open={open}
                    onToggle={() => setExpanded(open ? null : row.callsite_id)}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function CallsiteRow({
  row,
  open,
  onToggle,
}: {
  row: CallsiteDetail;
  open: boolean;
  onToggle: () => void;
}): React.ReactElement {
  return (
    <>
      <tr data-testid="callsite-row" data-callsite-id={row.callsite_id}>
        <td className="mono max-w-[320px] truncate" title={row.operation_key}>
          {row.operation_key}
        </td>
        <td className="num mono text-[var(--color-dim)]">{row.line}</td>
        <td>
          <VerdictTriple truth={row.truth} system={row.system} baseline={row.baseline} />
        </td>
        <td className="num">
          <button
            type="button"
            className="btn"
            aria-expanded={open}
            aria-controls={`detail-${row.callsite_id}`}
            onClick={onToggle}
          >
            {open ? "hide" : "evidence"}
          </button>
        </td>
      </tr>
      {open ? (
        <tr id={`detail-${row.callsite_id}`} data-testid="callsite-detail">
          <td colSpan={4} className="bg-[#0d1219] px-4 py-4">
            <CallsiteEvidence row={row} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

function CallsiteEvidence({ row }: { row: CallsiteDetail }): React.ReactElement {
  return (
    <div className="space-y-4">
      <div>
        <p className="kicker mb-1.5">
          Call site <span className="mono normal-case tracking-normal">{row.callsite_id}</span> ·
          generated from revision A, typechecked clean against it
        </p>
        <pre className="source">{row.source}</pre>
      </div>

      <div>
        <p className="kicker mb-1.5">Compiler diagnostics against revision B · ground truth</p>
        {row.compiler.length === 0 ? (
          <p className="text-[12px] text-[var(--color-muted)]">
            <code className="mono">tsc</code> emitted nothing on this call site. A type-level result
            only — it is not evidence that the call site is safe.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {row.compiler.map((diagnostic, index) => (
              <li
                key={`${diagnostic.ts_error_code}-${diagnostic.line}-${diagnostic.column}-${index}`}
                className="mono rounded border border-[#3a1b20] bg-[#150c0f] px-3 py-2 text-[11.5px] text-[#ffb3bb]"
              >
                <span className="font-bold">{diagnostic.ts_error_code}</span>{" "}
                <span className="text-[var(--color-dim)]">
                  ({diagnostic.line}:{diagnostic.column})
                </span>{" "}
                <span className="text-[#e8c7cb]">{diagnostic.message}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <p className="kicker mb-1.5">
          Findings · one per (call site × change) pair the system considered
        </p>
        {row.findings.length === 0 ? (
          <p className="text-[12px] text-[var(--color-muted)]">
            No change reached this call site, so the system reported nothing about it. Silence is a
            prediction here and is scored as UNAFFECTED, not as an absent answer.
          </p>
        ) : (
          <ul className="space-y-2">
            {row.findings.map((finding, index) => (
              <li
                key={`${finding.change_id}-${finding.line}-${index}`}
                className="rounded border border-[var(--color-line)] bg-[var(--color-panel)] px-3 py-2"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <VerdictChip verdict={finding.verdict} scope="System finding" />
                  <code className="mono text-[11px] text-[var(--color-accent)]">
                    {finding.change_id}
                  </code>
                  <span className="text-[10.5px] text-[var(--color-dim)]">
                    rule <code className="mono">{finding.rule}</code> · reason{" "}
                    <code className="mono">{finding.reason}</code>
                  </span>
                </div>
                <p className="mt-1.5 text-[12px] text-[var(--color-text)]">{finding.change_text}</p>
                <p className="mt-1 text-[11px] text-[var(--color-dim)]">
                  anchored at line {finding.line}
                  {finding.column !== null ? `, column ${finding.column}` : ""}
                  {finding.token ? (
                    <>
                      {" "}
                      on <code className="mono text-[var(--color-muted)]">{finding.token}</code>
                    </>
                  ) : null}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
