"""The two baselines ADR-001 predeclared, implemented so they cannot be made to lose.

A baseline invented after the results are in is decoration. Both of these were named in ADR-001
before any code existed, and both are what a team can actually do today with a spec differ and
``grep``: join the differ's changed operations against the call sites and call every hit a breakage.

Neither baseline reads the call-site source. That is the whole point of the comparison -- the system
under test parses the call site and can tell "this operation changed" from "this call site touches
the thing that changed", and the number that says whether that distinction is worth anything is the
precision gap between these functions and the system, scored by the same scorer on the same corpus.

Neither baseline ever returns UNKNOWN. A spec differ has no notion of a change class the type system
cannot express, so its abstention rate is zero by construction and its `maxLength` findings are
false positives. That is not a handicap imposed here; it is the behaviour being measured.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Final

from callsite_impact.domain import Callsite, Finding, SpecChange, Verdict

__all__ = [
    "BASELINE_IMPACTED_REASON",
    "candidate_pairs",
    "naive_err_level_only",
    "naive_touches_changed_operation",
]

BASELINE_IMPACTED_REASON: Final = "touches_changed_property_type"
"""The closest honest member of :class:`~callsite_impact.domain.Finding`'s reason vocabulary.

That vocabulary was written for the system's rules, and the baseline makes a claim none of its
members expresses: *the operation changed, therefore assume this call site breaks*. Every other
candidate is a worse fit -- ``operation_removed`` asserts a removal that usually did not happen, and
the ``*_untouched_by_callsite`` members assert the opposite verdict.
``touches_changed_property_type`` is the one member that asserts contact with a change
without asserting a specific structural edit.

It still overstates: the baseline does not know that a property type changed, and does not know
whether the call site touches the property at all. The overstatement is recorded here rather than
repaired by widening the Literal in ``domain.py``, because that vocabulary belongs to the system and
a baseline does not get to extend the system's language to describe itself. Nothing is lost by the
mismatch -- the scorer reads ``verdict``, never ``reason``.
"""

_ERR_LEVEL: Final = 3
"""oasdiff severity for a breaking change. ADR-001's second baseline is this filter alone."""


def candidate_pairs(
    changes: Sequence[SpecChange], callsites: Sequence[Callsite]
) -> list[tuple[Callsite, SpecChange]]:
    """Every (call site, change) pair on a shared operation -- the join the system also starts from.

    Both baselines and the system must consider the same pairs, or precision and recall are computed
    on different denominators and the comparison the README leads with is meaningless. Exposed as a
    function rather than inlined twice so that the two baselines provably enumerate one join.
    """
    by_operation: defaultdict[str, list[SpecChange]] = defaultdict(list)
    for change in changes:
        by_operation[change.operation_key].append(change)
    return [
        (callsite, change)
        for callsite in callsites
        for change in by_operation.get(callsite.operation_key, ())
    ]


def _finding(callsite: Callsite, change: SpecChange, rule: str) -> Finding:
    """An anchored IMPACTED finding for one pair.

    The call-site anchor is the call site's own file and line, which is all a differ-plus-grep
    workflow can point at. ``callsite_column`` and ``callsite_token`` stay ``None`` because the
    baseline has not read the source and has no token to name -- filling them in with the operation
    name would dress a whole-operation guess up as a token-level finding.
    """
    return Finding(
        callsite_id=callsite.callsite_id,
        pair_id=callsite.pair_id,
        verdict=Verdict.IMPACTED,
        rule=rule,
        reason=BASELINE_IMPACTED_REASON,
        change=change,
        callsite_file=callsite.file,
        callsite_line=callsite.line,
    )


def naive_touches_changed_operation(
    changes: Sequence[SpecChange], callsites: Sequence[Callsite]
) -> list[Finding]:
    """ADR-001's first baseline: every call site on a changed operation is IMPACTED.

    This is the spec-differ-and-grep workflow, written out. It should score near-perfect recall -- a
    breakage has to be on a changed operation to exist -- and poor precision, because most call
    sites on a changed operation never touch the part that changed. Whether that is what actually
    happens is what the run reports.

    The ``rule`` value is namespaced ``baseline.`` and deliberately does not name a branch in
    ``classify/rules.py``, so that a baseline finding can never be mistaken for a system finding in
    a committed artifact.
    """
    return [
        _finding(callsite, change, "baseline.touches_changed_operation")
        for callsite, change in candidate_pairs(changes, callsites)
    ]


def naive_err_level_only(
    changes: Sequence[SpecChange], callsites: Sequence[Callsite]
) -> list[Finding]:
    """ADR-001's second baseline: the same move, with the differ's own ERR filter on.

    It walks the identical join as :func:`naive_touches_changed_operation` and emits IMPACTED only
    where ``oasdiff`` graded the change level 3. On a sub-ERR pair it emits **nothing** rather than
    an explicit UNAFFECTED, because the reason vocabulary has no honest member for "the differ
    graded this below ERR so it was ignored" and inventing one would put a false claim in a typed
    field. Silence is not a gap in the comparison: the scorer's collapse rule scores a call site
    with no finding as predicted UNAFFECTED, which is exactly this baseline's verdict, on the
    identical call-site denominator.
    """
    return [
        _finding(callsite, change, "baseline.err_level_only")
        for callsite, change in candidate_pairs(changes, callsites)
        if change.level == _ERR_LEVEL
    ]
