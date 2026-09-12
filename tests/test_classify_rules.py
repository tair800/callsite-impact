"""Every rule, fired and not fired, plus the path matching that decides which of the two happens.

Two cases per rule is the floor, not the target: a rule tested only where it fires is a rule with no
evidence that it ever declines, and declining is most of what this system does. The path-matching
block is separate because that is where false positives come from — a matcher that walked upwards
would report every sibling property of a removed one as impacted, and the precision number would
still look plausible.

Every change here is built with an explicit :class:`~callsite_impact.domain.Expressibility`, so that
nothing in this file depends on the differ lane's table being present or correct. The one test that
does depend on it is skipped when that module is absent and says so.
"""

from __future__ import annotations

from typing import get_args

import pytest

from callsite_impact.classify.engine import classify_pair
from callsite_impact.classify.rules import (
    RULES,
    Reason,
    classify_change,
    matching_accesses,
    normalise_literal,
    parse_enum_removal,
    path_matches,
)
from callsite_impact.domain import (
    Callsite,
    CallsiteFacts,
    Expressibility,
    Finding,
    PropertyAccess,
    SpecChange,
    Verdict,
)

OPERATION = "POST /payments"


def a_change(
    change_id: str,
    *,
    property_path: tuple[str, ...] | None = ("amount",),
    property_path_parsed: bool = True,
    expressibility: Expressibility = Expressibility.TYPE_EXPRESSIBLE,
    text: str = "",
    method: str = "post",
    path: str = "/payments",
) -> SpecChange:
    """A change with everything defaulted except what the test is about."""
    return SpecChange(
        change_id=change_id,
        level=3,
        method=method,
        path=path,
        text=text or f"{change_id} at `{'/'.join(property_path or ())}`",
        property_path=property_path,
        property_path_parsed=property_path_parsed,
        expressibility=expressibility,
    )


def an_access(
    *path: str,
    line: int = 10,
    column: int = 5,
    optional_chained: bool = False,
    literal_value: str | None = None,
    pinned: bool = False,
) -> PropertyAccess:
    """One parsed property access."""
    return PropertyAccess(
        path=path,
        line=line,
        column=column,
        pinned=pinned,
        optional_chained=optional_chained,
        literal_value=literal_value,
    )


def some_facts(
    *,
    request: tuple[PropertyAccess, ...] = (),
    response: tuple[PropertyAccess, ...] = (),
    operation_key: str = OPERATION,
) -> CallsiteFacts:
    """What a parser saw at one call site."""
    return CallsiteFacts(
        operation_key=operation_key,
        request_properties=request,
        response_properties=response,
    )


def a_callsite(
    *,
    facts: CallsiteFacts | None = None,
    callsite_id: str = "cs_000000000001",
    file: str = "src/pay.ts",
    line: int = 3,
    operation_key: str = OPERATION,
) -> Callsite:
    """One admitted call site."""
    return Callsite(
        callsite_id=callsite_id,
        pair_id="acme_v1_v2",
        vendor="acme",
        file=file,
        line=line,
        operation_key=operation_key,
        facts=facts if facts is not None else some_facts(operation_key=operation_key),
        generator_seed=7,
    )


def verdict_of(change: SpecChange, facts: CallsiteFacts) -> tuple[Verdict, str]:
    """The pair a rule is specified in terms of, dropping the anchor the engine uses."""
    _, result = classify_change(change, facts)
    return result.verdict, result.reason


# ------------------------------------------------------------------------------------ path matching


def test_a_change_path_matches_the_same_access_path() -> None:
    assert path_matches(("billingAddress", "city"), ("billingAddress", "city"))


def test_a_change_path_matches_a_deeper_access() -> None:
    """You cannot read ``a.b.c`` once ``a.b`` is gone, so the parent's change reaches the child."""
    assert path_matches(("billingAddress",), ("billingAddress", "city"))
    assert path_matches(("a", "b"), ("a", "b", "c", "d"))


def test_a_change_path_does_not_match_a_shallower_access() -> None:
    """Removing ``a.b.c`` leaves ``a.b`` perfectly readable; matching upwards invents breakages."""
    assert not path_matches(("billingAddress", "city"), ("billingAddress",))


