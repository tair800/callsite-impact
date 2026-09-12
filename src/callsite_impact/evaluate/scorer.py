"""Scoring the system against the compiler, in the two views ADR-001 requires.

This module decides what the README is allowed to say, so it is written to be unflattering by
default. Two properties are load-bearing and neither is an implementation detail:

**Predictions and truth do not have the same shape.** The classifier emits one :class:`Finding` per
(call site, change) pair; ``tsc`` labels a *call site*. Comparing them requires collapsing the pairs
down to one verdict per call site, and the collapse rule is a judgement that changes the numbers, so
it is written down in :func:`collapse_verdict` rather than left in the code for a reader to
reverse-engineer.

**UNKNOWN is not a wrong answer.** Scoring an abstention as an error understates the system;
dropping abstentions from the denominator overstates it. Both readings are therefore computed
for every scope
and both are carried in the artifact — :attr:`ScopeMetrics.strict` and
:attr:`ScopeMetrics.abstaining`. Nothing in this module offers a way to publish one without the
other.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from callsite_impact.domain import Callsite, CompilerLabel, Finding, Verdict

__all__ = [
    "POOLED",
    "ConfusionCounts",
    "ScopeMetrics",
    "ScoreReport",
    "ViewMetrics",
    "collapse_predictions",
    "collapse_verdict",
    "impacted_callsite_ids",
    "score",
]

POOLED = "pooled"
"""Scope name for the whole corpus. Not a vendor, so it cannot collide with one."""


class _Frozen(BaseModel):
    """Scores are a record of a measurement. Nothing edits one after the run that produced it."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# ------------------------------------------------------------------------------------- rate helpers


def _ratio(numerator: int, denominator: int) -> float | None:
    """A rate, or ``None`` when there is nothing to take a rate over.

    Returning ``0.0`` for an empty denominator is the failure mode this helper exists to prevent: a
    precision of ``0.0`` on a run that never predicted a positive is indistinguishable in a table
    from a precision of ``0.0`` on a run that predicted fifty and got all fifty wrong. One is an
    absent measurement and the other is a bad score. ``None`` renders as an em dash and forces the
    reader to notice the difference.
    """
    if denominator == 0:
        return None
    return numerator / denominator


def _f1(precision: float | None, recall: float | None) -> float | None:
    """Harmonic mean, propagating the absence of either input.

    ``0.0`` is returned only when both inputs are a *measured* zero — positives were predicted and
    all of them were wrong, and real breakages existed and none were found. That zero is a score.
    When either input is ``None`` there is no measurement to combine and the result is ``None``.
    """
    if precision is None or recall is None:
        return None
    total = precision + recall
    if total == 0.0:
        return 0.0
    return 2 * precision * recall / total


# ----------------------------------------------------------------------------------- metric records


class ConfusionCounts(_Frozen):
    """Raw counts, carried alongside every rate so a reader can recompute the rate.

    Rates in a portfolio README are cheap to fake and hard to check. Counts are not.
    """

    true_positives: int = Field(ge=0)
    false_positives: int = Field(ge=0)
    true_negatives: int = Field(ge=0)
    false_negatives: int = Field(ge=0)

    @property
    def total(self) -> int:
        """Call sites in this view. Below the admitted count whenever abstentions were excluded."""
        return (
            self.true_positives + self.false_positives + self.true_negatives + self.false_negatives
        )


class ViewMetrics(_Frozen):
    """One reading of one scope: the counts, and the rates ADR-001 declared over them.

    Every rate here is optional because every rate here has a denominator that a small or degenerate
    corpus can empty. See :func:`_ratio`.
    """

    counts: ConfusionCounts
    false_negative_rate: float | None
    """The headline. Compiler-labelled breakages the system failed to report, over all of them."""
    false_positive_rate: float | None
    """Call sites reported IMPACTED that the compiler left clean, over all clean call sites."""
    precision: float | None
    recall: float | None
    f1: float | None
    callsites_excluded_as_abstention: int = Field(ge=0)
    """Call sites dropped from this view because the system abstained. Always 0 in the strict view.

    Published because it is the abstaining view's honest denominator disclosure: a system that
    abstains on everything it would have got wrong scores perfectly here, and this count is the
    number that gives that away.
    """


