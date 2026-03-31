"""logos/_agent_governor.py — Shim for shared.governance.agent_governor.

Re-exports agent governor factory during shared/ dissolution.
Will be replaced with vendored code when shared/ is deleted (phase 3.8).
"""

from agents._governance.agent_governor import (  # noqa: F401
    create_agent_governor,
)