def test_a_change_path_does_not_match_a_sibling() -> None:
    assert not path_matches(("billingAddress", "city"), ("billingAddress", "postalCode"))
    assert not path_matches(("amount",), ("amountDue",))


def test_items_is_skipped_in_the_change_path() -> None:
    """``oasdiff`` says ``lineItems/items/sku``; the source says ``lineItems[0].sku``."""
    assert path_matches(("lineItems", "items", "sku"), ("lineItems", "sku"))
    assert path_matches(("lineItems", "items"), ("lineItems", "sku"))


def test_items_is_not_skipped_in_the_access_path() -> None:
    """A call site may have a property named ``items``, and it is not a traversal marker."""
    assert not path_matches(("basket", "total"), ("basket", "items", "total"))


def test_a_change_path_of_nothing_but_traversal_matches_nothing() -> None:
    """An empty normalised path must not degrade into "matches every access"."""
    assert not path_matches(("items",), ("anything",))
    assert not path_matches((), ("anything",))


def test_matching_accesses_returns_source_order() -> None:
    """The anchor a finding carries must not depend on the order the extractor emitted facts in."""
    late = an_access("a", "b", line=20, column=1)
    early = an_access("a", "b", line=4, column=9)
    assert matching_accesses(("a",), (late, early)) == [early, late]


# ------------------------------------------------------------------------------------------- gates


def test_a_not_type_expressible_change_abstains_before_any_rule() -> None:
    """The gate runs first and nothing bypasses it, including a change class that has a rule."""
    change = a_change(
        "request-property-removed",
        expressibility=Expressibility.NOT_TYPE_EXPRESSIBLE,
    )
    facts = some_facts(request=(an_access("amount"),))
    rule_name, result = classify_change(change, facts)
    assert rule_name == "expressibility_gate"
    assert (result.verdict, result.reason) == (
        Verdict.UNKNOWN,
        "change_not_expressible_in_type_system",
    )


def test_an_unclassified_change_abstains() -> None:
    """UNCLASSIFIED fails towards abstention; treating it as expressible would invent accuracy."""
    change = a_change("request-property-removed", expressibility=Expressibility.UNCLASSIFIED)
    facts = some_facts(request=(an_access("amount"),))
    assert verdict_of(change, facts) == (
        Verdict.UNKNOWN,
        "change_not_expressible_in_type_system",
    )


def test_an_unparsable_property_path_abstains() -> None:
    """A guessed path would send a confident verdict to the wrong call site."""
    change = a_change("request-property-removed", property_path_parsed=False)
    facts = some_facts(request=(an_access("amount"),))
    rule_name, result = classify_change(change, facts)
    assert rule_name == "property_path_gate"
    assert (result.verdict, result.reason) == (Verdict.UNKNOWN, "property_path_unparsable")


def test_an_expressible_change_reaches_its_rule() -> None:
    change = a_change("request-property-removed")
    rule_name, _ = classify_change(change, some_facts(request=(an_access("amount"),)))
    assert rule_name == "removed_request_field"


@pytest.mark.parametrize(
    "change_id",
    [
        "request-property-removed",
        "request-parameter-removed",
        "request-property-became-required",
        "new-required-request-property",
        "response-optional-property-removed",
        "response-property-became-optional",
        "response-property-enum-value-added",
        "request-property-type-changed",
        "request-parameter-type-changed",
        "request-property-enum-value-removed",
    ],
)
def test_a_rule_that_needs_a_path_abstains_when_there_is_none(change_id: str) -> None:
    """``property_path_parsed`` can be True while the differ named no property at all."""
    change = a_change(change_id, property_path=None)
    assert verdict_of(change, some_facts()) == (Verdict.UNKNOWN, "property_path_unparsable")


# ------------------------------------------------ rule: a removed request property or parameter


