"""Measure the development corpus at several generation budgets: what scales, and what does not.

The kill criterion is an **absolute count** of compiler-verified breakages, so it necessarily scales
with how much client code the generator writes. The predictive metrics are **rates**, so they should
not. This script measures both claims instead of asserting them.

**It is a sensitivity experiment, not a release path.** `measure.py` — the command CI runs and the
command that writes the committed artifact — takes no budget flag and reads the constants in
`pipeline.py`. The budget is deliberately not a knob on the release path, because a knob that can be
turned per run is a policy that can be turned per result. Here the constants are rebound in-process,
visibly, for an experiment whose whole purpose is to vary them.

    uv run python scripts/budget_sweep.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from callsite_impact import pipeline  # noqa: E402
from callsite_impact.pipeline import run_corpus  # noqa: E402

#: (max operations, call sites per operation, label). The middle row is what the repository ships.
BUDGETS: tuple[tuple[int, int, str], ...] = (
    (40, 3, "harness default"),
    (120, 4, "canonical release"),
    (200, 6, "larger"),
)


def _row(budget: tuple[int, int, str], artifact: Any) -> dict[str, Any]:
    strict = artifact.system.pooled.strict
    return {
        "max_operations": budget[0],
        "callsites_per_operation": budget[1],
        "label": budget[2],
        "callsites_admitted": artifact.run.callsites_admitted,
        "callsites_discarded": artifact.run.callsites_discarded,
        "compiler_breakages": artifact.kill_criterion.observed_breakages,
        "vendors": artifact.kill_criterion.observed_vendors,
        "kill_criterion_passed": artifact.kill_criterion.passed,
        "precision": strict.precision,
        "recall": strict.recall,
        "f1": strict.f1,
        "false_negative_rate": strict.false_negative_rate,
        "false_positive_rate": strict.false_positive_rate,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure the corpus at several generation budgets."
    )
    parser.add_argument("--manifest", type=Path, default=ROOT / "corpus" / "manifest.json")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts" / "budget_sweep.json")
    args = parser.parse_args(argv)

    generated_at = dt.datetime.now(tz=dt.UTC).isoformat()
    canonical = (pipeline.MAX_OPERATIONS, pipeline.CALLSITES_PER_OPERATION)
    rows: list[dict[str, Any]] = []

    try:
        for budget in BUDGETS:
            pipeline.MAX_OPERATIONS, pipeline.CALLSITES_PER_OPERATION = budget[0], budget[1]
            workdir = ROOT / "work-sweep" / f"{budget[0]}x{budget[1]}"
            print(f"measuring at {budget[0]} x {budget[1]} ({budget[2]}) …", flush=True)
            run = run_corpus(args.manifest, workdir, generated_at=generated_at)
            rows.append(_row(budget, run.artifact))
    finally:
        pipeline.MAX_OPERATIONS, pipeline.CALLSITES_PER_OPERATION = canonical

    payload = {
        "generated_at": generated_at,
        "canonical": {"max_operations": canonical[0], "callsites_per_operation": canonical[1]},
        "note": (
            "The kill criterion is an absolute count and scales with the budget. The predictive "
            "metrics are rates and do not. Both are measured here rather than asserted."
        ),
        "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"\nwrote {args.out}\n")
    header = (
        f"{'budget':>10}  {'label':<18} {'admitted':>9} {'breakages':>10} "
        f"{'vendors':>8} {'kill':>7}  {'P':>6} {'R':>6} {'F1':>6}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        fmt = lambda x: "  n/a " if x is None else f"{x:6.3f}"  # noqa: E731
        print(
            f"{r['max_operations']:>4} x {r['callsites_per_operation']:<3} {r['label']:<18} "
            f"{r['callsites_admitted']:>9} {r['compiler_breakages']:>10} {r['vendors']:>8} "
            f"{'PASS' if r['kill_criterion_passed'] else 'FAIL':>7}  "
            f"{fmt(r['precision'])} {fmt(r['recall'])} {fmt(r['f1'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
