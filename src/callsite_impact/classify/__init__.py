"""The system under test.

Everything here predicts from two sources only: the spec diff, and what a parser could see
in the call-site source. It does not read `tsc` output, and it must not — the compiler is the answer
key this package is graded against, so an import from ``callsite_impact.oracle`` here would make the
measurement meaningless.

That is enforced by ``tests/test_oracle_boundary.py``, which parses every module in this package and
fails the build on such an import, and by ``tests/test_ai_boundary.py``, which goes red if the
verdict type grows a field a model could write a judgement into. Neither is a reminder; both are
tests that go red.
"""

from callsite_impact.classify.engine import classify_pair
from callsite_impact.classify.rules import RULES, Reason, Rule, RuleResult, classify_change

__all__ = ["RULES", "Reason", "Rule", "RuleResult", "classify_change", "classify_pair"]
