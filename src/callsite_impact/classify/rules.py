"""One rule per spec-change class. Each answers exactly one question: can this change reach *this*
call site's usage?

Every rule sees two things and nothing else — the :class:`~callsite_impact.domain.SpecChange` as the
differ reported it, and the :class:`~callsite_impact.domain.CallsiteFacts` a parser read out of the
source. No compiler output, no model, no type checker. That is not a convention to remember; the
signature has nowhere to put one, and ``tests/test_oracle_boundary.py`` fails the build if this
package ever imports the oracle.

**The shared rule contract.** Every function in ``RULES`` takes ``(change, facts)`` and returns a
:class:`RuleResult` — a verdict, a reason drawn from the closed vocabulary on
:class:`~callsite_impact.domain.Finding`, and optionally the single property access the verdict is
about so the engine can anchor the finding at a line and column. A rule that decides on an *absence*
(a newly required property the call site omits) returns no access: there is no token to point
at, and the finding is anchored at the call site itself.

**Limitations, stated rather than hidden.**

The reason vocabulary is closed and lives on ``Finding``, which this lane does not own. It carries
two ``*_untouched_by_callsite`` members and only ``property_untouched_by_callsite`` is usable here:
``operation_untouched_by_callsite`` cannot be true of anything this package emits, because a finding
exists only for a call site on the change's own operation. So several rules reach UNAFFECTED for a
reason that is not literally "untouched" — the requiredness is already satisfied, the read is
optional-chained, the literal passed is not the removed member — and they still use it. Widening
a type that exists in order to be narrow would be the worse trade.

The same borrowing happens on the other side, and it is named here because the reason is published.
An enum sentence whose member cannot be isolated reports ``property_path_unparsable`` although the
path parsed; a change id with no rule reports ``change_not_expressible_in_type_system`` although the
authority table called it expressible; a removed success status or media type reports
``operation_removed`` although the operation survives. In each case ``Finding.rule`` names the
branch that actually decided, and it is the field to read when the reason and the change disagree.

*Widening* on a response (``response-property-enum-value-added``) is not decided here wherever the
call site reads the path. It breaks only a call site that pinned the narrow type in an annotation,
and an annotation's content is not visible to a parser that does no type resolution. The rule
abstains there, and the abstention rate is published rather than quietly converted into an
UNAFFECTED; where the path is never read the answer is UNAFFECTED, which is decidable.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from typing import Final, Literal, NamedTuple

from callsite_impact.domain import (
    CallsiteFacts,
    Expressibility,
    PropertyAccess,
    SpecChange,
    Verdict,
)

__all__ = [
    "ARRAY_TRAVERSAL_SEGMENT",
    "RULES",
    "Reason",
    "Rule",
    "RuleResult",
    "added_response_enum_member",
    "added_response_one_of",
    "changed_request_field_type",
    "classify_change",
    "matching_accesses",
    "newly_required_request_field",
    "normalise_change_path",
    "normalise_literal",
    "parse_enum_removal",
    "path_matches",
    "removed_request_enum_member",
    "removed_request_field",
    "removed_response_property",
    "removed_response_shape",
    "request_body_became_required",
    "response_property_became_optional",
]


Reason = Literal[
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
    "pins_widened_response_type",
    "reads_through_now_nullable_property",
    "supplies_a_request_body_that_was_removed",
]
"""Mirror of ``Finding.reason``. Duplicated because ``domain.py`` is not this lane's to edit; the
duplication is held true by a test that compares the two literal sets member for member."""


class RuleResult(NamedTuple):
    """What a rule decided, and the one access it decided it on.

    ``access`` is ``None`` when the evidence is an absence rather than a token — the call site fails
    to set a newly required property, say — or when the change is not about a property at all.
    """

    verdict: Verdict
    reason: Reason
    access: PropertyAccess | None = None


Rule = Callable[[SpecChange, CallsiteFacts], RuleResult]
"""Every rule has this shape. Two inputs, both facts; one output, a verdict with its evidence."""


# ----------------------------------------------------------------------------------- path matching

ARRAY_TRAVERSAL_SEGMENT: Final = "items"
"""JSON Schema names the element type of an array ``items``; TypeScript source does not.

