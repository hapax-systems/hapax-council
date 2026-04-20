"""D-17 final piece — quiet_frame subscriber to MonetizationRiskGate decisions.

Closes the dead-bridge chain identified by the 2026-04-20 audit:

  D-27 (egress audit wire)     SHIPPED 1fb58b0b7
  D-26 (Programme plumb)       SHIPPED 866b66499
  D-18 (music_policy CPAL)     SHIPPED 3ea6074e9
  D-17 (THIS module)           — quiet_frame triggered by gate BLOCKED

Mechanism:

  * MonetizationRiskGate fires the registered listener after every
    ``_record_and_return()`` call (D-17 listener API).
  * On ANY ``allowed=False`` decision, this subscriber calls
    ``activate_quiet_frame()`` with a 5-minute in-process cooldown so a
    burst of blocks (e.g. ten medium-risk capabilities filtered in one
    affordance pipeline pass) does not generate ten Programme-store
    write storms.
  * ``activate_quiet_frame()`` is idempotent per D-20 (programme_store
    dedup-add); the cooldown is purely an I/O optimization, not a
    correctness requirement.
  * No automatic deactivation — quiet_frame Programme has a 15-min
    ``planned_duration_s`` and the operator can deactivate explicitly via
    ``hapax-quiet-frame --deactivate``. Auto-deactivation requires a
    sustained-ALLOWED detector that this proof-of-wiring intentionally
    does not include.

Behavior is GATED OFF by default. Set ``HAPAX_QUIET_FRAME_AUTO=1`` to
register the listener at import time. Off-by-default keeps the existing
gate behavior unchanged for sessions that import this module without
intending to enable the auto-quiet-frame loop (mostly tests). The
production import site (``shared/affordance_pipeline.py``) opts in by
setting the env var in the systemd unit when operator wants the wire
hot.
"""

from __future__ import annotations

import logging
import os
import time
from threading import Lock
from typing import TYPE_CHECKING

from shared.governance.monetization_safety import register_assess_listener

if TYPE_CHECKING:
    from shared.governance.monetization_safety import RiskAssessment

_log = logging.getLogger(__name__)

# Cooldown between quiet_frame activations. 5 minutes is well below the
# 15-min Programme duration so a sustained block stream re-arms the safety
# hold once per cooldown rather than per decision. Tunable via env var
# HAPAX_QUIET_FRAME_COOLDOWN_S.
COOLDOWN_S: float = float(os.environ.get("HAPAX_QUIET_FRAME_COOLDOWN_S", "300.0"))

_lock = Lock()
_last_activation_at: float = 0.0


def _on_assess(
    assessment: RiskAssessment,
    capability_name: str | None,
    programme_id: str | None,
) -> None:
    """Listener body — activate quiet_frame on BLOCKED with cooldown.

    Designed to be cheap on the steady-state ALLOWED path (a single
    branch + return). Activation path is rare (governance hold) and
    cooldown-bounded.
    """
    if assessment.allowed:
        return  # steady-state — no work
    global _last_activation_at  # noqa: PLW0603 — module-level singleton state
    now = time.time()
    with _lock:
        if now - _last_activation_at < COOLDOWN_S:
            return  # within cooldown — already activated recently
        _last_activation_at = now
    # Deferred import: quiet_frame imports programme_store which loads from
    # disk; do NOT pay that cost at module import time.
    try:
        from shared.governance.quiet_frame import activate_quiet_frame

        prog = activate_quiet_frame(
            reason=(
                f"governance: gate BLOCKED {capability_name or '<unknown>'} "
                f"({assessment.risk}) — {assessment.reason}"
            ),
        )
        _log.info(
            "quiet_frame ACTIVATED by gate BLOCKED on %s: programme=%s reason=%s",
            capability_name,
            prog.programme_id,
            assessment.reason,
        )
    except Exception:  # noqa: BLE001 — listener faults must not break the gate
        _log.warning("quiet_frame activation failed", exc_info=True)


def is_enabled() -> bool:
    """True iff the auto-quiet-frame loop is enabled via env var."""
    return os.environ.get("HAPAX_QUIET_FRAME_AUTO", "0") == "1"


def install() -> None:
    """Register the listener with MonetizationRiskGate.

    Called from production import sites (e.g. affordance_pipeline.py).
    No-op when ``HAPAX_QUIET_FRAME_AUTO != 1`` so test imports don't
    accidentally enable the wire.
    """
    if is_enabled():
        register_assess_listener(_on_assess)
        _log.info("quiet_frame_subscriber installed (cooldown=%.0fs)", COOLDOWN_S)


def reset_for_tests() -> None:
    """Clear cooldown state — tests only."""
    global _last_activation_at  # noqa: PLW0603 — test-only reset
    with _lock:
        _last_activation_at = 0.0
