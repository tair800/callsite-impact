/**
 * Fixtures for the console's tests.
 *
 * **These numbers are invented and are not a measurement.** They exist so the components can be
 * rendered and asserted on in a checkout where `make killtest` has never run. Nothing in
 * `app/` or `components/` imports this file, and the console never falls back to it: a missing
 * artifact produces the empty state, because rendering a plausible-looking fabricated result would
 * be the single worst thing this console could do.
 *
 * The shapes mirror `evaluate/report.py`, `evaluate/scorer.py` and `detail.py`. The rates are
 * produced by {@link viewFrom}, which reimplements `scorer._view`'s arithmetic so that a fixture
 * cannot be internally inconsistent — a hand-typed precision that does not match its own counts
 * would make a passing test meaningless.
 */

import type {
  CallsiteDetail,
  PairDetail,
  PairIndex,
  PairProvenance,
  ProvenanceBundle,
  ScopeMetrics,
  ScoreReport,
  Summary,
  ViewMetrics,
} from "@/lib/types";

function ratio(numerator: number, denominator: number): number | null {
  return denominator === 0 ? null : numerator / denominator;
}

function f1(precision: number | null, recall: number | null): number | null {
  if (precision === null || recall === null) return null;
  const total = precision + recall;
  return total === 0 ? 0 : (2 * precision * recall) / total;
}

/** The same arithmetic `scorer._view` performs, so a fixture's rates match its own counts. */
export function viewFrom(
  tp: number,
  fp: number,
  tn: number,
  fn: number,
  excluded = 0,
): ViewMetrics {
  const precision = ratio(tp, tp + fp);
  const recall = ratio(tp, tp + fn);
  return {
    counts: { true_positives: tp, false_positives: fp, true_negatives: tn, false_negatives: fn },
    false_negative_rate: ratio(fn, tp + fn),
    false_positive_rate: ratio(fp, fp + tn),
    precision,
    recall,
    f1: f1(precision, recall),
    callsites_excluded_as_abstention: excluded,
  };
}

function scope(
  name: string,
  options: {
    callsites: number;
    trulyImpacted: number;
    predictedImpacted: number;
    predictedUnaffected: number;
    predictedUnknown: number;
    strict: ViewMetrics;
    abstaining: ViewMetrics;
    candidatePairs: number;
    unknownPairs: number;
    suppressedPairs: number;
  },
): ScopeMetrics {
  return {
    scope: name,
    callsites: options.callsites,
    truly_impacted: options.trulyImpacted,
    truly_clean: options.callsites - options.trulyImpacted,
    predicted_impacted: options.predictedImpacted,
    predicted_unaffected: options.predictedUnaffected,
    predicted_unknown: options.predictedUnknown,
    strict: options.strict,
    abstaining: options.abstaining,
    candidate_pairs: options.candidatePairs,
    unknown_pairs: options.unknownPairs,
    suppressed_pairs: options.suppressedPairs,
    abstention_rate: ratio(options.unknownPairs, options.candidatePairs),
  };
}

// --------------------------------------------------------------------------------- the system
//
// 388 admitted call sites; `tsc` broke 71 of them. The system misses 7 in the strict reading, of
// which 5 are abstentions — which is why the abstaining reading looks so much better and why the
// console refuses to show it alone.

const SYSTEM_POOLED = scope("pooled", {
  callsites: 388,
  trulyImpacted: 71,
  predictedImpacted: 66,
  predictedUnaffected: 281,
  predictedUnknown: 41,
  strict: viewFrom(64, 2, 315, 7),
  abstaining: viewFrom(64, 2, 279, 2, 41),
  candidatePairs: 5104,
  unknownPairs: 1612,
  suppressedPairs: 18,
});

const SYSTEM_ADYEN = scope("adyen", {
  callsites: 164,
  trulyImpacted: 31,
  predictedImpacted: 28,
  predictedUnaffected: 112,
  predictedUnknown: 24,
  strict: viewFrom(27, 1, 132, 4),
  abstaining: viewFrom(27, 1, 111, 1, 24),
  candidatePairs: 2624,
  unknownPairs: 1004,
  suppressedPairs: 9,
});

