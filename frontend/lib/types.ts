/**
 * The shapes the two committed artifacts actually have.
 *
 * These mirror the Pydantic models and nothing else. The authority is, per file:
 *
 * * `src/callsite_impact/evaluate/scorer.py`  — `ViewMetrics`, `ScopeMetrics`, `ScoreReport`
 * * `src/callsite_impact/evaluate/report.py`  — `PairProvenance`, `PairCounts`, `KillCriterion`,
 *                                               `EvaluationArtifact`
 * * `src/callsite_impact/domain.py`           — `RunSummary`, `Verdict`
 * * `src/callsite_impact/detail.py`           — `ChangeRow`, `CompilerRow`, `FindingRow`,
 *                                               `CallsiteDetail`, `PairDetail`, `DetailArtifact`
 *
 * Two naming traps worth stating, because the obvious guess is wrong in both cases:
 * `ScoreReport`'s vendor list is `by_vendor`, not `per_vendor`; and `ViewMetrics` carries
 * `callsites_excluded_as_abstention`, which is the abstaining view's denominator disclosure and is
 * not optional to show.
 *
 * Every rate is `number | null`. `null` means the denominator was empty — an absent measurement,
 * which the scorer deliberately distinguishes from a measured zero. It renders as an em dash.
 */

/** `callsite_impact.domain.Verdict`. Three values, and the third one is load-bearing. */
export type Verdict = "impacted" | "unaffected" | "unknown";

/** `callsite_impact.detail.CallsiteDetail.truth`. What `tsc` said. Two values, never three. */
export type Truth = "impacted" | "clean";

/** `callsite_impact.domain.Expressibility`, serialised by `str()`. */
export type Expressibility = "type_expressible" | "not_type_expressible" | "unclassified";

// ------------------------------------------------------------------------------ evaluation.json

export interface ConfusionCounts {
  true_positives: number;
  false_positives: number;
  true_negatives: number;
  false_negatives: number;
}

export interface ViewMetrics {
  counts: ConfusionCounts;
  false_negative_rate: number | null;
  false_positive_rate: number | null;
  precision: number | null;
  recall: number | null;
  f1: number | null;
  callsites_excluded_as_abstention: number;
}

export interface ScopeMetrics {
  scope: string;
  callsites: number;
  truly_impacted: number;
  truly_clean: number;
  predicted_impacted: number;
  predicted_unaffected: number;
  predicted_unknown: number;
  strict: ViewMetrics;
  abstaining: ViewMetrics;
  candidate_pairs: number;
  unknown_pairs: number;
  suppressed_pairs: number;
  abstention_rate: number | null;
}

export interface ScoreReport {
  pooled: ScopeMetrics;
  by_vendor: ScopeMetrics[];
}

export interface RunSummary {
  pairs: number;
  vendors: string[];
  callsites_generated: number;
  callsites_admitted: number;
  callsites_discarded: number;
  compiler_breakages: number;
  compiler_clean: number;
  candidate_findings: number;
}

export interface KillCriterion {
  threshold: number;
  vendors_required: number;
  observed_breakages: number;
  observed_vendors: number;
  passed: boolean;
}

export interface PairProvenance {
  pair_id: string;
  vendor: string;
  service: string;
  before_revision: string;
  before_date: string | null;
  before_sha256: string;
  after_revision: string;
  after_date: string | null;
  after_sha256: string;
  source_url: string;
  licence: string;
}

export interface PairCounts {
  pair_id: string;
  vendor: string;
  callsites_admitted: number;
  candidate_pairs: number;
  breakage_callsites: number;
  compiler_labels: number;
}

/**
 * The headline block, exactly as `/api/v1/summary` returns it and exactly the subset of
 * `evaluation.json` that endpoint selects. One shape for both sources, so a page cannot behave
 * differently depending on where the bytes came from.
 */
export interface Summary {
  generated_at: string;
  run: RunSummary;
  kill_criterion: KillCriterion;
  total_compiler_labels: number;
  unclassified_changes: number;
  headline_false_negative_rate: number | null;
  abstention_rate: number | null;
  system: ScoreReport;
  baseline_touches_changed_operation: ScoreReport;
  baseline_err_level_only: ScoreReport;
}

/** `/api/v1/provenance`, and the corresponding two keys of `evaluation.json`. */
export interface ProvenanceBundle {
  pairs: PairProvenance[];
  per_pair: PairCounts[];
}

// -------------------------------------------------------------------------------- findings.json

export interface ChangeRow {
  change_id: string;
  level: number;
  method: string;
  path: string;
  text: string;
  expressibility: Expressibility | string;
}

export interface CompilerRow {
  line: number;
  column: number;
  ts_error_code: string;
  message: string;
}

export interface FindingRow {
  verdict: Verdict;
  reason: string;
  rule: string;
  change_id: string;
  change_text: string;
  line: number;
  column: number | null;
  token: string | null;
}

export interface CallsiteDetail {
  callsite_id: string;
  operation_key: string;
  line: number;
  source: string;
  truth: Truth;
  system: Verdict;
  baseline: Verdict;
  compiler: CompilerRow[];
  findings: FindingRow[];
}

export interface PairDetail {
  pair_id: string;
  vendor: string;
  service: string;
  before_revision: string;
  after_revision: string;
  source_url: string;
  changes_total: number;
  changes_shown: ChangeRow[];
  callsites_admitted: number;
  callsites_broken: number;
  clean_callsites_omitted: number;
  callsites: CallsiteDetail[];
}

/** One pair without the two heavy arrays — what `/api/v1/pairs` returns per entry. */
export type PairSummary = Omit<PairDetail, "callsites" | "changes_shown">;

/** `/api/v1/pairs`: the index, carrying the sampling sentence the detail artifact declares. */
export interface PairIndex {
  sampling: string;
  pairs: PairSummary[];
}
