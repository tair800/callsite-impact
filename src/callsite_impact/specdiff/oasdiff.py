"""Run `oasdiff` and turn its prose back into a typed change the rest of the pipeline can join on.

`oasdiff` reports a change as an English sentence with the interesting parts in backticks. The
property path -- the only thing that lets a change be matched against a call site -- lives inside
that sentence and nowhere else in the JSON, so it has to be parsed out.

**The obvious parser is wrong, and it is wrong quietly.** "the property path is the first backticked
span" holds for eight of the sixteen prose shapes read below and fails for five of them, because the
differ leads with the enum value, the schema ref or the parameter location instead:

    added the new `authorised` enum value to the `status` response property ...
    deleted the `query` request parameter `folderId`

Under the naive rule those changes would be filed against properties named ``authorised`` and
``query`` -- a wrong property path, delivered with full confidence, sending a verdict to the wrong
call site. So every shape is written down as its own anchored pattern, and prose matching none of
them is refused rather than guessed at. :func:`parse_property_path` never falls back to a heuristic.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Final

from callsite_impact.domain import SpecChange
from callsite_impact.specdiff.expressibility import expressibility_of

__all__ = [
    "OasdiffFailedError",
    "OasdiffNotFoundError",
    "diff_pair",
    "find_oasdiff",
    "oasdiff_version",
    "parse_property_path",
]


_INSTALL_HINT: Final = "go install github.com/oasdiff/oasdiff@v1.29.1"

DEFAULT_TIMEOUT_S: Final = 900
"""Generous on purpose: a multi-megabyte spec pair takes minutes on a normal laptop.

Sized against the Stripe pair (~8 MB a side) that was trialled and then dropped from the corpus;
the surviving pairs are far smaller, so the headroom is deliberate rather than currently needed.
"""


class OasdiffNotFoundError(RuntimeError):
    """The differ is not installed. Raised with the install command rather than a bare failure."""


class OasdiffFailedError(RuntimeError):
    """The differ ran and refused the input. Carries its stderr, which names the offending spec."""


# ------------------------------------------------------------------------------------- the binary


def find_oasdiff() -> Path:
    """Locate the `oasdiff` binary.

    Looks on `PATH` first, then in the Go bin directory, because `go install` puts it there without
    touching `PATH` and that is how most people will have got it.

    Returns:
        Path to the executable.

    Raises:
        OasdiffNotFoundError: with the command that installs it.
    """
    on_path = shutil.which("oasdiff")
    if on_path is not None:
        return Path(on_path)

    for candidate in _go_bin_candidates():
        if candidate.is_file():
            return candidate

    raise OasdiffNotFoundError(
        "oasdiff was not found on PATH or in the Go bin directory. "
        "The corpus and every diff in this repository depend on it. "
        f"Install it with: {_INSTALL_HINT}"
    )


def _go_bin_candidates() -> list[Path]:
    """Where `go install` would have put it, without requiring `go` itself to be installed."""
    roots: list[Path] = []
    gobin = os.environ.get("GOBIN")
    if gobin:
        roots.append(Path(gobin))
    gopath = os.environ.get("GOPATH")
    roots.append(Path(gopath) / "bin" if gopath else Path.home() / "go" / "bin")
    return [root / name for root in roots for name in ("oasdiff.exe", "oasdiff")]


def oasdiff_version() -> str:
    """The differ's self-reported version string, recorded in the corpus manifest.

    Kept verbatim rather than parsed into a version tuple: a change id set is a property of the
    exact build that produced it, and a manifest that rounded the version off would not let a reader
    reproduce the ids.

    Returns:
        The binary's `--version` output, stripped. A build made from source reports a branch name
        (``oasdiff version main``) rather than a tag, and that is recorded as-is.
    """
    completed = _run([str(find_oasdiff()), "--version"], timeout_s=60)
    return completed.stdout.strip()


def _run(argv: list[str], *, timeout_s: int) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with explicit UTF-8 decoding, which Windows does not default to."""
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        check=False,
    )


