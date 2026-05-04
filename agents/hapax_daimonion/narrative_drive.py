"""Endogenous narrative drive loop — emits drive impingements to the bus.

Ticks every 10 seconds, assembles a DriveContext from daemon state, and
evaluates the EndogenousDrive.  When the posterior crosses the stochastic
threshold, writes an impingement to the DMN bus that the AffordancePipeline
then recruits narration.autonomous_first_system against.

Spawned by ``run_inner._make_task(daemon, "narrative_drive_loop", ...)``.

Design reference:
    docs/research/2026-04-27-endogenous-drive-role-semantic-surfacing.md §3.1
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from shared.conative_impingement import narrative_drive_content_payload
from shared.endogenous_drive import DriveContext, EndogenousDrive

log = logging.getLogger(__name__)

_IMPINGEMENTS_FILE = Path("/dev/shm/hapax-dmn/impingements.jsonl")
_TICK_SLEEP_S: float = 10.0
# Minimum cooldown between impingement emissions.  Without this, high
# chronicle counts (250+ events) push the posterior above threshold on
# every tick because the chronicle modifier overwhelms the base_pressure
# exponential reset.  The pipeline's own 120s refractory inhibition
# prevents actual narration re-dispatch, but we should not flood the
# impingement bus with drive signals.
#
# Tuned 2026-05-04 from 60s → 30s as the cadence floor for sustained
# vocal presence on the broadcast (cc-task livestream-vocal-as-fuck-amp).
# The pipeline's own 120s refractory still prevents downstream re-dispatch
# of identical narration content — this is the impingement-bus floor.
_EMISSION_COOLDOWN_S: float = 30.0

# Drive tuning constants. Lower tau → faster pressure accumulation
# (~0.39 of full pressure at t=tau, ~0.63 at 2*tau).  At tau=60s the
# drive reaches surfacing threshold inside the 30s cooldown window so
# every cooldown expiry is an emission candidate when programme is
# active and operator is engaged.
_DRIVE_TAU_S: float = 60.0
_DRIVE_THRESHOLD: float = 0.12


def _read_chronicle_count(now: float, window_s: float = 600.0) -> int:
    """Count chronicle events in the recent window.

    Reads from the state_readers module to stay consistent with the
    composition pipeline.
    """
    try:
        from agents.hapax_daimonion.autonomous_narrative.state_readers import (
            read_chronicle_window,
        )

        events = read_chronicle_window(now=now, window_s=window_s)
        return len(events)
    except Exception:
        log.debug("chronicle count read failed", exc_info=True)
        return 0


def _read_stimmung_stance() -> str:
    """Read current stimmung stance from SHM."""
    try:
        from agents.hapax_daimonion.autonomous_narrative.state_readers import (
            read_stimmung_tone,
        )

        return read_stimmung_tone()
    except Exception:
        return "ambient"


def _read_presence_score(daemon: Any) -> float:
    """Read operator presence posterior from the perception engine."""
    try:
        presence_str = getattr(
            getattr(daemon, "perception", None),
            "latest",
            None,
        )
        if presence_str is None:
            return 0.0
        score = getattr(presence_str, "presence_score", "likely_absent")
        # presence_score is a string like "likely_absent", "likely_present"
        # Map to numeric [0, 1]
        if isinstance(score, (int, float)):
            return float(score)
        score_map = {
            "likely_absent": 0.1,
            "uncertain": 0.5,
            "likely_present": 0.9,
        }
        return score_map.get(str(score).lower(), 0.0)
    except Exception:
        return 0.0


def _read_programme_role(daemon: Any) -> str | None:
    """Read active programme role from the daemon's programme manager."""
    try:
        from agents.hapax_daimonion.autonomous_narrative.state_readers import (
            read_active_programme,
        )

        prog = read_active_programme(daemon)
        if prog is None:
            return None
        role = getattr(prog, "role", None)
        return str(role) if role is not None else None
    except Exception:
        return None


# Freshness window for the programme_authorization payload composed
# alongside each impingement. The broadcast playback gate accepts an
# auth as fresh when ``now - authorized_at <= 120s``; we set
# expires_at to authorized_at + this constant so the gate has a
# matching forward window.
_PROGRAMME_AUTH_FRESHNESS_S: float = 90.0


