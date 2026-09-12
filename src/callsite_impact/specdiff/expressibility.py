"""Which `oasdiff` change classes the TypeScript type system can express, decided in a table.

This exists as a written table rather than a function that reasons about each change because the
judgement is the load-bearing part of the project and a judgement made per case is a judgement
nobody can review. A reader who disagrees with a row can point at the row.

The default matters more than any single row. An id absent from the table is ``UNCLASSIFIED``,
which the pipeline treats as not expressible and answers UNKNOWN. The opposite default is the
dangerous one: an unruled change class silently treated as expressible would let a clean compile be
scored as a correct UNAFFECTED, manufacturing accuracy out of ignorance. See DECISIONS.md ADR-001.

The pinned `oasdiff` build can emit 514 distinct change ids (`oasdiff checks changelog`; the build
self-reports ``oasdiff version main``, not a tag). This repository does not pretend to have ruled on
514. It rules on the 24 below and abstains on the rest.

**Those 24 are currently the exact id set the corpus emits**: the 18 pairs across Adyen, Twilio and
Xero produce 3,383 breaking changes spanning 24 distinct ids, and every one of them is ruled on
here. Nothing in the present corpus falls through to ``UNCLASSIFIED``. That is a statement about
this corpus on this day, not a claim of completeness against the other 490 ids -- a new vendor or a
wider revision span is expected to surface classes this table has not read, and those abstain.

The remaining shortfall is downstream of this table, not in it, and is recorded rather than papered
over: 8 of the 24 ruled ids have no prose shape in :mod:`~callsite_impact.specdiff.oasdiff`, so
:func:`~callsite_impact.specdiff.oasdiff.parse_property_path` cannot recover a property path for
them and they abstain at match time despite being ruled expressible here.
``response-property-became-nullable`` alone is 2,087 of the 3,383 changes; the eight together are
2,294, about 68% of corpus change volume. Closing that gap means writing anchored patterns for those
shapes and validating them against real prose -- not widening any default.
"""

from __future__ import annotations

from typing import Final

from callsite_impact.domain import Expressibility

__all__ = ["EXPRESSIBILITY_TABLE", "RULED_ON", "expressibility_of"]