# -------------------------------------------------------------------------------- property paths


_SPAN: Final = r"`([^`]*)`"
"""A backticked span that is allowed to be empty: `oasdiff` prints the empty enum member as ``."""

_PATH: Final = r"`([^`]+)`"
"""A backticked span holding a property path, which is never empty."""

_SUBSCHEMA_SELECTORS: Final = ("oneOf[", "anyOf[", "allOf[")
"""Composition selectors. A path containing one does not name a single concrete property chain."""

_SHAPES: Final[tuple[tuple[str, re.Pattern[str], int | None], ...]] = (
    # (change id the shape belongs to, anchored pattern, 1-based group holding the property path;
    #  None where the change class has no property to speak of).
    #
    # Shapes where the property path is NOT the first span are marked. They are the reason this
    # table exists instead of a one-line regex.
    (
        "new-required-request-property",
        re.compile(rf"^added the new required request property {_PATH}$"),
        1,
    ),
    (
        "request-body-became-required",
        re.compile(r"^request body became required$"),
        None,  # the whole body, not a property
    ),
    (
        "request-parameter-removed",
        re.compile(rf"^deleted the {_PATH} request parameter {_PATH}$"),
        2,  # span 1 is the parameter location (`query`, `header`)
    ),
    (
        "request-parameter-type-changed",
        re.compile(
            rf"^for the {_PATH} request parameter {_PATH}, the {_PATH} was changed "
            rf"from {_SPAN} to {_SPAN}$"
        ),
        2,  # span 1 is the parameter location, span 3 the schema keyword that moved
    ),
    (
        "request-property-became-required",
        re.compile(rf"^the request property {_PATH} became required$"),
        1,
    ),
    (
        "request-property-enum-value-removed",
        re.compile(rf"^removed the enum value {_SPAN} of the request property {_PATH}$"),
        2,  # span 1 is the removed member, and it can be the empty string
    ),
    (
        "request-property-max-length-decreased",
        re.compile(rf"^the {_PATH} request property's maxLength was decreased to {_SPAN}$"),
        1,
    ),
    (
        "request-property-max-length-set",
        re.compile(rf"^the {_PATH} request property's maxLength was set to {_SPAN}$"),
        1,
    ),
    (
        "request-property-removed",
        re.compile(rf"^removed the request property {_PATH}$"),
        1,
    ),
    (
        "request-property-type-changed",
        re.compile(rf"^the {_PATH} request property {_PATH} changed from {_SPAN} to {_SPAN}$"),
        1,  # span 2 is the schema keyword (`type`, `format`), not a property
    ),
    (
        "response-media-type-removed",
        re.compile(rf"^removed the media type {_SPAN} for the response with the status {_SPAN}$"),
        None,  # a media type key, not a property
    ),
    (
        "response-optional-property-removed",
        re.compile(
            rf"^removed the optional property {_PATH} from the response with the {_SPAN} status$"
        ),
        1,
    ),
    (
        "response-property-became-optional",
        re.compile(rf"^the response property {_PATH} became optional for the status {_SPAN}$"),
        1,
    ),
    (
        "response-property-enum-value-added",
        re.compile(
            rf"^added the new {_SPAN} enum value to the {_PATH} response property "
            rf"for the response status {_SPAN}$"
        ),
        2,  # span 1 is the added member
    ),
    (
        "response-property-one-of-added",
        re.compile(
            rf"^added {_SPAN} to the {_PATH} response property `oneOf` list "
            rf"for the response status {_SPAN}$"
        ),
        2,  # span 1 is a `#/components/schemas/...` ref
    ),
    (
        "response-success-status-removed",
        re.compile(rf"^removed the success response with the status {_SPAN}$"),
        None,  # a status key, not a property
    ),
    # ---- Written after a review found the gap these eight left -----------------------------
    #
    # The expressibility table ruled on 24 ids while this table read 16 shapes, and the eight it
    # did not read carried 2,294 of the corpus's 3,383 changes. Those changes were ruled
    # expressible and then abstained anyway, because the property path is the only thing that
    # joins a change to a call site and there was nothing here to produce one. The abstention
    # rate looked like a property of the domain; it was a missing table.
    (
        "response-property-became-nullable",
        re.compile(rf"^the response property {_PATH} became nullable for the status {_SPAN}$"),
        1,
    ),
    (
        "response-property-type-changed",
        # Span 2 is the *schema keyword* that moved, and it is load-bearing: `type` changes the
        # emitted TypeScript, `format` does not (both render as `string`). The rule reads span 2
        # and abstains on anything but `type`, which is why the keyword is captured rather than
        # skipped over. 136 of this corpus's 144 are `type`; 8 are `format`.
        re.compile(
            rf"^the {_PATH} response's property {_SPAN} changed from {_SPAN} to {_SPAN} "
            rf"for status {_SPAN}$"
        ),
        1,
    ),
    (
        "response-required-property-removed",
        re.compile(
            rf"^removed the required property {_PATH} from the response with the {_SPAN} status$"
        ),
        1,
    ),
    (
        "request-body-removed",
        re.compile(r"^removed the request body$"),
        None,  # the whole body, not a property
    ),
    (
        "request-body-media-type-removed",
        re.compile(rf"^removed the media type {_SPAN} from the request body$"),
        None,  # a media type, not a property
    ),
    (
        "response-property-max-length-unset",
        re.compile(
            rf"^the {_PATH} response property's maxLength was unset from {_SPAN} "
            rf"for the response status {_SPAN}$"
        ),
        1,
    ),
    (
        "request-parameter-max-decreased",
        re.compile(
            rf"^for the {_PATH} request parameter {_PATH}, the max was decreased "
            rf"from {_SPAN} to {_SPAN}$"
        ),
        2,  # span 1 is the parameter location (`query`, `header`)
    ),
    (
        "response-property-min-length-decreased",
        re.compile(
            rf"^the {_PATH} response property's minLength was decreased from {_SPAN} to {_SPAN} "
            rf"for the response status {_SPAN}$"
        ),
        1,
    ),
)