def _compose_programme_authorization(daemon: Any, now: float) -> dict[str, Any] | None:
    """Compose a programme_authorization payload from the active Programme.

    Returns ``None`` when no Programme is active, when the active
    Programme is not in the ``ACTIVE`` status, or when the canonical
    store is unreadable. The destination_channel gate already treats
    a missing payload as ``programme_authorization_missing`` and
    fails closed, so returning ``None`` here is the safe path.
    """
    try:
        from agents.hapax_daimonion.autonomous_narrative.state_readers import (
            read_active_programme,
        )

        prog = read_active_programme(daemon)
        if prog is None:
            return None
        status = getattr(prog, "status", None)
        if status is None or str(status) not in {"active", "ProgrammeStatus.ACTIVE"}:
            return None
        programme_id = getattr(prog, "programme_id", None)
        if not programme_id:
            return None
        role = getattr(prog, "role", None)
        return {
            "authorized": True,
            "authorized_at": now,
            "expires_at": now + _PROGRAMME_AUTH_FRESHNESS_S,
            "programme_id": str(programme_id),
            "evidence_ref": (
                f"programme_active:{role}:{programme_id}"
                if role is not None
                else f"programme_active:{programme_id}"
            ),
        }
    except Exception:
        log.debug("programme_authorization composition failed", exc_info=True)
        return None


def _assemble_drive_context(daemon: Any, now: float) -> DriveContext:
    """Build a DriveContext from live daemon state."""
    return DriveContext(
        chronicle_event_count=_read_chronicle_count(now),
        stimmung_stance=_read_stimmung_stance(),
        operator_presence_score=_read_presence_score(daemon),
        programme_role=_read_programme_role(daemon),
        now=now,
    )


def _emit_drive_impingement(
    drive: EndogenousDrive,
    context: DriveContext,
    *,
    programme_authorization: dict[str, Any] | None = None,
) -> bool:
    """Write an endogenous drive impingement to the DMN bus.

    ``programme_authorization`` (optional) is forwarded into the content
    payload so downstream playback resolution can confirm fresh
    broadcast-voice authorization. Pass ``None`` when no programme is
    active — the playback gate will then fail closed on
    ``programme_authorization_missing``, which is the correct behavior.

    Returns True if the write succeeded, False otherwise.
    """
    now = context.now or time.time()
    narrative = drive.build_narrative(context)
    posterior_pressure = min(1.0, max(0.0, drive.evaluate(context)))
    impingement_id = uuid.uuid4().hex[:12]

    imp = {
        "id": impingement_id,
        "timestamp": now,
        "source": "endogenous.narrative_drive",
        "type": "endogenous",
        "strength": posterior_pressure,
        "content": narrative_drive_content_payload(
            impingement_id=impingement_id,
            narrative=narrative,
            drive_name=drive.name,
            strength_posterior=posterior_pressure,
            chronicle_event_count=context.chronicle_event_count,
            stimmung_stance=context.stimmung_stance,
            programme_role=context.programme_role,
            programme_authorization=programme_authorization,
        ),
        "context": {},
    }
    try:
        _IMPINGEMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _IMPINGEMENTS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(imp) + "\n")
        log.info(
            "Narrative drive emitted impingement (pressure=%.3f, chronicle=%d, role=%s)",
            posterior_pressure,
            context.chronicle_event_count,
            context.programme_role or "none",
        )
        return True
    except OSError:
        log.warning("Failed to write narrative drive impingement", exc_info=True)
        return False


async def narrative_drive_loop(daemon: Any) -> None:
    """Run the endogenous narrative drive evaluator until shutdown.

    On each tick:
    1. Assemble DriveContext from daemon state
    2. Check cooldown (skip if within _EMISSION_COOLDOWN_S of last emission)
    3. Evaluate drive posterior
    4. If posterior > threshold, emit impingement + record emission
    """
    drive = EndogenousDrive(tau=_DRIVE_TAU_S, threshold=_DRIVE_THRESHOLD, name="narration")
    last_emission_at: float = 0.0

    log.info(
        "Narrative drive loop started (tau=%.0fs, threshold=%.2f, cooldown=%.0fs)",
        drive.tau,
        drive.threshold,
        _EMISSION_COOLDOWN_S,
    )

    while getattr(daemon, "_running", True):
        try:
            now = time.time()

            # Cooldown: don't evaluate or emit within _EMISSION_COOLDOWN_S
            # of the last emission to prevent bus flooding when contextual
            # modifiers (high chronicle count) overwhelm base_pressure reset.
            if (now - last_emission_at) < _EMISSION_COOLDOWN_S:
                await asyncio.sleep(_TICK_SLEEP_S)
                continue

            context = _assemble_drive_context(daemon, now)

            if drive.should_emit(context):
                programme_auth = _compose_programme_authorization(daemon, now)
                ok = _emit_drive_impingement(
                    drive,
                    context,
                    programme_authorization=programme_auth,
                )
                if ok:
                    drive.record_emission(now)
                    last_emission_at = now
        except Exception:
            log.exception("Narrative drive tick raised; continuing")

        await asyncio.sleep(_TICK_SLEEP_S)
