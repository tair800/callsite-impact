"""The per-call-site record the console renders.

`artifacts/evaluation.json` holds counts, and counts are what the claim rests on — but a reader who
does not believe the counts cannot check them from a count. This second artifact carries the
individual rows: the call site's actual source, what the compiler said about it, what the system
predicted, what the naive baseline predicted, and the change each verdict is anchored to.

**It is a display sample and says so in its own schema.** Every call site the compiler broke is
included, because those are the rows the claim is about and dropping any of them would be choosing
the evidence. Clean call sites are sampled to a cap, in a fixed order, because there are thousands
of them and a browser does not need all of them to show what UNAFFECTED looks like. The sampling
touches nothing that is measured: every rate in `evaluation.json` is computed over the full corpus
before this file is written.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from callsite_impact.domain import CompilerLabel, Finding, Verdict
from callsite_impact.pipeline import PairResult

__all__ = ["CallsiteDetail", "DetailArtifact", "PairDetail", "build_detail", "write_detail"]

#: Clean call sites shown per pair. Breakages are never capped.
CLEAN_SAMPLE_CAP = 25

#: Changes shown per pair. The full count travels alongside so the cap cannot be mistaken for it.
CHANGE_SAMPLE_CAP = 40


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class ChangeRow(_Frozen):
    change_id: str
    level: int
    method: str
    path: str
    text: str
    expressibility: str


class CompilerRow(_Frozen):
    line: int
    column: int
    ts_error_code: str
    message: str


class FindingRow(_Frozen):
    verdict: Verdict
    reason: str
    rule: str
    change_id: str
    change_text: str
    line: int
    column: int | None
    token: str | None


class CallsiteDetail(_Frozen):
    """One call site, with every side of the question about it.

    ``truth`` comes from the compiler and ``system``/``baseline`` from predictors that never saw it.
    They are placed side by side deliberately: the interesting rows are the ones where they differ,
    and a reader should be able to find those without running anything.
    """

    callsite_id: str
    operation_key: str
    line: int
    source: str
    truth: Literal["impacted", "clean"]
    system: Verdict
    baseline: Verdict
    compiler: tuple[CompilerRow, ...]
    findings: tuple[FindingRow, ...]


class PairDetail(_Frozen):
    pair_id: str
    vendor: str
    service: str
    before_revision: str
    after_revision: str
    source_url: str
    changes_total: int = Field(ge=0)
    changes_shown: tuple[ChangeRow, ...]
    callsites_admitted: int = Field(ge=0)
    callsites_broken: int = Field(ge=0)
    clean_callsites_omitted: int = Field(ge=0)
    """How many UNAFFECTED rows the cap left out. Published so the sample is visibly a sample."""
    callsites: tuple[CallsiteDetail, ...]


class DetailArtifact(_Frozen):
    schema_version: Literal["1"] = "1"
    generated_at: str
    sampling: str = (
        "Every call site the compiler broke is included. Clean call sites are capped per pair "
        f"at {CLEAN_SAMPLE_CAP}, in corpus order. Sampling happens after every published rate has "
        "been computed over the full corpus."
    )
    pairs: tuple[PairDetail, ...]


def _source_of(callsites_ts: Path, start_line: int, next_line: int | None) -> str:
    """The call site's own text, read back from the file the compiler actually read."""
    lines = callsites_ts.read_text(encoding="utf-8").splitlines()
    end = (next_line - 1) if next_line is not None else len(lines)
    return "\n".join(lines[start_line - 1 : end]).rstrip()


def _collapse(findings: list[Finding]) -> Verdict:
    """The same precedence the scorer uses: IMPACTED beats UNKNOWN beats UNAFFECTED.

    Duplicated rather than imported so that a change to the scorer's rule breaks the tests that
    compare them, instead of silently changing what the console shows.
    """
    verdicts = {f.verdict for f in findings}
    if Verdict.IMPACTED in verdicts:
        return Verdict.IMPACTED
    if Verdict.UNKNOWN in verdicts:
        return Verdict.UNKNOWN
    return Verdict.UNAFFECTED


