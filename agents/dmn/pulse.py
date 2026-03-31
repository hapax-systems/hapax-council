"""DMN pulse engine — multi-rate tick loop with Ollama inference."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from agents._circuit_breaker import CircuitBreaker
from agents._impingement import Impingement, ImpingementType
from agents.dmn.buffer import DMNBuffer
from agents.dmn.ollama import (
    CONSOLIDATION_SYSTEM,
    EVALUATIVE_SYSTEM,
    SENSORY_SYSTEM,
    _format_sensor_prompt,
    _ollama_generate,
)
from agents.dmn.sensor import read_all
from agents.dmn.vision import _generate_visual_observation

VISUAL_OBSERVATION_PATH = Path("/dev/shm/hapax-dmn/visual-observation.txt")

log = logging.getLogger("dmn.pulse")

SENSORY_TICK_S = 5.0
EVALUATIVE_TICK_S = 30.0
CONSOLIDATION_TICK_S = 180.0


class DMNPulse:
    """Multi-rate DMN pulse engine."""

    def __init__(self, buffer: DMNBuffer) -> None:
        self._buffer = buffer
        self._last_sensory = 0.0
        self._last_evaluative = 0.0
        self._last_consolidation = 0.0
        self._prior_snapshot: dict | None = None
        self._tpn_active = False
        self._pending_impingements: list[Impingement] = []
        self._ollama_breaker = CircuitBreaker("ollama", failure_threshold=5, cooldown_s=30.0)
        self._degradation_emitted = False
        self._starvation_last_emitted: dict[str, float] = {}

    def set_tpn_active(self, active: bool) -> None:
        self._tpn_active = active

    async def tick(self) -> None:
        now = time.monotonic()
        sensory_rate = SENSORY_TICK_S * (2.0 if self._tpn_active else 1.0)
        evaluative_rate = EVALUATIVE_TICK_S * (2.0 if self._tpn_active else 1.0)
        snapshot = read_all()
        self._check_sensor_starvation(snapshot)

        if now - self._last_sensory >= sensory_rate:
            await self._sensory_tick(snapshot)
            self._last_sensory = now
        if now - self._last_evaluative >= evaluative_rate:
            await self._evaluative_tick(snapshot)
            self._last_evaluative = now
        if now - self._last_consolidation >= CONSOLIDATION_TICK_S:
            if self._buffer.needs_consolidation():
                await self._consolidation_tick()
            self._last_consolidation = now

        self._prior_snapshot = snapshot

    async def _sensory_tick(self, snapshot: dict) -> None:
        deltas = self._buffer.format_delta_context(self._prior_snapshot, snapshot)
        if not deltas and self._prior_snapshot is not None:
            self._buffer.add_observation("stable")
            return
        prompt = _format_sensor_prompt(snapshot, deltas)
        if self._ollama_breaker.allow_request():
            observation = await _ollama_generate(prompt, SENSORY_SYSTEM)
            if observation:
                self._ollama_breaker.record_success()
                self._degradation_emitted = False
            else:
                self._ollama_breaker.record_failure()
                self._check_ollama_degradation()
                observation = ""
        else:
            observation = ""
        if observation:
            self._buffer.add_observation(observation, deltas, raw_sensor=prompt)
            log.debug("Sensory: %s", observation[:80])
        else:
            self._buffer.add_observation(prompt[:100], deltas, raw_sensor=prompt)

    def _check_absolute_thresholds(self, snapshot: dict) -> None:
        fortress = snapshot.get("fortress")
        if fortress:
            pop = fortress.get("population", 0)
            drink = fortress.get("drink", 0)
            if pop > 0 and drink < pop * 2:
                self._pending_impingements.append(
                    Impingement(
                        timestamp=time.time(),
                        source="dmn.absolute_threshold",
                        type=ImpingementType.ABSOLUTE_THRESHOLD,
                        strength=min(1.0, 1.0 - (drink / max(1, pop * 2))),
                        content={
                            "metric": "drink_per_capita",
                            "value": drink,
                            "threshold": pop * 2,
                        },
                        context={"fortress": fortress.get("fortress_name", ""), "population": pop},
                    )
                )
            if pop > 0 and pop < 3:
                self._pending_impingements.append(
                    Impingement(
                        timestamp=time.time(),
                        source="dmn.absolute_threshold",
                        type=ImpingementType.ABSOLUTE_THRESHOLD,
                        strength=1.0,
                        content={"metric": "extinction_risk", "value": pop, "threshold": 3},
                        context={"fortress": fortress.get("fortress_name", "")},
                        interrupt_token="population_critical",
                    )
                )
        stimmung = snapshot.get("stimmung", {})
        if stimmung.get("stance") == "critical":
            self._pending_impingements.append(
                Impingement(
                    timestamp=time.time(),
                    source="dmn.absolute_threshold",
                    type=ImpingementType.ABSOLUTE_THRESHOLD,
                    strength=0.9,
                    content={"metric": "stimmung_critical", "stance": "critical"},
                    context={"operator_stress": stimmung.get("operator_stress", 0)},
                )
            )

    def _check_ollama_degradation(self) -> None:
        failures = self._ollama_breaker.consecutive_failures
        if failures >= 5 and not self._degradation_emitted:
            self._pending_impingements.append(
                Impingement(
                    timestamp=time.time(),
                    source="dmn.ollama_degraded",
                    type=ImpingementType.ABSOLUTE_THRESHOLD,
                    strength=0.7 if failures < 10 else 1.0,
                    content={"metric": "ollama_degraded", "consecutive_failures": failures},
                )
            )
            self._degradation_emitted = True
            log.error("Ollama degraded: %d consecutive failures", failures)

    def _check_sensor_starvation(self, snapshot: dict) -> None:
        """Emit impingement for sensors that are stale >60s or missing."""
        for sensor_name in ("perception", "stimmung", "fortress", "watch"):
            data = snapshot.get(sensor_name)
            if isinstance(data, dict):
                age = data.get("age_s", float("inf"))
            else:
                age = float("inf")
            if age > 60.0:
                last = self._starvation_last_emitted.get(sensor_name, 0.0)
                if time.time() - last > 300.0:
                    self._pending_impingements.append(
                        Impingement(
                            timestamp=time.time(),
                            source="dmn.sensor_starvation",
                            type=ImpingementType.ABSOLUTE_THRESHOLD,
                            strength=0.5,
                            content={"sensor": sensor_name, "age_s": age},
                        )
                    )
                    self._starvation_last_emitted[sensor_name] = time.time()

    def drain_impingements(self) -> list[Impingement]:
        pending = self._pending_impingements[:]
        self._pending_impingements.clear()
        return pending

    async def _write_visual_observation(self, snapshot: dict) -> None:
        visual = snapshot.get("visual_surface", {})
        if not visual or visual.get("stale", True):
            return
        frame_path = visual.get("frame_path")
        if not frame_path:
            return
        narrative = snapshot.get("imagination", {}).get("narrative", "")
        result = await _generate_visual_observation(frame_path, narrative)
        if result:
            try:
                VISUAL_OBSERVATION_PATH.parent.mkdir(parents=True, exist_ok=True)
                tmp = VISUAL_OBSERVATION_PATH.with_suffix(".tmp")
                tmp.write_text(result)
                tmp.rename(VISUAL_OBSERVATION_PATH)
            except OSError:
                pass

    async def _evaluative_tick(self, snapshot: dict) -> None:
        self._check_absolute_thresholds(snapshot)
        deltas = self._buffer.format_delta_context(self._prior_snapshot, snapshot)
        stimmung = snapshot.get("stimmung", {})
        if not deltas and stimmung.get("stance") == "nominal":
            return
        prompt = _format_sensor_prompt(snapshot, deltas)
        if self._ollama_breaker.allow_request():
            result = await _ollama_generate(prompt, EVALUATIVE_SYSTEM)
            if result:
                self._ollama_breaker.record_success()
                self._degradation_emitted = False
            else:
                self._ollama_breaker.record_failure()
                self._check_ollama_degradation()
                result = ""
        else:
            result = ""
        if result:
            trajectory = "stable"
            concerns = []
            lower = result.lower()
            if "degrading" in lower:
                trajectory = "degrading"
            elif "improving" in lower:
                trajectory = "improving"
            if "concern:" in lower:
                concern_part = result.split("oncern:")[-1].strip().rstrip(".")
                if concern_part and concern_part.lower() != "none":
                    concerns.append(concern_part)
            self._buffer.add_evaluation(trajectory, concerns)
            log.debug("Evaluative: %s %s", trajectory, concerns)
            await self._write_visual_observation(snapshot)
            if trajectory == "degrading":
                self._pending_impingements.append(
                    Impingement(
                        timestamp=time.time(),
                        source="dmn.evaluative",
                        type=ImpingementType.SALIENCE_INTEGRATION,
                        strength=0.6,
                        content={"trajectory": trajectory, "concerns": concerns},
                        context={"stimmung_stance": stimmung.get("stance", "unknown")},
                    )
                )

    async def _consolidation_tick(self) -> None:
        input_text = self._buffer.get_consolidation_input()
        if not input_text:
            return
        if self._ollama_breaker.allow_request():
            summary = await _ollama_generate(input_text, CONSOLIDATION_SYSTEM)
            if summary:
                self._ollama_breaker.record_success()
                self._degradation_emitted = False
            else:
                self._ollama_breaker.record_failure()
                self._check_ollama_degradation()
                summary = ""
        else:
            summary = ""
        if summary:
            self._buffer.set_retentional_summary(summary)
            pruned = self._buffer.prune_consolidated()
            log.info(
                "Consolidated %d observations into summary, pruned %d",
                len(input_text.split("\n")),
                pruned,
            )