@pytest.mark.parametrize("change_id", ["request-property-removed", "request-parameter-removed"])
def test_removed_request_field_fires_when_the_callsite_sets_it(change_id: str) -> None:
    change = a_change(change_id, property_path=("billingAddress", "city"))
    facts = some_facts(request=(an_access("billingAddress", "city"),))
    assert verdict_of(change, facts) == (Verdict.IMPACTED, "sets_removed_request_property")


@pytest.mark.parametrize("change_id", ["request-property-removed", "request-parameter-removed"])
def test_removed_request_field_declines_when_the_callsite_does_not(change_id: str) -> None:
    change = a_change(change_id, property_path=("billingAddress", "city"))
    facts = some_facts(request=(an_access("billingAddress", "postalCode"),))
    assert verdict_of(change, facts) == (Verdict.UNAFFECTED, "property_untouched_by_callsite")


def test_removed_request_field_fires_on_a_deeper_write() -> None:
    """Setting ``billingAddress.city.line1`` breaks when ``billingAddress.city`` is removed."""
    change = a_change("request-property-removed", property_path=("billingAddress", "city"))
    facts = some_facts(request=(an_access("billingAddress", "city", "line1"),))
    assert verdict_of(change, facts) == (Verdict.IMPACTED, "sets_removed_request_property")


def test_removed_request_field_ignores_the_response_side() -> None:
    """A request-side removal cannot break a response read, and is not scored as if it could."""
    change = a_change("request-property-removed", property_path=("amount",))
    facts = some_facts(response=(an_access("amount"),))
    assert verdict_of(change, facts) == (Verdict.UNAFFECTED, "property_untouched_by_callsite")


# ----------------------------------------------------- rule: a request property became required


@pytest.mark.parametrize(
    "change_id",
    ["request-property-became-required", "new-required-request-property"],
)
def test_newly_required_request_field_fires_when_the_callsite_omits_it(change_id: str) -> None:
    change = a_change(change_id, property_path=("reference",))
    facts = some_facts(request=(an_access("amount"),))
    assert verdict_of(change, facts) == (
        Verdict.IMPACTED,
        "omits_newly_required_request_property",
    )


@pytest.mark.parametrize(
    "change_id",
    ["request-property-became-required", "new-required-request-property"],
)
def test_newly_required_request_field_declines_when_the_callsite_sets_it(change_id: str) -> None:
    change = a_change(change_id, property_path=("reference",))
    facts = some_facts(request=(an_access("reference"),))
    assert verdict_of(change, facts) == (Verdict.UNAFFECTED, "property_untouched_by_callsite")


def test_newly_required_request_field_carries_no_token_when_it_fires() -> None:
    """The evidence is an absence. There is no source token, so none is invented."""
    change = a_change("request-property-became-required", property_path=("reference",))
    _, result = classify_change(change, some_facts(request=(an_access("amount"),)))
    assert result.access is None


# -------------------------------------------------------- rule: the request body became required


def test_request_body_became_required_fires_when_no_properties_are_supplied() -> None:
    change = a_change("request-body-became-required", property_path=None)
    assert verdict_of(change, some_facts()) == (
        Verdict.IMPACTED,
        "omits_newly_required_request_property",
    )


def test_request_body_became_required_declines_when_any_property_is_supplied() -> None:
    """One optional field is proof a body is being constructed; which field is irrelevant here."""
    change = a_change("request-body-became-required", property_path=None)
    facts = some_facts(request=(an_access("reference"),))
    assert verdict_of(change, facts) == (Verdict.UNAFFECTED, "property_untouched_by_callsite")


# ------------------------------------------------------ rule: a removed optional response property


def test_removed_response_property_fires_when_the_callsite_reads_it() -> None:
    change = a_change("response-optional-property-removed", property_path=("pspReference",))
    facts = some_facts(response=(an_access("pspReference"),))
    assert verdict_of(change, facts) == (Verdict.IMPACTED, "reads_removed_response_property")


def test_removed_response_property_declines_when_the_callsite_does_not_read_it() -> None:
    change = a_change("response-optional-property-removed", property_path=("pspReference",))
    facts = some_facts(response=(an_access("resultCode"),))
    assert verdict_of(change, facts) == (Verdict.UNAFFECTED, "property_untouched_by_callsite")


