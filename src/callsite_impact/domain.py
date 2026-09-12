"""The shared vocabulary. Every stage of the pipeline speaks in these types and nothing else.

Written before the stages that use them, because the interesting decisions in this project are all
decisions about what a *label* is, and those have to be settled before anything can be measured.

The one that matters most is :class:`Expressibility`. A specification differ reports a change to a
document; the TypeScript compiler reports a failure to typecheck. Those are not the same set, and the
gap between them is not noise — it is the finding. ``maxLength`` decreasing is unambiguously a
breaking change to an API and is **invisible** to a type system. Any verdict that treats a clean
compile there as evidence of safety is lying, so the type below forces the question to be answered
for every change class before a verdict can be formed.
"""

from __future__ import annotations

import enum
import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Callsite",
    "CallsiteFacts",
    "CompilerLabel",
    "Expressibility",
    "Finding",
    "PropertyAccess",
    "SpecChange",
    "SpecPair",
    "Verdict",
    "VendorSpec",
    "callsite_id",
]


class _Frozen(BaseModel):
    """Everything here is a record of something that happened. None of it is edited afterwards."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------------------- provenance


class VendorSpec(_Frozen):
    """One revision of one specification document, pinned hard enough to fetch again.

    ``sha256`` is over the bytes actually used. A corpus that cannot prove it ran against the bytes
    it claims is a corpus whose numbers cannot be checked.
    """

    vendor: str
    service: str
    revision: str
    """The vendor's own identifier: a git commit SHA, a release tag, or a version suffix."""
    revision_date: str | None = None
    source_url: str
    licence: str
    sha256: str
    local_path: str


class SpecPair(_Frozen):
    """A before/after pair. The unit the whole pipeline is organised around."""

    pair_id: str
    vendor: str
    service: str
    before: VendorSpec
    after: VendorSpec


# ------------------------------------------------------------------------------------- spec changes


class Expressibility(enum.StrEnum):
    """Can the TypeScript type system represent this change class at all?

    This is a property of the *change class*, not of any call site, and it is decided from a table
    that is written down, reviewed and tested — never inferred per case, which is how a judgement
    call becomes a silent default.
    """

    TYPE_EXPRESSIBLE = "type_expressible"
    """A call site can be made to fail on it: removals, renames, requiredness, type and enum shape."""

    NOT_TYPE_EXPRESSIBLE = "not_type_expressible"
    """A runtime or prose constraint: `maxLength`, `pattern`, `minimum`, auth, rate limit, behaviour.

    Compilation proves nothing here in either direction, so the only honest verdict is UNKNOWN.
    """

    UNCLASSIFIED = "unclassified"
    """A change class this repository has not ruled on. Treated as NOT_TYPE_EXPRESSIBLE.

    Deliberately fails towards abstention: an unclassified change silently treated as expressible
    would let the scorer count a clean compile as a correct UNAFFECTED, inventing accuracy.
    """


class SpecChange(_Frozen):
    """One change, as the differ reported it, plus what this repository decided it means.

    ``property_path`` is parsed out of the differ's prose because that is where the differ puts it.
    The parse can fail, and when it fails the field is ``None`` rather than a guess — a wrong
    property path would send a verdict to the wrong call site with full confidence.
    """

    change_id: str
    """`oasdiff`'s stable identifier, e.g. `request-property-removed`."""
    level: int
    """`oasdiff` severity. 3 = ERR (breaking), 2 = WARN, 1 = INFO."""
    method: str
    path: str
    text: str
    """The differ's own sentence, kept verbatim so a reader can check the parse against it."""
    property_path: tuple[str, ...] | None = None
    """The dotted property the change is about, split on `/`, e.g. `("billingAddress", "city")`."""
    property_path_parsed: bool = True
    """False when the prose carried a property but this repository could not parse it cleanly."""
    expressibility: Expressibility
    source_file: str | None = None
    source_line: int | None = None
    source_column: int | None = None

    @property
    def operation_key(self) -> str:
        """`METHOD path` — the join key between a change and the call sites that use it."""
        return f"{self.method.upper()} {self.path}"


# ---------------------------------------------------------------------------------------- callsites