class ScopeMetrics(_Frozen):
    """Everything measured for one vendor, or for the pooled corpus."""

    scope: str
    """A vendor name, or :data:`POOLED`."""
    callsites: int = Field(ge=0)
    truly_impacted: int = Field(ge=0)
    """Call sites on which ``tsc`` emitted at least one error. Truth, not a prediction."""
    truly_clean: int = Field(ge=0)
    predicted_impacted: int = Field(ge=0)
    predicted_unaffected: int = Field(ge=0)
    predicted_unknown: int = Field(ge=0)
    strict: ViewMetrics
    """UNKNOWN treated as a non-report: a false negative wherever the compiler found a breakage."""
    abstaining: ViewMetrics
    """Call sites the system abstained on are removed from the confusion matrix entirely."""
    candidate_pairs: int = Field(ge=0)
    """(call site x change) pairs the predictor *emitted a finding for*, plus the pairs it declared
    suppressed for lack of an anchor. The abstention denominator.

    Not necessarily every pair the predictor looked at. A predictor that walks the full join and
    stays silent on the pairs it rejects -- :func:`~callsite_impact.evaluate.baselines.
    naive_err_level_only` is exactly that, dropping sub-ERR pairs without emitting -- reports a
    smaller number here than it considered, because silence is indistinguishable from a pair never
    enumerated once the findings are all the scorer has. Only ``suppressed_pairs`` makes a
    non-emitted pair visible, and only the caller can declare it. This does not move precision,
    recall or the false-negative rate, which are call-site-level and share one denominator across
    the system and both baselines; it does mean two predictors over one corpus can publish different
    ``candidate_pairs``, and so different abstention denominators.
    """
    unknown_pairs: int = Field(ge=0)
    """Pairs returned UNKNOWN, plus every suppressed pair. ADR-001: a suppressed unanchorable
    claim counts as an abstention, never as a hit."""
    suppressed_pairs: int = Field(ge=0)
    abstention_rate: float | None
    """``unknown_pairs / candidate_pairs``. Pair-level, as ADR-001 defines it -- deliberately
    not the call-site-level abstention count, which is smaller and would read better."""


class ScoreReport(_Frozen):
    """One scorer run over one prediction set. Produced the same way for system and baseline.

    A baseline that were scored by a different function, or on a different denominator, would be a
    baseline chosen to lose. Everything here goes through :func:`score`.
    """

    pooled: ScopeMetrics
    by_vendor: tuple[ScopeMetrics, ...]


# -------------------------------------------------------------------------------------- collapsing


def collapse_verdict(verdicts: Iterable[Verdict]) -> Verdict:
    """Reduce every verdict about one call site to the one verdict the call site gets.

    The order is IMPACTED, then UNKNOWN, then UNAFFECTED, and the ordering is the decision:

    * **Any IMPACTED wins.** A tool that says "this breaks" about one change and "unknown" about
      another has told you the call site breaks. Letting the abstention dilute the breakage report
      would lose the only finding that matters.
    * **UNKNOWN beats UNAFFECTED.** If one change reaching this call site is of a class the type
      system cannot express, then a clean compile is not evidence about that change, and calling the
      call site UNAFFECTED would launder ignorance into a safety claim.
    * **UNAFFECTED only when every change was ruled on and none reached the usage.**

    A call site with no findings at all collapses to UNAFFECTED. That is a real prediction and is
    scored as one: the system was given the call site and the diff and reported no breakage on it.
    Treating silence as "no answer" would let a classifier raise its precision by emitting less.
    """
    seen = set(verdicts)
    if Verdict.IMPACTED in seen:
        return Verdict.IMPACTED
    if Verdict.UNKNOWN in seen:
        return Verdict.UNKNOWN
    return Verdict.UNAFFECTED