# ------------------------------------------------------ rule: a response property became optional


def test_became_optional_fires_on_an_unguarded_read() -> None:
    change = a_change("response-property-became-optional", property_path=("resultCode",))
    facts = some_facts(response=(an_access("resultCode", optional_chained=False),))
    assert verdict_of(change, facts) == (
        Verdict.IMPACTED,
        "reads_property_that_became_optional",
    )


def test_became_optional_declines_on_an_optional_chained_read() -> None:
    """``a?.b`` already handles the undefined case, which is the whole point of recording it."""
    change = a_change("response-property-became-optional", property_path=("resultCode",))
    facts = some_facts(response=(an_access("resultCode", optional_chained=True),))
    assert verdict_of(change, facts) == (Verdict.UNAFFECTED, "property_untouched_by_callsite")


def test_became_optional_declines_when_the_property_is_never_read() -> None:
    change = a_change("response-property-became-optional", property_path=("resultCode",))
    facts = some_facts(response=(an_access("pspReference"),))
    assert verdict_of(change, facts) == (Verdict.UNAFFECTED, "property_untouched_by_callsite")


def test_became_optional_anchors_at_the_unguarded_read_when_both_exist() -> None:
    """One unguarded read is enough, and it is the one a reader needs to be shown."""
    change = a_change("response-property-became-optional", property_path=("resultCode",))
    guarded = an_access("resultCode", line=4, optional_chained=True)
    unguarded = an_access("resultCode", line=9, optional_chained=False)
    _, result = classify_change(change, some_facts(response=(guarded, unguarded)))
    assert result.verdict is Verdict.IMPACTED
    assert result.access == unguarded


# --------------------------------------------------------- rule: a removed request enum member


ENUM_REMOVED = "request-property-enum-value-removed"
ENUM_TEXT = "removed the enum value `visa` of the request property `paymentMethod/type`"
"""Verbatim ``oasdiff`` shape. The member comes *first* here, which is why the parse locates it by
elimination against the property path rather than by position."""


def test_removed_enum_member_fires_on_an_equal_literal() -> None:
    change = a_change(ENUM_REMOVED, property_path=("paymentMethod", "type"), text=ENUM_TEXT)
    facts = some_facts(request=(an_access("paymentMethod", "type", literal_value="'visa'"),))
    assert verdict_of(change, facts) == (Verdict.IMPACTED, "passes_removed_enum_member")


def test_removed_enum_member_declines_on_a_different_literal() -> None:
    change = a_change(ENUM_REMOVED, property_path=("paymentMethod", "type"), text=ENUM_TEXT)
    facts = some_facts(request=(an_access("paymentMethod", "type", literal_value="'mc'"),))
    assert verdict_of(change, facts) == (Verdict.UNAFFECTED, "property_untouched_by_callsite")


def test_removed_enum_member_declines_on_a_non_literal() -> None:
    """The parser cannot see what a variable holds, and will not claim what it cannot anchor."""
    change = a_change(ENUM_REMOVED, property_path=("paymentMethod", "type"), text=ENUM_TEXT)
    facts = some_facts(request=(an_access("paymentMethod", "type", literal_value=None),))
    assert verdict_of(change, facts) == (Verdict.UNAFFECTED, "property_untouched_by_callsite")


def test_removed_enum_member_declines_when_the_property_is_never_set() -> None:
    change = a_change(ENUM_REMOVED, property_path=("paymentMethod", "type"), text=ENUM_TEXT)
    facts = some_facts(request=(an_access("amount"),))
    assert verdict_of(change, facts) == (Verdict.UNAFFECTED, "property_untouched_by_callsite")


def test_removed_enum_member_fires_on_the_empty_member() -> None:
    """``oasdiff`` prints the empty enum member as an empty span, and ``''`` is a real literal."""
    text = "removed the enum value `` of the request property `paymentMethod/type`"
    change = a_change(ENUM_REMOVED, property_path=("paymentMethod", "type"), text=text)
    facts = some_facts(request=(an_access("paymentMethod", "type", literal_value="''"),))
    assert verdict_of(change, facts) == (Verdict.IMPACTED, "passes_removed_enum_member")