def build_detail(
    results: list[PairResult],
    system: dict[str, list[Finding]],
    baseline: dict[str, list[Finding]],
    workdir: Path,
    *,
    generated_at: str,
) -> DetailArtifact:
    """Assemble the display artifact.

    Args:
        results: what each pair produced.
        system: pair id -> the classifier's findings for that pair.
        baseline: pair id -> the naive baseline's findings for that pair.
        workdir: where the admitted call-site files were written, so their source can be read back.
        generated_at: supplied by the caller; this module reads no clock.
    """
    pairs: list[PairDetail] = []

    for result in results:
        callsites_ts = workdir / result.pair.pair_id / "admitted" / "callsites.ts"
        by_line = sorted(result.callsites, key=lambda c: c.line)
        next_line: dict[str, int | None] = {c.callsite_id: None for c in by_line}
        for earlier, later in pairwise(by_line):
            next_line[earlier.callsite_id] = later.line

        labels_by_callsite: dict[str, list[CompilerLabel]] = {}
        for label in result.labels:
            labels_by_callsite.setdefault(label.callsite_id, []).append(label)

        system_by_callsite: dict[str, list[Finding]] = {}
        for finding in system.get(result.pair.pair_id, []):
            system_by_callsite.setdefault(finding.callsite_id, []).append(finding)
        baseline_by_callsite: dict[str, list[Finding]] = {}
        for finding in baseline.get(result.pair.pair_id, []):
            baseline_by_callsite.setdefault(finding.callsite_id, []).append(finding)

        change_text = {c.change_id: c.text for c in result.changes}

        broken = [c for c in by_line if c.callsite_id in labels_by_callsite]
        clean = [c for c in by_line if c.callsite_id not in labels_by_callsite]
        shown = broken + clean[:CLEAN_SAMPLE_CAP]

        rows: list[CallsiteDetail] = []
        for callsite in shown:
            findings = system_by_callsite.get(callsite.callsite_id, [])
            rows.append(
                CallsiteDetail(
                    callsite_id=callsite.callsite_id,
                    operation_key=callsite.operation_key,
                    line=callsite.line,
                    source=_source_of(callsites_ts, callsite.line, next_line[callsite.callsite_id]),
                    truth=("impacted" if callsite.callsite_id in labels_by_callsite else "clean"),
                    system=_collapse(findings),
                    baseline=_collapse(baseline_by_callsite.get(callsite.callsite_id, [])),
                    compiler=tuple(
                        CompilerRow(
                            line=label.line,
                            column=label.column,
                            ts_error_code=label.ts_error_code,
                            message=label.message,
                        )
                        for label in labels_by_callsite.get(callsite.callsite_id, [])
                    ),
                    findings=tuple(
                        FindingRow(
                            verdict=f.verdict,
                            reason=f.reason,
                            rule=f.rule,
                            change_id=f.change.change_id,
                            change_text=change_text.get(f.change.change_id, f.change.text),
                            line=f.callsite_line,
                            column=f.callsite_column,
                            token=f.callsite_token,
                        )
                        for f in findings
                    ),
                )
            )

        pairs.append(
            PairDetail(
                pair_id=result.pair.pair_id,
                vendor=result.pair.vendor,
                service=result.pair.service,
                before_revision=result.pair.before.revision,
                after_revision=result.pair.after.revision,
                source_url=result.pair.after.source_url,
                changes_total=len(result.changes),
                changes_shown=tuple(
                    ChangeRow(
                        change_id=c.change_id,
                        level=c.level,
                        method=c.method,
                        path=c.path,
                        text=c.text,
                        expressibility=str(c.expressibility),
                    )
                    for c in result.changes[:CHANGE_SAMPLE_CAP]
                ),
                callsites_admitted=len(result.callsites),
                callsites_broken=len(broken),
                clean_callsites_omitted=max(0, len(clean) - CLEAN_SAMPLE_CAP),
                callsites=tuple(rows),
            )
        )

    return DetailArtifact(generated_at=generated_at, pairs=tuple(pairs))


def write_detail(artifact: DetailArtifact, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path
