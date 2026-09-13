"""The confirmatory slice: spec pairs chosen by name, frozen before anything was scored.

ADR-004. The development corpus in `acquire.py` is the corpus the rule table was fitted to — eight
prose patterns were written *after* seeing a score on it, which makes every number measured there a
development figure. This module defines a second, disjoint set of pairs whose purpose is to be
measured **once**, with no rule changed afterwards.

**What makes it a hold-out is the order of operations, and that order is checkable.** This file is
committed before `artifacts/holdout.json` exists. `git log --diff-filter=A` on the two paths shows
which came first; if they ever land in one commit, the freeze is worthless and a reader should say
so. Nothing here was selected by looking at a diff, a change id, or a result — only at service names
and which revisions exist.

**What this slice does and does not test.** It is a *data* hold-out, not a *vendor* hold-out. The
services are new and so are the call sites, the changes and the compiler labels, so it tests whether
the rule logic — path matching, pinned-type detection, optional-chaining, the abstention gate —
generalises to instances nobody tuned against. It does **not** independently test the expressibility
table: these are the same three vendors and their change ids will largely be ids already ruled on.
An id that has not been ruled on falls through to `UNCLASSIFIED` and abstains, which is the honest
behaviour and will show up in the strict score rather than being hidden.

**The one exclusion rule, declared here rather than applied later.** A pair may be dropped **only**
when the toolchain cannot process it at all — `oasdiff` refuses the specification, `openapi-typescript`
fails, or the generator emits nothing. A pair is **never** dropped because of the result it produced.
Every exclusion is counted and published beside the score.
"""

from __future__ import annotations

from typing import Final

__all__ = ["HOLDOUT_ADYEN", "HOLDOUT_TWILIO", "HOLDOUT_XERO", "EXCLUSION_RULE"]

EXCLUSION_RULE: Final = (
    "A pair is excluded only when the toolchain cannot process it (the differ refuses the "
    "specification, type generation fails, or the generator emits no call site). Never because of "
    "its measured result. Every exclusion is counted and published."
)

#: Adyen services with side-by-side major versions, none of them in the development corpus, which
#: uses checkout, balance-platform, account and bin-lookup. Same pinned commit as that corpus.
HOLDOUT_ADYEN: Final = (
    ("legal-entity", "LegalEntityService", ("v3", "v4")),
    ("transfer", "TransferService", ("v3", "v4")),
    ("payment", "PaymentService", ("v67", "v68")),
    ("payout", "PayoutService", ("v67", "v68")),
    ("recurring", "RecurringService", ("v67", "v68")),
    ("management", "ManagementService", ("v1", "v3")),
)

#: Twilio products present at both the initial public import and the recent revision, none of them
#: in the development corpus, which uses flex, messaging, verify, taskrouter, conversations, events.
HOLDOUT_TWILIO: Final = (
    ("lookups", "twilio_lookups_v1.json"),
    ("notify", "twilio_notify_v1.json"),
    ("proxy", "twilio_proxy_v1.json"),
    ("serverless", "twilio_serverless_v1.json"),
    ("studio", "twilio_studio_v2.json"),
    ("supersim", "twilio_supersim_v1.json"),
)

#: Xero APIs not in the development corpus, which uses bankfeeds, files and payroll-au. The three
#: specifications the differ rejects outright — accounting, finance, projects — are still excluded
#: for the reason recorded in `acquire.py`; that exclusion predates this slice and is not a result.
HOLDOUT_XERO: Final = (
    ("payroll-nz", "xero-payroll-nz.yaml"),
    ("payroll-uk", "xero-payroll-uk.yaml"),
    ("assets", "xero_assets.yaml"),
)
