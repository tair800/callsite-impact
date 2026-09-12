import { ExpressibilityChip, LevelBadge } from "@/components/chips";
import { count } from "@/lib/format";
import type { ChangeRow } from "@/lib/types";

/**
 * What the differ reported, with the question the differ cannot answer attached to each row.
 *
 * The rows marked *not type-expressible* are given a rail and a heavier chip because they are the
 * project's first finding: of the 39 changes `oasdiff` calls breaking between Adyen Checkout v71
 * and v72, 26 are `maxLength` changes, and `maxLength` does not exist in the TypeScript type
 * system. No call site can be made to fail on those, and no call site compiling clean is evidence
 * of safety. A reader should be able to count them by eye.
 */

function railClass(expressibility: string): string {
  if (expressibility === "not_type_expressible") return "change-inexpressible";
  if (expressibility === "unclassified") return "change-unclassified";
  return "change-expressible";
}

export function ChangeList({
  changes,
  total,
}: {
  changes: ChangeRow[];
  total: number;
}): React.ReactElement {
  const omitted = Math.max(0, total - changes.length);

  return (
    <section className="panel" data-testid="change-list">
      <div className="panel-head flex flex-wrap items-center gap-3 rounded-t-[5px] px-4 py-2">
        <h2 className="kicker">Changes the differ reported</h2>
        <span className="ml-auto text-[11px] text-[var(--color-dim)]">
          {count(changes.length)} shown of {count(total)}
          {omitted > 0 ? ` · ${count(omitted)} not shown` : ""}
        </span>
      </div>

      {changes.length === 0 ? (
        <p role="status" className="px-4 py-6 text-[12.5px] text-[var(--color-muted)]">
          The artifact was read and lists no change for this pair.
        </p>
      ) : (
        <ul className="divide-y divide-[var(--color-line-soft)]">
          {changes.map((change, index) => (
            <li
              key={`${change.change_id}-${change.method}-${change.path}-${index}`}
              className={`px-4 py-2.5 ${railClass(String(change.expressibility))}`}
              data-testid="change-row"
              data-expressibility={change.expressibility}
            >
              <div className="flex flex-wrap items-center gap-2">
                <LevelBadge level={change.level} />
                <code className="mono text-[11px] text-[var(--color-accent)]">
                  {change.change_id}
                </code>
                <ExpressibilityChip value={change.expressibility} />
                <code className="mono ml-auto text-[11px] text-[var(--color-dim)]">
                  {change.method.toUpperCase()} {change.path}
                </code>
              </div>
              <p className="mt-1 text-[12.5px] text-[var(--color-text)]">{change.text}</p>
            </li>
          ))}
        </ul>
      )}

      <p className="border-t border-[var(--color-line-soft)] px-4 py-2.5 text-[11.5px] leading-snug text-[var(--color-muted)]">
        A change marked{" "}
        <span className="chip chip-inexpressible">not type-expressible</span> is one no compiler can
        decide. Every call site touching it compiles clean, and that clean compile is not evidence
        of safety — the system returns UNKNOWN there and the abstention is counted, never scored as
        a hit.
      </p>
    </section>
  );
}
