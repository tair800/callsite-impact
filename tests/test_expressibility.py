"""The expressibility table is a claim about the TypeScript type system, so it gets a test per row.

The point of these tests is not that a dict lookup works. It is that the table's *shape* cannot
drift: that the default stays abstention, that the two `maxLength` rows keep the ruling the whole
three-valued verdict was designed around, and that nobody quietly promotes an unruled id.
"""

from __future__ import annotations

import pytest

from callsite_impact.domain import Expressibility
from callsite_impact.specdiff.expressibility import (
    EXPRESSIBILITY_TABLE,
    RULED_ON,
    expressibility_of,
)

# The ids this repository has ruled on, repeated as a literal so the test fails if the table gains
# or loses a row silently.
#
# The first sixteen were the complete id set of the corpus the table was originally written against.
# The corpus then grew -- more Adyen services, and Twilio as a third vendor alongside Adyen and Xero
# (Stripe was trialled and dropped; see corpus/acquire.py) -- and the last eight were ruled on in
# response. As measured today these 24 are exactly the id set the corpus emits, so nothing in it
# currently abstains as UNCLASSIFIED. That equality is NOT asserted here on purpose: it is a fact
# about this corpus, not an invariant, and a wider corpus is expected to break it in the safe
# direction. The live abstention cost now sits downstream, in oasdiff._SHAPES, which reads prose for
# only 16 of these 24 ids.
TYPE_EXPRESSIBLE_IDS = (
    "new-required-request-property",
    "request-body-became-required",
    "request-parameter-removed",
    "request-parameter-type-changed",
    "request-property-became-required",
    "request-property-enum-value-removed",
    "request-property-removed",
    "request-property-type-changed",
    "response-media-type-removed",
    "response-optional-property-removed",
    "response-property-became-optional",
    "response-property-enum-value-added",
    "response-property-one-of-added",
    "response-success-status-removed",
    # Added when the corpus grew to Twilio; see the table's own comment for each justification.
    "response-property-became-nullable",
    "response-property-type-changed",
    "response-required-property-removed",
    "request-body-removed",
    "request-body-media-type-removed",
)

NOT_TYPE_EXPRESSIBLE_IDS = (
    "request-property-max-length-set",
    "request-property-max-length-decreased",
    # Length and range keywords: JSON Schema validation with no type-level representation.
    "response-property-max-length-unset",
    "request-parameter-max-decreased",
    "response-property-min-length-decreased",
)


def test_ruled_on_is_exactly_the_declared_id_set() -> None:
    expected = frozenset(TYPE_EXPRESSIBLE_IDS) | frozenset(NOT_TYPE_EXPRESSIBLE_IDS)
    assert set(RULED_ON) == expected
    assert len(RULED_ON) == 24


@pytest.mark.parametrize("change_id", sorted(RULED_ON))
def test_every_ruled_on_id_resolves_to_a_real_judgement(change_id: str) -> None:
    assert expressibility_of(change_id) is not Expressibility.UNCLASSIFIED


@pytest.mark.parametrize("change_id", TYPE_EXPRESSIBLE_IDS)
def test_type_expressible_ids(change_id: str) -> None:
    assert expressibility_of(change_id) is Expressibility.TYPE_EXPRESSIBLE


@pytest.mark.parametrize("change_id", NOT_TYPE_EXPRESSIBLE_IDS)
def test_max_length_is_not_type_expressible(change_id: str) -> None:
    """`maxLength` is the change class the UNKNOWN verdict exists for. See DECISIONS.md ADR-001."""
    assert expressibility_of(change_id) is Expressibility.NOT_TYPE_EXPRESSIBLE


@pytest.mark.parametrize(
    "change_id",
    [
        "request-property-pattern-changed",  # real oasdiff id, genuinely not ruled on here
        "api-deprecated-sunset-parse",
        "totally-invented-change-id",
        "",
    ],
)
def test_unruled_ids_fall_through_to_unclassified(change_id: str) -> None:
    """The default has to be abstention: see the UNCLASSIFIED docstring in domain.py."""
    assert expressibility_of(change_id) is Expressibility.UNCLASSIFIED


def test_table_contains_no_unclassified_entries() -> None:
    """UNCLASSIFIED means "absent". Writing it into the table would make the default ambiguous."""
    assert Expressibility.UNCLASSIFIED not in EXPRESSIBILITY_TABLE.values()
