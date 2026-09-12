import type { Expressibility, Truth, Verdict } from "@/lib/types";
import { expressibilityChip, levelLabel, truthChip, verdictChip } from "@/lib/verdicts";

/**
 * The verdict vocabulary, rendered.
 *
 * Every chip carries its `title` from `lib/verdicts.ts`, so the explanation of what UNKNOWN means
 * travels with every single instance of it rather than living in a legend a reader has to find.
 */

export function VerdictChip({
  verdict,
  scope,
}: {
  verdict: Verdict | string;
  /** Who produced it — announced to screen readers so three chips in a row are distinguishable. */
  scope?: string;
}): React.ReactElement {
  const spec = verdictChip(verdict);
  return (
    <span
      className={spec.className}
      title={spec.title}
      data-verdict={verdict}
      data-testid="verdict-chip"
      aria-label={scope ? `${scope}: ${spec.label}` : spec.label}
    >
      {spec.label}
    </span>
  );
}

export function TruthChip({ truth }: { truth: Truth | string }): React.ReactElement {
  const spec = truthChip(truth);
  return (
    <span
      className={spec.className}
      title={spec.title}
      data-truth={truth}
      data-testid="truth-chip"
      aria-label={`Compiler: ${spec.label}`}
    >
      {spec.label}
    </span>
  );
}

export function ExpressibilityChip({
  value,
}: {
  value: Expressibility | string;
}): React.ReactElement {
  const spec = expressibilityChip(value);
  return (
    <span
      className={spec.className}
      title={spec.title}
      data-expressibility={value}
      data-testid="expressibility-chip"
    >
      {spec.label}
    </span>
  );
}

export function LevelBadge({ level }: { level: number }): React.ReactElement {
  const label = levelLabel(level);
  const className =
    level === 3 ? "level level-err" : level === 2 ? "level level-warn" : "level";
  return (
    <span className={className} title={`oasdiff severity level ${level}`}>
      {label}
    </span>
  );
}

/**
 * The three answers to one question, side by side: what the compiler did, what the system
 * predicted, what the naive baseline predicted.
 *
 * Compiler first, and labelled *compiler*, because it is the only column that is truth. The other
 * two are predictions made without ever seeing it.
 */
export function VerdictTriple({
  truth,
  system,
  baseline,
}: {
  truth: Truth | string;
  system: Verdict | string;
  baseline: Verdict | string;
}): React.ReactElement {
  return (
    <span className="inline-flex items-center gap-3" data-testid="verdict-triple">
      <span className="inline-flex items-center gap-1.5">
        <span className="text-[9.5px] uppercase tracking-wider text-[var(--color-dim)]">cmp</span>
        <TruthChip truth={truth} />
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="text-[9.5px] uppercase tracking-wider text-[var(--color-dim)]">sys</span>
        <VerdictChip verdict={system} scope="System" />
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="text-[9.5px] uppercase tracking-wider text-[var(--color-dim)]">base</span>
        <VerdictChip verdict={baseline} scope="Baseline" />
      </span>
    </span>
  );
}
