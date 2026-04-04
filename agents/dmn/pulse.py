"""DMN pulse engine — multi-rate tick loop with Ollama inference."""

from __future__ import annotations

import logging
import time

from agents._circuit_breaker import CircuitBreaker
from agents._impingement import Impingement, ImpingementType
from agents.dmn.buffer import DMNBuffer
from agents.dmn.ollama import (
    CONSOLIDATION_SYSTEM,
    EVALUATIVE_SYSTEM,
    SENSORY_SYSTEM,
    _format_sensor_prompt,
    _tabby_fast,
    collect_thinking,
    start_thinking,
)
from agents.dmn.sensor import read_all
from shared.control_signal import ControlSignal, publish_health

log = logging.getLogger("dmn.pulse")

SENSORY_TICK_S = 5.0
EVALUATIVE_TICK_S = 30.0
CONSOLIDATION_TICK_S = 180.0


class DMNPulse:
    """Multi-rate DMN pulse engine."""

    # Stimmung stance → tick rate multiplier (higher = slower)
    _STANCE_RATE_MULTIPLIERS: dict[str, float] = {
        "critical": 4.0,
        "degraded": 2.0,
        "cautious": 1.5,
        "nominal": 1.0,
    }

    def __init__(self, buffer: DMNBuffer) -> None:
        self._buffer = buffer
        self._last_sensory = 0.0
        self._last_evaluative = 0.0
        self._last_consolidation = 0.0
        self._prior_snapshot: dict | None = None
        self._tpn_active = False
        self._last_stance: str = "nominal"
        self._pending_impingements: list[Impingement] = []
        self._ollama_breaker = CircuitBreaker("ollama", failure_threshold=5, cooldown_s=30.0)
        self._degradation_emitted = False
        self._starvation_last_emitted: dict[str, float] = {}
        self._fortress_acted_on: dict[str, float] = {}
        # Control law state
        self._cl_errors = 0
        self._cl_ok = 0
        self._cl_degraded = False
        self._cl_original_sensory_tick = SENSORY_TICK_S
        # Exploration escalation state
        self._exploration_targets: list[str] = []
        self._boredom_window: list[tuple[float, str]] = []
        # Own exploration signal (spec §8: kappa=0.02, T_patience=180s)
        from shared.exploration_tracker import ExplorationTrackerBundle

        self._exploration_tracker = ExplorationTrackerBundle(
            component="dmn_pulse",
            edges=["observation_quality", "evaluative_trajectory"],
            traces=["sensor_freshness", "stance_value"],
            neighbors=["imagination", "stimmung"],
            kappa=0.02,
            t_patience=180.0,
            sigma_explore=0.15,
        )
        self._prev_obs_quality: float = 1.0

    def receive_exploration_impingement(self, imp: Impingement) -> None:
        """Receive boredom/curiosity impingement for escalation processing."""
        import time as _time

        if imp.type == ImpingementType.BOREDOM:
            self._exploration_targets.append(imp.source)
            self._boredom_window.append((_time.time(), imp.source))
            cutoff = _time.time() - 60.0
            self._boredom_window = [(t, s) for t, s in self._boredom_window if t > cutoff]

    def exploration_level(self) -> int:
        """Current escalation: 0=none, 1=single-component, 2=multi-component, 3=sustained."""
        if not self._boredom_window:
            return 0
        unique_sources = {s for _, s in self._boredom_window}
        if len(unique_sources) >= 3:
            return 2
        return 1

    @property
    def last_exploration_deficit(self) -> float:
        """Most recent aggregate exploration deficit (0-1)."""
        return getattr(self, "_last_exploration_deficit", 0.0)

    def _read_exploration_deficit(self) -> float:
        """Read all ExplorationSignals and compute aggregate deficit."""
        try:
            from shared.exploration_writer import ExplorationReader

            reader = ExplorationReader()
            signals = reader.read_all()
            if not signals:
                return 0.0
            # Top-k aggregation: worst-case components drive deficit
            # PCT: reorganization pressure = intrinsic error (boredom)
            # Curiosity modulates exploration MODE, not deficit magnitude
            boredom = sorted(
                (s.get("boredom_index", 0.0) for s in signals.values()),
                reverse=True,
            )
            k = max(3, len(boredom) // 3)
            return max(0.0, min(1.0, sum(boredom[:k]) / k))
        except Exception:
            return 0.0

    def set_tpn_active(self, active: bool) -> None:
        self._tpn_active = active

    def _get_stance_rate_multiplier(self) -> float:
        """Return tick rate multiplier based on stimmung stance."""
        return self._STANCE_RATE_MULTIPLIERS.get(self._last_stance, 1.0)

    async def tick(self) -> None:
        now = time.monotonic()
        tpn_mult = 2.0 if self._tpn_active else 1.0
        stimmung_mult = self._get_stance_rate_multiplier()
        sensory_rate = SENSORY_TICK_S * tpn_mult * stimmung_mult
        evaluative_rate = EVALUATIVE_TICK_S * tpn_mult * stimmung_mult
        snapshot = read_all()

        # Read exploration signals and compute aggregate deficit
        self._last_exploration_deficit = self._read_exploration_deficit()

        # Extract stimmung stance for rate modulation
        stimmung = snapshot.get("stimmung", {})
        if isinstance(stimmung, dict) and "stance" in stimmung:
            self._last_stance = stimmung["stance"]
        vs = snapshot.get("visual_surface", {})
        if vs.get("imagination_narrative"):
            self._buffer.set_imagination_context(
                salience=vs.get("imagination_salience", 0.0),
                material=vs.get("imagination_material", "void"),
                narrative=vs["imagination_narrative"],
            )
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

        # Exploration signal: track own observation quality + stance stability
        obs_quality = 1.0 if snapshot.get("perception") else 0.0
        self._exploration_tracker.feed_habituation(
            "observation_quality", obs_quality, self._prev_obs_quality, 0.2
        )
        self._exploration_tracker.feed_interest("sensor_freshness", obs_quality, 0.3)
        stance_val = {
            "nominal": 0.0,
            "seeking": 0.1,
            "cautious": 0.3,
            "degraded": 0.6,
            "critical": 1.0,
        }.get(self._last_stance, 0.0)
        self._exploration_tracker.feed_interest("stance_value", stance_val, 0.2)
        self._exploration_tracker.feed_error(1.0 - obs_quality)
        self._exploration_tracker.compute_and_publish()
        self._prev_obs_quality = obs_quality

        self._prior_snapshot = snapshot

    async def _sensory_tick(self, snapshot: dict) -> None:
        deltas = self._buffer.format_delta_context(self._prior_snapshot, snapshot)
        if not deltas and self._prior_snapshot is not None:
            self._buffer.add_observation("stable")
            return
        prompt = _format_sensor_prompt(snapshot, deltas)
        if self._ollama_breaker.allow_request():
            observation = await _tabby_fast(prompt, SENSORY_SYSTEM)
            if observation:
                self._ollama_breaker.record_success()
                self._degradation_emitted = False
            else:
                self._ollama_breaker.record_failure()
                self._check_ollama_degradation()
                observation = ""
        else:
            observation = ""
        observation_produced = bool(observation)
        if observation:
            self._buffer.add_observation(observation, deltas, raw_sensor=prompt)
            log.debug("Sensory: %s", observation[:80])
        else:
            self._buffer.add_observation(prompt[:100], deltas, raw_sensor=prompt)
        publish_health(
            ControlSignal(
                component="dmn",
                reference=1.0,
                perception=1.0 if observation_produced else 0.0,
            )
        )

        # Control law: error drives behavior
        if not observation_produced:
            self._cl_errors += 1
            self._cl_ok = 0
        else:
            self._cl_errors = 0
            self._cl_ok += 1

        if self._cl_errors >= 3 and not self._cl_degraded:
            global SENSORY_TICK_S
            self._cl_original_sensory_tick = SENSORY_TICK_S
            SENSORY_TICK_S = SENSORY_TICK_S * 2.0
            self._cl_degraded = True
            log.warning("Control law [dmn]: degrading — doubling sensory tick interval")

        if self._cl_ok >= 5 and self._cl_degraded:
            SENSORY_TICK_S = self._cl_original_sensory_tick
            self._cl_degraded = False
            log.info("Control law [dmn]: recovered")

    def _recently_acted(self, metric: str) -> bool:
        return time.time() - self._fortress_acted_on.get(metric, 0.0) <= 300

    def _check_absolute_thresholds(self, snapshot: dict) -> None:
        fortress = snapshot.get("fortress")
        if fortress:
            pop = fortress.get("population", 0)
            drink = fortress.get("drink", 0)
            if pop > 0 and drink < pop * 2 and not self._recently_acted("drink_per_capita"):
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
            if pop > 0 and pop < 3 and not self._recently_acted("extinction_risk"):
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
        if stimmung.get("stance") == "critical" and not self._recently_acted("stimmung_critical"):
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

    def consume_fortress_feedback(self, impingements: list[Impingement]) -> None:
        """Record fortress action timestamps to suppress re-emission."""
        for imp in impingements:
            if imp.source == "fortress.action_taken":
                metric = imp.content.get("trigger_metric", "")
                if metric:
                    self._fortress_acted_on[metric] = time.time()

    def drain_impingements(self) -> list[Impingement]:
        pending = self._pending_impingements[:]
        self._pending_impingements.clear()
        return pending

    def _read_frame_b64(self) -> str:
        """Read the Reverie visual frame as base64, if fresh (<30s)."""
        import base64
        from pathlib import Path

        frame_path = Path("/dev/shm/hapax-visual/frame.jpg")
        try:
            if not frame_path.exists():
                return ""
            age = time.time() - frame_path.stat().st_mtime
            if age > 30.0:
                return ""
            return base64.b64encode(frame_path.read_bytes()).decode()
        except OSError:
            return ""

    async def _evaluative_tick(self, snapshot: dict) -> None:
        self._check_absolute_thresholds(snapshot)

        # Collect previous thinking result if ready
        result = collect_thinking("evaluative")
        if result:
            self._ollama_breaker.record_success()
            self._degradation_emitted = False
            self._process_evaluative_result(result, snapshot)
        elif result == "":
            self._ollama_breaker.record_failure()
            self._check_ollama_degradation()

        # Fire new thinking request (multimodal if frame available)
        deltas = self._buffer.format_delta_context(self._prior_snapshot, snapshot)
        stimmung = snapshot.get("stimmung", {})
        if not deltas and stimmung.get("stance") == "nominal":
            return
        frame_b64 = self._read_frame_b64()
        prompt = _format_sensor_prompt(snapshot, deltas)
        if self._ollama_breaker.allow_request():
            start_thinking("evaluative", prompt, EVALUATIVE_SYSTEM, frame_b64=frame_b64)

    def _write_visual_observation(self, result: str) -> None:
        """Write the evaluative result as visual observation for reverberation."""
        from pathlib import Path

        obs_dir = Path("/dev/shm/hapax-vision")
        try:
            obs_dir.mkdir(parents=True, exist_ok=True)
            import json

            tmp = obs_dir / "observation.tmp"
            tmp.write_text(result, encoding="utf-8")
            tmp.rename(obs_dir / "observation.txt")
            status = {"timestamp": time.time(), "length": len(result), "source": "dmn"}
            tmp_s = obs_dir / "status.tmp"
            tmp_s.write_text(json.dumps(status), encoding="utf-8")
            tmp_s.rename(obs_dir / "status.json")
        except OSError:
            pass

    def _process_evaluative_result(self, result: str, snapshot: dict) -> None:
        # Extract visual description for reverberation loop
        visual_desc = ""
        lower = result.lower()
        if "visual:" in lower:
            vis_part = result.split("isual:")[-1]
            # Take until "Trajectory:" or end
            if "rajectory:" in vis_part:
                visual_desc = vis_part.split("rajectory:")[0].strip().rstrip(".")
            else:
                visual_desc = vis_part.strip()
            if visual_desc.lower() == "none":
                visual_desc = ""
        if visual_desc:
            self._write_visual_observation(visual_desc)

        trajectory = "stable"
        concerns: list[str] = []
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
        stimmung = snapshot.get("stimmung", {})
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
        # Collect previous thinking result if ready
        summary = collect_thinking("consolidation")
        if summary:
            self._ollama_breaker.record_success()
            self._degradation_emitted = False
            self._buffer.set_retentional_summary(summary)
            pruned = self._buffer.prune_consolidated()
            log.info("Consolidated into summary, pruned %d", pruned)
        elif summary == "":
            self._ollama_breaker.record_failure()
            self._check_ollama_degradation()

        # Fire new thinking request
        input_text = self._buffer.get_consolidation_input()
        if not input_text:
            return
        if self._ollama_breaker.allow_request():
            start_thinking("consolidation", input_text, CONSOLIDATION_SYSTEM)
