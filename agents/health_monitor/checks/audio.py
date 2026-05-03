"""Audio subsystem health checks.

Currently covers ``hapax-audio-ducker.service`` liveness — audit C#2
(2026-05-02) caught the ducker dead for ~8h with no operator-visible
signal. The ducker is the daemon that writes per-channel mixer gain
values into the music-duck filter chain in response to Rode VAD and TTS
envelope events; without it, music does not duck under voice and the
operator's narration is buried in the bed-music level.
"""

from __future__ import annotations

import time

from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group

_DUCKER_UNIT = "hapax-audio-ducker.service"


@check_group("audio")
async def check_audio_ducker_liveness() -> list[CheckResult]:
    """Verify ``hapax-audio-ducker.service`` is active.

    The ducker is the bridge between voice-activity detection and the
    per-channel mixer gain values written into ``hapax-music-duck`` and
    ``hapax-tts-duck`` filter chains. When inactive, music does not duck
    under operator voice or TTS — a livestream-quality regression.

    Sends an explicit ntfy notification on inactive state because the
    failure mode is silent (broadcast continues, just at the wrong
    relative levels).
    """
    t = time.monotonic()
    rc, out, _err = await _u.run_cmd(["systemctl", "--user", "is-active", _DUCKER_UNIT])
    active = out.strip() == "active"

    if active:
        return [
            CheckResult(
                name="audio.ducker_liveness",
                group="audio",
                status=Status.HEALTHY,
                message="hapax-audio-ducker active",
                duration_ms=_u._timed(t),
            )
        ]

    # Fire ntfy on inactive: silent failure mode otherwise (audio keeps
    # flowing, just without ducking).
    try:
        from shared.notify import send_notification

        send_notification(
            title="Audio ducker inactive",
            message=(
                f"{_DUCKER_UNIT} is {out.strip() or 'inactive'}. "
                "Music will not duck under operator voice or TTS. "
                "Restart with: systemctl --user restart " + _DUCKER_UNIT
            ),
            priority="high",
            tags=["warning", "audio"],
        )
    except Exception:  # noqa: BLE001 — notification failure must not mask the check
        pass

    return [
        CheckResult(
            name="audio.ducker_liveness",
            group="audio",
            status=Status.FAILED,
            message=f"{_DUCKER_UNIT} {out.strip() or 'inactive'}",
            detail=(
                "Music will not duck under operator voice or TTS until the daemon is restored."
            ),
            remediation=f"systemctl --user restart {_DUCKER_UNIT}",
            duration_ms=_u._timed(t),
        )
    ]
