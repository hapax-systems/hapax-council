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
_EMISSION_COOLDOWN_S: float = 60.0


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


def _assemble_drive_context(daemon: Any, now: float) -> DriveContext:
    """Build a DriveContext from live daemon state."""
    return DriveContext(
        chronicle_event_count=_read_chronicle_count(now),
        stimmung_stance=_read_stimmung_stance(),
        operator_presence_score=_read_presence_score(daemon),
        programme_role=_read_programme_role(daemon),
        now=now,
    )


def _emit_drive_impingement(drive: EndogenousDrive, context: DriveContext) -> bool:
    """Write an endogenous drive impingement to the DMN bus.

    Returns True if the write succeeded, False otherwise.
    """
    now = context.now or time.time()
    narrative = drive.build_narrative(context)

    imp = {
        "id": uuid.uuid4().hex[:12],
        "timestamp": now,
        "source": "endogenous.narrative_drive",
        "type": "endogenous",
        "strength": min(1.0, drive.base_pressure(now)),
        "content": {
            "narrative": narrative,
            "drive": drive.name,
            "chronicle_event_count": context.chronicle_event_count,
            "stimmung_stance": context.stimmung_stance,
            "programme_role": context.programme_role or "none",
        },
        "context": {},
    }
    try:
        _IMPINGEMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _IMPINGEMENTS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(imp) + "\n")
        log.info(
            "Narrative drive emitted impingement (pressure=%.3f, chronicle=%d, role=%s)",
            drive.base_pressure(now),
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
    drive = EndogenousDrive(tau=120.0, threshold=0.12, name="narration")
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
                ok = _emit_drive_impingement(drive, context)
                if ok:
                    drive.record_emission(now)
                    last_emission_at = now
        except Exception:
            log.exception("Narrative drive tick raised; continuing")

        await asyncio.sleep(_TICK_SLEEP_S)
