import type { Expressibility, Truth, Verdict } from "@/lib/types";

/**
 * How the three verdicts are shown, decided once.
 *
 * The rule this file exists to enforce is ADR-001's third value. **UNKNOWN is not a failure and is
 * not a soft IMPACTED.** It means the change is of a class the TypeScript type system cannot
 * express, so no call site could be made to fail on it and a clean compile is not evidence of
 * safety either way. It therefore gets a colour of its own — neither the red of a breakage nor the
 * green of a clean call site — and a tooltip that says what it means, so a reader who hovers it
 * once never has to guess again.
 */

export interface ChipSpec {
  /** The text in the chip. */
  label: string;
  /** A static class from `globals.css`. Static because Tailwind cannot see a constructed name. */
  className: string;
  /** The one line a reader gets on hover. */
  title: string;
}

const UNRECOGNISED: ChipSpec = {
  label: "unrecognised",
  className: "chip chip-unrecognised",
  title: "A value this build of the console does not recognise. Shown rather than swallowed.",
};

const VERDICTS: Record<Verdict, ChipSpec> = {
  impacted: {
    label: "IMPACTED",
    className: "chip chip-impacted",
    title: "Predicted to break under the after revision, anchored to a spec change and a source token.",
  },
  unaffected: {
    label: "UNAFFECTED",
    className: "chip chip-unaffected",
    title:
      "The change reaches this operation but cannot reach this call site's usage. Every change was ruled on.",
  },
  unknown: {
    label: "UNKNOWN",
    className: "chip chip-unknown",
    title:
      "The type system cannot decide. The change is of a class TypeScript cannot express, so no call site could fail on it and a clean compile is not evidence of safety. An abstention, not a miss and not a soft IMPACTED.",
  },
};

export function verdictChip(verdict: Verdict | string): ChipSpec {
  return VERDICTS[verdict as Verdict] ?? { ...UNRECOGNISED, label: String(verdict || "unrecognised") };
}

/**
 * The compiler's own two values. Kept apart from {@link verdictChip} on purpose: `tsc` has no third
 * value and never abstains, and giving truth the same vocabulary as a prediction would invite a
 * reader to look for an UNKNOWN column that cannot exist.
 */
const TRUTHS: Record<Truth, ChipSpec> = {
  impacted: {
    label: "BREAKS",
    className: "chip chip-impacted",
    title: "`tsc` emitted at least one error on this call site against the after revision.",
  },
  clean: {
    label: "CLEAN",
    className: "chip chip-unaffected",
    title:
      "`tsc` emitted no error on this call site against the after revision. A type-level result only: it does not prove the call site is safe.",
  },
};

export function truthChip(truth: Truth | string): ChipSpec {
  return TRUTHS[truth as Truth] ?? { ...UNRECOGNISED, label: String(truth || "unrecognised") };
}

const EXPRESSIBILITY: Record<Expressibility, ChipSpec> = {
  type_expressible: {
    label: "type-expressible",
    className: "chip chip-expressible",
    title:
      "A call site can be made to fail on this change class: removals, renames, requiredness, type and enum shape.",
  },
  not_type_expressible: {
    label: "not type-expressible",
    className: "chip chip-inexpressible",
    title:
      "No compiler can decide this. A runtime or prose constraint — maxLength, pattern, minimum, format, auth, rate limit, behaviour. Compilation proves nothing here in either direction.",
  },
  unclassified: {
    label: "unclassified",
    className: "chip chip-unclassified",
    title:
      "A change class this repository has not ruled on. Treated as not type-expressible, so it fails towards abstention rather than inventing a clean result.",
  },
};

export function expressibilityChip(value: Expressibility | string): ChipSpec {
  return (
    EXPRESSIBILITY[value as Expressibility] ?? {
      ...UNRECOGNISED,
      label: String(value || "unrecognised"),
    }
  );
}

/** `oasdiff` severity, as `SpecChange.level` carries it. 3 = ERR, 2 = WARN, 1 = INFO. */
export function levelLabel(level: number): string {
  if (level === 3) return "ERR";
  if (level === 2) return "WARN";
  if (level === 1) return "INFO";
  return `level ${level}`;
}

/**
 * Does a predictor's verdict disagree with what the compiler did?
 *
 * This is a **row filter, not a metric** — no count derived from it is published — and it is
 * written to mirror `scorer._view(abstaining=False)` exactly so that the rows a reader can filter
 * to are the same rows the strict confusion matrix counted:
 *
 * * the compiler broke it and the predictor did not say IMPACTED — a false negative, UNKNOWN
 *   included, because an abstention is not a report of a breakage that exists;
 * * the compiler left it clean and the predictor said IMPACTED — a false positive.
 *
 * An UNKNOWN on a clean call site is **not** a disagreement, for the same reason the scorer does
 * not count it as a false positive: ADR-001 defines a false positive as a call site *reported
 * IMPACTED*, and an abstention is not that.
 */
export function disagreesWithCompiler(truth: Truth, predicted: Verdict): boolean {
  if (truth === "impacted") {
    return predicted !== "impacted";
  }
  return predicted === "impacted";
}
