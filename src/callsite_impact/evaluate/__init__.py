"""Evaluation: the baselines, the scorer, and the artifact every published number comes from.

Nothing in this package imports the classifier or the oracle. It is handed findings, labels and call
sites and grades them, which keeps it usable as-is for the system and for both baselines -- and
keeps it honest, since a scorer that could reach into the classifier could be tuned against it.
"""

from callsite_impact.evaluate.baselines import (
    naive_err_level_only,
    naive_touches_changed_operation,
)
from callsite_impact.evaluate.report import (
    EvaluationArtifact,
    KillCriterion,
    build_report,
    evaluate_kill_criterion,
    write_report,
)
from callsite_impact.evaluate.scorer import (
    ConfusionCounts,
    ScopeMetrics,
    ScoreReport,
    ViewMetrics,
    collapse_predictions,
    collapse_verdict,
    impacted_callsite_ids,
    score,
)

__all__ = [
    "ConfusionCounts",
    "EvaluationArtifact",
    "KillCriterion",
    "ScopeMetrics",
    "ScoreReport",
    "ViewMetrics",
    "build_report",
    "collapse_predictions",
    "collapse_verdict",
    "evaluate_kill_criterion",
    "impacted_callsite_ids",
    "naive_err_level_only",
    "naive_touches_changed_operation",
    "score",
    "write_report",
]
