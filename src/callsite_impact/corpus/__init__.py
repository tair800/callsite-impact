"""Corpus acquisition and provenance.

The specs are real and public; only the call sites measured against them are generated. Everything
here exists so that a reader can obtain the same bytes this repository ran on.
"""

from callsite_impact.corpus.manifest import (
    CorpusManifest,
    index_specs,
    load_manifest,
    resolve_local_path,
    save_manifest,
    sha256_of,
)

__all__ = [
    "CorpusManifest",
    "index_specs",
    "load_manifest",
    "resolve_local_path",
    "save_manifest",
    "sha256_of",
]
