"""The scorer, checked against a corpus small enough to grade by hand.

Every expected number in this file was worked out on paper from the fixture below before the module
was run, which is the only way a test of a metric is worth anything: a test that asserts whatever
the implementation returned proves the implementation is deterministic, not that it is right.

The fixture is built directly from :mod:`callsite_impact.domain` types. It never calls the
classifier, so a change in classification rules cannot move these numbers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from callsite_impact.domain import (
    Callsite,
    CallsiteFacts,
    CompilerLabel,
    Expressibility,
    Finding,
    RunSummary,
    SpecChange,
    SpecPair,
    VendorSpec,
    Verdict,
)
from callsite_impact.evaluate.report import (
    EvaluationArtifact,
    KillCriterion,
    build_report,
    count_unclassified,
    evaluate_kill_criterion,
    write_report,
)
from callsite_impact.evaluate.scorer import collapse_verdict, score

OPERATION = "POST /payments"
ACME_PAIR = "acme-v1-v2"
GLOBEX_PAIR = "globex-v3-v4"


def make_change(
    change_id: str = "request-property-removed",
    level: int = 3,
    expressibility: Expressibility = Expressibility.TYPE_EXPRESSIBLE,
) -> SpecChange:
    return SpecChange(
        change_id=change_id,
        level=level,
        method="POST",
        path="/payments",
        text=f"{change_id} at /payments",
        expressibility=expressibility,
    )


def make_callsite(callsite_id: str, vendor: str, pair_id: str = ACME_PAIR) -> Callsite:
    return Callsite(
        callsite_id=callsite_id,
        pair_id=pair_id,
        vendor=vendor,
        file=f"harness/src/{callsite_id}.ts",
        line=12,
        operation_key=OPERATION,
        facts=CallsiteFacts(operation_key=OPERATION),
        generator_seed=7,
    )


def make_finding(
    callsite_id: str,
    verdict: Verdict,
    *,
    pair_id: str = ACME_PAIR,
    line: int = 12,
) -> Finding:
    """A finding anchored by default; pass ``line=0`` to build an unanchorable one."""
    return Finding(
        callsite_id=callsite_id,
        pair_id=pair_id,
        verdict=verdict,
        rule="test.fixture",
        reason="touches_changed_property_type",
        change=make_change(),
        callsite_file=f"harness/src/{callsite_id}.ts",
        callsite_line=line,
    )


def make_label(callsite_id: str, code: str = "TS2345") -> CompilerLabel:
    return CompilerLabel(
        callsite_id=callsite_id,
        file=f"harness/src/{callsite_id}.ts",
        line=12,
        column=5,
        ts_error_code=code,
        message="Argument of type X is not assignable to parameter of type Y.",
    )


# ------------------------------------------------------------------------------ the graded fixture
#
# Ten call sites over two vendors. Truth and prediction for each, worked out by hand:
#
#   id   vendor   truth      predicted     strict      abstaining
#   a1   acme     impacted   IMPACTED      TP          TP
#   a2   acme     impacted   UNKNOWN       FN          excluded
#   a3   acme     impacted   UNAFFECTED    FN          FN
#   a4   acme     clean      IMPACTED      FP          FP
#   a5   acme     clean      UNAFFECTED    TN          TN
#   a6   acme     clean      UNKNOWN       TN          excluded
#   g1   globex   impacted   IMPACTED      TP          TP
#   g2   globex   clean      UNAFFECTED    TN          TN        (no FINDINGS at all)
#   g3   globex   clean      IMPACTED      FP          FP
#   g4   globex   impacted   IMPACTED      TP          TP

ACME = ["a1", "a2", "a3", "a4", "a5", "a6"]
GLOBEX = ["g1", "g2", "g3", "g4"]


CALLSITES: list[Callsite] = [make_callsite(cid, "acme") for cid in ACME] + [
    make_callsite(cid, "globex", pair_id=GLOBEX_PAIR) for cid in GLOBEX
]

# a3 carries two diagnostics, so the tests prove truth is per call site and not per label.
LABELS: list[CompilerLabel] = [
    make_label("a1"),
    make_label("a2"),
    make_label("a3"),
    make_label("a3", code="TS2339"),
    make_label("g1"),
    make_label("g4"),
]

# Eleven candidate pairs. a2 and g1 exercise the two interesting collapses.
FINDINGS: list[Finding] = [
    make_finding("a1", Verdict.IMPACTED),
    make_finding("a2", Verdict.UNAFFECTED),
    make_finding("a2", Verdict.UNKNOWN),
    make_finding("a3", Verdict.UNAFFECTED),
    make_finding("a4", Verdict.IMPACTED),
    make_finding("a5", Verdict.UNAFFECTED),
    make_finding("a6", Verdict.UNKNOWN),
    make_finding("g1", Verdict.UNKNOWN, pair_id=GLOBEX_PAIR),
    make_finding("g1", Verdict.IMPACTED, pair_id=GLOBEX_PAIR),
    make_finding("g3", Verdict.IMPACTED, pair_id=GLOBEX_PAIR),
    make_finding("g4", Verdict.IMPACTED, pair_id=GLOBEX_PAIR),
]


# --------------------------------------------------------------------------------- collapse rule


def test_impacted_beats_unknown_and_unaffected() -> None:
    """A tool that says "this breaks" about one change has told you the call site breaks."""
    assert collapse_verdict([Verdict.UNAFFECTED, Verdict.UNKNOWN, Verdict.IMPACTED]) is (
        Verdict.IMPACTED
    )


def test_unknown_beats_unaffected() -> None:
    """Calling a call site safe when one reaching change is inexpressible launders ignorance."""
    assert collapse_verdict([Verdict.UNAFFECTED, Verdict.UNKNOWN]) is Verdict.UNKNOWN


def test_silence_collapses_to_unaffected() -> None:
    """Otherwise a classifier could raise its precision by emitting fewer FINDINGS."""
    assert collapse_verdict([]) is Verdict.UNAFFECTED


def test_callsite_with_no_findings_is_scored_as_a_prediction() -> None:
    pooled = score(FINDINGS, LABELS, CALLSITES).pooled
    assert pooled.callsites == 10
    assert pooled.strict.counts.total == 10, "g2 has no FINDINGS and must still be scored"


# ----------------------------------------------------------------------------- pooled, strict view


def test_pooled_truth_is_per_callsite_not_per_label() -> None:
    pooled = score(FINDINGS, LABELS, CALLSITES).pooled
    assert len(LABELS) == 6
    assert pooled.truly_impacted == 5
    assert pooled.truly_clean == 5


def test_pooled_strict_counts() -> None:
    strict = score(FINDINGS, LABELS, CALLSITES).pooled.strict
    assert (strict.counts.true_positives, strict.counts.false_positives) == (3, 2)
    assert (strict.counts.false_negatives, strict.counts.true_negatives) == (2, 3)
    assert strict.callsites_excluded_as_abstention == 0


def test_pooled_strict_rates() -> None:
    strict = score(FINDINGS, LABELS, CALLSITES).pooled.strict
    assert strict.false_negative_rate == pytest.approx(2 / 5)
    assert strict.false_positive_rate == pytest.approx(2 / 5)
    assert strict.precision == pytest.approx(3 / 5)
    assert strict.recall == pytest.approx(3 / 5)
    assert strict.f1 == pytest.approx(0.6)


def test_unknown_on_a_clean_callsite_is_not_a_false_positive() -> None:
    """a6 abstains on a clean call site. ADR-001 defines FP as *reported IMPACTED*, and it was not.

    Counting abstentions as false positives would make the abstention class look like noise; the
    whole claim of ADR-001 is that it is a third answer.
    """
    strict = score(FINDINGS, LABELS, CALLSITES).pooled.strict
    assert strict.counts.false_positives == 2, "a4 and g3; a6's abstention is not a third"


# ------------------------------------------------------------- the case the module exists for


def test_unknown_moves_strict_and_abstaining_apart() -> None:
    """a2 is truly impacted and the system abstained on it; a6 is clean and it abstained there too.

    Strict pays for both by keeping them in the matrix; abstaining drops them and the headline
    improves. Publishing only the second reading would be the flattering lie this test pins down.
    """
    pooled = score(FINDINGS, LABELS, CALLSITES).pooled

    assert pooled.strict.false_negative_rate == pytest.approx(2 / 5)
    assert pooled.abstaining.false_negative_rate == pytest.approx(1 / 4)
    assert pooled.strict.recall == pytest.approx(3 / 5)
    assert pooled.abstaining.recall == pytest.approx(3 / 4)
    abstaining_fnr = pooled.abstaining.false_negative_rate
    strict_fnr = pooled.strict.false_negative_rate
    assert abstaining_fnr is not None and strict_fnr is not None
    assert abstaining_fnr < strict_fnr, "dropping the abstentions can only flatter the headline"


def test_pooled_abstaining_counts() -> None:
    abstaining = score(FINDINGS, LABELS, CALLSITES).pooled.abstaining
    assert (abstaining.counts.true_positives, abstaining.counts.false_positives) == (3, 2)
    assert (abstaining.counts.false_negatives, abstaining.counts.true_negatives) == (1, 2)
    assert abstaining.counts.total == 8
    assert abstaining.callsites_excluded_as_abstention == 2


def test_pooled_abstaining_rates() -> None:
    abstaining = score(FINDINGS, LABELS, CALLSITES).pooled.abstaining
    assert abstaining.precision == pytest.approx(3 / 5)
    assert abstaining.recall == pytest.approx(3 / 4)
    assert abstaining.false_positive_rate == pytest.approx(2 / 4)
    assert abstaining.f1 == pytest.approx(2 * 0.6 * 0.75 / 1.35)


def test_predicted_verdict_tallies() -> None:
    pooled = score(FINDINGS, LABELS, CALLSITES).pooled
    assert (pooled.predicted_impacted, pooled.predicted_unaffected, pooled.predicted_unknown) == (
        5,
        3,
        2,
    )


# ----------------------------------------------------------------------------- abstention rate


def test_abstention_rate_is_pair_level_not_callsite_level() -> None:
    """ADR-001 defines it over (call site x change) pairs. The call-site count is smaller here."""
    pooled = score(FINDINGS, LABELS, CALLSITES).pooled
    assert pooled.candidate_pairs == 11
    assert pooled.unknown_pairs == 3, "a2, a6 and g1 each carry one UNKNOWN pair"
    assert pooled.abstention_rate == pytest.approx(3 / 11)
    assert pooled.predicted_unknown == 2, "g1 collapses to IMPACTED despite carrying an UNKNOWN"


def test_unanchored_finding_is_suppressed_and_counted_as_abstention() -> None:
    """CLAUDE.md rule 3: an unanchorable verdict is suppressed, and ADR-001 counts it as abstention.

    a4 is clean and its only finding claims IMPACTED without a line. The claim must not reach the
    confusion matrix, and it must not vanish from the abstention denominator either.
    """
    unanchored = [make_finding("a4", Verdict.IMPACTED, line=0)]
    pooled = score(unanchored, LABELS, CALLSITES).pooled
    assert pooled.predicted_impacted == 0
    assert pooled.strict.counts.false_positives == 0
    assert pooled.suppressed_pairs == 1
    assert pooled.unknown_pairs == 1
    assert pooled.abstention_rate == pytest.approx(1.0)


def test_declared_suppressed_pairs_enter_both_sides_of_the_rate() -> None:
    scored = score(FINDINGS, LABELS, CALLSITES, suppressed_pairs={"acme": 2})
    assert scored.pooled.candidate_pairs == 13
    assert scored.pooled.unknown_pairs == 5
    assert scored.pooled.abstention_rate == pytest.approx(5 / 13)


# ------------------------------------------------------------------------------------ per vendor


def test_per_vendor_scopes_are_named_and_sorted() -> None:
    scored = score(FINDINGS, LABELS, CALLSITES)
    assert [s.scope for s in scored.by_vendor] == ["acme", "globex"]


def test_acme_scope() -> None:
    acme = next(s for s in score(FINDINGS, LABELS, CALLSITES).by_vendor if s.scope == "acme")
    assert (acme.callsites, acme.truly_impacted, acme.truly_clean) == (6, 3, 3)
    assert (acme.strict.counts.true_positives, acme.strict.counts.false_positives) == (1, 1)
    assert (acme.strict.counts.false_negatives, acme.strict.counts.true_negatives) == (2, 2)
    assert acme.strict.false_negative_rate == pytest.approx(2 / 3)
    assert acme.abstaining.false_negative_rate == pytest.approx(1 / 2)
    assert acme.abstention_rate == pytest.approx(2 / 7)


def test_globex_scope_has_no_abstentions_so_both_views_agree() -> None:
    globex = next(s for s in score(FINDINGS, LABELS, CALLSITES).by_vendor if s.scope == "globex")
    assert (globex.callsites, globex.truly_impacted) == (4, 2)
    assert globex.strict.false_negative_rate == pytest.approx(0.0)
    assert globex.strict.precision == pytest.approx(2 / 3)
    assert globex.strict.recall == pytest.approx(1.0)
    assert globex.abstaining.counts == globex.strict.counts
    assert globex.abstention_rate == pytest.approx(1 / 4)


def test_vendor_counts_sum_to_pooled() -> None:
    scored = score(FINDINGS, LABELS, CALLSITES)
    assert sum(s.callsites for s in scored.by_vendor) == scored.pooled.callsites
    assert sum(s.candidate_pairs for s in scored.by_vendor) == scored.pooled.candidate_pairs
    assert (
        sum(s.strict.counts.true_positives for s in scored.by_vendor)
        == scored.pooled.strict.counts.true_positives
    )


# ------------------------------------------------------- empty denominators must not read as 0.0


def test_no_positive_predictions_gives_none_precision_not_zero() -> None:
    """TP=0 and FP=0. Precision is undefined, and 0.0 here would read as "predicted badly"."""
    all_clear = [make_finding(cid, Verdict.UNAFFECTED) for cid in ACME]
    all_clear += [make_finding(cid, Verdict.UNAFFECTED, pair_id=GLOBEX_PAIR) for cid in GLOBEX]
    strict = score(all_clear, LABELS, CALLSITES).pooled.strict

    assert strict.counts.true_positives == 0
    assert strict.counts.false_positives == 0
    assert strict.precision is None
    assert strict.f1 is None, "f1 cannot exist where precision does not"
    assert strict.recall == pytest.approx(0.0), "recall is measured: 5 breakages, none found"
    assert strict.false_negative_rate == pytest.approx(1.0)


def test_clean_corpus_gives_none_for_the_headline() -> None:
    """No compiler LABELS at all: the false-negative rate has no denominator.

    ``None`` matters more here than anywhere else. A run with nothing to find would otherwise
    publish a false-negative rate of 0.0 on the front page and read as a perfect score.
    """
    strict = score(FINDINGS, [], CALLSITES).pooled.strict
    assert strict.false_negative_rate is None
    assert strict.recall is None
    assert strict.f1 is None
    assert strict.false_positive_rate == pytest.approx(5 / 10), "five IMPACTED reports, all wrong"


def test_all_wrong_gives_a_measured_zero_f1() -> None:
    """TP=0 with positives predicted and breakages missed. 0.0 is a score here, not an absence."""
    sites = [make_callsite("a1", "acme"), make_callsite("a4", "acme")]
    wrong = [make_finding("a4", Verdict.IMPACTED), make_finding("a1", Verdict.UNAFFECTED)]
    strict = score(wrong, [make_label("a1")], sites).pooled.strict

    assert strict.precision == pytest.approx(0.0)
    assert strict.recall == pytest.approx(0.0)
    assert strict.f1 == pytest.approx(0.0)


def test_empty_corpus_yields_no_rates_at_all() -> None:
    pooled = score([], [], []).pooled
    assert pooled.callsites == 0
    assert pooled.abstention_rate is None
    assert pooled.strict.precision is None
    assert pooled.strict.false_positive_rate is None


# ------------------------------------------------------------------------------- corpus integrity


def test_label_for_an_unadmitted_callsite_is_an_error() -> None:
    """Oracle and generator disagreeing about the corpus invalidates every number downstream."""
    with pytest.raises(ValueError, match="not in the admitted corpus"):
        score(FINDINGS, [make_label("ghost")], CALLSITES)


def test_finding_for_an_unadmitted_callsite_is_an_error() -> None:
    with pytest.raises(ValueError, match="not in the admitted corpus"):
        score([make_finding("ghost", Verdict.IMPACTED)], LABELS, CALLSITES)


def test_suppressed_pairs_for_an_unknown_vendor_is_an_error() -> None:
    with pytest.raises(ValueError, match="unknown vendor"):
        score(FINDINGS, LABELS, CALLSITES, suppressed_pairs={"initech": 1})


# --------------------------------------------------------------------------------- kill criterion


def test_kill_criterion_counts_callsites_not_labels() -> None:
    killed = evaluate_kill_criterion(LABELS, CALLSITES)
    assert killed.observed_breakages == 5, "a3 has two LABELS and is one breakage"
    assert killed.observed_vendors == 2
    assert killed.passed is False


def test_kill_criterion_requires_both_conditions() -> None:
    assert KillCriterion(observed_breakages=200, observed_vendors=2).passed is False
    assert KillCriterion(observed_breakages=59, observed_vendors=9).passed is False
    assert KillCriterion(observed_breakages=60, observed_vendors=3).passed is True


def test_kill_criterion_threshold_cannot_be_lowered() -> None:
    """The literal types are the enforcement. ADR-001 says the criterion is not relaxed."""
    with pytest.raises(ValueError, match="threshold"):
        KillCriterion(threshold=10, observed_breakages=10, observed_vendors=3)  # type: ignore[arg-type]


def test_kill_criterion_passed_cannot_be_hand_set() -> None:
    """``passed`` is derived on every access, so a supplied value is accepted and then ignored."""
    killed = KillCriterion.model_validate(
        {"observed_breakages": 0, "observed_vendors": 0, "passed": True}
    )
    assert killed.passed is False


def test_vendors_are_counted_over_breaking_callsites_only() -> None:
    """A corpus that spans vendors but only breaks on one has not shown the claim across vendors."""
    sites = [make_callsite("a1", "acme"), make_callsite("g1", "globex")]
    assert evaluate_kill_criterion([make_label("a1")], sites).observed_vendors == 1


# ----------------------------------------------------------------------------------- the artifact


def make_pair(pair_id: str, vendor: str) -> SpecPair:
    def rev(tag: str) -> VendorSpec:
        return VendorSpec(
            vendor=vendor,
            service="checkout",
            revision=tag,
            revision_date="2026-01-01",
            source_url=f"https://example.invalid/{vendor}/{tag}.yaml",
            licence="MIT",
            sha256=f"{tag}-sha",
            local_path=f"corpus/{vendor}/{tag}.yaml",
        )

    return SpecPair(
        pair_id=pair_id, vendor=vendor, service="checkout", before=rev("v1"), after=rev("v2")
    )


def build(generated_at: str = "2026-09-12T00:00:00Z") -> EvaluationArtifact:
    run = RunSummary(
        pairs=2,
        vendors=("acme", "globex"),
        callsites_generated=12,
        callsites_admitted=len(CALLSITES),
        callsites_discarded=2,
        compiler_breakages=5,
        compiler_clean=5,
        candidate_findings=len(FINDINGS),
    )
    return build_report(
        generated_at=generated_at,
        run=run,
        pairs=[make_pair(ACME_PAIR, "acme"), make_pair(GLOBEX_PAIR, "globex")],
        changes=[
            make_change(),
            make_change("api-rate-limit-changed", 1, Expressibility.UNCLASSIFIED),
            make_change("request-property-max-length-decreased", 3, Expressibility.UNCLASSIFIED),
        ],
        callsites=CALLSITES,
        labels=LABELS,
        system_findings=FINDINGS,
        baseline_touches_findings=[
            make_finding(cs.callsite_id, Verdict.IMPACTED) for cs in CALLSITES
        ],
        baseline_err_findings=[make_finding("a1", Verdict.IMPACTED)],
    )


def test_artifact_publishes_both_readings_of_the_oracle() -> None:
    artifact = build()
    assert artifact.kill_criterion.observed_breakages == 5
    assert artifact.total_compiler_labels == 6, "the loose count sits beside the strict one"


def test_artifact_hoists_the_headline_without_duplicating_it() -> None:
    artifact = build()
    pooled = artifact.system.pooled
    assert artifact.headline_false_negative_rate == pooled.strict.false_negative_rate
    assert artifact.abstention_rate == artifact.system.pooled.abstention_rate
    assert artifact.headline_false_negative_rate == pytest.approx(2 / 5)


def test_artifact_scores_both_baselines_on_the_same_corpus() -> None:
    artifact = build()
    naive = artifact.baseline_touches_changed_operation.pooled
    assert naive.callsites == artifact.system.pooled.callsites == 10
    assert naive.strict.recall == pytest.approx(1.0), "flagging everything cannot miss a breakage"
    assert naive.strict.precision == pytest.approx(5 / 10)
    assert naive.abstention_rate == pytest.approx(0.0), "a differ has no third answer"


def test_artifact_counts_unclassified_changes() -> None:
    assert build().unclassified_changes == 2


def test_count_unclassified_is_by_expressibility_not_by_level() -> None:
    changes = [make_change("x", 3, Expressibility.NOT_TYPE_EXPRESSIBLE), make_change()]
    assert count_unclassified(changes) == 0


def test_per_pair_counts_split_the_corpus() -> None:
    per_pair = {p.pair_id: p for p in build().per_pair}
    assert per_pair["acme-v1-v2"].callsites_admitted == 6
    assert per_pair["acme-v1-v2"].breakage_callsites == 3
    assert per_pair["acme-v1-v2"].compiler_labels == 4, "a3 contributes two diagnostics"
    assert per_pair["globex-v3-v4"].breakage_callsites == 2


def test_artifact_records_the_provenance_of_both_pairs() -> None:
    provenance = build().provenance
    assert [p.vendor for p in provenance] == ["acme", "globex"]
    assert provenance[0].before_sha256 == "v1-sha"
    assert provenance[0].licence == "MIT"


def test_generated_at_comes_from_the_caller() -> None:
    """No clock inside the module: same inputs, byte-identical JSON."""
    first = build(generated_at="2026-09-12T00:00:00Z")
    second = build(generated_at="2026-09-12T00:00:00Z")
    assert first.model_dump_json() == second.model_dump_json()
    assert first.generated_at == "2026-09-12T00:00:00Z"


def test_write_report_round_trips(tmp_path: Path) -> None:
    artifact = build()
    written = write_report(artifact, tmp_path / "nested" / "evaluation.json")
    text = written.read_text(encoding="utf-8")

    assert text.endswith("\n")
    assert EvaluationArtifact.model_validate_json(text) == artifact
