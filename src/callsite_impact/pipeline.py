"""The run. One spec pair in, one measured artifact out.

The order of the stages here is the argument the project makes, so it is worth reading as prose:

1.  generate types from revision **A** and from revision **B** (the same generator, twice);
2.  generate call sites from **A** and an integer seed — never from B, never from the diff;
3.  **admit** only the call sites that typecheck clean against A, discarding the rest;
4.  run the oracle: recompile the admitted set against **B** and keep what ``tsc`` said;
5.  extract call-site facts with a parser that has no type checker;
6.  diff A against B with ``oasdiff``;
7.  classify, using (6) and (5) and **never** (4);
8.  run both predeclared baselines over the identical candidate pairs;
9.  score everything against (4) with one scorer.

Stage 3 happens before stage 4 for a reason that is easy to lose: it means the admitted set was
fixed on evidence from revision A alone, so it cannot have been shaped by what turned out to break.

This module is deliberately the only place that touches both the oracle and the classifier. Every
other module sees one or the other, which is what makes the import guard in
``tests/test_oracle_boundary.py`` able to say something true.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from callsite_impact.classify.engine import classify_pair
from callsite_impact.corpus.manifest import load_manifest
from callsite_impact.domain import (
    Callsite,
    CallsiteFacts,
    CompilerLabel,
    Finding,
    PropertyAccess,
    RunSummary,
    SpecChange,
    SpecPair,
)
from callsite_impact.evaluate.baselines import naive_err_level_only, naive_touches_changed_operation
from callsite_impact.evaluate.report import EvaluationArtifact, build_report
from callsite_impact.specdiff.oasdiff import diff_pair, oasdiff_version

__all__ = ["CorpusRun", "PairResult", "run_corpus", "run_pair"]

HARNESS = Path(__file__).resolve().parents[2] / "harness"
_MARKER = re.compile(r"^// @callsite id=(cs_[0-9a-f]{12}) ")

#: Generation parameters. Fixed here rather than passed in, because ADR-001 pre-registers the
#: generator's policy and a knob that can be turned per run is a policy that can be turned per
#: result. Changing these changes the corpus, and the corpus is what the claim rests on.
MAX_OPERATIONS = 120
CALLSITES_PER_OPERATION = 4
SEED = 20260912


def _node(script: str, *args: str) -> str:
    """Run one harness script, and fail loudly rather than returning a half-run.

    Raises:
        RuntimeError: with the script's own stderr. A swallowed harness failure would show up much
            later as a corpus that is mysteriously small, which is the worst way to find it.
    """
    completed = subprocess.run(
        ["node", str(HARNESS / "scripts" / script), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{script} failed ({completed.returncode}): {completed.stderr.strip()}")
    return completed.stdout.strip()


def _callsite_line_index(callsites_ts: Path) -> list[tuple[int, str]]:
    """Line number -> call-site id, for every marker, ascending.

    The oracle reports a file and a line; the corpus is keyed by call-site id. This is the join, and
    it is done by reading the markers rather than by trusting the generator's own record, so that a
    generator that mislabels itself cannot quietly move a compiler error onto the wrong call site.
    """
    index: list[tuple[int, str]] = []
    for number, line in enumerate(callsites_ts.read_text(encoding="utf-8").splitlines(), start=1):
        match = _MARKER.match(line)
        if match:
            index.append((number, match.group(1)))
    return index


def _owner_of_line(index: list[tuple[int, str]], line: int) -> str | None:
    """The call site whose block contains ``line`` — the last marker at or above it."""
    owner: str | None = None
    for marker_line, callsite in index:
        if marker_line <= line:
            owner = callsite
        else:
            break
    return owner


DIFF_CACHE = Path(__file__).resolve().parents[2] / "corpus" / "diffs"


@functools.cache
def _differ_version() -> str:
    """One version probe per process. It shells out, and the answer cannot change mid-run."""
    return oasdiff_version()


def _cached_changes(pair: SpecPair) -> tuple[SpecChange, ...]:
    """Diff a pair, reusing an earlier result when the inputs are byte-for-byte the same.

    Not an optimisation for its own sake. `oasdiff` on the two 8 MB Stripe revisions takes about
    half an hour of CPU — it walks a very large `anyOf` graph — and every other pair in the corpus
    finishes in seconds. Without this, a re-run of the measurement is dominated by one vendor and CI
    cannot re-measure on every push, which is the check that keeps the published numbers honest.

    **The key is content, not a filename or a timestamp.** It is the SHA-256 of both revisions plus
    the differ's own version, so a cache hit is a proof that the same inputs went into the same
    differ. Change a spec, a pin, or the differ, and the key changes and the work is redone. There
    is no staleness window and no flag to forget.
    """
    key_material = f"{pair.before.sha256}|{pair.after.sha256}|{_differ_version()}"
    key = hashlib.sha256(key_material.encode()).hexdigest()[:16]
    cached = DIFF_CACHE / f"{key}.json"

    if cached.is_file():
        raw = json.loads(cached.read_text(encoding="utf-8"))
        return tuple(SpecChange.model_validate(entry) for entry in raw)

    changes = tuple(diff_pair(Path(pair.before.local_path), Path(pair.after.local_path)))
    DIFF_CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(
        json.dumps([c.model_dump(mode="json") for c in changes], indent=1),
        encoding="utf-8",
    )
    return changes


@dataclass(frozen=True)
class PairResult:
    """Everything one spec pair produced, before anything is pooled."""

    pair: SpecPair
    changes: tuple[SpecChange, ...]
    callsites: tuple[Callsite, ...]
    labels: tuple[CompilerLabel, ...]
    generated: int
    discarded: int


def run_pair(pair: SpecPair, workdir: Path) -> PairResult:
    """Take one pair through stages 1 to 6. Stages 7 to 9 are pooled and happen in the caller."""
    work = workdir / pair.pair_id
    work.mkdir(parents=True, exist_ok=True)

    types_a, types_b = work / "types_a.ts", work / "types_b.ts"
    _node("gen-types.mjs", pair.before.local_path, str(types_a))
    _node("gen-types.mjs", pair.after.local_path, str(types_b))

    generated_dir = work / "generated"
    _node(
        "gen-callsites.mjs",
        "--spec",
        pair.before.local_path,
        "--out",
        str(generated_dir),
        "--pair",
        pair.pair_id,
        "--vendor",
        pair.vendor,
        "--seed",
        str(SEED),
        "--max-operations",
        str(MAX_OPERATIONS),
        "--per-operation",
        str(CALLSITES_PER_OPERATION),
    )

    admitted_dir = work / "admitted"
    _node(
        "admit.mjs",
        "--callsites",
        str(generated_dir / "callsites.ts"),
        "--types",
        str(types_a),
        "--out",
        str(admitted_dir),
    )
    admission = json.loads((admitted_dir / "admission.json").read_text(encoding="utf-8"))

    facts_path = work / "facts.json"
    _node("extract-facts.mjs", "--callsites", str(admitted_dir), "--out", str(facts_path))
    facts_raw = json.loads(facts_path.read_text(encoding="utf-8"))

    callsites = tuple(
        Callsite(
            callsite_id=entry["callsiteId"],
            pair_id=pair.pair_id,
            vendor=pair.vendor,
            file=entry["file"],
            line=entry["line"],
            operation_key=entry["operationKey"],
            generator_seed=SEED,
            facts=CallsiteFacts(
                operation_key=entry["operationKey"],
                request_properties=tuple(
                    PropertyAccess(
                        path=tuple(p["path"]),
                        line=p["line"],
                        column=p["column"],
                        literal_value=p.get("literalValue"),
                    )
                    for p in entry.get("requestProperties", ())
                ),
                response_properties=tuple(
                    PropertyAccess(
                        path=tuple(p["path"]),
                        line=p["line"],
                        column=p["column"],
                        optional_chained=bool(p.get("optionalChained", False)),
                        pinned=bool(p.get("pinned", False)),
                    )
                    for p in entry.get("responseProperties", ())
                ),
            ),
        )
        for entry in facts_raw
    )

    # --- the oracle. Nothing above this line has seen revision B's effect on the call sites.
    labels_path = work / "labels.json"
    _node(
        "run-tsc.mjs",
        "--types",
        str(types_b),
        "--callsites",
        str(admitted_dir),
        "--out",
        str(labels_path),
    )
    raw_labels = json.loads(labels_path.read_text(encoding="utf-8"))["errors"]
    index = _callsite_line_index(admitted_dir / "callsites.ts")
    known = {cs.callsite_id for cs in callsites}

    labels: list[CompilerLabel] = []
    for error in raw_labels:
        owner = _owner_of_line(index, int(error["line"]))
        if owner is None or owner not in known:
            # A diagnostic that lands outside every call-site block is a harness fault, not a label.
            # Counting it would put a breakage on a call site that did not cause it.
            continue
        labels.append(
            CompilerLabel(
                callsite_id=owner,
                file=error["file"],
                line=int(error["line"]),
                column=int(error["column"]),
                ts_error_code=str(error["code"]),
                message=str(error["message"])[:400],
            )
        )

    changes = _cached_changes(pair)

    return PairResult(
        pair=pair,
        changes=changes,
        callsites=callsites,
        labels=tuple(labels),
        generated=int(admission["generated"]),
        discarded=int(admission["discarded"]),
    )


@dataclass(frozen=True)
class CorpusRun:
    """Everything a run produced, kept per pair as well as pooled.

    The scored artifact is pooled by design, but the console needs to show individual rows, and
    re-deriving which finding came from which pair afterwards would mean re-running the classifier.
    Carrying both out of one run is cheaper and, more importantly, guarantees the two artifacts
    describe the same execution rather than two that happened to agree.
    """

    artifact: EvaluationArtifact
    results: list[PairResult]
    system_by_pair: dict[str, list[Finding]]
    baseline_by_pair: dict[str, list[Finding]]


def run_corpus(
    manifest_path: Path, workdir: Path, *, generated_at: str, only: str | None = None
) -> CorpusRun:
    """Run every pair in the manifest and score the pooled result.

    Args:
        manifest_path: the corpus manifest written by ``python -m callsite_impact.corpus.acquire``.
        workdir: scratch space for generated types, call sites and compiler output.
        generated_at: timestamp string, supplied by the caller so this module stays deterministic.
        only: run a single pair by id. For development; a scored run uses the whole corpus, because
            a kill criterion measured on a chosen subset is not a kill criterion.

    Returns:
        The pooled artifact and the per-pair pieces the console's detail artifact is built from.
    """
    manifest = load_manifest(manifest_path)
    pairs = [p for p in manifest.pairs if only is None or p.pair_id == only]

    results = [run_pair(pair, workdir) for pair in pairs]

    all_changes: list[SpecChange] = []
    all_callsites: list[Callsite] = []
    all_labels: list[CompilerLabel] = []
    system: list[Finding] = []
    baseline_touches: list[Finding] = []
    baseline_err: list[Finding] = []

    system_by_pair: dict[str, list[Finding]] = {}
    baseline_by_pair: dict[str, list[Finding]] = {}

    for result in results:
        all_changes.extend(result.changes)
        all_callsites.extend(result.callsites)
        all_labels.extend(result.labels)

        pair_system = classify_pair(result.changes, result.callsites)
        pair_touches = naive_touches_changed_operation(result.changes, result.callsites)
        pair_err = naive_err_level_only(result.changes, result.callsites)

        system_by_pair[result.pair.pair_id] = pair_system
        baseline_by_pair[result.pair.pair_id] = pair_touches

        system.extend(pair_system)
        baseline_touches.extend(pair_touches)
        baseline_err.extend(pair_err)

    run = RunSummary(
        pairs=len(results),
        vendors=tuple(sorted({r.pair.vendor for r in results})),
        callsites_generated=sum(r.generated for r in results),
        callsites_admitted=len(all_callsites),
        callsites_discarded=sum(r.discarded for r in results),
        compiler_breakages=len({label.callsite_id for label in all_labels}),
        compiler_clean=len(all_callsites) - len({label.callsite_id for label in all_labels}),
        candidate_findings=len(system),
    )

    artifact = build_report(
        generated_at=generated_at,
        run=run,
        pairs=[r.pair for r in results],
        changes=all_changes,
        callsites=all_callsites,
        labels=all_labels,
        system_findings=system,
        baseline_touches_findings=baseline_touches,
        baseline_err_findings=baseline_err,
    )
    return CorpusRun(
        artifact=artifact,
        results=results,
        system_by_pair=system_by_pair,
        baseline_by_pair=baseline_by_pair,
    )
