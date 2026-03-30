"""logos/_carrier.py — Shim for shared.governance.carrier.

Re-exports carrier types during shared/ dissolution.
Will be replaced with vendored code when shared/ is deleted (phase 3.8).
"""

from shared.governance.carrier import (  # noqa: F401
    CarrierFact,
    CarrierRegistry,
    DisplacementResult,
    epistemic_contradiction_veto,
)
