"""Pairing and anchoring: turn a spec diff and a call-site corpus into findings a reader can check.

The engine owns two decisions that the rules deliberately do not.

**What counts as a candidate pair.** A change is paired only with call sites on its own operation.
A change to ``POST /payments`` and a call site on ``GET /accounts`` are not a pair, they are not a
finding, and — this is the part that matters — they are not in the denominator either. Emitting a
finding for every (change x call site) combination would inflate the denominator that the abstention
rate and every other published rate divide by, which is a way of making a number look good without
changing anything about the system. Changes on operations no call site touches produce nothing.

**Where a finding points.** Every finding carries the change's own anchors and the call site's file
and line; where a rule decided on a specific property access, the finding is narrowed to that
access's line, column and dotted path. A finding that cannot be anchored at all is suppressed rather
than published unanchored, per the project rule that a verdict without an anchor is not a verdict.

The classifier's expressibility authority is ``callsite_impact.specdiff.expressibility``, whose
``expressibility_of`` the differ lane calls when it builds a :class:`SpecChange`. The engine reads
the resolved value off the change rather than calling the table a second time: re-deriving a field
from the same source it came from is not a check, and it would give the classification path a second
place where an abstention could be lost. ``tests/test_classify_rules.py`` asserts the two agree —
every change id with a rule here must be type-expressible there, or the gate silently swallows the
rule.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Sequence

from callsite_impact.classify.rules import RuleResult, classify_change
from callsite_impact.domain import Callsite, Finding, SpecChange

__all__ = ["classify_pair"]

_LOGGER = logging.getLogger(__name__)


def classify_pair(
    changes: Sequence[SpecChange],
    callsites: Sequence[Callsite],
) -> list[Finding]:
    """Classify every candidate (change, call site) pair for one spec pair.

    Ordering is deterministic: changes in the order the differ reported them, and per change the
    call sites sorted by file, line and id. Two runs over the same inputs produce the same list in
    the same order, which is what makes a committed artifact diffable.

    Args:
        changes: The changes for one spec pair, with expressibility already resolved.
        callsites: The admitted corpus. Call sites on operations no change touches are simply never
            visited.

    Returns:
        One anchored :class:`Finding` per candidate pair. Pairs whose call site is on a different
        operation are not represented at all, by design.
    """
    by_operation = _index_by_operation(callsites)
    findings: list[Finding] = []
    suppressed = 0
    for change in changes:
        for callsite in by_operation.get(change.operation_key, ()):
            rule_name, result = classify_change(change, callsite.facts)
            finding = _anchor(change, callsite, rule_name, result)
            if not finding.anchored:
                suppressed += 1
                continue
            findings.append(finding)
    if suppressed:
        _LOGGER.warning(
            "suppressed %d unanchored finding(s); an unanchored verdict is counted, not published",
            suppressed,
        )
    return findings


def _index_by_operation(callsites: Sequence[Callsite]) -> dict[str, list[Callsite]]:
    """Group call sites by operation key, sorted so the output order does not depend on the input.

    Args:
        callsites: The admitted corpus, in whatever order the generator emitted it.

    Returns:
        Operation key to call sites, each bucket sorted by file, line, then id.
    """
    buckets: dict[str, list[Callsite]] = defaultdict(list)
    for callsite in callsites:
        buckets[callsite.operation_key].append(callsite)
    for bucket in buckets.values():
        bucket.sort(key=lambda site: (site.file, site.line, site.callsite_id))
    return dict(buckets)


def _anchor(
    change: SpecChange,
    callsite: Callsite,
    rule_name: str,
    result: RuleResult,
) -> Finding:
    """Attach the anchors to a rule's verdict.

    When the rule named a property access, the finding points at that access rather than at the call
    site's line — a reader checking a false positive needs the token, not the function. When it
    did not, because the evidence was an absence or the change was not about a property, the call
    site's own position is the most specific honest anchor.

    The token is reconstructed as the dotted access path. ``PropertyAccess`` records the parsed path
    rather than the raw source slice, so this is the parser's reading of the token, not the bytes;
    together with the line and column it is enough to find the exact expression.

    Args:
        change: The change being judged.
        callsite: The call site being judged.
        rule_name: The branch that decided, from :func:`classify_change`.
        result: The rule's verdict, reason and optional access.

    Returns:
        The finding, which the caller still checks for anchoring before publishing.
    """
    access = result.access
    return Finding(
        callsite_id=callsite.callsite_id,
        pair_id=callsite.pair_id,
        verdict=result.verdict,
        rule=rule_name,
        reason=result.reason,
        change=change,
        callsite_file=callsite.file,
        callsite_line=access.line if access is not None else callsite.line,
        callsite_column=access.column if access is not None else None,
        callsite_token=".".join(access.path) if access is not None else None,
    )
