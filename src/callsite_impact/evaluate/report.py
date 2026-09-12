"""The evaluation artifact: the one file the README, the API and the UI are allowed to read.

Every number this repository publishes comes from here, and nothing in here is typed in by hand.
That is the point of the module: a figure in a README that no script produced cannot be checked, and
CLAUDE.md rule 10 forbids one.

Two things are structural rather than conventional:

* **``generated_at`` is a parameter.** No clock is read inside this module, so two runs over
  the same inputs produce byte-identical JSON apart from the string the caller passed. A
  committed artifact
  that changes on every run is an artifact whose diffs nobody reads.
* **The kill criterion cannot be lowered by writing to it.** :class:`KillCriterion` pins the
  threshold and the vendor count as literal types, and ``passed`` is derived rather than stored, so
  there is no field to set to ``True`` when the corpus comes up short.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from callsite_impact.domain import (
    Callsite,
    CompilerLabel,
    Expressibility,
    Finding,
    RunSummary,
    SpecChange,
    SpecPair,
)
from callsite_impact.evaluate.scorer import ScoreReport, impacted_callsite_ids, score

__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "KILL_THRESHOLD",
    "KILL_VENDORS_REQUIRED",
    "EvaluationArtifact",
    "KillCriterion",
    "PairCounts",
    "PairProvenance",
    "build_report",
    "count_unclassified",
    "evaluate_kill_criterion",
    "write_report",
]

ARTIFACT_SCHEMA_VERSION: Final = "1"

KILL_THRESHOLD: Final = 60
"""Compiler-verified call-site breakages required. Inherited verbatim from ADR-001."""

KILL_VENDORS_REQUIRED: Final = 3
"""Distinct vendors those breakages must span."""


class _Frozen(BaseModel):
    """The artifact is a record of a run. Nothing edits one after the run that produced it.

    ``extra="ignore"`` rather than ``"forbid"`` for one reason: the models here carry computed
    fields, which serialise into the JSON and would then be rejected as unexpected input if the
    artifact were read back. A committed artifact that its own schema cannot parse is not much of a
    schema. Ignoring them is also the stronger guarantee for :class:`KillCriterion` -- a caller may
    pass ``passed=True`` and it changes nothing, because the value is derived on every access.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")


# -------------------------------------------------------------------------------------- provenance


class PairProvenance(_Frozen):
    """What was actually run, pinned hard enough for a reader to fetch the same bytes.

    Flattened out of :class:`~callsite_impact.domain.SpecPair` rather than nested, because this
    block exists to be read by a human checking a claim, and the checksums are the part they check.
    """

    pair_id: str
    vendor: str
    service: str
    before_revision: str
    before_date: str | None
    before_sha256: str
    after_revision: str
    after_date: str | None
    after_sha256: str
    source_url: str
    licence: str


def _provenance(pair: SpecPair) -> PairProvenance:
    """Flatten one pair. ``source_url`` and ``licence`` are taken from the *after* revision.

    Both revisions of a vendor spec come from the same repository and licence in this corpus, so one
    of the two is redundant; the later one is kept because it is the one a reader will look up.
    """
    return PairProvenance(
        pair_id=pair.pair_id,
        vendor=pair.vendor,
        service=pair.service,
        before_revision=pair.before.revision,
        before_date=pair.before.revision_date,
        before_sha256=pair.before.sha256,
        after_revision=pair.after.revision,
        after_date=pair.after.revision_date,
        after_sha256=pair.after.sha256,
        source_url=pair.after.source_url,
        licence=pair.after.licence,
    )


# ------------------------------------------------------------------------------------ corpus counts


