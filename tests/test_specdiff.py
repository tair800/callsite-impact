"""Parser tests over strings `oasdiff` actually emitted, copied out of real runs.

Nothing here is a made-up sentence. Every string below was produced by running the pinned differ
over a pinned pair in `corpus/manifest.json` and copying the `text` field verbatim, because a parser
tested against prose its author invented is a parser tested against its own assumptions.

The case these tests exist for is the one in the middle: `oasdiff` puts the property path in the
first backticked span in most sentences and *not* in five of the sixteen shapes this corpus
produces. A parser that took the first span would file an enum member as a property name and send a
verdict to the wrong call site. `test_property_path_is_not_always_the_first_span` pins that down.
"""

from __future__ import annotations

import pytest

from callsite_impact.specdiff.oasdiff import (
    OasdiffNotFoundError,
    find_oasdiff,
    oasdiff_version,
    parse_property_path,
)

# A real Stripe sentence. Seven `anyOf` selectors deep; it does not describe a path through one
# object, it describes a path that depends on which branch each value took.
ANYOF_REMOVAL = (
    "removed the optional property `data/items/usage_threshold/anyOf[subschema #1: "
    "ThresholdsResourceUsageThresholdConfig -> subschema #1: Usage threshold alert "
    "configuration]/filters/items/customer/anyOf[subschema #2: Customer]/subscriptions/data/"
    "items/latest_invoice/anyOf[subschema #2: Invoice]/payments/data/items/payment/"
    "payment_record/anyOf[subschema #2: PaymentRecord -> subschema #2: Payment Record]/"
    "payment_method_details/anyOf[subschema #1: PaymentsPrimitivesPaymentRecordsResource"
    "PaymentMethodDetails]/card/three_d_secure/anyOf[subschema #1: PaymentsPrimitives"
    "PaymentRecordsResourcePaymentMethodCardDetailsResourceThreeDSecure]/cryptogram` "
    "from the response with the `200` status"
)

ONEOF_BECAME_REQUIRED = (
    "the request property `paymentMethod/oneOf[subschema #17: DirectDebitAu]/holderName` "
    "became required"
)


# ------------------------------------------------------------- one real sentence per change class

PARSED: list[tuple[str, tuple[str, ...]]] = [
    (
        "added the new required request property `recurringProcessingModel`",
        ("recurringProcessingModel",),
    ),
    (
        "added the new required request property `EarningsRates/items/IsQualifyingEarnings`",
        ("EarningsRates", "items", "IsQualifyingEarnings"),
    ),
    ("deleted the `query` request parameter `folderId`", ("folderId",)),
    (
        "for the `header` request parameter `if-modified-since`, the `format` was changed "
        "from `none` to `date-time`",
        ("if-modified-since",),
    ),
    ("the request property `body` became required", ("body",)),
    (
        "removed the enum value `JOBKEEPER` of the request property "
        "`EarningsRates/items/AllowanceType`",
        ("EarningsRates", "items", "AllowanceType"),
    ),
    (
        "the `billingAddress/stateOrProvince` request property's maxLength was decreased to `3`",
        ("billingAddress", "stateOrProvince"),
    ),
    (
        "the `billingAddress/postalCode` request property's maxLength was set to `10`",
        ("billingAddress", "postalCode"),
    ),
    ("removed the request property `storePaymentMethod`", ("storePaymentMethod",)),
    (
        "removed the request property `subMerchants/items/SubMerchant`",
        ("subMerchants", "items", "SubMerchant"),
    ),
    (
        "the `expiresAt` request property `format` changed from `none` to `date-time`",
        ("expiresAt",),
    ),
    (
        "removed the optional property `paymentMethods/items/details` from the response "
        "with the `200` status",
        ("paymentMethods", "items", "details"),
    ),
    (
        "the response property `donationCampaigns/items/donation/donationType` became optional "
        "for the status `200`",
        ("donationCampaigns", "items", "donation", "donationType"),
    ),
    (
        "added the new `authorised` enum value to the `status` response property "
        "for the response status `201`",
        ("status",),
    ),
    (
        "added `#/components/schemas/CheckoutDelegatedAuthenticationAction` to the "
        "`payment/action` response property `oneOf` list for the response status `200`",
        ("payment", "action"),
    ),
]


@pytest.mark.parametrize(("text", "expected"), PARSED, ids=[t[:44] for t, _ in PARSED])
def test_parses_real_sentences(text: str, expected: tuple[str, ...]) -> None:
    assert parse_property_path(text) == (expected, True)


# --------------------------------------------------------------------- the five brief cases, real

