"""`python -m callsite_impact.measure` — run the corpus and write the artifact the README reads.

A module rather than an endpoint, and a file rather than a database. The measurement takes minutes,
shells out to a compiler and writes one JSON document; nothing about that wants to be reachable over
HTTP, and nothing about it needs a server to hold it.

The timestamp is stamped **here**, at the edge, and passed down. Everything below this line is a
pure function of the corpus and the seed, which is what makes two runs on one commit comparable.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from callsite_impact.detail import build_detail, write_detail
from callsite_impact.evaluate.report import write_report
from callsite_impact.pipeline import run_corpus

ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the corpus and score it against the compiler."
    )
    parser.add_argument("--manifest", type=Path, default=ROOT / "corpus" / "manifest.json")
    parser.add_argument("--workdir", type=Path, default=ROOT / "work")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts" / "evaluation.json")
    parser.add_argument("--detail", type=Path, default=ROOT / "artifacts" / "findings.json")
    parser.add_argument("--only", default=None, help="run a single pair id (development only)")
    args = parser.parse_args(argv)

    if not args.manifest.exists():
        print(
            f"no corpus manifest at {args.manifest}\nrun: make corpus",
            file=sys.stderr,
        )
        return 2

    generated_at = dt.datetime.now(tz=dt.UTC).isoformat()
    run = run_corpus(args.manifest, args.workdir, generated_at=generated_at, only=args.only)
    artifact = run.artifact
    write_report(artifact, args.out)
    write_detail(
        build_detail(
            run.results,
            run.system_by_pair,
            run.baseline_by_pair,
            args.workdir,
            generated_at=generated_at,
        ),
        args.detail,
    )

    kill = artifact.kill_criterion
    print(f"wrote {args.out} and {args.detail}")
    print(
        f"  corpus:   {artifact.run.callsites_admitted} admitted call sites "
        f"({artifact.run.callsites_discarded} discarded) across {artifact.run.pairs} pairs"
    )
    print(f"  vendors:  {', '.join(artifact.run.vendors)}")
    print(
        f"  compiler: {kill.observed_breakages} call sites broken, "
        f"{artifact.total_compiler_labels} diagnostics"
    )
    print(
        f"  KILL CRITERION ({kill.threshold} breakages, {kill.vendors_required} vendors): "
        f"{'PASSED' if kill.passed else 'FAILED'}"
    )
    if args.only is not None:
        print("  NOTE: --only was used. This is a partial run and is not a scored result.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
