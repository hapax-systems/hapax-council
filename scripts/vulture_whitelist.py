"""Justified dynamic-entrypoint references for scripts/check-unused-functions.py.

Keep this file narrow. Add names here only when a callable is invoked by a
framework, subprocess entrypoint, import string, or other dynamic path that
vulture cannot see. Do not use this as a baseline for ordinary dead code.
"""

# FastAPI registers this route by decorator; vulture does not follow APIRouter.
studio_egress_state
