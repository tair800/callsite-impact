"""The predeclared baselines, and the one comparison the README is built on.

The centrepiece is :func:`test_naive_flags_a_callsite_the_system_correctly_clears`. Two call sites
sit on the same changed operation; one touches the removed property and one does not. A spec differ
cannot tell them apart, so the naive baseline reports both. That single false positive, multiplied
across a real corpus, is the entire value proposition of parsing the call site -- and if it ever
stops being true, this test is where it shows up.

The system's findings here are written by hand rather than produced by the classifier. That keeps
the file independent of classification rules and keeps it honest about what it is measuring: the
*shape* of the difference between a differ and a call-site-aware tool, on a corpus whose answers are
stated in the fixture.
"""

from __future__ import annotations

import pytest

from callsite_impact.domain import (
    Callsite,
    CallsiteFacts,
    CompilerLabel,
    Expressibility,
    Finding,
    PropertyAccess,
    SpecChange,
    Verdict,
)
from callsite_impact.evaluate.baselines import (
    BASELINE_IMPACTED_REASON,
    candidate_pairs,
    naive_err_level_only,
    naive_touches_changed_operation,
)
from callsite_impact.evaluate.scorer import score

PAIR = "acme-v71-v72"
VENDOR = "acme"

# The corpus, and every answer in it, stated up front:
#
#   change  operation           id                                 level  expressible
#   A       POST /payments      request-property-removed             3    yes
#   B       GET /accounts       request-property-max-length-decreased 3   no
#   C       GET /health         response-property-added              1    yes
#
#   callsite  operation        touches the changed thing?   tsc
#   p1        POST /payments   yes, sets legacyToken        error   <- truly impacted
#   p2        POST /payments   no                           clean   <- the headline false positive
#   a1        GET /accounts    n/a, maxLength is invisible  clean
#   h1        GET /health      no                           clean
#   d1        DELETE /cards    no change on this operation  clean

CHANGE_A = SpecChange(
    change_id="request-property-removed",
    level=3,
    method="POST",
    path="/payments",
    text="removed the request property 'legacyToken'",
    property_path=("legacyToken",),
    expressibility=Expressibility.TYPE_EXPRESSIBLE,
)
CHANGE_B = SpecChange(
    change_id="request-property-max-length-decreased",
    level=3,
    method="GET",
    path="/accounts",
    text="the 'reference' request property's maxLength was decreased from 80 to 40",
    property_path=("reference",),
    expressibility=Expressibility.NOT_TYPE_EXPRESSIBLE,
)
CHANGE_C = SpecChange(
    change_id="response-property-added",
    level=1,
    method="GET",
    path="/health",
    text="added the optional response property 'region'",
    property_path=("region",),
    expressibility=Expressibility.TYPE_EXPRESSIBLE,
)
CHANGES = [CHANGE_A, CHANGE_B, CHANGE_C]


def make_callsite(callsite_id: str, operation_key: str, touches: str | None = None) -> Callsite:
    accesses = (PropertyAccess(path=(touches,), line=14, column=9),) if touches is not None else ()
    return Callsite(
        callsite_id=callsite_id,
        pair_id=PAIR,
        vendor=VENDOR,
        file=f"harness/src/{callsite_id}.ts",
        line=12,
        operation_key=operation_key,
        facts=CallsiteFacts(operation_key=operation_key, request_properties=accesses),
        generator_seed=3,
    )


P1 = make_callsite("p1", "POST /payments", touches="legacyToken")
P2 = make_callsite("p2", "POST /payments")
A1 = make_callsite("a1", "GET /accounts", touches="reference")
H1 = make_callsite("h1", "GET /health")
D1 = make_callsite("d1", "DELETE /cards")
CALLSITES = [P1, P2, A1, H1, D1]

LABELS = [
    CompilerLabel(
        callsite_id="p1",
        file="harness/src/p1.ts",
        line=14,
        column=9,
        ts_error_code="TS2353",
        message="Object literal may only specify known properties; 'legacyToken' does not exist.",
    )
]