class PairCounts(_Frozen):
    """Per-pair corpus and oracle counts, so a single vendor cannot carry the whole result unseen.

    ``breakage_callsites`` and ``compiler_labels`` are both published because they are the strict
    and the loose reading of the same oracle output, and ADR-001 forbids swapping one for the other
    later: ``tsc`` can emit several errors on one call site, so the label count is always the larger
    and more flattering number.
    """

    pair_id: str
    vendor: str
    callsites_admitted: int = Field(ge=0)
    candidate_pairs: int = Field(ge=0)
    breakage_callsites: int = Field(ge=0)
    """Call sites with at least one compiler error. The kill criterion counts these."""
    compiler_labels: int = Field(ge=0)
    """Individual ``tsc`` diagnostics. Never used as the kill-criterion count."""


def _pair_counts(
    callsites: Sequence[Callsite],
    labels: Sequence[CompilerLabel],
    findings: Sequence[Finding],
) -> tuple[PairCounts, ...]:
    """Group the run by spec pair. Vendor is read off the call sites, which is where it lives."""
    impacted = impacted_callsite_ids(labels, callsites)
    pair_of = {cs.callsite_id: cs.pair_id for cs in callsites}
    out: list[PairCounts] = []
    for pair_id in sorted({cs.pair_id for cs in callsites}):
        members = [cs for cs in callsites if cs.pair_id == pair_id]
        member_ids = {cs.callsite_id for cs in members}
        out.append(
            PairCounts(
                pair_id=pair_id,
                vendor=members[0].vendor,
                callsites_admitted=len(members),
                candidate_pairs=sum(1 for f in findings if f.callsite_id in member_ids),
                breakage_callsites=len(member_ids & impacted),
                compiler_labels=sum(1 for lb in labels if pair_of[lb.callsite_id] == pair_id),
            )
        )
    return tuple(out)


def count_unclassified(changes: Sequence[SpecChange]) -> int:
    """Changes of a class this repository has not ruled on.

    Published beside the results because UNCLASSIFIED fails towards abstention: a large count means
    the abstention rate is large for a reason that is about this repository's coverage rather than
    about the type system, and a reader is entitled to tell those apart.
    """
    return sum(1 for c in changes if c.expressibility is Expressibility.UNCLASSIFIED)


# ----------------------------------------------------------------------------------- kill criterion