def parse_property_path(text: str) -> tuple[tuple[str, ...] | None, bool]:
    """Pull the property path out of one `oasdiff` sentence.

    Args:
        text: The differ's `text` field, verbatim.

    Returns:
        A ``(path, parsed)`` pair, matching :class:`~callsite_impact.domain.SpecChange`:

        - ``(("billingAddress", "city"), True)`` -- parsed to a concrete chain.
        - ``(None, True)`` -- this change class has no property to parse. `request body became
          required` and `removed the success response with the status 200` are about an operation,
          not a field, so nothing failed.
        - ``(None, False)`` -- the sentence carries a property but it cannot be reduced to one
          chain, so the classifier abstains. Two causes, both deliberate:

          1. A ``oneOf``/``anyOf``/``allOf`` selector. `data/items/customer/anyOf[subschema #2:
             Customer]/id` is not a path through one object; it is a path that depends on which
             branch the value took. Emitting `("data", "items", "customer", "id")` would be a
             fabricated chain, so it is refused. This was the dominant source of abstention on the
             Stripe pair that was trialled and then dropped from the corpus (a selector on 80% and
             96% of changes across two runs, which also disagreed on the *total* change count for
             byte-identical input -- 3072 against 16466 -- while a third run was killed outright).
             Stripe is no longer in the corpus, so no Stripe figure is published; on the three
             vendors that remain the differ is byte-for-byte reproducible and selectors are a much
             smaller effect than cause 2 below.
          2. Prose matching no shape in :data:`_SHAPES` -- a change class this repository has not
             read. **This is now the bulk source of abstention.** :data:`_SHAPES` reads 16 shapes
             while the expressibility table rules on 24 ids, and the 8 unread ones carry 2,294 of
             the corpus's 3,383 changes (~68%), `response-property-became-nullable` alone being
             2,087. Those changes are ruled expressible and still return ``(None, False)`` here.
             Guessing the first backticked span is exactly the failure this module exists to avoid,
             so they abstain until their shapes are written and validated.

        A trailing empty segment (`subMerchants/items/`) is dropped: it is how the differ renders
        the array element itself, and the shortened chain still points at the right thing. An
        interior empty segment has no such reading and is refused.
    """
    for _change_id, pattern, group in _SHAPES:
        match = pattern.match(text)
        if match is None:
            continue
        if group is None:
            return None, True

        raw = match.group(group)
        if any(selector in raw for selector in _SUBSCHEMA_SELECTORS):
            return None, False

        segments = raw.split("/")
        if segments[-1] == "":
            segments = segments[:-1]
        if not segments or any(segment == "" for segment in segments):
            return None, False
        return tuple(segments), True

    return None, False