const SYSTEM_GITHUB = scope("github", {
  callsites: 121,
  trulyImpacted: 22,
  predictedImpacted: 21,
  predictedUnaffected: 90,
  predictedUnknown: 10,
  strict: viewFrom(20, 1, 98, 2),
  abstaining: viewFrom(20, 1, 89, 1, 10),
  candidatePairs: 1452,
  unknownPairs: 402,
  suppressedPairs: 5,
});

const SYSTEM_STRIPE = scope("stripe", {
  callsites: 103,
  trulyImpacted: 18,
  predictedImpacted: 17,
  predictedUnaffected: 79,
  predictedUnknown: 7,
  strict: viewFrom(17, 0, 85, 1),
  abstaining: viewFrom(17, 0, 78, 1, 7),
  candidatePairs: 1028,
  unknownPairs: 206,
  suppressedPairs: 4,
});

export const SYSTEM_REPORT: ScoreReport = {
  pooled: SYSTEM_POOLED,
  by_vendor: [SYSTEM_ADYEN, SYSTEM_GITHUB, SYSTEM_STRIPE],
};

// ------------------------------------------------------------------------------- the baselines
//
// Near-perfect recall, poor precision — exactly what ADR-001 predicted a spec differ plus grep
// would do. Neither baseline ever abstains, so its two views are identical.

const TOUCHES_POOLED = scope("pooled", {
  callsites: 388,
  trulyImpacted: 71,
  predictedImpacted: 219,
  predictedUnaffected: 169,
  predictedUnknown: 0,
  strict: viewFrom(71, 148, 169, 0),
  abstaining: viewFrom(71, 148, 169, 0, 0),
  candidatePairs: 5104,
  unknownPairs: 0,
  suppressedPairs: 0,
});

export const BASELINE_TOUCHES: ScoreReport = {
  pooled: TOUCHES_POOLED,
  by_vendor: [
    scope("adyen", {
      callsites: 164,
      trulyImpacted: 31,
      predictedImpacted: 104,
      predictedUnaffected: 60,
      predictedUnknown: 0,
      strict: viewFrom(31, 73, 60, 0),
      abstaining: viewFrom(31, 73, 60, 0, 0),
      candidatePairs: 2624,
      unknownPairs: 0,
      suppressedPairs: 0,
    }),
    scope("github", {
      callsites: 121,
      trulyImpacted: 22,
      predictedImpacted: 66,
      predictedUnaffected: 55,
      predictedUnknown: 0,
      strict: viewFrom(22, 44, 55, 0),
      abstaining: viewFrom(22, 44, 55, 0, 0),
      candidatePairs: 1452,
      unknownPairs: 0,
      suppressedPairs: 0,
    }),
    scope("stripe", {
      callsites: 103,
      trulyImpacted: 18,
      predictedImpacted: 49,
      predictedUnaffected: 54,
      predictedUnknown: 0,
      strict: viewFrom(18, 31, 54, 0),
      abstaining: viewFrom(18, 31, 54, 0, 0),
      candidatePairs: 1028,
      unknownPairs: 0,
      suppressedPairs: 0,
    }),
  ],
};

export const BASELINE_ERR: ScoreReport = {
  pooled: scope("pooled", {
    callsites: 388,
    trulyImpacted: 71,
    predictedImpacted: 164,
    predictedUnaffected: 224,
    predictedUnknown: 0,
    strict: viewFrom(68, 96, 221, 3),
    abstaining: viewFrom(68, 96, 221, 3, 0),
    candidatePairs: 2180,
    unknownPairs: 0,
    suppressedPairs: 0,
  }),
  by_vendor: [
    scope("adyen", {
      callsites: 164,
      trulyImpacted: 31,
      predictedImpacted: 77,
      predictedUnaffected: 87,
      predictedUnknown: 0,
      strict: viewFrom(30, 47, 86, 1),
      abstaining: viewFrom(30, 47, 86, 1, 0),
      candidatePairs: 1120,
      unknownPairs: 0,
      suppressedPairs: 0,
    }),
    scope("github", {
      callsites: 121,
      trulyImpacted: 22,
      predictedImpacted: 50,
      predictedUnaffected: 71,
      predictedUnknown: 0,
      strict: viewFrom(21, 29, 70, 1),
      abstaining: viewFrom(21, 29, 70, 1, 0),
      candidatePairs: 640,
      unknownPairs: 0,
      suppressedPairs: 0,
    }),
    scope("stripe", {
      callsites: 103,
      trulyImpacted: 18,
      predictedImpacted: 37,
      predictedUnaffected: 66,
      predictedUnknown: 0,
      strict: viewFrom(17, 20, 65, 1),
      abstaining: viewFrom(17, 20, 65, 1, 0),
      candidatePairs: 420,
      unknownPairs: 0,
      suppressedPairs: 0,
    }),
  ],
};