def test_removed_enum_member_abstains_when_the_member_cannot_be_isolated() -> None:
    """One span, and it is the property path. No member is left to compare a literal against."""
    text = "removed an enum value of the request property `paymentMethod/type`"
    change = a_change(ENUM_REMOVED, property_path=("paymentMethod", "type"), text=text)
    facts = some_facts(request=(an_access("paymentMethod", "type", literal_value="'visa'"),))
    assert verdict_of(change, facts) == (Verdict.UNKNOWN, "property_path_unparsable")


def test_enum_removal_parse_does_not_depend_on_span_order() -> None:
    """The real sentence leads with the member; the parse must not care either way."""
    member_first = a_change(ENUM_REMOVED, property_path=("paymentMethod", "type"), text=ENUM_TEXT)
    path_first = a_change(
        ENUM_REMOVED,
        property_path=("paymentMethod", "type"),
        text="request property `paymentMethod/type` lost enum value `visa`",
    )
    assert parse_enum_removal(member_first) == (("paymentMethod", "type"), "visa")
    assert parse_enum_removal(path_first) == (("paymentMethod", "type"), "visa")


def test_enum_removal_parse_refuses_to_rebuild_a_path_the_differ_lane_could_not() -> None:
    """Re-deriving the path here would be a second heuristic, and a second place to be wrong."""
    assert parse_enum_removal(a_change(ENUM_REMOVED, property_path=None, text=ENUM_TEXT)) is None


def test_enum_removal_parse_tolerates_the_differs_trailing_array_segment() -> None:
    """The differ writes ``subMerchants/items/``; the differ lane stores it without the trailing
    empty segment. The member must still be the only span left after eliminating the path."""
    change = a_change(
        ENUM_REMOVED,
        property_path=("subMerchants", "items"),
        text="removed the enum value `gold` of the request property `subMerchants/items/`",
    )
    assert parse_enum_removal(change) == (("subMerchants", "items"), "gold")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("'visa'", "visa"),
        ('"visa"', "visa"),
        ("`visa`", "visa"),
        ("visa", "visa"),
        (" visa ", "visa"),
    ],
)
def test_literal_normalisation_strips_one_pair_of_quotes(raw: str, expected: str) -> None:
    assert normalise_literal(raw) == expected


# ---------------------------------------------------------- rule: an added response enum member


def test_added_response_enum_member_fires_only_on_a_pinned_read() -> None:
    """Widening breaks the call site that wrote the narrow type down, and only that one."""
    change = a_change("response-property-enum-value-added", property_path=("resultCode",))
    pinned = some_facts(response=(an_access("resultCode", pinned=True),))
    assert verdict_of(change, pinned) == (Verdict.IMPACTED, "pins_widened_response_type")


def test_added_response_enum_member_leaves_an_inferred_read_alone() -> None:
    """`const x = res.resultCode` simply widens with the union. Nothing to report."""
    change = a_change("response-property-enum-value-added", property_path=("resultCode",))
    inferred = some_facts(response=(an_access("resultCode"),))
    assert verdict_of(change, inferred) == (Verdict.UNAFFECTED, "property_untouched_by_callsite")


# ------------------------------------------------- rule: a response property that became nullable


def test_became_nullable_fires_on_a_pinned_read() -> None:
    change = a_change("response-property-became-nullable", property_path=("status",))
    facts = some_facts(response=(an_access("status", pinned=True),))
    assert verdict_of(change, facts) == (Verdict.IMPACTED, "pins_widened_response_type")


def test_became_nullable_fires_on_an_unguarded_read_through_it() -> None:
    """`res.a.b` is TS18047 once `a` can be null -- the dereference is what breaks, not the read."""
    change = a_change("response-property-became-nullable", property_path=("meta",))
    facts = some_facts(response=(an_access("meta"), an_access("meta", "page")))
    assert verdict_of(change, facts) == (
        Verdict.IMPACTED,
        "reads_through_now_nullable_property",
    )


