"""The AI boundary, enforced by the shape of the verdict type rather than by a rule in a document.

ADR-001 permits a model to explain a verdict the compiler reached, to rank verified findings,
and to draft migration guidance. It forbids a model producing a verdict. The difference between
those two is one field.

A policy sentence — "the model must not decide" — is not enforcement. It survives exactly until
someone adds ``confidence: float`` for a ranking feature, or ``explanation: str`` to carry a
nicer sentence to the UI, and at that point a model's output sits inside the evidence record.
Nothing goes red. The number in the README does not move, and no longer measures what it says.

So the enforcement is the type. :class:`~callsite_impact.domain.Finding` has nowhere for a model's
judgement: ``verdict`` is a closed enum, ``reason`` is a closed ``Literal``, and every string field
on it is an anchor whose value comes from the corpus or from the name of a Python function. A closed
type is enforcement because widening it is an edit to a file, and this test is what makes that edit
fail the build.

**What this test does not cover.** It walks ``Finding`` itself for open string fields, and recurses
only for numeric-score and judgement-shaped names. The nested
:class:`~callsite_impact.domain.SpecChange` carries ``text``, the differ's own sentence, kept
so a reader can check the property-path parse against it — an open string by necessity, written by
``oasdiff`` and never by a model. Its producer is the differ lane and its boundary is that lane's to
state.
"""

from __future__ import annotations

import types
import typing
from typing import Any, Literal, get_args, get_origin

import pytest
from pydantic import BaseModel

from callsite_impact.domain import Expressibility, Finding, SpecChange, Verdict

ANCHOR_STRING_FIELDS = frozenset(
    {
        "callsite_id",
        "pair_id",
        "callsite_file",
        "callsite_token",
        "rule",
    }
)
"""The only open strings ``Finding`` is allowed, each with a reason it cannot carry a judgement.

``callsite_id`` and ``pair_id`` are derived identifiers: ``domain.callsite_id`` hashes business
identity and nothing else. ``callsite_file`` and ``callsite_token`` are corpus positions, both
checkable by opening the file. ``rule`` names a branch in ``classify/rules.py`` and the engine fills
it from ``function.__name__``, so its value set is the dispatch table — free text in type, a closed
set in fact. Adding a sixth name to this list is the edit a reviewer should refuse.
"""

JUDGEMENT_WORDS = frozenset(
    {
        "score",
        "scores",
        "scoring",
        "confidence",
        "probability",
        "certainty",
        "likelihood",
        "weight",
        "rating",
        "rank",
        "ranking",
        "priority",
        "estimate",
        "guess",
        "opinion",
        "judgement",
        "judgment",
        "assessment",
        "explanation",
        "rationale",
        "justification",
        "narrative",
        "commentary",
        "summary",
        "analysis",
        "note",
        "notes",
        "comment",
        "comments",
        "llm",
        "model",
        "prompt",
        "completion",
        "generated",
    }
)
"""Name parts that give the game away. Matched per underscore-separated word, so ``rule`` is safe
and ``rule_confidence`` is not."""


def _flatten(annotation: Any) -> list[Any]:
    """Expand a union into its members; leave everything else alone.

    Both union spellings can appear — ``str | None`` produces ``types.UnionType`` and
    ``typing.Optional`` produces ``typing.Union`` — and a guard that understood only one of them
    would wave through ``Optional[float]``.
    """
    origin = get_origin(annotation)
    if origin is types.UnionType or origin is typing.Union:
        return list(get_args(annotation))
    return [annotation]


def _is_literal(annotation: Any) -> bool:
    """True for ``Literal[...]``, the closed-string shape this repository requires for reasons."""
    return get_origin(annotation) is Literal


def _nested_models(model: type[BaseModel]) -> list[type[BaseModel]]:
    """Pydantic models reachable one level down from ``model``'s own fields."""
    found: list[type[BaseModel]] = []
    for info in model.model_fields.values():
        for member in _flatten(info.annotation):
            if isinstance(member, type) and issubclass(member, BaseModel):
                found.append(member)
    return found


def _finding_and_everything_under_it() -> list[type[BaseModel]]:
    """``Finding`` plus the models it nests, the surface the numeric checks below walk."""
    models: list[type[BaseModel]] = [Finding]
    models.extend(_nested_models(Finding))
    return models


def _judgement_words_in(field_name: str) -> set[str]:
    """The judgement words a field name contains, split on underscores."""
    return {word for word in field_name.split("_") if word in JUDGEMENT_WORDS}