def collapse_predictions(
    findings: Sequence[Finding], callsites: Sequence[Callsite]
) -> dict[str, Verdict]:
    """Per-call-site predictions for every admitted call site, including the ones nothing touched.

    Unanchored findings are dropped here rather than scored. CLAUDE.md rule 3 says a verdict that
    cannot be anchored is suppressed and counted; this enforces it instead of trusting the producer
    to have done it, and :func:`score` counts what was dropped into the abstention rate.
    """
    by_callsite: defaultdict[str, list[Verdict]] = defaultdict(list)
    for finding in findings:
        if finding.anchored:
            by_callsite[finding.callsite_id].append(finding.verdict)
    return {cs.callsite_id: collapse_verdict(by_callsite[cs.callsite_id]) for cs in callsites}


def impacted_callsite_ids(
    labels: Sequence[CompilerLabel], callsites: Sequence[Callsite]
) -> frozenset[str]:
    """Ground truth: a call site is impacted iff at least one compiler label names it.

    ``callsites`` is required rather than inferred from the labels so that a call site with no label
    is *known clean* instead of unknown. Without it the scorer would have no negatives and a system
    that reported every call site as IMPACTED would be unfalsifiable.

    Raises:
        ValueError: if a label names a call site that was never admitted. That means the oracle and
            the generator disagree about which corpus ran, and any number computed through the
            disagreement is indefensible -- so it fails loudly rather than being dropped.
    """
    admitted = {cs.callsite_id for cs in callsites}
    unknown = sorted({label.callsite_id for label in labels} - admitted)
    if unknown:
        raise ValueError(
            f"compiler labels name {len(unknown)} call site(s) not in the admitted corpus: "
            f"{unknown[:5]}"
        )
    return frozenset(label.callsite_id for label in labels)


# -------------------------------------------------------------------------------------- the scorer


def _view(
    *,
    predictions: Mapping[str, Verdict],
    truth: frozenset[str],
    abstaining: bool,
) -> ViewMetrics:
    """Build one confusion matrix and its rates.

    The two views differ in exactly one place: whether an UNKNOWN call site is scored as "not
    reported as breaking" (strict) or removed from the matrix (abstaining).

    The strict view is pessimistic where the headline lives and neutral elsewhere, on purpose.
    An UNKNOWN on a truly impacted call site is a false negative, because the system did not report
    a breakage that exists. An UNKNOWN on a clean call site is *not* a false positive, because
    ADR-001 defines a false positive as a call site *reported IMPACTED*, and an abstention is not
    that. Inflating false positives with abstentions would make the abstention class look like
    noise, when the whole point of ADR-001 is that it is a separate answer.
    """
    tp = fp = tn = fn = excluded = 0
    for callsite_id, verdict in predictions.items():
        truly_impacted = callsite_id in truth
        if verdict is Verdict.UNKNOWN and abstaining:
            excluded += 1
            continue
        if verdict is Verdict.IMPACTED:
            if truly_impacted:
                tp += 1
            else:
                fp += 1
        elif truly_impacted:
            fn += 1
        else:
            tn += 1

    counts = ConfusionCounts(
        true_positives=tp, false_positives=fp, true_negatives=tn, false_negatives=fn
    )
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    return ViewMetrics(
        counts=counts,
        false_negative_rate=_ratio(fn, tp + fn),
        false_positive_rate=_ratio(fp, fp + tn),
        precision=precision,
        recall=recall,
        f1=_f1(precision, recall),
        callsites_excluded_as_abstention=excluded,
    )