def test_became_nullable_leaves_a_guarded_read_through_it_alone() -> None:
    change = a_change("response-property-became-nullable", property_path=("meta",))
    facts = some_facts(
        response=(an_access("meta"), an_access("meta", "page", optional_chained=True))
    )
    assert verdict_of(change, facts) == (Verdict.UNAFFECTED, "property_untouched_by_callsite")


def test_became_nullable_leaves_a_shallow_inferred_read_alone() -> None:
    """`const x = res.a` absorbs `| null`. Reporting it would be a false positive."""
    change = a_change("response-property-became-nullable", property_path=("status",))
    facts = some_facts(response=(an_access("status"),))
    assert verdict_of(change, facts) == (Verdict.UNAFFECTED, "property_untouched_by_callsite")


# --------------------------------------------- rule: a changed response property type, and bodies


def test_changed_response_property_type_fires_only_when_pinned() -> None:
    change = a_change("response-property-type-changed", property_path=("amount",))
    assert verdict_of(change, some_facts(response=(an_access("amount", pinned=True),))) == (
        Verdict.IMPACTED,
        "touches_changed_property_type",
    )
    assert verdict_of(change, some_facts(response=(an_access("amount"),))) == (
        Verdict.UNAFFECTED,
        "property_untouched_by_callsite",
    )


def test_removed_request_body_fires_when_the_callsite_supplies_one() -> None:
    change = a_change("request-body-removed", property_path=None)
    assert verdict_of(change, some_facts(request=(an_access("reference"),))) == (
        Verdict.IMPACTED,
        "supplies_a_request_body_that_was_removed",
    )
    assert verdict_of(change, some_facts()) == (
        Verdict.UNAFFECTED,
        "property_untouched_by_callsite",
    )


def test_added_response_enum_member_declines_when_the_property_is_not_read() -> None:
    """A widened union nobody reads is decidable, and abstaining there would overstate the gap."""
    change = a_change("response-property-enum-value-added", property_path=("resultCode",))
    facts = some_facts(response=(an_access("pspReference"),))
    assert verdict_of(change, facts) == (Verdict.UNAFFECTED, "property_untouched_by_callsite")


# ------------------------------------------------------ rule: a changed request property type


@pytest.mark.parametrize(
    "change_id",
    ["request-property-type-changed", "request-parameter-type-changed"],
)
def test_changed_request_field_type_fires_when_the_callsite_touches_it(change_id: str) -> None:
    change = a_change(change_id, property_path=("amount", "value"))
    facts = some_facts(request=(an_access("amount", "value"),))
    assert verdict_of(change, facts) == (Verdict.IMPACTED, "touches_changed_property_type")


@pytest.mark.parametrize(
    "change_id",
    ["request-property-type-changed", "request-parameter-type-changed"],
)
def test_changed_request_field_type_declines_when_it_does_not(change_id: str) -> None:
    change = a_change(change_id, property_path=("amount", "value"))
    facts = some_facts(request=(an_access("amount", "currency"),))
    assert verdict_of(change, facts) == (Verdict.UNAFFECTED, "property_untouched_by_callsite")


# ------------------------------------------------- rule: a removed success status or media type


@pytest.mark.parametrize(
    "change_id",
    ["response-success-status-removed", "response-media-type-removed"],
)
def test_removed_response_shape_fires_on_any_response_read(change_id: str) -> None:
    change = a_change(change_id, property_path=None)
    facts = some_facts(response=(an_access("anything", "at", "all"),))
    assert verdict_of(change, facts) == (Verdict.IMPACTED, "operation_removed")


@pytest.mark.parametrize(
    "change_id",
    ["response-success-status-removed", "response-media-type-removed"],
)
def test_removed_response_shape_declines_when_nothing_is_read(change_id: str) -> None:
    """Calling an operation and ignoring its body still compiles; the baseline says otherwise."""
    change = a_change(change_id, property_path=None)
    facts = some_facts(request=(an_access("amount"),))
    assert verdict_of(change, facts) == (Verdict.UNAFFECTED, "property_untouched_by_callsite")


