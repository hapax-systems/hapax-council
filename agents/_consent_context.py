"""agents/_consent_context.py — Shim for shared.governance.consent_context.

Re-exports consent context utilities during shared/ dissolution.
Will be replaced with vendored code when shared/ is deleted (phase 3.8).
"""

from agents._governance.consent_context import (  # noqa: F401
    consent_scope,
    current_principal,
    current_registry,
    maybe_principal,
    maybe_registry,
    principal_scope,
)
