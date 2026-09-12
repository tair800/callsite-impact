"""Typed configuration. Every value arrives from the environment; none is invented here."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings"]

_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """What the service needs to start.

    ``extra="forbid"`` so a misspelled variable fails at startup rather than being silently ignored
    — the failure mode where a setting looks configured and is not.

    There is deliberately no database URL and no model credential. The API serves one committed JSON
    artifact; it has nothing to connect to, and a setting for a connection it does not make would be
    an invitation to add one.
    """

    model_config = SettingsConfigDict(
        env_prefix="CSI_", env_file=".env", extra="forbid", case_sensitive=False
    )

    environment: str = Field(default="local", pattern="^(local|ci|staging|production)$")

    artifact_path: Path = Field(
        default=_ROOT / "artifacts" / "evaluation.json",
        description="The committed measurement. Read once at startup; the API computes nothing.",
    )

    #: Fail-closed. An empty list means no browser origin may call the API directly, which is
    #: correct when the console reaches it server-side.
    cors_allow_origins: list[str] = Field(default_factory=list)