EXPRESSIBILITY_TABLE: Final[dict[str, Expressibility]] = {
    # The generated request type loses the member, so an object literal still supplying it is an
    # excess property against a known shape.
    "request-property-removed": Expressibility.TYPE_EXPRESSIBLE,
    # The member disappears from the generated response type, so any read of it is a property
    # access on a type that does not declare it.
    "response-optional-property-removed": Expressibility.TYPE_EXPRESSIBLE,
    # `openapi-typescript` emits enums as string-literal unions, so dropping a member narrows the
    # union and a call site passing the dropped literal no longer assigns.
    "request-property-enum-value-removed": Expressibility.TYPE_EXPRESSIBLE,
    # `T` becomes `T | undefined`; under `strict` that stops assigning to a non-optional target,
    # which is why PropertyAccess records whether the read was optional-chained.
    "response-property-became-optional": Expressibility.TYPE_EXPRESSIBLE,
    # The body argument stops being optional, so a call that omitted it is now missing an argument.
    "request-body-became-required": Expressibility.TYPE_EXPRESSIBLE,
    # The parameter's declared type changes, so an argument of the old type stops assigning.
    "request-parameter-type-changed": Expressibility.TYPE_EXPRESSIBLE,
    # An object literal that does not supply a required member does not satisfy the type.
    "new-required-request-property": Expressibility.TYPE_EXPRESSIBLE,
    # Responses are keyed by status in the generated types, so the removed status is no longer a
    # member and indexing it fails.
    "response-success-status-removed": Expressibility.TYPE_EXPRESSIBLE,
    # The member moves out of the optional set; same mechanism as new-required-request-property.
    "request-property-became-required": Expressibility.TYPE_EXPRESSIBLE,
    # The media type is a key of the generated `content` object, so removing it removes the member
    # a call site reads through.
    "response-media-type-removed": Expressibility.TYPE_EXPRESSIBLE,
    # The declared member type changes, so the value the call site passes stops assigning.
    "request-property-type-changed": Expressibility.TYPE_EXPRESSIBLE,
    # The parameter member is gone from the generated parameters object.
    "request-parameter-removed": Expressibility.TYPE_EXPRESSIBLE,
    # A widening, and expressible only through the binding: an added union member breaks an
    # exhaustive `switch` (the `never` assignment stops typechecking) and breaks a `const`
    # annotated with the old union. It cannot reach an inferred `const`. DECISIONS.md fixes the
    # binding axis before any count exists precisely because this row depends on it.
    "response-property-enum-value-added": Expressibility.TYPE_EXPRESSIBLE,
    # Same widening mechanism one level up: the `oneOf` union gains a member, so a target annotated
    # with the old union no longer accepts the value.
    "response-property-one-of-added": Expressibility.TYPE_EXPRESSIBLE,
    # `maxLength` is a string-length constraint checked at runtime. `openapi-typescript` emits
    # `string` with or without it, so no call site can be made to fail and a clean compile is not
    # evidence of safety. This is the row the three-valued verdict exists for.
    "request-property-max-length-set": Expressibility.NOT_TYPE_EXPRESSIBLE,
    # Identical reasoning: a narrower runtime bound on the same `string`.
    "request-property-max-length-decreased": Expressibility.NOT_TYPE_EXPRESSIBLE,
    # ---- Ruled on after the corpus grew to Twilio ------------------------------------------
    # Twilio's revisions span six years and forced most of these:
    # `response-property-became-nullable` alone accounts for 2,087 of the corpus's 3,383 changes --
    # more than the other twenty-three ids combined -- and does not occur in the Adyen or Xero pairs
    # at all. Three of the eight are not Twilio-only, though: `response-property-max-length-unset`
    # (20), `response-property-min-length-decreased` (16) and `response-required-property-removed`
    # (8) do occur in Adyen/Xero pairs and were simply unruled until this pass. Adding a vendor
    # changed which questions the table has to answer, an argument for a corpus wider than one.
    #
    # `T` -> `T | null` is a union in the emitted types: a pinned annotation contradicts it and an
    # unguarded dereference through it is TS18047.
    "response-property-became-nullable": Expressibility.TYPE_EXPRESSIBLE,
    # The property's declared type is replaced. A read that named the old type contradicts the new.
    "response-property-type-changed": Expressibility.TYPE_EXPRESSIBLE,
    # A required response property disappearing is TS2339 on any read of it -- the same question as
    # `response-optional-property-removed`, one level stronger.
    "response-required-property-removed": Expressibility.TYPE_EXPRESSIBLE,
    # The body type, or the JSON media type that carried it, stops existing. Anything constructing
    # a body types against nothing.
    "request-body-removed": Expressibility.TYPE_EXPRESSIBLE,
    "request-body-media-type-removed": Expressibility.TYPE_EXPRESSIBLE,
    # Length and range keywords are JSON Schema validation, enforced at runtime by the server. They
    # have no representation in a TypeScript type: `string` is `string` whatever its maxLength says,
    # so no call site can be made to fail on one and a clean compile proves nothing about it.
    "response-property-max-length-unset": Expressibility.NOT_TYPE_EXPRESSIBLE,
    "request-parameter-max-decreased": Expressibility.NOT_TYPE_EXPRESSIBLE,
    "response-property-min-length-decreased": Expressibility.NOT_TYPE_EXPRESSIBLE,
}

RULED_ON: Final[frozenset[str]] = frozenset(EXPRESSIBILITY_TABLE)
"""The change ids this repository has an opinion about. Everything else is UNCLASSIFIED."""


def expressibility_of(change_id: str) -> Expressibility:
    """Look up a change class, defaulting to abstention.

    Args:
        change_id: An `oasdiff` change id, e.g. `request-property-removed`.

    Returns:
        The ruling from :data:`EXPRESSIBILITY_TABLE`, or ``UNCLASSIFIED`` for an id this repository
        has not ruled on. The default is deliberate and is the safe direction: it costs recall and
        shows up in the published abstention rate, whereas guessing `TYPE_EXPRESSIBLE` would let a
        clean compile be scored as a correct UNAFFECTED.
    """
    return EXPRESSIBILITY_TABLE.get(change_id, Expressibility.UNCLASSIFIED)
