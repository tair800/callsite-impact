import type { Summary } from "@/lib/types";

import { ratePercent } from "@/lib/format";

/**
 * Development corpus beside held-out slice.
 *
 * This panel sits above the metrics table because without it the table reads as a statement about
 * how well the tool works, and it is not one: the rule table was fitted to the corpus that table
 * scores. The held-out column is the only unbiased estimate on the page, it is much worse, and
 * putting it second but adjacent is the smallest arrangement that stops the first number being
 * mistaken for the answer.
 */
export function GeneralisationPanel({
  development,
  holdout,
}: {
  development: Summary;
  holdout: Summary | null;
}): React.ReactElement {
  if (!holdout) {
    return (
      <section className="panel">
        <h2 className="panel-title">Generalisation</h2>
        <div className="p-4 text-[13px] leading-relaxed text-[var(--color-muted)]">
          No held-out slice has been measured in this checkout, so every figure below is a{" "}
          <strong className="text-[var(--color-text)]">development-corpus</strong> number: the rule
          table was fitted to the corpus it is scored on. Run{" "}
          <code>make corpus-holdout &amp;&amp; make killtest-holdout</code> to produce one.
        </div>
      </section>
    );
  }

  const dev = development.system.pooled.strict;
  const held = holdout.system.pooled.strict;

  const rows: Array<[string, string, string]> = [
    [
      "Compiler-verified breakages",
      String(development.kill_criterion.observed_breakages),
      String(holdout.kill_criterion.observed_breakages),
    ],
    [
      "Admitted call sites",
      development.run.callsites_admitted.toLocaleString("en-GB"),
      holdout.run.callsites_admitted.toLocaleString("en-GB"),
    ],
    ["Precision", ratePercent(dev.precision), ratePercent(held.precision)],
    ["Recall", ratePercent(dev.recall), ratePercent(held.recall)],
    ["F1", ratePercent(dev.f1), ratePercent(held.f1)],
    [
      "False negatives",
      ratePercent(dev.false_negative_rate),
      ratePercent(held.false_negative_rate),
    ],
    [
      "False positives",
      ratePercent(dev.false_positive_rate),
      ratePercent(held.false_positive_rate),
    ],
  ];

  return (
    <section className="panel">
      <h2 className="panel-title">Generalisation — development corpus versus a held-out slice</h2>
      <div className="overflow-x-auto">
        <table className="grid-table">
          <thead>
            <tr>
              <th scope="col">Measure</th>
              <th scope="col" className="num">
                Development corpus
              </th>
              <th scope="col" className="num col-headline">
                Held-out slice
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, a, b]) => (
              <tr key={label}>
                <th scope="row" className="font-normal normal-case tracking-normal">
                  {label}
                </th>
                <td className="num">{a}</td>
                <td className="num col-headline font-bold">{b}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="p-4 text-[13px] leading-relaxed text-[var(--color-muted)]">
        <strong className="text-[var(--color-text)]">
          The development column is not an estimate of generalisation.
        </strong>{" "}
        Eight rules were written after seeing a score on that corpus. The held-out slice is fifteen
        spec pairs from services the rules had never seen, frozen in git before it was measured and
        scored once with nothing changed afterwards — so it is the unbiased number, and it is far
        worse. The system is never wrong when it speaks (precision {ratePercent(held.precision)},
        zero false positives); it is silent. Most of the silence traces to path-parameter renames
        that the spec differ normalises away and the type generator does not, so no change is
        reported and the call site comes out UNAFFECTED rather than UNKNOWN. See ADR-005.
      </div>
    </section>
  );
}
