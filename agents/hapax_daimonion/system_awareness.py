"""agents/hapax_daimonion/system_awareness.py — Surface DMN degradation to operator.

Recruited by the affordance pipeline when DMN health signals (sensor
starvation, Ollama failure, resolver degradation) reach the impingement
cascade. Gated on stimmung stance — only activates when the system is
genuinely degraded, not on transient blips.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from agents._impingement import Impingement

log = logging.getLogger("voice.system_awareness")

SYSTEM_AWARENESS_DESCRIPTION = (
    "Surface system health degradation to operator awareness. "
    "Recruitable when infrastructure, inference, or sensor subsystems "
    "are failing and stimmung stance is DEGRADED or CRITICAL."
)

_STIMMUNG_GATE = {"degraded", "critical"}
_DEFAULT_STIMMUNG_PATH = Path("/dev/shm/hapax-stimmung/state.json")


class SystemAwarenessCapability:
    """Surfaces DMN degradation signals to operator via voice daemon."""

    def __init__(
        self,
        stimmung_path: Path = _DEFAULT_STIMMUNG_PATH,
        cooldown_s: float = 300.0,
    ) -> None:
        self._stimmung_path = stimmung_path
        self._cooldown_s = cooldown_s
        self._last_activation: float = -(cooldown_s + 1.0)
        self._pending: list[Impingement] = []

    def can_resolve(self, impingement: Impingement) -> float:
        """Score: impingement.strength if gate passes, 0.0 otherwise."""
        if time.monotonic() - self._last_activation < self._cooldown_s:
            return 0.0
        try:
            data = json.loads(self._stimmung_path.read_text(encoding="utf-8"))
            stance = data.get("overall_stance", "nominal")
        except (OSError, json.JSONDecodeError):
            return 0.0
        if stance not in _STIMMUNG_GATE:
            return 0.0
        return impingement.strength

    def activate(self, impingement: Impingement, level: float) -> None:
        """Queue awareness signal for voice pipeline consumption."""
        self._last_activation = time.monotonic()
        self._pending.append(impingement)
        log.info(
            "System awareness recruited: %s (strength=%.2f, level=%.2f)",
            impingement.content.get("metric", impingement.source),
            impingement.strength,
            level,
        )

    def has_pending(self) -> bool:
        return len(self._pending) > 0

    def consume_pending(self) -> Impingement | None:
        if self._pending:
            return self._pending.pop(0)
        return None
