"""agents/_guest_detection.py — Shim for shared.governance.guest_detection.

Re-exports guest detection types during shared/ dissolution.
Will be replaced with vendored code when shared/ is deleted (phase 3.8).
"""

from shared.governance.guest_detection import (  # noqa: F401
    GuestDetectionEvent,
    check_guest_consent,
    notify_guest_detected,
)