// ----------------------------------------------------------------------------- evaluation.json

export const SUMMARY: Summary = {
  generated_at: "2026-09-12T11:42:07Z",
  run: {
    pairs: 3,
    vendors: ["adyen", "github", "stripe"],
    callsites_generated: 412,
    callsites_admitted: 388,
    callsites_discarded: 24,
    compiler_breakages: 71,
    compiler_clean: 317,
    candidate_findings: 5104,
  },
  kill_criterion: {
    threshold: 60,
    vendors_required: 3,
    observed_breakages: 71,
    observed_vendors: 3,
    passed: true,
  },
  total_compiler_labels: 94,
  unclassified_changes: 11,
  headline_false_negative_rate: SYSTEM_POOLED.strict.false_negative_rate,
  abstention_rate: SYSTEM_POOLED.abstention_rate,
  system: SYSTEM_REPORT,
  baseline_touches_changed_operation: BASELINE_TOUCHES,
  baseline_err_level_only: BASELINE_ERR,
};

/** The same corpus short of the bar, for asserting the failed-kill-test rendering. */
export const FAILED_SUMMARY: Summary = {
  ...SUMMARY,
  kill_criterion: {
    threshold: 60,
    vendors_required: 3,
    observed_breakages: 41,
    observed_vendors: 2,
    passed: false,
  },
};

const ADYEN_PROVENANCE: PairProvenance = {
  pair_id: "adyen-checkout-v71-v72",
  vendor: "adyen",
  service: "checkout",
  before_revision: "v71",
  before_date: "2024-03-14",
  before_sha256: "8f14e45fceea167a5a36dedd4bea2543f0d9b0a1c4f2d3e5b6a7980112233445",
  after_revision: "v72",
  after_date: "2024-09-02",
  after_sha256: "c9f0f895fb98ab9159f51fd0297e236d4b7a1e9c0d2f3a4b5c6d7e8f90112233",
  source_url: "https://github.com/Adyen/adyen-openapi",
  licence: "MIT",
};

export const PROVENANCE: ProvenanceBundle = {
  pairs: [
    ADYEN_PROVENANCE,
    {
      pair_id: "github-rest-2024-06-2024-11",
      vendor: "github",
      service: "rest",
      before_revision: "2024-06-11",
      before_date: "2024-06-11",
      before_sha256: "45c48cce2e2d7fbdea1afc51c7c6ad26a1b2c3d4e5f60718293a4b5c6d7e8f90",
      after_revision: "2024-11-05",
      after_date: "2024-11-05",
      after_sha256: "d3d9446802a44259755d38e6d163e820ffeeddccbbaa99887766554433221100",
      source_url: "https://github.com/github/rest-api-description",
      licence: "MIT",
    },
    {
      pair_id: "stripe-api-2024-04-2024-10",
      vendor: "stripe",
      service: "api",
      before_revision: "2024-04-10",
      before_date: "2024-04-10",
      before_sha256: "6512bd43d9caa6e02c990b0a82652dca1122334455667788990aabbccddeeff0",
      after_revision: "2024-10-28",
      after_date: "2024-10-28",
      after_sha256: "c20ad4d76fe97759aa27a0c99bff671139f0e1a2b3c4d5e6f708192a3b4c5d6e",
      source_url: "https://github.com/stripe/openapi",
      licence: "MIT",
    },
  ],
  per_pair: [
    {
      pair_id: "adyen-checkout-v71-v72",
      vendor: "adyen",
      callsites_admitted: 164,
      candidate_pairs: 2624,
      breakage_callsites: 31,
      compiler_labels: 41,
    },
    {
      pair_id: "github-rest-2024-06-2024-11",
      vendor: "github",
      callsites_admitted: 121,
      candidate_pairs: 1452,
      breakage_callsites: 22,
      compiler_labels: 29,
    },
    {
      pair_id: "stripe-api-2024-04-2024-10",
      vendor: "stripe",
      callsites_admitted: 103,
      candidate_pairs: 1028,
      breakage_callsites: 18,
      compiler_labels: 24,
    },
  ],
};