def system_finding(
    callsite: Callsite, change: SpecChange, verdict: Verdict, reason: str, rule: str
) -> Finding:
    """A hand-written stand-in for the classifier's output on this fixture."""
    return Finding(
        callsite_id=callsite.callsite_id,
        pair_id=PAIR,
        verdict=verdict,
        rule=rule,
        reason=reason,  # type: ignore[arg-type]
        change=change,
        callsite_file=callsite.file,
        callsite_line=14,
        callsite_column=9,
    )


SYSTEM_FINDINGS = [
    system_finding(
        P1, CHANGE_A, Verdict.IMPACTED, "sets_removed_request_property", "request_property_removed"
    ),
    system_finding(
        P2,
        CHANGE_A,
        Verdict.UNAFFECTED,
        "property_untouched_by_callsite",
        "request_property_removed",
    ),
    system_finding(
        A1,
        CHANGE_B,
        Verdict.UNKNOWN,
        "change_not_expressible_in_type_system",
        "not_type_expressible",
    ),
    system_finding(
        H1,
        CHANGE_C,
        Verdict.UNAFFECTED,
        "property_untouched_by_callsite",
        "response_property_added",
    ),
]


# --------------------------------------------------------------------------------------- the join


def test_candidate_pairs_joins_on_operation_only() -> None:
    pairs = candidate_pairs(CHANGES, CALLSITES)
    assert len(pairs) == 4
    assert [cs.callsite_id for cs, _ in pairs] == ["p1", "p2", "a1", "h1"]
    assert "d1" not in {cs.callsite_id for cs, _ in pairs}, "no change touches DELETE /cards"


def test_both_baselines_walk_the_same_join() -> None:
    """Different denominators would make the precision comparison meaningless."""
    join = {(cs.callsite_id, ch.change_id) for cs, ch in candidate_pairs(CHANGES, CALLSITES)}
    naive = {
        (f.callsite_id, f.change.change_id)
        for f in naive_touches_changed_operation(CHANGES, CALLSITES)
    }
    err = {(f.callsite_id, f.change.change_id) for f in naive_err_level_only(CHANGES, CALLSITES)}
    assert naive == join
    assert err <= join


def test_empty_inputs_produce_no_findings() -> None:
    assert naive_touches_changed_operation([], CALLSITES) == []
    assert naive_touches_changed_operation(CHANGES, []) == []
    assert naive_err_level_only([], CALLSITES) == []


# ---------------------------------------------------------------------------------- finding shape


def test_every_baseline_finding_is_anchored() -> None:
    """An unanchored finding is suppressed by the scorer, silently sparing the baseline."""
    assert all(f.anchored for f in naive_touches_changed_operation(CHANGES, CALLSITES))


def test_baseline_findings_carry_no_token_they_did_not_read() -> None:
    """The baseline never opened the source, so it has no column and no token to name."""
    findings = naive_touches_changed_operation(CHANGES, CALLSITES)
    assert all(f.callsite_column is None and f.callsite_token is None for f in findings)


def test_baseline_reason_is_the_documented_choice() -> None:
    findings = naive_touches_changed_operation(CHANGES, CALLSITES)
    assert {f.reason for f in findings} == {BASELINE_IMPACTED_REASON}


def test_baseline_rules_are_namespaced_and_name_no_system_branch() -> None:
    touches = naive_touches_changed_operation(CHANGES, CALLSITES)
    err = naive_err_level_only(CHANGES, CALLSITES)
    assert {f.rule for f in touches} == {"baseline.touches_changed_operation"}
    assert {f.rule for f in err} == {"baseline.err_level_only"}


def test_baselines_never_abstain() -> None:
    """A spec differ has no third answer. Its abstention rate is zero by construction."""
    findings = naive_touches_changed_operation(CHANGES, CALLSITES)
    assert {f.verdict for f in findings} == {Verdict.IMPACTED}
    assert score(findings, LABELS, CALLSITES).pooled.abstention_rate == pytest.approx(0.0)


