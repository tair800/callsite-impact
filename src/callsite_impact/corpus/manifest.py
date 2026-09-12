"""The corpus manifest: what was fetched, from where, and the hash of the bytes actually used.

A number in this repository is only checkable if a reader can obtain the same input bytes. The
manifest is how that is made possible, so it records a content hash per spec rather than trusting a
tag to be immutable -- Stripe's tags point at a moving `openapi/spec3.json`, and a vendor editing a
version-suffixed file in place would otherwise change the corpus silently.

``generated_at`` is a parameter, never `datetime.now()` inside this module. A module that reads
the clock cannot be tested for equality across runs, and reproducibility is the point of the file.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict

from callsite_impact.domain import SpecPair, VendorSpec

__all__ = [
    "CorpusManifest",
    "index_specs",
    "load_manifest",
    "resolve_local_path",
    "save_manifest",
    "sha256_of",
]

_HASH_CHUNK_BYTES = 1 << 20
"""Hash in 1 MiB chunks: the Stripe spec is ~8 MB a side, and holding it in RAM buys nothing."""


class CorpusManifest(BaseModel):
    """Everything a reader needs to reconstruct the corpus this repository measured."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: str
    """ISO-8601 timestamp supplied by the caller that produced the manifest."""
    oasdiff_version: str
    """The differ's self-reported version. A change id set belongs to the build that emitted it."""
    pairs: tuple[SpecPair, ...]

    @property
    def vendors(self) -> tuple[str, ...]:
        """Distinct vendors, sorted. The kill criterion counts vendors, so this gets read."""
        return tuple(sorted({pair.vendor for pair in self.pairs}))

    @property
    def specs(self) -> tuple[VendorSpec, ...]:
        """Every revision referenced, before and after, in pair order."""
        return tuple(spec for pair in self.pairs for spec in (pair.before, pair.after))


def sha256_of(path: Path) -> str:
    """Hex SHA-256 of a file's bytes.

    Args:
        path: File to hash.

    Returns:
        Lowercase hex digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_local_path(root: Path, spec: VendorSpec) -> Path:
    """Turn a manifest's `local_path` into a real path on this machine.

    `local_path` is stored repo-root-relative and POSIX-separated so that a manifest committed on
    one machine still resolves on another; this is the only place that assumption is applied.

    Args:
        root: Repository root.
        spec: The spec whose bytes are wanted.

    Returns:
        Absolute path to the spec file, which may not exist until `make corpus` has run.
    """
    return root / PurePosixPath(spec.local_path)


def index_specs(manifest: CorpusManifest) -> dict[tuple[str, str, str], VendorSpec]:
    """Index a manifest by ``(vendor, service, revision)`` so acquisition can skip settled work.

    Args:
        manifest: A previously written manifest.

    Returns:
        Mapping from spec identity to the record. Later entries win, which is harmless: the same
        revision appearing in two pairs carries the same bytes and the same hash.
    """
    return {(spec.vendor, spec.service, spec.revision): spec for spec in manifest.specs}


def load_manifest(path: Path) -> CorpusManifest:
    """Read and validate a manifest.

    Args:
        path: Path to `corpus/manifest.json`.

    Returns:
        The parsed manifest.

    Raises:
        FileNotFoundError: If the manifest has not been generated yet.
        pydantic.ValidationError: If the file on disk no longer matches the schema, which is a real
            failure and not something to paper over -- a manifest that cannot be read cannot vouch
            for the bytes a run used.
    """
    return CorpusManifest.model_validate_json(path.read_text(encoding="utf-8"))


def save_manifest(manifest: CorpusManifest, path: Path) -> None:
    """Write a manifest as indented JSON with a trailing newline.

    Indented and key-stable so that a change to the corpus shows up as a readable diff rather than
    one reflowed line.

    Args:
        manifest: The manifest to write.
        path: Destination; parent directories are created.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(manifest.model_dump_json())
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
