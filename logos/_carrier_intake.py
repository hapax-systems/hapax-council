"""logos/_carrier_intake.py — Shim for shared.governance.carrier_intake.

Re-exports carrier intake during shared/ dissolution.
Will be replaced with vendored code when shared/ is deleted (phase 3.8).
"""

from agents._governance.carrier_intake import (  # noqa: F401
    CarrierIntakeResult,
    intake_carrier_fact,
    parse_carrier_fact,
)