# --------------------------------------------------------------------- the ERR filter, on its own


def test_err_baseline_drops_sub_err_changes() -> None:
    findings = naive_err_level_only(CHANGES, CALLSITES)
    assert [f.callsite_id for f in findings] == ["p1", "p2", "a1"]
    assert "response-property-added" not in {f.change.change_id for f in findings}


def test_err_baseline_silence_collapses_to_unaffected() -> None:
    """h1's only change is level 1, so the baseline says nothing; the scorer reads that as safe."""
    scored = score(naive_err_level_only(CHANGES, CALLSITES), LABELS, CALLSITES).pooled
    assert scored.predicted_impacted == 3
    assert scored.predicted_unaffected == 2, "h1 and d1"
    assert scored.callsites == 5, "silence does not shrink the denominator"


def test_err_filter_does_not_rescue_the_maxlength_false_positive() -> None:
    """oasdiff grades the maxLength decrease ERR, so the severity filter keeps flagging a1.

    This is the finding ADR-001 opened with: severity is about the API, not about the type system,
    and filtering on it cannot substitute for knowing what a compiler can see.
    """
    findings = naive_err_level_only(CHANGES, CALLSITES)
    assert "a1" in {f.callsite_id for f in findings}


# ------------------------------------------------------ the comparison the README leads with


def test_naive_flags_a_callsite_the_system_correctly_clears() -> None:
    """p2 sits on the changed operation and never touches the removed property. tsc says clean.

    The system reads the source and says UNAFFECTED. The baseline cannot read the source and says
    IMPACTED. One is a false positive and one is not, and the difference is not a tuning choice --
    it is the only thing separating this tool from a spec differ.
    """
    naive = score(naive_touches_changed_operation(CHANGES, CALLSITES), LABELS, CALLSITES).pooled
    system = score(SYSTEM_FINDINGS, LABELS, CALLSITES).pooled

    assert "p2" not in {label.callsite_id for label in LABELS}, "the compiler left p2 clean"
    assert naive.strict.counts.false_positives >= 1
    assert system.strict.counts.false_positives == 0


def test_the_full_baseline_comparison_on_this_fixture() -> None:
    """Every number below is read off the fixture table at the top of this file."""
    naive = score(naive_touches_changed_operation(CHANGES, CALLSITES), LABELS, CALLSITES).pooled
    err = score(naive_err_level_only(CHANGES, CALLSITES), LABELS, CALLSITES).pooled
    system = score(SYSTEM_FINDINGS, LABELS, CALLSITES).pooled

    assert (naive.truly_impacted, naive.truly_clean) == (1, 4)

    # Flag everything on a changed operation: nothing is missed, three of four flags are wrong.
    assert naive.strict.recall == pytest.approx(1.0)
    assert naive.strict.precision == pytest.approx(1 / 4)
    assert naive.strict.false_positive_rate == pytest.approx(3 / 4)

    # The differ's own severity filter removes one false positive and leaves two.
    assert err.strict.precision == pytest.approx(1 / 3)
    assert err.strict.recall == pytest.approx(1.0)

    # Reading the call site removes the rest -- at the cost of one abstention, published as such.
    assert system.strict.precision == pytest.approx(1.0)
    assert system.strict.recall == pytest.approx(1.0)
    assert system.strict.false_negative_rate == pytest.approx(0.0)
    assert system.abstention_rate == pytest.approx(1 / 4)
    assert system.predicted_unknown == 1


def test_the_system_pays_for_its_precision_with_an_abstention() -> None:
    """a1 is clean and the system refuses to say so, because maxLength is invisible to tsc.

    The strict view scores that refusal as a true negative -- it was not reported IMPACTED --
    but the abstaining view drops the call site entirely, and the gap between the denominators is
    the
    honest cost of the third verdict.
    """
    system = score(SYSTEM_FINDINGS, LABELS, CALLSITES).pooled
    assert system.strict.counts.total == 5
    assert system.abstaining.counts.total == 4
    assert system.abstaining.callsites_excluded_as_abstention == 1