BRIEF_EXAMPLES: list[tuple[str, tuple[str, ...] | None, bool]] = [
    ("removed the request property `storePaymentMethod`", ("storePaymentMethod",), True),
    (ONEOF_BECAME_REQUIRED, None, False),
    (
        "the `billingAddress/stateOrProvince` request property's maxLength was decreased to `3`",
        ("billingAddress", "stateOrProvince"),
        True,
    ),
    (
        "the response property `donationCampaigns/items/donation/donationType` became optional "
        "for the status `200`",
        ("donationCampaigns", "items", "donation", "donationType"),
        True,
    ),
    (ANYOF_REMOVAL, None, False),
]


@pytest.mark.parametrize(("text", "path", "parsed"), BRIEF_EXAMPLES)
def test_brief_examples(text: str, path: tuple[str, ...] | None, parsed: bool) -> None:
    assert parse_property_path(text) == (path, parsed)


# ------------------------------------------------------------------------------- abstention cases


@pytest.mark.parametrize("text", [ANYOF_REMOVAL, ONEOF_BECAME_REQUIRED])
def test_subschema_selectors_abstain_rather_than_guess(text: str) -> None:
    """A composition selector cannot be reduced to one concrete chain, so the parse refuses.

    Returning a chain with the selector stripped out would produce a confident, wrong property path.
    On this corpus that would be roughly two thirds of all changes misfiled.
    """
    path, parsed = parse_property_path(text)
    assert path is None
    assert parsed is False


@pytest.mark.parametrize(
    "text",
    [
        "request body became required",
        "removed the success response with the status `201`",
        "removed the media type `application/json` for the response with the status `204`",
    ],
)
def test_change_classes_with_no_property_are_not_parse_failures(text: str) -> None:
    """These are about an operation, not a field. Nothing was there to parse, so nothing failed."""
    assert parse_property_path(text) == (None, True)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "some change oasdiff has not been taught to this parser",
        "removed the request property `storePaymentMethod` from somewhere else",
        "removed the request property",
    ],
)
def test_unrecognised_prose_abstains(text: str) -> None:
    """No first-span fallback. An unread shape is refused, not guessed at."""
    assert parse_property_path(text) == (None, False)


# -------------------------------------------------------------------------------- the sharp edges


@pytest.mark.parametrize(
    ("text", "naive_first_span", "expected"),
    [
        (
            "added the new `authorised` enum value to the `status` response property "
            "for the response status `201`",
            "authorised",
            ("status",),
        ),
        (
            "added `#/components/schemas/CheckoutDelegatedAuthenticationAction` to the "
            "`payment/action` response property `oneOf` list for the response status `200`",
            "#/components/schemas/CheckoutDelegatedAuthenticationAction",
            ("payment", "action"),
        ),
        ("deleted the `query` request parameter `folderId`", "query", ("folderId",)),
        (
            "removed the enum value `JOBKEEPER` of the request property `ObjectType`",
            "JOBKEEPER",
            ("ObjectType",),
        ),
        (
            "for the `header` request parameter `if-modified-since`, the `format` was changed "
            "from `none` to `date-time`",
            "header",
            ("if-modified-since",),
        ),
    ],
)
def test_property_path_is_not_always_the_first_span(
    text: str, naive_first_span: str, expected: tuple[str, ...]
) -> None:
    """Guard against anyone reintroducing the "first backticked span" heuristic.

    In each of these the differ leads with the enum member, the schema ref or the parameter
    location. The naive reading is not merely imprecise, it names a different thing entirely.
    """
    path, parsed = parse_property_path(text)
    assert parsed is True
    assert path == expected
    assert path != (naive_first_span,)


def test_empty_enum_member_does_not_break_the_parse() -> None:
    """`oasdiff` renders the empty-string enum member as an empty span, so the value may be ``."""
    text = "removed the enum value `` of the request property `items/items/currency`"
    assert parse_property_path(text) == (("items", "items", "currency"), True)


def test_trailing_empty_segment_names_the_array_element() -> None:
    """`subMerchants/items/` is how the differ renders the element type itself."""
    text = "the `subMerchants/items/` request property `type` changed from `any` to `object`"
    assert parse_property_path(text) == (("subMerchants", "items"), True)


def test_interior_empty_segment_abstains() -> None:
    """A hole in the middle of a chain has no honest reading, unlike a trailing one."""
    text = "removed the request property `billingAddress//city`"
    assert parse_property_path(text) == (None, False)


# ------------------------------------------------------------------------- needs the real binary


@pytest.mark.corpus
def test_binary_is_installed_and_reports_a_version() -> None:
    """Provenance depends on this string, so check the call works rather than assuming it."""
    try:
        binary = find_oasdiff()
    except OasdiffNotFoundError as exc:  # pragma: no cover - only on a machine without the differ
        pytest.skip(str(exc))
    assert binary.is_file()
    assert oasdiff_version().startswith("oasdiff")
