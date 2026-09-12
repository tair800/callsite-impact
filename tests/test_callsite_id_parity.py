"""The two sides of the pipeline must name a call site the same thing.

`harness/scripts/gen-callsites.mjs` mints call-site ids in JavaScript and
`callsite_impact.domain.callsite_id` mints them in Python. Nothing forces those two implementations
to agree, and if they ever drift the failure is silent and total: the oracle's labels key on ids the
classifier's call sites do not have, every join comes back empty, and the scorer reports a corpus
with no breakages in it — which reads exactly like a passing run of a tool that found nothing.

So this test runs the real JavaScript and compares it to the real Python. It is marked ``node``
because it needs a Node runtime; the offline suite skips it, and CI runs it in the job that has one.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from callsite_impact.domain import callsite_id

HARNESS = Path(__file__).resolve().parents[1] / "harness"

CASES = [
    ("adyen-checkout-v71-v72", "POST /payments", 0),
    ("adyen-checkout-v71-v72", "POST /payments", 7),
    ("xero-bankfeeds-a-b", "GET /Statements", 3),
    ("stripe-core-v2470-v2484", "POST /v1/charges", 12),
    # Deliberately awkward: a path with a template segment and a path with a dash.
    ("adyen-checkout-v67-v68", "POST /payments/{paymentPspReference}/cancels", 1),
    ("adyen-checkout-v67-v68", "POST /applePay/sessions", 2),
]

_SCRIPT = """
import { createHash } from "node:crypto";
function callsiteId(pairId, operationKey, index) {
  const digest = createHash("sha256").update(`${pairId}|${operationKey}|${index}`).digest("hex");
  return `cs_${digest.slice(0, 12)}`;
}
const cases = JSON.parse(process.argv[2]);
console.log(JSON.stringify(cases.map(([p, o, i]) => callsiteId(p, o, i))));
"""


@pytest.mark.node
def test_javascript_and_python_mint_the_same_callsite_ids(tmp_path: Path) -> None:
    """Identical inputs, identical ids — checked against the JavaScript that actually ships.

    The JavaScript under test is copied out of the generator rather than re-typed here, and a second
    test asserts that the copy still matches the original. Testing a re-typed copy would pass
    happily while the shipped generator drifted away from it.
    """
    if shutil.which("node") is None:
        pytest.skip("node is not on PATH")

    script = tmp_path / "parity.mjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    completed = subprocess.run(
        ["node", str(script), json.dumps(CASES)],
        capture_output=True,
        text=True,
        check=True,
    )
    from_js = json.loads(completed.stdout)
    from_py = [callsite_id(pair, operation, index) for pair, operation, index in CASES]

    assert from_js == from_py, (
        "the JavaScript and Python call-site id functions disagree. Every join between the oracle "
        "and the classifier keys on this value, so a disagreement empties the corpus silently "
        "rather than failing."
    )


@pytest.mark.node
def test_the_parity_script_still_matches_the_shipped_generator() -> None:
    """Pin the copy above to the original, so this file cannot pass against dead code."""
    source = (HARNESS / "scripts" / "gen-callsites.mjs").read_text(encoding="utf-8")
    shipped = (
        "function callsiteId(pairId, operationKey, index) {\n"
        "  const digest = createHash"
        '("sha256").update(`${pairId}|${operationKey}|${index}`).digest("hex");\n'
        "  return `cs_${digest.slice(0, 12)}`;\n"
        "}"
    )
    assert shipped in source, (
        "gen-callsites.mjs no longer contains the id function this test pins. Update both "
        "together, or the parity test is checking something no longer shipped."
    )
