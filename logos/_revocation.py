"""logos/_revocation.py — Shim for shared.governance.revocation.

Re-exports revocation types during shared/ dissolution.
Will be replaced with vendored code when shared/ is deleted (phase 3.8).
"""

from shared.governance.revocation import (  # noqa: F401
    PurgeResult,
    RevocationPropagator,
    RevocationReport,
    check_provenance,
)
