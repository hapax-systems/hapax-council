"""logos/_revocation_wiring.py — Shim for shared.governance.revocation_wiring.

Re-exports revocation wiring during shared/ dissolution.
Will be replaced with vendored code when shared/ is deleted (phase 3.8).
"""

from shared.governance.revocation_wiring import (  # noqa: F401
    get_revocation_propagator,
    set_revocation_propagator,
)