``oasdiff`` reports ``lineItems/items/sku``. A call site writes ``lineItems[0].sku``, and
the extractor records that as ``("lineItems", "sku")`` — the index is a subscript, not a named
property. Comparing the two literally would miss every array member on the corpus, so the segment is
dropped from the *change* path before comparison. It is never dropped from the access path: a call
site really can have a property called ``items``, and silently deleting it there would make
``basket.items.total`` match a change to ``basket.total``.
"""


def normalise_change_path(path: Sequence[str]) -> tuple[str, ...]:
    """Drop array-traversal segments so a spec path can be compared to a source access.

    Args:
        path: The property path as the differ reported it, already split on ``/``.

    Returns:
        The same path with every ``items`` segment removed. Possibly empty, if the path consisted of
        nothing else — a case the caller must treat as "no usable path" rather than "matches
        everything".
    """
    return tuple(segment for segment in path if segment != ARRAY_TRAVERSAL_SEGMENT)


def path_matches(change_path: Sequence[str], access_path: Sequence[str]) -> bool:
    """Does a change at ``change_path`` reach an access at ``access_path``?

    Prefix containment, in one direction only. A change to ``("a", "b")`` reaches ``a.b`` and also
    reaches ``a.b.c``, because you cannot read ``a.b.c`` once ``a.b`` is gone. It does not reach
    ``a`` — the parent survives its child — and it does not reach ``a.c``. Getting the direction
    wrong in either sense costs accuracy: matching upwards invents false positives on every sibling,
    matching only exactly misses every deep read.

    Args:
        change_path: Property path from the spec change, pre-normalisation.
        access_path: Property path the parser recorded at the call site.

    Returns:
        True when the normalised change path is a prefix of the access path.
    """
    wanted = normalise_change_path(change_path)
    if not wanted:
        return False
    return tuple(access_path[: len(wanted)]) == wanted


def matching_accesses(
    change_path: Sequence[str],
    accesses: Iterable[PropertyAccess],
) -> list[PropertyAccess]:
    """Every access the change reaches, in source order.

    Args:
        change_path: Property path from the spec change.
        accesses: The parsed accesses on one side of one call site.

    Returns:
        Matching accesses sorted by line, then column, then path, so that the anchor a finding
        carries does not depend on the order the extractor happened to emit.
    """
    hits = [access for access in accesses if path_matches(change_path, access.path)]
    return sorted(hits, key=lambda access: (access.line, access.column, access.path))


def _first(accesses: Iterable[PropertyAccess]) -> PropertyAccess | None:
    """The earliest access in source order, or None. Deterministic anchor selection."""
    ordered = sorted(accesses, key=lambda access: (access.line, access.column, access.path))
    return ordered[0] if ordered else None


# --------------------------------------------------------------------------------- prose parsing

_BACKTICKED: Final = re.compile(r"`([^`]*)`")
"""``oasdiff`` quotes the identifiers it names in backticks. That is the only handle its prose gives
us, and the parse is checked against ``change.text``, which is kept verbatim for exactly that.