class PropertyAccess(_Frozen):
    """One property a call site touches, with the position the source has it at.

    ``optional_chained`` exists because ``a?.b`` and ``a.b`` fail differently when ``b`` becomes
    optional: under ``strict`` the second stops assigning to a non-optional target and the first does
    not. A classifier that cannot see the difference cannot get `became-optional` right.
    """

    path: tuple[str, ...]
    line: int
    column: int
    optional_chained: bool = False
    literal_value: str | None = None
    """The literal passed, when there is one. Needed to decide enum-member removals."""


class CallsiteFacts(_Frozen):
    """What a *parser* can see in a call site — no type checking, no compiler, no model.

    Produced by the extractor in `harness/`, which builds a TypeScript AST and walks it. The guard
    test in `tests/test_oracle_boundary.py` fails the build if that extractor ever reaches for
    `createProgram` or `getTypeChecker`, because the moment it does, the system under test is reading
    the answer key.
    """

    operation_key: str
    request_properties: tuple[PropertyAccess, ...] = ()
    response_properties: tuple[PropertyAccess, ...] = ()


class Callsite(_Frozen):
    """One generated call site: a single realistic use of a single operation.

    Generated from the **before** revision and typechecked clean against it before it is admitted.
    One that does not compile clean is discarded — never repaired — because repairing it would let
    the author choose what breaks.
    """

    callsite_id: str
    pair_id: str
    vendor: str
    file: str
    line: int
    operation_key: str
    facts: CallsiteFacts
    generator_seed: int


def callsite_id(pair_id: str, operation_key: str, index: int) -> str:
    """A stable id from business identity alone.

    No clock, no host, no run counter: two runs of the same generator over the same pair must name
    the same call site the same thing, or nothing can be compared across runs.
    """
    digest = hashlib.sha256(f"{pair_id}|{operation_key}|{index}".encode()).hexdigest()
    return f"cs_{digest[:12]}"


# ------------------------------------------------------------------------------------- ground truth


class CompilerLabel(_Frozen):
    """What `tsc` said. The answer key, and the only thing in this repository that is ground truth.

    Lives in its own type so that it can be kept out of the classifier's reach by import, not by
    good intentions.
    """

    callsite_id: str
    file: str
    line: int
    column: int
    ts_error_code: str
    message: str


# ------------------------------------------------------------------------------------------ verdict


class Verdict(enum.StrEnum):
    IMPACTED = "impacted"
    UNAFFECTED = "unaffected"
    UNKNOWN = "unknown"


class Finding(_Frozen):
    """One (call site, change) pair, judged, with the anchors that let a reader check it.

    There is deliberately **no confidence score and no free-text field a model may write**. A model
    cannot express a verdict here because the type has nowhere to put one; that is the AI boundary,
    and it is structural rather than a rule someone has to remember. `tests/test_ai_boundary.py`
    walks this schema and fails the build if such a field appears.
    """

    callsite_id: str
    pair_id: str
    verdict: Verdict
    rule: str
    """Which declared rule produced this verdict. Names a branch in `classify/rules.py`."""
    reason: Literal[
        "sets_removed_request_property",
        "omits_newly_required_request_property",
        "reads_removed_response_property",
        "reads_property_that_became_optional",
        "passes_removed_enum_member",
        "touches_changed_property_type",
        "operation_removed",
        "property_untouched_by_callsite",
        "operation_untouched_by_callsite",
        "change_not_expressible_in_type_system",
        "property_path_unparsable",
        "property_path_shape_unsupported",
    ]
    change: SpecChange
    callsite_file: str
    callsite_line: int
    callsite_column: int | None = None
    callsite_token: str | None = None
    """The source token the verdict is about, so a reader can look at the exact thing."""

    @property
    def anchored(self) -> bool:
        """A verdict with no call-site position is not publishable; it is counted and suppressed."""
        return bool(self.callsite_file) and self.callsite_line > 0


class RunSummary(_Frozen):
    """The numbers a run produced, written by the run rather than typed into a document."""

    pairs: int
    vendors: tuple[str, ...]
    callsites_generated: int
    callsites_admitted: int
    callsites_discarded: int
    compiler_breakages: int = Field(
        description="Call sites on which tsc errored. The strict kill-criterion count."
    )
    compiler_clean: int
    candidate_findings: int