// ------------------------------------------------------------------------------- findings.json

export const SAMPLING =
  "Every call site the compiler broke is included. Clean call sites are capped per pair at 25, " +
  "in corpus order. Sampling happens after every published rate has been computed over the full " +
  "corpus.";

/**
 * Six call sites chosen so that every filter in `CallsiteTable` selects a different, non-empty
 * set, and so that an UNKNOWN appears both on a broken call site (a strict false negative) and on
 * a clean one (not a false positive, and not a disagreement).
 */
export const CALLSITES: CallsiteDetail[] = [
  {
    callsite_id: "cs_agree_impacted",
    operation_key: "POST /payments",
    line: 14,
    source:
      "const payment = await client.payments.post({\n" +
      "  amount: { value: 1099, currency: 'EUR' },\n" +
      "  reference: 'order-4417',\n" +
      "  shopperInteraction: 'Ecommerce',\n" +
      "});",
    truth: "impacted",
    system: "impacted",
    baseline: "impacted",
    compiler: [
      {
        line: 17,
        column: 3,
        ts_error_code: "TS2353",
        message:
          "Object literal may only specify known properties, and 'shopperInteraction' does not exist in type 'PaymentRequest'.",
      },
    ],
    findings: [
      {
        verdict: "impacted",
        reason: "sets_removed_request_property",
        rule: "request_property_removed",
        change_id: "request-property-removed",
        change_text: "removed the request property 'shopperInteraction' for the media type application/json",
        line: 17,
        column: 3,
        token: "shopperInteraction",
      },
    ],
  },
  {
    callsite_id: "cs_system_abstains_on_break",
    operation_key: "POST /payments/{paymentPspReference}/captures",
    line: 31,
    source:
      "const capture = await client.payments.captures.post(reference, {\n" +
      "  amount: { value: 1099, currency: 'EUR' },\n" +
      "  reference: 'capture-4417',\n" +
      "});",
    truth: "impacted",
    system: "unknown",
    baseline: "impacted",
    compiler: [
      {
        line: 33,
        column: 5,
        ts_error_code: "TS2322",
        message: "Type 'string' is not assignable to type 'number'.",
      },
    ],
    findings: [
      {
        verdict: "unknown",
        reason: "change_not_expressible_in_type_system",
        rule: "not_type_expressible",
        change_id: "request-property-max-length-decreased",
        change_text:
          "the 'reference' request property's maxLength was decreased from 80 to 64 for the media type application/json",
        line: 33,
        column: 5,
        token: "reference",
      },
    ],
  },
  {
    callsite_id: "cs_baseline_overreports",
    operation_key: "GET /paymentMethods",
    line: 48,
    source:
      "const methods = await client.paymentMethods.get({ countryCode: 'NL' });\n" +
      "const first = methods.paymentMethods?.[0]?.name;",
    truth: "clean",
    system: "unaffected",
    baseline: "impacted",
    compiler: [],
    findings: [
      {
        verdict: "unaffected",
        reason: "property_untouched_by_callsite",
        rule: "request_property_removed",
        change_id: "request-property-removed",
        change_text: "removed the request property 'blockedPaymentMethods' for the media type application/json",
        line: 48,
        column: 22,
        token: "paymentMethods",
      },
    ],
  },
  {
    callsite_id: "cs_abstention_on_clean",
    operation_key: "POST /sessions",
    line: 62,
    source:
      "const session = await client.sessions.post({\n" +
      "  merchantAccount: 'TestMerchant',\n" +
      "  returnUrl: 'https://example.test/return',\n" +
      "});",
    truth: "clean",
    system: "unknown",
    baseline: "unaffected",
    compiler: [],
    findings: [
      {
        verdict: "unknown",
        reason: "change_not_expressible_in_type_system",
        rule: "not_type_expressible",
        change_id: "request-property-pattern-changed",
        change_text:
          "the 'returnUrl' request property's pattern was changed from '^https?://' to '^https://'",
        line: 64,
        column: 3,
        token: "returnUrl",
      },
    ],
  },
  {
    callsite_id: "cs_both_miss",
    operation_key: "POST /payments/details",
    line: 78,
    source:
      "const details = await client.payments.details.post({ details: { redirectResult } });\n" +
      "const status: 'Authorised' | 'Refused' = details.resultCode;",
    truth: "impacted",
    system: "unaffected",
    baseline: "unaffected",
    compiler: [
      {
        line: 79,
        column: 42,
        ts_error_code: "TS2322",
        message:
          "Type '\"Authorised\" | \"Refused\" | \"PartiallyAuthorised\"' is not assignable to type '\"Authorised\" | \"Refused\"'.",
      },
    ],
    findings: [
      {
        verdict: "unaffected",
        reason: "property_untouched_by_callsite",
        rule: "response_enum_member_added",
        change_id: "response-property-enum-value-added",
        change_text: "added the new 'PartiallyAuthorised' enum value to the 'resultCode' response property",
        line: 79,
        column: 42,
        token: "resultCode",
      },
    ],
  },
  {
    callsite_id: "cs_system_false_positive",
    operation_key: "GET /payments/{paymentPspReference}",
    line: 94,
    source: "const payment = await client.payments.get(reference);\nconst method = payment.paymentMethod;",
    truth: "clean",
    system: "impacted",
    baseline: "impacted",
    compiler: [],
    findings: [
      {
        verdict: "impacted",
        reason: "reads_removed_response_property",
        rule: "response_property_removed",
        change_id: "response-property-removed",
        change_text: "removed the response property 'paymentMethod' for the response status 200",
        line: 95,
        column: 24,
        token: "paymentMethod",
      },
    ],
  },
];