The span is allowed to be **empty**: ``oasdiff`` prints the empty enum member as a pair of backticks
with nothing between them, and a call site really can pass ``''``. A ``+`` here would skip that
member and quietly return UNAFFECTED on a genuine breakage.
"""

_QUOTE_CHARACTERS: Final = "\"'`"


def normalise_literal(value: str) -> str:
    """Strip the quoting a TypeScript literal carries so it can be compared to a spec enum member.

    The extractor records ``'visa'`` or ``"visa"`` as written; the differ writes ``visa``. Comparing
    them raw would make every enum rule return UNAFFECTED, which is the quiet failure — a missed
    breakage reads as a pass.

    Args:
        value: A literal as recorded by the extractor, or an enum member as the differ wrote it.

    Returns:
        The value with surrounding whitespace and one matched pair of quotes removed.
    """
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in _QUOTE_CHARACTERS:
        return stripped[1:-1]
    return stripped


def parse_enum_removal(change: SpecChange) -> tuple[tuple[str, ...], str] | None:
    """Identify the removed enum member in an enum-removal sentence.

    ``oasdiff`` writes::

        removed the enum value `visa` of the request property `paymentMethod/type`

    The member is the span that is **not** the property path, and which position it occupies is not
    relied on. Span order varies between change classes — the differ lane keeps a per-id table for
    exactly that reason — so a rule that hard-coded "first" or "last" would be a second place for
    the same mistake, and its failure would be silent: comparing a call site's literal against a
    property name always mismatches, and a mismatch reads as UNAFFECTED.

    The path is never re-derived from the prose. ``change.property_path`` is the differ lane's
    parse and is the only one; where that lane produced none, this abstains rather than guess. The
    span is compared with a trailing ``/`` stripped, because that lane drops the differ's trailing
    empty segment (``subMerchants/items/``) and the two spellings must still recognise each other.

    Args:
        change: An enum-removal change, with ``text`` as the differ emitted it.

    Returns:
        ``(property_path, removed_member)``, or None when exactly one non-path span cannot be found.
    """
    path = change.property_path
    if path is None:
        return None
    rendered = "/".join(path)
    spans: list[str] = _BACKTICKED.findall(change.text)
    candidates = [span for span in spans if span.rstrip("/") != rendered]
    if len(candidates) != 1:
        return None
    return path, candidates[0]


# ----------------------------------------------------------------------------------------- rules


def removed_request_field(change: SpecChange, facts: CallsiteFacts) -> RuleResult:
    """A removed request property or parameter breaks only the call sites that set it.

    Everything else on the operation keeps compiling, which is the whole reason a differ's count of
    "breaking changes" overstates the work: the change is real, it just does not reach most callers.

    Returns:
        IMPACTED anchored at the assignment, or UNAFFECTED.
    """
    path = change.property_path
    if path is None:
        return RuleResult(Verdict.UNKNOWN, "property_path_unparsable")
    hit = _first(matching_accesses(path, facts.request_properties))
    if hit is not None:
        return RuleResult(Verdict.IMPACTED, "sets_removed_request_property", hit)
    return RuleResult(Verdict.UNAFFECTED, "property_untouched_by_callsite")


def newly_required_request_field(change: SpecChange, facts: CallsiteFacts) -> RuleResult:
    """A newly required property breaks the call sites that *omit* it — the inverse of removal.

    The evidence is therefore an absence, and an absence has no line and no token. The finding is
    anchored at the call site, which is the most specific anchor that honestly exists.

    Returns:
        IMPACTED unanchored when the path is not set, otherwise UNAFFECTED anchored at the setter.
    """
    path = change.property_path
    if path is None:
        return RuleResult(Verdict.UNKNOWN, "property_path_unparsable")
    hit = _first(matching_accesses(path, facts.request_properties))
    if hit is None:
        return RuleResult(Verdict.IMPACTED, "omits_newly_required_request_property")
    return RuleResult(Verdict.UNAFFECTED, "property_untouched_by_callsite", hit)


def request_body_became_required(change: SpecChange, facts: CallsiteFacts) -> RuleResult:
    """A newly required request body breaks only a call site that passes no body at all.

    Which property the call site sets does not matter here; that it sets *any* is proof a body is
    being constructed. A call site supplying a single optional field already satisfies the new
    requirement, so treating the whole operation as impacted would be the naive baseline's mistake.

    Returns:
        IMPACTED when the call site supplies no request properties, otherwise UNAFFECTED.
    """
    hit = _first(facts.request_properties)
    if hit is None:
        return RuleResult(Verdict.IMPACTED, "omits_newly_required_request_property")
    return RuleResult(Verdict.UNAFFECTED, "property_untouched_by_callsite", hit)


def removed_response_property(change: SpecChange, facts: CallsiteFacts) -> RuleResult:
    """A removed response property breaks only the call sites that read it.

    Returns:
        IMPACTED anchored at the read, or UNAFFECTED.
    """
    path = change.property_path
    if path is None:
        return RuleResult(Verdict.UNKNOWN, "property_path_unparsable")
    hit = _first(matching_accesses(path, facts.response_properties))
    if hit is not None:
        return RuleResult(Verdict.IMPACTED, "reads_removed_response_property", hit)
    return RuleResult(Verdict.UNAFFECTED, "property_untouched_by_callsite")


def response_property_became_optional(change: SpecChange, facts: CallsiteFacts) -> RuleResult:
    """A response property that became optional breaks the reads that did not guard for it.

    Under ``strict``, ``a.b`` on a now-optional ``b`` stops assigning to a non-optional target and
    ``a?.b`` does not. This is the one rule where how a read is *navigated* decides, which
    is why :class:`~callsite_impact.domain.PropertyAccess` records ``optional_chained`` at all. A
    call site with both a guarded and an unguarded read of the same path is impacted: one unguarded
    read is enough.

    Returns:
        IMPACTED anchored at the earliest unguarded read, otherwise UNAFFECTED.
    """
    path = change.property_path
    if path is None:
        return RuleResult(Verdict.UNKNOWN, "property_path_unparsable")
    hits = matching_accesses(path, facts.response_properties)
    unguarded = [access for access in hits if not access.optional_chained]
    if unguarded:
        return RuleResult(
            Verdict.IMPACTED, "reads_property_that_became_optional", _first(unguarded)
        )
    return RuleResult(Verdict.UNAFFECTED, "property_untouched_by_callsite", _first(hits))


def removed_request_enum_member(change: SpecChange, facts: CallsiteFacts) -> RuleResult:
    """A removed enum member breaks only the call sites that pass that exact member.

    Narrowing a request union is the change class where the *value* decides, not the path. A call
    site that sets the property from a variable rather than a literal is not judged impacted: the
    parser cannot see what the variable holds, and asserting a breakage it cannot anchor would be a
    claim about code it did not read.

    Returns:
        IMPACTED anchored at the literal, UNAFFECTED, or UNKNOWN when the prose will not parse.
    """
    parsed = parse_enum_removal(change)
    if parsed is None:
        return RuleResult(Verdict.UNKNOWN, "property_path_unparsable")
    path, member = parsed
    hits = matching_accesses(path, facts.request_properties)
    if not hits:
        return RuleResult(Verdict.UNAFFECTED, "property_untouched_by_callsite")
    target = normalise_literal(member)
    passing = [
        access
        for access in hits
        if access.literal_value is not None and normalise_literal(access.literal_value) == target
    ]
    if passing:
        return RuleResult(Verdict.IMPACTED, "passes_removed_enum_member", _first(passing))
    return RuleResult(Verdict.UNAFFECTED, "property_untouched_by_callsite", _first(hits))


def added_response_enum_member(change: SpecChange, facts: CallsiteFacts) -> RuleResult:
    """An enum member added to a response *widens* a union, and widening is the hard case.

    It can only break a call site that pinned the narrow type — an annotation naming revision A's
    union, or an exhaustive ``switch`` whose ``never`` default the new member falls through. An
    inferred ``const x = res.status`` simply becomes wider and compiles.

    **An earlier version of this rule abstained here**, on the reasoning that a parser cannot see
    what a binding does. That was wrong, and expensively so: this is the single largest change class
    in the corpus, and abstaining on all of it traded most of the tool's recall for nothing. An
    annotation and a ``never`` assertion are *tokens*, not types — `extract-facts.mjs` reads them
    off the syntax tree without resolving anything, and `PropertyAccess.pinned` carries it. The
    boundary that matters is the type **checker**, and it is still untouched.

    Returns:
        IMPACTED anchored at the earliest pinned read, UNAFFECTED otherwise.
    """
    path = change.property_path
    if path is None:
        return RuleResult(Verdict.UNKNOWN, "property_path_unparsable")
    hits = matching_accesses(path, facts.response_properties)
    pinned = [access for access in hits if access.pinned]
    if pinned:
        return RuleResult(Verdict.IMPACTED, "pins_widened_response_type", _first(pinned))
    return RuleResult(Verdict.UNAFFECTED, "property_untouched_by_callsite", _first(hits))


def response_property_became_nullable(change: SpecChange, facts: CallsiteFacts) -> RuleResult:
    """``T`` becoming ``T | null`` breaks two shapes of read and leaves a third alone.

    It breaks a read that **pinned** the non-nullable type, and it breaks a read that goes *through*
    the property without guarding — ``res.a.b`` is TS18047 once ``a`` can be null. It does not break
    ``const x = res.a``, which simply infers the wider type, nor ``res.a?.b``, which guards.

    This is the largest change class in the corpus by a wide margin, so the distinction above is
    doing most of the work in the headline numbers. It is also the reason ``pinned`` exists.

    Returns:
        IMPACTED anchored at the read that breaks, UNAFFECTED otherwise.
    """
    path = change.property_path
    if path is None:
        return RuleResult(Verdict.UNKNOWN, "property_path_unparsable")
    hits = matching_accesses(path, facts.response_properties)
    pinned = [access for access in hits if access.pinned]
    if pinned:
        return RuleResult(Verdict.IMPACTED, "pins_widened_response_type", _first(pinned))
    # A read strictly deeper than the changed path dereferences it; unguarded, that is TS18047.
    through = [
        access for access in hits if len(access.path) > len(path) and not access.optional_chained
    ]
    if through:
        return RuleResult(Verdict.IMPACTED, "reads_through_now_nullable_property", _first(through))
    return RuleResult(Verdict.UNAFFECTED, "property_untouched_by_callsite", _first(hits))


_RESPONSE_KEYWORD = re.compile(r"^the `[^`]*` response's property `([^`]*)` changed")


def changed_response_property_type(change: SpecChange, facts: CallsiteFacts) -> RuleResult:
    """A response property whose type changed breaks the reads that named the old type.

    Two instances of this change class are not the same question, and the id does not distinguish
    them. The differ says *"the `X` response's property `type` changed"* and also *"… property
    `format` changed"* — and only the first reaches the type system. `format: uri-map` and
    `format: none` both emit ``string``, so a `format` change cannot make any call site fail and a
    clean compile on one proves nothing. It abstains. This corpus holds 136 `type` and 8 `format`.

    That is the one place where expressibility is a property of the *instance* rather than the
    class, so the authority table cannot settle it and the rule has to read the prose.

    An inferred binding absorbs a genuinely changed type silently — ``const x = res.a`` compiles
    whether ``a`` is a string or a number. Only a pinned read states the old type.

    Returns:
        UNKNOWN for a non-`type` keyword, IMPACTED at the earliest pinned read, else UNAFFECTED.
    """
    keyword = _RESPONSE_KEYWORD.match(change.text)
    if keyword is not None and keyword.group(1) != "type":
        return RuleResult(Verdict.UNKNOWN, "change_not_expressible_in_type_system")
    path = change.property_path
    if path is None:
        return RuleResult(Verdict.UNKNOWN, "property_path_unparsable")
    hits = matching_accesses(path, facts.response_properties)
    pinned = [access for access in hits if access.pinned]
    if pinned:
        return RuleResult(Verdict.IMPACTED, "touches_changed_property_type", _first(pinned))
    return RuleResult(Verdict.UNAFFECTED, "property_untouched_by_callsite", _first(hits))


def removed_request_body(change: SpecChange, facts: CallsiteFacts) -> RuleResult:
    """The whole request body, or its JSON media type, is gone.

    Any call site that builds a body at all now types it against nothing. Unlike the per-property
    rules there is no path to match: the evidence is that the call site supplies a body.

    Returns:
        IMPACTED when the call site sets any request property, UNAFFECTED when it sets none.
    """
    if facts.request_properties:
        return RuleResult(
            Verdict.IMPACTED,
            "supplies_a_request_body_that_was_removed",
            _first(facts.request_properties),
        )
    return RuleResult(Verdict.UNAFFECTED, "property_untouched_by_callsite")


def changed_request_field_type(change: SpecChange, facts: CallsiteFacts) -> RuleResult:
    """A request property or parameter whose type changed breaks every call site that touches it.

    Unlike a removal, the direction of the type change does not need to be known: a call site that
    supplies the old type is passing a value the new declaration does not accept, whatever the new
    declaration is. Only the request side is consulted — a request-side type change cannot reach a
    response read.

    Returns:
        IMPACTED anchored at the assignment, or UNAFFECTED.
    """
    path = change.property_path
    if path is None:
        return RuleResult(Verdict.UNKNOWN, "property_path_unparsable")
    hit = _first(matching_accesses(path, facts.request_properties))
    if hit is not None:
        return RuleResult(Verdict.IMPACTED, "touches_changed_property_type", hit)
    return RuleResult(Verdict.UNAFFECTED, "property_untouched_by_callsite")


def removed_response_shape(change: SpecChange, facts: CallsiteFacts) -> RuleResult:
    """A removed success status or media type takes the whole response type with it.

    There is no property path to match: the operation stops returning a typed body, so every read of
    that body fails. A call site that calls the operation and reads nothing from it still compiles,
    which is why this is not simply "every call site on the operation".

    Returns:
        IMPACTED anchored at the first response read, or UNAFFECTED when nothing is read.
    """
    hit = _first(facts.response_properties)
    if hit is not None:
        return RuleResult(Verdict.IMPACTED, "operation_removed", hit)
    return RuleResult(Verdict.UNAFFECTED, "property_untouched_by_callsite")


def added_response_one_of(change: SpecChange, facts: CallsiteFacts) -> RuleResult:
    """A new ``oneOf`` branch on a response turns a concrete object into a union, unconditionally
    unresolved here.

    Whether a read still typechecks depends on whether the property survives into every branch, and
    the branches live in the spec document rather than in the call-site source this lane reads. No
    parse of the call site can settle it, so there is no case in which this rule rules.

    Returns:
        Always UNKNOWN.
    """
    return RuleResult(Verdict.UNKNOWN, "property_path_shape_unsupported")


RULES: Final[dict[str, Rule]] = {
    "request-property-removed": removed_request_field,
    "request-parameter-removed": removed_request_field,
    "request-property-became-required": newly_required_request_field,
    "new-required-request-property": newly_required_request_field,
    "request-body-became-required": request_body_became_required,
    "response-optional-property-removed": removed_response_property,
    "response-property-became-optional": response_property_became_optional,
    "request-property-enum-value-removed": removed_request_enum_member,
    "response-property-enum-value-added": added_response_enum_member,
    "request-property-type-changed": changed_request_field_type,
    "request-parameter-type-changed": changed_request_field_type,
    "response-success-status-removed": removed_response_shape,
    "response-media-type-removed": removed_response_shape,
    "response-property-one-of-added": added_response_one_of,
    # Ruled on after the corpus grew to Twilio, whose six-year revision gaps produce change classes
    # the first three Adyen and Xero pairs never did. `response-property-became-nullable` alone is
    # 2,087 of the corpus's 3,383 changes -- more than the other twenty-three ids put together.
    "response-property-became-nullable": response_property_became_nullable,
    "response-property-type-changed": changed_response_property_type,
    "response-required-property-removed": removed_response_property,
    "request-body-removed": removed_request_body,
    "request-body-media-type-removed": removed_request_body,
}
"""Every change id this repository has ruled on, and nothing else.

