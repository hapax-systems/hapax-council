"""Audio subsystem health checks.

The hapax-audio-ducker.service is architecturally obsolete as of
2026-05-19 — all ducking now occurs on the MPC Live III hardware
(sidechain from voice channel). The liveness check is retained but
returns HEALTHY unconditionally to prevent false-alarm notifications.
"""

from __future__ import annotations

import time

from ..models import CheckResult, Status
from ..registry import check_group


@check_group("audio")
async def check_audio_ducker_liveness() -> list[CheckResult]:
    """Ducking moved to MPC hardware — always healthy."""
    t = time.monotonic()
    return [
        CheckResult(
            name="audio.ducker_liveness",
            group="audio",
            status=Status.HEALTHY,
            message="ducking on MPC hardware — software ducker retired",
            duration_ms=int((time.monotonic() - t) * 1000),
        )
    ]