export const PAIR_DETAIL: PairDetail = {
  pair_id: "adyen-checkout-v71-v72",
  vendor: "adyen",
  service: "checkout",
  before_revision: "v71",
  after_revision: "v72",
  source_url: "https://github.com/Adyen/adyen-openapi",
  changes_total: 39,
  changes_shown: [
    {
      change_id: "request-property-removed",
      level: 3,
      method: "post",
      path: "/payments",
      text: "removed the request property 'shopperInteraction' for the media type application/json",
      expressibility: "type_expressible",
    },
    {
      change_id: "request-property-max-length-decreased",
      level: 3,
      method: "post",
      path: "/payments/{paymentPspReference}/captures",
      text: "the 'reference' request property's maxLength was decreased from 80 to 64 for the media type application/json",
      expressibility: "not_type_expressible",
    },
    {
      change_id: "request-property-pattern-changed",
      level: 3,
      method: "post",
      path: "/sessions",
      text: "the 'returnUrl' request property's pattern was changed from '^https?://' to '^https://'",
      expressibility: "not_type_expressible",
    },
    {
      change_id: "response-property-enum-value-added",
      level: 2,
      method: "post",
      path: "/payments/details",
      text: "added the new 'PartiallyAuthorised' enum value to the 'resultCode' response property",
      expressibility: "type_expressible",
    },
    {
      change_id: "api-operation-id-changed",
      level: 1,
      method: "get",
      path: "/paymentMethods",
      text: "the operation id was changed from 'PaymentMethods' to 'paymentMethods'",
      expressibility: "unclassified",
    },
  ],
  callsites_admitted: 164,
  callsites_broken: 31,
  clean_callsites_omitted: 108,
  callsites: CALLSITES,
};

export const PAIR_INDEX: PairIndex = {
  sampling: SAMPLING,
  pairs: [
    {
      pair_id: PAIR_DETAIL.pair_id,
      vendor: PAIR_DETAIL.vendor,
      service: PAIR_DETAIL.service,
      before_revision: PAIR_DETAIL.before_revision,
      after_revision: PAIR_DETAIL.after_revision,
      source_url: PAIR_DETAIL.source_url,
      changes_total: PAIR_DETAIL.changes_total,
      callsites_admitted: PAIR_DETAIL.callsites_admitted,
      callsites_broken: PAIR_DETAIL.callsites_broken,
      clean_callsites_omitted: PAIR_DETAIL.clean_callsites_omitted,
    },
  ],
};