``oasdiff`` v1.29.1 can emit 514 ids. This table does not pretend to 514; an id absent from
this table falls through to abstention, and the count of changes that did so is published beside the
results. One function may serve several ids where the question they pose is genuinely the same — a
removed query parameter and a removed body property are the same question — and the finding still
carries the original ``change_id`` so a reader can see which one arrived.
"""


def classify_change(change: SpecChange, facts: CallsiteFacts) -> tuple[str, RuleResult]:
    """Judge one change against one call site's parsed facts.

    Two gates run before any rule, in this order and with no way around them:

    1. **Expressibility.** If the change class is not one the TypeScript type system can represent,
       no call site can be made to fail on it and a clean compile proves nothing. The test is
       ``is not TYPE_EXPRESSIBLE`` rather than a list of the abstaining values, so a member added to
       the enum later fails towards abstention instead of towards a confident wrong answer.
    2. **Path parse.** ``property_path_parsed`` is False when the differ named a property this
       repository could not read cleanly — a subschema selector, typically. A wrong path would send
       a verdict to the wrong call site at full confidence, so it is not guessed.

    Args:
        change: The change as the differ reported it, with its expressibility already resolved.
        facts: What a parser could see at one call site. Never compiler output.

    Returns:
        ``(rule_name, result)``. ``rule_name`` names the branch that decided, including the gates,
        so that every finding says what produced it.
    """
    if change.expressibility is not Expressibility.TYPE_EXPRESSIBLE:
        return (
            "expressibility_gate",
            RuleResult(Verdict.UNKNOWN, "change_not_expressible_in_type_system"),
        )
    if not change.property_path_parsed:
        return ("property_path_gate", RuleResult(Verdict.UNKNOWN, "property_path_unparsable"))
    rule = RULES.get(change.change_id)
    if rule is None:
        return (
            "no_rule_for_change_id",
            RuleResult(Verdict.UNKNOWN, "change_not_expressible_in_type_system"),
        )
    return (rule.__name__, rule(change, facts))
