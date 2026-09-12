/**
 * Display helpers. Nothing here derives a figure.
 *
 * The distinction the console holds to: a **unit change** on a number the artifact contains is
 * formatting, and is allowed here; a **new number** computed from two artifact fields is a metric,
 * and belongs in `evaluate/scorer.py` where it can be tested and committed. So `0.0625` may be
 * shown as `6.25%`, and a rate that is absent from the artifact is simply not shown anywhere.
 */

/**
 * A rate as a percentage, or an em dash when the scorer recorded no measurement.
 *
 * `null` from the scorer means the denominator was empty — see `_ratio` in `scorer.py`, which
 * returns `None` rather than `0.0` precisely so that "never predicted a positive" cannot be read
 * off a table as "predicted fifty and got all fifty wrong". The em dash carries that distinction
 * onto the screen instead of quietly printing a zero.
 */
export function ratePercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return `${(value * 100).toFixed(digits)}%`;
}

/** The same rate as the artifact stores it, for a reader who wants the raw ratio. */
export function rateRaw(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return value.toFixed(digits);
}

export function count(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return value.toLocaleString("en-GB");
}

/** A sha256 shown short enough to scan, with the full value left to a `title` attribute. */
export function shortSha(sha: string): string {
  return sha.length > 16 ? `${sha.slice(0, 16)}…` : sha;
}

/** One fixed rendering for every instant on screen. UTC, so two readers see the same string. */
export function formatInstant(iso: string | null | undefined): string {
  if (!iso) {
    return "—";
  }
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) {
    return iso;
  }
  const pad = (value: number): string => String(value).padStart(2, "0");
  return (
    `${at.getUTCFullYear()}-${pad(at.getUTCMonth() + 1)}-${pad(at.getUTCDate())} ` +
    `${pad(at.getUTCHours())}:${pad(at.getUTCMinutes())}Z`
  );
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) {
    return "—";
  }
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) {
    return iso;
  }
  const pad = (value: number): string => String(value).padStart(2, "0");
  return `${at.getUTCFullYear()}-${pad(at.getUTCMonth() + 1)}-${pad(at.getUTCDate())}`;
}
