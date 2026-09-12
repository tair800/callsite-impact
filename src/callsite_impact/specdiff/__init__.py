"""Spec differencing: invoke `oasdiff`, type its output, and rule on what a type system can express.

Nothing in this package reads compiler output. It is on the system-under-test side of the boundary
described in CLAUDE.md rule 1.
"""

from callsite_impact.specdiff.expressibility import (
    EXPRESSIBILITY_TABLE,
    RULED_ON,
    expressibility_of,
)
from callsite_impact.specdiff.oasdiff import (
    OasdiffFailedError,
    OasdiffNotFoundError,
    diff_pair,
    find_oasdiff,
    oasdiff_version,
    parse_property_path,
)

__all__ = [
    "EXPRESSIBILITY_TABLE",
    "RULED_ON",
    "OasdiffFailedError",
    "OasdiffNotFoundError",
    "diff_pair",
    "expressibility_of",
    "find_oasdiff",
    "oasdiff_version",
    "parse_property_path",
]
