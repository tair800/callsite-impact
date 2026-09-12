"""A read-only API over two committed artifacts.

Every route here is a read, and there is nothing behind them but two JSON files loaded at startup.
That is not a simplification of something larger: the measurement is a batch job that shells out to
a compiler and takes minutes, and exposing it over HTTP would mean a public endpoint that runs
`tsc` on demand. The console needs the *result*, and the result is a file.

The consequence worth stating: this service cannot compute a verdict, cannot re-run the oracle and
cannot be made to disagree with what was committed. If the numbers on the site are wrong, they were
wrong in the repository first, where CI checks them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from callsite_impact.config import Settings

__all__ = ["create_app"]


class HealthView(BaseModel):
    status: str
    service: str
    version: str


class MetaView(BaseModel):
    version: str
    revision: str
    """The deployed commit, from the platform's own variable. Empty when nothing sets one."""
    artifact_generated_at: str
    kill_criterion_passed: bool


def _load(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app.

    A factory rather than a module-level instance so tests can point it at a fixture artifact
    instead of the committed one, without touching the environment of the process running them.
    """
    resolved = settings or Settings()

    app = FastAPI(
        title="callsite-impact",
        version="0.1.0",
        summary=(
            "Which client call sites an OpenAPI change actually breaks, graded by the compiler."
        ),
        docs_url=None if resolved.environment == "production" else "/docs",
    )

    if resolved.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved.cors_allow_origins,
            allow_methods=["GET"],
            allow_headers=["*"],
        )

    # Loaded once, at startup. A re-read per request would let the file change under a reader
    # mid-session, and the artifact only changes when the repository does.
    evaluation: dict[str, Any] = {}
    detail: dict[str, Any] = {}
    if resolved.artifact_path.exists():
        evaluation = _load(resolved.artifact_path)
    findings_path = resolved.artifact_path.parent / "findings.json"
    if findings_path.exists():
        detail = _load(findings_path)

    def _require_artifact() -> dict[str, Any]:
        if not evaluation:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "status": "no_artifact",
                    "hint": "run 'make corpus && make killtest' and commit artifacts/",
                },
            )
        return evaluation

    @app.get("/healthz", response_model=HealthView)
    async def healthz() -> HealthView:
        """Liveness. Deliberately touches nothing, so it cannot fail for an unrelated reason."""
        return HealthView(status="alive", service="callsite-impact", version="0.1.0")

    @app.get("/readyz")
    async def readyz() -> dict[str, Any]:
        """Readiness. Distinct from liveness: it fails when the artifact is missing.

        Worth having even with no database. A deployment that shipped without the artifact would
        answer `/healthz` perfectly while serving an empty console, and only this route tells the
        two apart.
        """
        if not evaluation:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"status": "not_ready", "artifact": "missing"},
            )
        return {"status": "ready", "artifact": "loaded", "detail": bool(detail)}

    @app.get("/api/v1/meta", response_model=MetaView)
    async def meta() -> MetaView:
        import os

        for name in ("RENDER_GIT_COMMIT", "VERCEL_GIT_COMMIT_SHA", "GIT_COMMIT_SHA"):
            revision = os.environ.get(name)
            if revision:
                break
        else:
            revision = ""
        artifact = _require_artifact()
        return MetaView(
            version="0.1.0",
            revision=revision,
            artifact_generated_at=artifact["generated_at"],
            kill_criterion_passed=bool(artifact["kill_criterion"]["passed"]),
        )

    @app.get("/api/v1/summary")
    async def summary() -> dict[str, Any]:
        """The headline block: corpus, kill criterion, system metrics and both baselines."""
        artifact = _require_artifact()
        return {
            "generated_at": artifact["generated_at"],
            "run": artifact["run"],
            "kill_criterion": artifact["kill_criterion"],
            "total_compiler_labels": artifact["total_compiler_labels"],
            "unclassified_changes": artifact["unclassified_changes"],
            "headline_false_negative_rate": artifact.get("headline_false_negative_rate"),
            "abstention_rate": artifact.get("abstention_rate"),
            "system": artifact["system"],
            "baseline_touches_changed_operation": artifact["baseline_touches_changed_operation"],
            "baseline_err_level_only": artifact["baseline_err_level_only"],
        }

    @app.get("/api/v1/provenance")
    async def provenance() -> dict[str, Any]:
        """Where every spec came from, with the checksums a reader can verify against."""
        artifact = _require_artifact()
        return {"pairs": artifact["provenance"], "per_pair": artifact["per_pair"]}

    @app.get("/api/v1/pairs")
    async def pairs() -> dict[str, Any]:
        """The pairs the console offers, without the per-call-site rows."""
        if not detail:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"status": "no_detail_artifact"},
            )
        return {
            "sampling": detail["sampling"],
            "pairs": [
                {k: v for k, v in pair.items() if k not in {"callsites", "changes_shown"}}
                for pair in detail["pairs"]
            ],
        }

    @app.get("/api/v1/pairs/{pair_id}")
    async def pair_detail(pair_id: str) -> dict[str, Any]:
        """One pair in full: changes, call sites, the compiler's verdict and the system's."""
        if not detail:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"status": "no_detail_artifact"},
            )
        for pair in detail["pairs"]:
            if pair["pair_id"] == pair_id:
                found: dict[str, Any] = pair
                return found
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"pair_id": pair_id})

    return app
