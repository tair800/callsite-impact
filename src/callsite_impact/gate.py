"""`python -m callsite_impact.gate` — the build-failing check on a measurement.

Two things fail a build here, and they fail it for different reasons.

**The kill criterion.** ADR-001 fixed it at 60 compiler-verified call-site breakages across at least
three vendors, before anything was built. This gate re-checks it on every run so that the threshold
cannot quietly stop being met while the README goes on saying it is.

**Staleness.** `artifacts/evaluation.json` is committed, and the README and the console render it
rather than recomputing anything. A change that moves the measurement without regenerating the
artifact leaves published numbers describing code that no longer exists. This compares the committed
artifact against one measured from the current tree, **field by field except `generated_at`** — a
byte comparison would fail on every run because the timestamp is meant to differ, and a check that
always fails is a check everyone learns to skip.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

__all__ = ["differences", "main"]

#: Fields expected to differ between two honest runs of the same commit. Anything else that differs
#: is a real change in what the repository measured.
VOLATILE = frozenset({"generated_at"})


def _strip(node: Any) -> Any:
    """Drop the volatile fields, recursively, so the rest can be compared as data."""
    if isinstance(node, dict):
        return {k: _strip(v) for k, v in node.items() if k not in VOLATILE}
    if isinstance(node, list):
        return [_strip(v) for v in node]
    return node


def differences(committed: dict[str, Any], fresh: dict[str, Any]) -> list[str]:
    """Paths at which the two artifacts disagree, as dotted strings.

    Returns paths rather than a boolean because "the artifact is stale" is not actionable and
    "``system.pooled.strict.recall`` moved" is.
    """
    found: list[str] = []

    def walk(a: Any, b: Any, path: str) -> None:
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                walk(a.get(key), b.get(key), f"{path}.{key}" if path else key)
            return
        if isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                found.append(f"{path}: {len(a)} entries committed, {len(b)} measured")
                return
            for i, (x, y) in enumerate(zip(a, b, strict=True)):
                walk(x, y, f"{path}[{i}]")
            return
        if a != b:
            found.append(f"{path}: committed {a!r}, measured {b!r}")

    walk(_strip(committed), _strip(fresh), "")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail the build on a stale or failing measurement."
    )
    parser.add_argument("--committed", type=Path, required=True)
    parser.add_argument(
        "--fresh",
        type=Path,
        default=None,
        help="a freshly measured artifact. Omitted, only the kill criterion is checked.",
    )
    args = parser.parse_args(argv)

    if not args.committed.exists():
        print(f"no committed artifact at {args.committed}", file=sys.stderr)
        return 2
    committed = json.loads(args.committed.read_text(encoding="utf-8"))

    failed = False

    if args.fresh is not None:
        fresh = json.loads(args.fresh.read_text(encoding="utf-8"))
        drift = differences(committed, fresh)
        if drift:
            print(
                f"the committed artifact is stale — {len(drift)} field(s) differ from what this "
                "commit measures. Run 'make killtest' and commit the result.",
                file=sys.stderr,
            )
            for line in drift[:25]:
                print(f"  {line}", file=sys.stderr)
            if len(drift) > 25:
                print(f"  … and {len(drift) - 25} more", file=sys.stderr)
            failed = True
        else:
            print("artifact is current: every field matches this commit's measurement")

    kill = committed["kill_criterion"]
    verdict = "PASSED" if kill["passed"] else "FAILED"
    print(
        f"kill criterion {verdict}: {kill['observed_breakages']} compiler-verified breakages "
        f"(need {kill['threshold']}) across {kill['observed_vendors']} vendors "
        f"(need {kill['vendors_required']})"
    )
    if not kill["passed"]:
        print(
            "the predeclared kill criterion is not met. ADR-001 forbids lowering it; the honest "
            "response is a larger corpus or a published failure.",
            file=sys.stderr,
        )
        failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