# -------------------------------------------------------------------------------------- diffing


def diff_pair(
    before: Path,
    after: Path,
    *,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> list[SpecChange]:
    """Diff two spec revisions and return the breaking changes, typed.

    Only breaking changes are requested. The tool's question is which call sites break, and
    `oasdiff`'s non-breaking changelog would add rows that cannot produce a compiler label.

    Args:
        before: Revision A, the spec the call sites were generated from.
        after: Revision B.
        timeout_s: Wall-clock limit for the differ.

    Returns:
        One :class:`~callsite_impact.domain.SpecChange` per reported change, in the order the differ
        emitted them.

    Raises:
        FileNotFoundError: If either spec is missing, checked here so the failure names the file
            rather than surfacing as a differ exit code.
        OasdiffNotFoundError: If the binary is not installed.
        OasdiffFailedError: If the differ rejected a spec. Its stderr is carried through because
            it is specific and useful -- duplicate endpoints and unmarshal failures land here.
    """
    for label, path in (("before", before), ("after", after)):
        if not path.is_file():
            raise FileNotFoundError(f"{label} spec not found: {path}")

    argv = [str(find_oasdiff()), "breaking", str(before), str(after), "-f", "json"]
    completed = _run(argv, timeout_s=timeout_s)
    if completed.returncode != 0:
        raise OasdiffFailedError(
            f"oasdiff exited {completed.returncode} diffing {before.name} -> {after.name}: "
            f"{completed.stderr.strip()}"
        )

    payload = completed.stdout.strip()
    if not payload:
        return []
    raw_changes = json.loads(payload)
    if raw_changes is None:
        return []
    return [_to_change(entry) for entry in raw_changes]


def _to_change(entry: dict[str, Any]) -> SpecChange:
    """Map one `oasdiff` JSON object onto the domain type.

    `source`, `source_line` and `source_column` are read defensively and left ``None`` when absent.
    The build measured here emits `id`, `text`, `level`, `operation`, `operationId`, `path`,
    `section` and `fingerprint` and no source location at all, so those fields are usually empty --
    recorded as unknown rather than filled with a plausible guess.
    """
    text = str(entry["text"])
    property_path, parsed = parse_property_path(text)
    source = entry.get("source")
    return SpecChange(
        change_id=str(entry["id"]),
        level=int(entry["level"]),
        method=str(entry.get("operation") or ""),
        path=str(entry.get("path") or ""),
        text=text,
        property_path=property_path,
        property_path_parsed=parsed,
        expressibility=expressibility_of(str(entry["id"])),
        source_file=source if isinstance(source, str) and source else None,
        source_line=_as_int(entry.get("sourceLine")),
        source_column=_as_int(entry.get("sourceColumn")),
    )


def _as_int(value: object) -> int | None:
    """Accept only a genuine integer. A missing position is ``None``, never 0."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None