# ------------------------------------------------------------ rule: a new oneOf branch, unruled


def test_added_response_one_of_abstains_when_the_property_is_read() -> None:
    change = a_change("response-property-one-of-added", property_path=("action",))
    facts = some_facts(response=(an_access("action", "type"),))
    assert verdict_of(change, facts) == (Verdict.UNKNOWN, "property_path_shape_unsupported")


def test_added_response_one_of_abstains_even_when_nothing_is_read() -> None:
    """The branches live in the spec, not in the source, so no call-site fact can settle it."""
    change = a_change("response-property-one-of-added", property_path=("action",))
    assert verdict_of(change, some_facts()) == (
        Verdict.UNKNOWN,
        "property_path_shape_unsupported",
    )


# ------------------------------------------------------------------- fallback: an unruled change id


def test_an_unruled_change_id_abstains() -> None:
    """514 ids exist and this repository has ruled on a handful. The rest are not guessed at."""
    change = a_change("request-property-max-length-decreased", property_path=("reference",))
    rule_name, result = classify_change(change, some_facts())
    assert rule_name == "no_rule_for_change_id"
    assert (result.verdict, result.reason) == (
        Verdict.UNKNOWN,
        "change_not_expressible_in_type_system",
    )


def test_an_unruled_change_id_abstains_even_with_matching_accesses() -> None:
    """Having a matching access is not evidence when the change class was never ruled on."""
    change = a_change("request-property-max-length-decreased", property_path=("reference",))
    facts = some_facts(request=(an_access("reference", literal_value="'x'"),))
    assert verdict_of(change, facts) == (
        Verdict.UNKNOWN,
        "change_not_expressible_in_type_system",
    )


# ------------------------------------------------------------------------------ type consistency


def test_the_reason_alias_matches_the_findings_closed_vocabulary() -> None:
    """``rules.Reason`` duplicates ``Finding.reason`` because domain.py is another lane's file.

    The duplication is only safe while it is exact, so it is checked rather than trusted.
    """
    assert set(get_args(Reason)) == set(get_args(Finding.model_fields["reason"].annotation))


def test_every_ruled_change_id_is_type_expressible_in_the_authority_table() -> None:
    """A rule on a class the differ lane calls inexpressible is dead code the gate swallows.

    This is the integration seam between the two lanes and the failure is silent: the rule would
    never run, every one of its changes would come back UNKNOWN, and the abstention rate would climb
    for a reason nobody could see in either file alone.
    """
    module = pytest.importorskip(
        "callsite_impact.specdiff.expressibility",
        reason="the differ lane has not landed expressibility_of yet",
    )
    expressibility_of = module.expressibility_of
    disagreements = [
        change_id
        for change_id in sorted(RULES)
        if expressibility_of(change_id) is not Expressibility.TYPE_EXPRESSIBLE
    ]
    assert not disagreements, (
        "classify/rules.py rules on change ids the authority table calls inexpressible, so the "
        "expressibility gate silently swallows them: " + ", ".join(disagreements)
    )


# --------------------------------------------------------------------------------------- engine


def test_a_change_on_an_untouched_operation_produces_no_finding() -> None:
    """Not a candidate pair, so not in the denominator every published rate divides by."""
    change = a_change("request-property-removed", path="/refunds")
    callsite = a_callsite(facts=some_facts(request=(an_access("amount"),)))
    assert classify_pair([change], [callsite]) == []


def test_one_finding_per_candidate_pair() -> None:
    change = a_change("request-property-removed", property_path=("amount",))
    sets_it = some_facts(request=(an_access("amount"),))
    one = a_callsite(callsite_id="cs_1", file="a.ts", facts=sets_it)
    two = a_callsite(callsite_id="cs_2", file="b.ts", facts=some_facts(request=(an_access("x"),)))
    findings = classify_pair([change], [one, two])
    assert [(f.callsite_id, f.verdict) for f in findings] == [
        ("cs_1", Verdict.IMPACTED),
        ("cs_2", Verdict.UNAFFECTED),
    ]


