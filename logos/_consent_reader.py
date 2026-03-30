"""logos/_consent_reader.py — Shim for shared.governance.consent_reader.

Re-exports ConsentGatedReader during shared/ dissolution.
Will be replaced with vendored code when shared/ is deleted (phase 3.8).
"""

from shared.governance.consent_reader import (  # noqa: F401
    ConsentGatedReader,
    ReaderDecision,
    RetrievedDatum,
)
