"""agents/_fix_capabilities.py — Shim for shared.fix_capabilities.

Re-exports fix capability loading during shared/ dissolution.
Will be replaced with vendored code when shared/ is deleted (phase 3.8).
"""

from shared.fix_capabilities import load_builtin_capabilities  # noqa: F401
from shared.fix_capabilities.pipeline import run_fix_pipeline  # noqa: F401