def _a_change() -> SpecChange:
    """A minimal well-formed change, so the runtime checks below are about ``Finding`` alone."""
    return SpecChange(
        change_id="request-property-removed",
        level=3,
        method="post",
        path="/payments",
        text="removed the request property `amount`",
        property_path=("amount",),
        expressibility=Expressibility.TYPE_EXPRESSIBLE,
    )


# ------------------------------------------------------------------------------------- the guards


def test_finding_has_no_open_string_field_outside_the_anchors() -> None:
    """A free-text string on the evidence record is a place a model can write a verdict."""
    offenders: list[str] = []
    for name, info in Finding.model_fields.items():
        if name in ANCHOR_STRING_FIELDS:
            continue
        members = _flatten(info.annotation)
        has_open_string = any(member is str for member in members)
        has_closed_set = any(_is_literal(member) for member in members)
        if has_open_string and not has_closed_set:
            offenders.append(name)
    assert not offenders, (
        "Finding grew an open string field: "
        + ", ".join(offenders)
        + ". If it is an anchor, add it to ANCHOR_STRING_FIELDS with the reason it cannot carry a "
        "judgement. If it is prose, it does not belong on the evidence record."
    )


def test_finding_has_no_float_field_anywhere_it_reaches() -> None:
    """A float on a verdict is a confidence whatever it is named. Confidence is a model's job."""
    offenders: list[str] = []
    for model in _finding_and_everything_under_it():
        for name, info in model.model_fields.items():
            if any(member is float for member in _flatten(info.annotation)):
                offenders.append(f"{model.__name__}.{name}")
    assert not offenders, "float fields reachable from Finding: " + ", ".join(offenders)


def test_no_field_name_reachable_from_finding_suggests_a_judgement() -> None:
    """Catches the field that is honestly typed and dishonestly named: ``reason_score: int``."""
    offenders: list[str] = []
    for model in _finding_and_everything_under_it():
        for name in model.model_fields:
            hits = _judgement_words_in(name)
            if hits:
                offenders.append(f"{model.__name__}.{name} ({', '.join(sorted(hits))})")
    assert not offenders, "judgement-shaped field names reachable from Finding: " + ", ".join(
        offenders
    )


def test_reason_is_a_closed_literal_and_not_an_open_string() -> None:
    """The reason vocabulary is the field most likely to be widened, so it is checked by name."""
    annotation = Finding.model_fields["reason"].annotation
    assert _is_literal(annotation), (
        "Finding.reason must stay a Literal. An open str there is free text on the evidence "
        "record, which is exactly what the AI boundary forbids."
    )
    members = get_args(annotation)
    assert members, "Finding.reason is a Literal with no members"
    assert all(isinstance(member, str) for member in members)


def test_verdict_is_a_closed_enum() -> None:
    """Three values, one of which is an abstention. A fourth cannot be introduced at runtime."""
    assert Finding.model_fields["verdict"].annotation is Verdict
    assert {member.value for member in Verdict} == {"impacted", "unaffected", "unknown"}


def _finding_fields(**overrides: Any) -> dict[str, Any]:
    """A valid ``Finding`` payload, overridable with the field a test is trying to smuggle in.

    Built as a dict rather than as keyword arguments so that the static checker does not reject the
    invalid payloads before the runtime does. Both halves of the boundary matter: the type refuses
    it at review time, ``extra="forbid"`` refuses it at construction time, and these two tests are
    about the second half.
    """
    payload: dict[str, Any] = {
        "callsite_id": "cs_000000000000",
        "pair_id": "pair",
        "verdict": Verdict.IMPACTED,
        "rule": "removed_request_field",
        "reason": "sets_removed_request_property",
        "change": _a_change(),
        "callsite_file": "a.ts",
        "callsite_line": 1,
    }
    payload.update(overrides)
    return payload


def test_finding_rejects_an_invented_reason() -> None:
    """A closed type is only enforcement if the runtime honours it, so the runtime is checked."""
    with pytest.raises(ValueError, match="reason"):
        Finding(**_finding_fields(reason="the model thinks this one is risky"))


def test_finding_rejects_an_extra_field() -> None:
    """``extra="forbid"`` is the other half: a field cannot be smuggled in at construction time."""
    with pytest.raises(ValueError, match="confidence"):
        Finding(**_finding_fields(confidence=0.91))


def test_the_valid_payload_these_tests_negate_is_actually_valid() -> None:
    """Otherwise the two tests above could pass for the wrong reason and nobody would notice."""
    assert Finding(**_finding_fields()).anchored
