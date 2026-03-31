"""DMN pulse engine — multi-rate tick loop with Ollama inference."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

from agents._circuit_breaker import CircuitBreaker
from agents._impingement import Impingement, ImpingementType
from agents.dmn.buffer import DMNBuffer
from agents.dmn.sensor import read_all
from agents.dmn.vision import _generate_visual_observation

VISUAL_OBSERVATION_PATH = Path("/dev/shm/hapax-dmn/visual-observation.txt")

log = logging.getLogger("dmn.pulse")

SENSORY_TICK_S = 5.0
EVALUATIVE_TICK_S = 30.0
CONSOLIDATION_TICK_S = 180.0

OLLAMA_URL = "http://localhost:11434/api/generate"
DMN_MODEL = "qwen3.5:4b"

SENSORY_SYSTEM = (
    "You are a continuous situation monitor. Report WHAT is happening in one sentence. "
    "Never explain WHY. Never evaluate quality. Never use abstract language. "
    "Format: one concrete sentence describing the current state."
)
EVALUATIVE_SYSTEM = (
    "You are a value trajectory assessor. Given the current state and what changed, "
    "report whether the situation is IMPROVING, DEGRADING, or STABLE. "
    "If degrading, state the specific concern in concrete terms (what is wrong, not why). "
    'Format: "Trajectory: [improving|degrading|stable]. Concern: [specific issue or none]" '
    "Never evaluate your own performance. Never use abstract language."
)
CONSOLIDATION_SYSTEM = (
    "Compress the following observations into one paragraph. "
    "Preserve: specific numbers, state changes, trends, anomalies. "
    "Discard: redundant stable readings, repeated values. "
    "Never interpret or evaluate. Just compress the facts."
)


async def _ollama_generate(prompt: str, system: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                OLLAMA_URL,
                json={
                    "model": DMN_MODEL,
                    "prompt": prompt,
                    "system": system,
                    "stream": False,
                    "options": {"num_predict": 100, "temperature": 0.3},
                },
            )
            if resp.status_code == 200:
                return resp.json().get("response", "").strip()
            log.warning("Ollama returned %d", resp.status_code)
            return ""
    except Exception as exc:
        log.debug("Ollama call failed: %s", exc)
        return ""


def _format_sensor_prompt(snapshot: dict, deltas: list[str]) -> str:
    parts = []
    p = snapshot.get("perception", {})
    parts.append(f"Activity: {p.get('activity', '?')}. Flow: {p.get('flow_score', 0):.1f}.")
    s = snapshot.get("stimmung", {})
    parts.append(f"Stimmung: {s.get('stance', '?')}. Stress: {s.get('operator_stress', 0):.2f}.")
    f = snapshot.get("fortress")
    if f:
        parts.append(
            f"Fortress {f.get('fortress_name', '?')}: pop={f.get('population')}, "
            f"food={f.get('food')}, drink={f.get('drink')}, "
            f"threats={f.get('threats')}, idle={f.get('idle')}."
        )
    w = snapshot.get("watch", {})
    if w.get("heart_rate", 0) > 0:
        parts.append(f"Heart rate: {w['heart_rate']} bpm.")
    if deltas:
        parts.append("Changes: " + "; ".join(deltas) + ".")
    return " ".join(parts)


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

    def set_tpn_active(self, active: bool) -> None:
        self._tpn_active = active

    async def tick(self) -> None:
        now = time.monotonic()
        sensory_rate = SENSORY_TICK_S * (2.0 if self._tpn_active else 1.0)
        evaluative_rate = EVALUATIVE_TICK_S * (2.0 if self._tpn_active else 1.0)
        snapshot = read_all()

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