class KillCriterion(_Frozen):
    """The predeclared kill test, evaluated.

    ``threshold`` and ``vendors_required`` are literal types, not configurable integers, so the
    criterion cannot be relaxed by constructing this model with smaller numbers after seeing the
    corpus. ``passed`` is derived from the observations on every access; there is no stored field to
    override.
    """

    threshold: Literal[60] = KILL_THRESHOLD
    vendors_required: Literal[3] = KILL_VENDORS_REQUIRED
    observed_breakages: int = Field(ge=0)
    """Call sites on which ``tsc`` errored -- the strict reading, not the label count."""
    observed_vendors: int = Field(ge=0)
    """Distinct vendors among those call sites, not among the corpus."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def passed(self) -> bool:
        """Both conditions, conjunctively. 200 breakages from two vendors is a failed kill test."""
        return (
            self.observed_breakages >= self.threshold
            and self.observed_vendors >= self.vendors_required
        )


def evaluate_kill_criterion(
    labels: Sequence[CompilerLabel], callsites: Sequence[Callsite]
) -> KillCriterion:
    """Count breakages the strict way: distinct call sites, and the vendors those call sites are on.

    The vendor count is taken over *breaking* call sites rather than over the corpus, because a
    corpus spanning five vendors that only breaks on one has not demonstrated the claim across
    vendors -- it has demonstrated it on one vendor and carried four along.
    """
    impacted = impacted_callsite_ids(labels, callsites)
    vendors = {cs.vendor for cs in callsites if cs.callsite_id in impacted}
    return KillCriterion(observed_breakages=len(impacted), observed_vendors=len(vendors))


# ----------------------------------------------------------------------------------- the artifact


class EvaluationArtifact(_Frozen):
    """One run, complete enough that every README sentence can point at a field in it."""

    schema_version: Literal["1"] = ARTIFACT_SCHEMA_VERSION
    generated_at: str
    """Supplied by the caller. This module reads no clock -- see the module docstring."""
    run: RunSummary
    provenance: tuple[PairProvenance, ...]
    per_pair: tuple[PairCounts, ...]
    total_compiler_labels: int = Field(ge=0)
    """The loose count. Published next to ``kill_criterion.observed_breakages`` so the strict
    and the loose reading are visible together and cannot be quietly interchanged."""
    unclassified_changes: int = Field(ge=0)
    kill_criterion: KillCriterion
    system: ScoreReport
    baseline_touches_changed_operation: ScoreReport
    baseline_err_level_only: ScoreReport

    @computed_field  # type: ignore[prop-decorator]
    @property
    def headline_false_negative_rate(self) -> float | None:
        """The strict, pooled false-negative rate -- ADR-001's headline, hoisted for the README.

        Derived from ``system`` rather than stored, so the number on the front page and the
        number in the metrics block cannot drift apart. ``None`` means the corpus contained no
        compiler-labelled breakage at all, which is a failed run, not a perfect score.
        """
        return self.system.pooled.strict.false_negative_rate

    @computed_field  # type: ignore[prop-decorator]
    @property
    def abstention_rate(self) -> float | None:
        """The pooled pair-level abstention rate. Hoisted for the same reason, and never *omitted*:
        ADR-001 requires it published wherever the accuracy figures are.

        Still ``float | None``. ``None`` means there were no candidate pairs to take a rate over --
        an empty run, not a system that never abstained. A reader must not render it as zero.
        """
        return self.system.pooled.abstention_rate


def build_report(
    *,
    generated_at: str,
    run: RunSummary,
    pairs: Sequence[SpecPair],
    changes: Sequence[SpecChange],
    callsites: Sequence[Callsite],
    labels: Sequence[CompilerLabel],
    system_findings: Sequence[Finding],
    baseline_touches_findings: Sequence[Finding],
    baseline_err_findings: Sequence[Finding],
    suppressed_pairs: Mapping[str, int] | None = None,
) -> EvaluationArtifact:
    """Assemble the artifact. The system and both baselines go through one scorer on one corpus.

    Args:
        generated_at: timestamp string, supplied by the caller so this module stays deterministic.
        run: the corpus counts the generator and oracle produced, including the discarded count,
            which cannot be recovered from the admitted call sites alone.
        pairs: the spec pairs, for the provenance block.
        changes: every change the differ reported, for the UNCLASSIFIED count.
        callsites: every admitted call site.
        labels: every ``tsc`` diagnostic.
        system_findings: the classifier's findings.
        baseline_touches_findings: from :func:`~callsite_impact.evaluate.baselines.
            naive_touches_changed_operation`.
        baseline_err_findings: from
            :func:`~callsite_impact.evaluate.baselines.naive_err_level_only`.
        suppressed_pairs: vendor -> pairs the classifier dropped for lack of an anchor. Applied to
            the system only; the baselines anchor every finding by construction.

    Returns:
        The artifact, unwritten. Persisting it is :func:`write_report`'s job.
    """
    return EvaluationArtifact(
        generated_at=generated_at,
        run=run,
        provenance=tuple(_provenance(p) for p in pairs),
        per_pair=_pair_counts(callsites, labels, system_findings),
        total_compiler_labels=len(labels),
        unclassified_changes=count_unclassified(changes),
        kill_criterion=evaluate_kill_criterion(labels, callsites),
        system=score(system_findings, labels, callsites, suppressed_pairs=suppressed_pairs),
        baseline_touches_changed_operation=score(baseline_touches_findings, labels, callsites),
        baseline_err_level_only=score(baseline_err_findings, labels, callsites),
    )


def write_report(artifact: EvaluationArtifact, path: Path) -> Path:
    """Write the artifact as indented JSON with a trailing newline, creating parent directories.

    Indented and newline-terminated because this file is committed: a one-line JSON blob produces a
    diff nobody can review, and a review is the only thing standing between a published number and a
    wrong one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path
