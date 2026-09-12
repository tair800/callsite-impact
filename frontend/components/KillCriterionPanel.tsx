import { count } from "@/lib/format";
import type { KillCriterion } from "@/lib/types";

/**
 * The predeclared kill test, reported.
 *
 * ADR-001 fixed the threshold at 60 compiler-verified call-site breakages across at least three
 * vendors, *before implementation*, and said that if the corpus cannot reach it honestly the
 * repository says so on its front page. This component is that sentence. It is therefore written
 * so that a failure is the loudest thing on the screen and cannot be read as a caveat: the word is
 * FAILED, the panel is red, and the shortfall is named in plain numbers directly underneath.
 *
 * `passed` is not recomputed here. It is a derived field on the Python model and arrives already
 * decided; a browser that re-derived it would be a second place the criterion could be relaxed.
 */
export function KillCriterionPanel({
  criterion,
}: {
  criterion: KillCriterion;
}): React.ReactElement {
  const breakagesMet = criterion.observed_breakages >= criterion.threshold;
  const vendorsMet = criterion.observed_vendors >= criterion.vendors_required;

  return (
    <section
      className={`rounded-md px-5 py-4 ${criterion.passed ? "verdict-pass" : "verdict-fail"}`}
      data-testid="kill-criterion"
      data-passed={criterion.passed}
    >
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="kicker" style={{ color: "inherit", opacity: 0.75 }}>
          Predeclared kill criterion
        </span>
        <span className="text-[22px] font-extrabold tracking-tight">
          {criterion.passed ? "PASSED" : "FAILED"}
        </span>
      </div>

      <p className="mt-2 text-[13.5px] leading-snug text-[var(--color-text)]">
        <strong className="font-bold">{count(criterion.observed_breakages)}</strong>{" "}
        compiler-verified call-site breakages across{" "}
        <strong className="font-bold">{count(criterion.observed_vendors)}</strong>{" "}
        {criterion.observed_vendors === 1 ? "vendor" : "vendors"}, against a threshold of{" "}
        {count(criterion.threshold)} across {count(criterion.vendors_required)}.
      </p>

      <ul className="mt-3 grid gap-1 text-[12px] sm:grid-cols-2">
        <li>
          <span className="mono">{breakagesMet ? "met" : "NOT MET"}</span>
          <span className="text-[var(--color-muted)]">
            {" "}
            · breakages {count(criterion.observed_breakages)} / {count(criterion.threshold)}
          </span>
        </li>
        <li>
          <span className="mono">{vendorsMet ? "met" : "NOT MET"}</span>
          <span className="text-[var(--color-muted)]">
            {" "}
            · vendors {count(criterion.observed_vendors)} / {count(criterion.vendors_required)}
          </span>
        </li>
      </ul>

      {criterion.passed ? null : (
        <p className="mt-3 border-t border-current/25 pt-3 text-[12.5px] leading-snug">
          The corpus did not reach the bar this repository set for itself before it was built. The
          claim is <strong className="font-bold">not proven</strong> by this run. The criterion is
          not lowered and the numbers above are published as they came out.
        </p>
      )}
    </section>
  );
}