def _scope(
    *,
    name: str,
    callsites: Sequence[Callsite],
    findings: Sequence[Finding],
    truth: frozenset[str],
    suppressed: int,
) -> ScopeMetrics:
    """Score one vendor, or the pooled corpus, from the slice of the run that belongs to it."""
    predictions = collapse_predictions(findings, callsites)
    scope_truth = frozenset(cs.callsite_id for cs in callsites) & truth

    anchored = [f for f in findings if f.anchored]
    unanchored = len(findings) - len(anchored)
    # A suppressed pair is an abstention on both sides of the ratio: ADR-001 refuses to let an
    # unanchorable claim disappear from the denominator, which would make abstention look rarer.
    abstained = sum(1 for f in anchored if f.verdict is Verdict.UNKNOWN) + unanchored + suppressed
    candidates = len(findings) + suppressed

    predicted = list(predictions.values())
    return ScopeMetrics(
        scope=name,
        callsites=len(callsites),
        truly_impacted=len(scope_truth),
        truly_clean=len(callsites) - len(scope_truth),
        predicted_impacted=predicted.count(Verdict.IMPACTED),
        predicted_unaffected=predicted.count(Verdict.UNAFFECTED),
        predicted_unknown=predicted.count(Verdict.UNKNOWN),
        strict=_view(predictions=predictions, truth=scope_truth, abstaining=False),
        abstaining=_view(predictions=predictions, truth=scope_truth, abstaining=True),
        candidate_pairs=candidates,
        unknown_pairs=abstained,
        suppressed_pairs=unanchored + suppressed,
        abstention_rate=_ratio(abstained, candidates),
    )


def score(
    findings: Sequence[Finding],
    labels: Sequence[CompilerLabel],
    callsites: Sequence[Callsite],
    *,
    suppressed_pairs: Mapping[str, int] | None = None,
) -> ScoreReport:
    """Score one prediction set against the compiler, pooled and per vendor.

    Args:
        findings: one per (call site, change) pair the predictor considered. The system and both
            baselines are scored through this same function, on the same corpus, so that a baseline
            delta is a difference in the predictor and not a difference in the scoring.
        labels: what ``tsc`` emitted. Ground truth.
        callsites: every *admitted* call site. Required, and not derivable from the other two: it is
            what makes an unlabelled call site a true negative rather than an absent row.
        suppressed_pairs: vendor -> count of pairs the predictor dropped before emitting, because
            they could not be anchored. Added to both the abstention numerator and the candidate
            denominator. Defaults to none suppressed, which is an assertion by the caller; findings
            that arrive already unanchored are detected here and counted without being declared.

    Returns:
        Pooled and per-vendor metrics in both the strict and the abstaining reading.

    Raises:
        ValueError: if a label or a finding names a call site that is not in ``callsites``.
    """
    truth = impacted_callsite_ids(labels, callsites)
    vendor_of = {cs.callsite_id: cs.vendor for cs in callsites}

    stray = sorted({f.callsite_id for f in findings} - vendor_of.keys())
    if stray:
        raise ValueError(
            f"findings name {len(stray)} call site(s) not in the admitted corpus: {stray[:5]}"
        )

    declared = dict(suppressed_pairs or {})
    vendors = sorted({cs.vendor for cs in callsites})
    unknown_vendors = sorted(declared.keys() - set(vendors))
    if unknown_vendors:
        raise ValueError(f"suppressed_pairs names unknown vendor(s): {unknown_vendors}")

    by_vendor = tuple(
        _scope(
            name=vendor,
            callsites=[cs for cs in callsites if cs.vendor == vendor],
            findings=[f for f in findings if vendor_of[f.callsite_id] == vendor],
            truth=truth,
            suppressed=declared.get(vendor, 0),
        )
        for vendor in vendors
    )
    pooled = _scope(
        name=POOLED,
        callsites=list(callsites),
        findings=list(findings),
        truth=truth,
        suppressed=sum(declared.values()),
    )
    return ScoreReport(pooled=pooled, by_vendor=by_vendor)
