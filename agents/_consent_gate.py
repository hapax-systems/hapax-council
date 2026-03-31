"""agents/_consent_gate.py — Shim for shared.governance.consent_gate.

Re-exports ConsentGatedWriter during shared/ dissolution.
Will be replaced with vendored code when shared/ is deleted (phase 3.8).
"""

from agents._governance.consent_gate import (  # noqa: F401
    ConsentGatedWriter,
    GateDecision,
)