def test_a_finding_is_anchored_at_the_property_access_when_there_is_one() -> None:
    change = a_change("request-property-removed", property_path=("billingAddress", "city"))
    access = an_access("billingAddress", "city", line=42, column=17)
    callsite = a_callsite(line=3, facts=some_facts(request=(access,)))
    finding = classify_pair([change], [callsite])[0]
    assert (finding.callsite_line, finding.callsite_column) == (42, 17)
    assert finding.callsite_token == "billingAddress.city"
    assert finding.anchored


def test_a_finding_falls_back_to_the_callsite_position_when_there_is_no_token() -> None:
    """An omitted property has no source token; the call site is the most specific honest anchor."""
    change = a_change("request-property-became-required", property_path=("reference",))
    callsite = a_callsite(line=3, facts=some_facts(request=(an_access("amount"),)))
    finding = classify_pair([change], [callsite])[0]
    assert finding.verdict is Verdict.IMPACTED
    anchors = (finding.callsite_line, finding.callsite_column, finding.callsite_token)
    assert anchors == (3, None, None)
    assert finding.anchored


def test_findings_carry_the_rule_that_decided_and_the_change_that_caused_it() -> None:
    change = a_change("request-property-removed", property_path=("amount",))
    callsite = a_callsite(facts=some_facts(request=(an_access("amount"),)))
    finding = classify_pair([change], [callsite])[0]
    assert finding.rule == "removed_request_field"
    assert finding.change == change
    assert finding.pair_id == "acme_v1_v2"


def test_ordering_does_not_depend_on_the_order_callsites_arrive_in() -> None:
    """A committed artifact must diff across runs, so the order is derived, not inherited."""
    change = a_change("request-property-removed", property_path=("amount",))
    sites = [
        a_callsite(callsite_id="cs_c", file="c.ts", line=1),
        a_callsite(callsite_id="cs_a", file="a.ts", line=9),
        a_callsite(callsite_id="cs_b", file="a.ts", line=2),
    ]
    forwards = [f.callsite_id for f in classify_pair([change], sites)]
    backwards = [f.callsite_id for f in classify_pair([change], list(reversed(sites)))]
    assert forwards == ["cs_b", "cs_a", "cs_c"]
    assert forwards == backwards


def test_every_finding_the_engine_returns_is_anchored() -> None:
    """An unanchorable verdict is suppressed and counted, never published unanchored."""
    changes = [
        a_change(change_id, property_path=("amount",), text=ENUM_TEXT)
        for change_id in sorted(RULES)
    ]
    callsite = a_callsite(
        facts=some_facts(
            request=(an_access("amount", literal_value="'visa'"),),
            response=(an_access("amount"),),
        )
    )
    findings = classify_pair(changes, [callsite])
    assert len(findings) == len(changes)
    assert all(finding.anchored for finding in findings)
    assert all(isinstance(finding, Finding) for finding in findings)


@pytest.mark.parametrize(("file", "line"), [("", 3), ("src/pay.ts", 0)])
def test_an_unanchorable_verdict_is_suppressed_rather_than_published(file: str, line: int) -> None:
    """A call site with no position cannot be checked by a reader, so its verdict is not published.

    It is dropped and counted rather than emitted with a missing anchor, which is the project rule
    for every verdict. A degenerate call site like this means the extractor produced something
    wrong; the right response is to lose the finding, not to publish one nobody can look up.
    """
    change = a_change("request-property-became-required", property_path=("reference",))
    callsite = a_callsite(file=file, line=line, facts=some_facts(request=(an_access("amount"),)))
    assert classify_pair([change], [callsite]) == []


def test_the_engine_never_widens_the_reason_vocabulary() -> None:
    """Every reason the rules can emit is one the closed type on ``Finding`` already admits."""
    allowed = set(get_args(Finding.model_fields["reason"].annotation))
    changes = [
        a_change(change_id, property_path=("amount",), text=ENUM_TEXT) for change_id in RULES
    ]
    callsite = a_callsite(facts=some_facts(request=(an_access("amount"),)))
    assert {finding.reason for finding in classify_pair(changes, [callsite])} <= allowed
