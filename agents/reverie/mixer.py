"""Reverie mixer — visual expression orchestrator.

Subsumes ReverieActuationLoop. Central orchestrator for the Reverie
compositing engine. Consumes impingements, manages visual chain,
handles cross-modal coupling with Daimonion, writes content manifests.

Tick cadence: 1s (governance rate, not frame rate).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from shared.control_signal import ControlSignal, publish_health

if TYPE_CHECKING:
    from agents._impingement import Impingement

log = logging.getLogger("reverie.mixer")

ACOUSTIC_IMPULSE_FILE = Path("/dev/shm/hapax-visual/acoustic-impulse.json")
VISUAL_SALIENCE_FILE = Path("/dev/shm/hapax-dmn/visual-salience.json")


class ReverieMixer:
    """Visual expression orchestrator — the DMN is the VJ.

    Each tick:
    1. Read cross-modal input (acoustic impulse from Daimonion)
    2. Consume pending impingements from capabilities
    3. Decay all dimensions (compressor release envelope)
    4. Read imagination state (material, salience, dimensions)
    5. Read stimmung state (stance, color_warmth)
    6. Compute merged uniforms and write to SHM
    7. Update trace state (Amendment 2: dwelling)
    8. Write visual chain state for Rust StateReader
    9. Write cross-modal output (visual salience for Daimonion)
    """

    def __init__(self) -> None:
        from agents._context import ContextAssembler
        from agents.effect_graph.capability import ShaderGraphCapability
        from agents.reverie.governance import build_reverie_veto_chain, guest_reduction_factor
        from agents.visual_chain import VisualChainCapability

        self._shader_cap = ShaderGraphCapability()
        self._visual_chain = VisualChainCapability(decay_rate=0.02)
        self._veto_chain = build_reverie_veto_chain()
        self._guest_reduction = guest_reduction_factor
        self._context = ContextAssembler()
        self._last_tick = time.monotonic()
        self._tick_count = 0

        # Trace state (Amendment 2: dwelling and trace)
        self._trace_center: tuple[float, float] = (0.5, 0.5)
        self._trace_radius = 0.0
        self._trace_strength = 0.0
        self._trace_decay_rate = 0.15
        self._last_salience = 0.0

        # Cross-modal refractory damping (500ms)
        self._last_acoustic_inject = 0.0
        self._refractory_ms = 500
        # Satellite recruitment
        from agents.reverie._satellites import SatelliteManager
        from agents.reverie.bootstrap import load_vocabulary

        self._satellites = SatelliteManager(load_vocabulary(), decay_rate=0.02)
        from agents.reverie._content_capabilities import ContentCapabilityRouter

        self._content_router = ContentCapabilityRouter()
        self._pipeline = self._init_pipeline()
        # Exploration tracking (spec §8: kappa=0.015, T_patience=240s)
        from shared.exploration_tracker import ExplorationTrackerBundle

        self._exploration = ExplorationTrackerBundle(
            component="visual_chain",
            edges=["salience_input", "technique_selection"],
            traces=["visual_salience", "imagination_material"],
            neighbors=["imagination", "stimmung"],
            kappa=0.015,
            t_patience=240.0,
            sigma_explore=0.12,
        )
        self._prev_salience_input: float = 0.0
        self._recruited_content_count: int = 0

    @staticmethod
    def _init_pipeline():
        from agents.reverie._affordances import build_reverie_pipeline

        p = build_reverie_pipeline()
        p.load_activation_state()
        return p

    @property
    def pipeline(self):
        return self._pipeline

    @property
    def shader_capability(self):
        return self._shader_cap

    @property
    def visual_chain(self):
        return self._visual_chain

    async def tick(self) -> None:
        """One mixer cycle."""
        now = time.monotonic()
        dt = now - self._last_tick
        self._last_tick = now
        self._tick_count += 1

        self._recruited_content_count = 0

        # 1. Read cross-modal input
        acoustic = self._read_acoustic_impulse()
        if acoustic:
            self._inject_acoustic_impingement(acoustic)

        # 2. Governance check
        from agents._capability import SystemContext
        from agents.reverie._uniforms import write_uniforms
        from agents.reverie.governance import read_consent_phase

        ctx = self._context.assemble()
        consent_phase = read_consent_phase()
        gov_ctx = SystemContext(
            stimmung_stance=ctx.stimmung_stance,
            consent_state={"phase": consent_phase},
            guest_present=consent_phase not in ("no_guest",),
        )
        result = self._veto_chain.evaluate(gov_ctx)
        if not result.allowed:
            if self._tick_count % 30 == 1:
                log.info(
                    "Mixer vetoed: denied_by=%s axiom_ids=%s",
                    result.denied_by,
                    result.axiom_ids,
                )
            write_uniforms(
                None,
                ctx.stimmung_raw,
                self._visual_chain,
                self._trace_strength,
                self._trace_center,
                self._trace_radius,
            )
            return

        reduction = self._guest_reduction(consent_phase)

        # 3. Consume shader graph impingements
        while self._shader_cap.has_pending():
            imp = self._shader_cap.consume_pending()
            if imp is None:
                break
            self._apply_shader_impingement(imp)

        # 4. Decay visual chain dimensions + satellites
        self._visual_chain.decay(dt)
        self._satellites.decay(dt)
        self._satellites.maybe_rebuild()

        # 5. Read imagination + stimmung from context
        imagination = ctx.imagination_fragments[0] if ctx.imagination_fragments else None
        stimmung = ctx.stimmung_raw

        # 6. Update trace (Amendment 2)
        self._update_trace(imagination, dt)

        # 7. Write visual chain state
        self._visual_chain.write_state()

        # 8. Write merged uniforms
        write_uniforms(
            imagination,
            stimmung,
            self._visual_chain,
            self._trace_strength,
            self._trace_center,
            self._trace_radius,
            reduction,
        )

        # 8b. Chronicle: detect param shifts (dead zone 0.05)
        try:
            from shared.chronicle import ChronicleEvent, current_otel_ids
            from shared.chronicle import record as chronicle_record

            current_deltas = self._visual_chain.compute_param_deltas()
            _prev = getattr(self, "_prev_chronicle_params", {})
            changed = {}
            for k, v in current_deltas.items():
                if isinstance(v, (int, float)) and abs(v - _prev.get(k, 0.0)) > 0.01:
                    changed[k] = round(v, 4)
            if changed:
                _tid, _sid = current_otel_ids()
                chronicle_record(
                    ChronicleEvent(
                        ts=time.time(),
                        trace_id=_tid,
                        span_id=_sid,
                        parent_span_id=None,
                        source="visual",
                        event_type="params.shifted",
                        payload={"changed_params": changed},
                    )
                )
            self._prev_chronicle_params = {
                k: v for k, v in current_deltas.items() if isinstance(v, (int, float))
            }
        except Exception:
            pass

        # 9. Write cross-modal output
        current_salience = float(imagination.get("salience", 0.0)) if imagination else 0.0
        content_density = self._recruited_content_count
        n_sat = self._satellites.active_count
        self._write_visual_salience(
            salience=current_salience, content_density=content_density, satellites_active=n_sat
        )

        # 10. ControlSignal health
        publish_health(ControlSignal(component="reverie", reference=1.0, perception=1.0))

        # 11. Exploration signal: track visual salience habituation
        self._exploration.feed_habituation(
            "salience_input", current_salience, self._prev_salience_input, 0.2
        )
        technique = imagination.get("material", "void") if imagination else "void"
        self._exploration.feed_habituation(
            "technique_selection", hash(technique) % 100 / 100.0, 0.0, 0.3
        )
        self._exploration.feed_interest("visual_salience", current_salience, 0.2)
        self._exploration.feed_interest("imagination_material", hash(technique) % 100 / 100.0, 0.3)
        self._exploration.feed_error(0.0 if current_salience > 0.1 else 0.5)
        sig = self._exploration.compute_and_publish()
        self._prev_salience_input = current_salience

        # 12. Control law: modulate visual expression when bored
        action = self._exploration.evaluate_action(sig, sigma_explore=0.12)
        if action.mode in ("directed", "undirected"):
            # Bored → increase diffusion and temporal distortion (contemplative mode)
            from shared.impingement import Impingement, ImpingementType

            boredom_imp = Impingement(
                timestamp=time.time(),
                source="exploration.boredom",
                type=ImpingementType.BOREDOM,
                strength=sig.boredom_index,
                content={"mode": action.mode},
            )
            self._visual_chain.activate_dimension("visual_chain.diffusion", boredom_imp, 0.3)
            self._visual_chain.activate_dimension(
                "visual_chain.temporal_distortion", boredom_imp, 0.2
            )

    def dispatch_impingement(self, imp: Impingement) -> None:
        """Route impingement through affordance pipeline. Recruits satellites for node.* matches."""
        candidates = self._pipeline.select(imp)
        if candidates:
            t = candidates[0]
            log.info("match: %s → %s (%.2f)", imp.source[:30], t.capability_name, t.combined)
        for c in candidates:
            name = c.capability_name
            if name.startswith("node."):
                self._satellites.recruit(name.removeprefix("node."), c.combined)
                self._chronicle_technique(name, c.combined)
                # Recruited candidates already survived pipeline threshold (biased
                # competition). Recording activation as success prevents Thompson
                # death spiral for cold-start affordances while the combined score
                # determines response intensity via slot opacity.
                # Context enables Hebbian association learning (source → capability).
                ctx = {"source": imp.source, "metric": imp.content.get("metric", "")}
                self._pipeline.record_outcome(name, success=True, context=ctx)
                self._apply_shader_impingement(imp)
                break
            elif name.startswith("content."):
                narrative = imp.content.get("narrative", "")
                if self._content_router.camera_for_affordance(name):
                    self._content_router.activate_camera(name, c.combined)
                else:
                    self._content_router.activate_content(name, narrative, c.combined)
                self._recruited_content_count += 1
                self._chronicle_technique(name, c.combined)
                # Same rationale as node.*: pipeline selection IS the quality gate.
                # Activation level (c.combined) drives opacity, not learning signal.
                ctx = {"source": imp.source, "metric": imp.content.get("metric", "")}
                self._pipeline.record_outcome(name, success=True, context=ctx)
                self._apply_shader_impingement(imp)
                break
            elif name.startswith("knowledge."):
                narrative = imp.content.get("narrative", "")
                if self._content_router.activate_content(name, narrative, c.combined):
                    self._recruited_content_count += 1
                self._chronicle_technique(name, c.combined)
                ctx = {"source": imp.source, "metric": imp.content.get("metric", "")}
                self._pipeline.record_outcome(name, success=True, context=ctx)
                break
            elif name.startswith("space."):
                if self._content_router.camera_for_affordance(name):
                    self._content_router.activate_camera(name, c.combined)
                    self._chronicle_technique(name, c.combined)
                    ctx = {"source": imp.source, "metric": imp.content.get("metric", "")}
                    self._pipeline.record_outcome(name, success=True, context=ctx)
                # Non-camera space.* affordances (ir_presence, posture, etc.) are
                # perception signals — they inform the pipeline's learning but don't
                # produce visual output. Break to prevent fall-through to lower-ranked
                # candidates (preserves biased competition).
                break
            elif name == "shader_graph":
                self._shader_cap.activate(imp, imp.strength)
                self._apply_shader_impingement(imp)
            elif name == "visual_chain":
                self._visual_chain.activate(imp, c.combined)
            elif name == "fortress_visual_response":
                s = imp.strength
                self._visual_chain.activate_dimension("visual_chain.tension", imp, s * 0.8)
                self._visual_chain.activate_dimension("visual_chain.degradation", imp, s * 0.6)

    # --- Chronicle integration ---

    def _chronicle_technique(self, name: str, confidence: float) -> None:
        """Record technique activation to chronicle."""
        try:
            from shared.chronicle import ChronicleEvent, current_otel_ids
            from shared.chronicle import record as chronicle_record

            _tid, _sid = current_otel_ids()
            chronicle_record(
                ChronicleEvent(
                    ts=time.time(),
                    trace_id=_tid,
                    span_id=_sid,
                    parent_span_id=None,
                    source="visual",
                    event_type="technique.activated",
                    payload={"technique_name": name, "confidence": round(confidence, 3)},
                )
            )
        except Exception:
            pass

    # --- Cross-modal coupling ---

    def _read_acoustic_impulse(self, path: Path | None = None) -> dict | None:
        """Read acoustic impulse from Daimonion."""
        p = path or ACOUSTIC_IMPULSE_FILE
        try:
            data = json.loads(p.read_text())
            return data if data.get("source") == "daimonion" else None
        except (OSError, json.JSONDecodeError):
            return None

    def _inject_acoustic_impingement(self, acoustic: dict) -> None:
        """Convert acoustic impulse to impingement with refractory damping."""
        now = time.monotonic()
        if (now - self._last_acoustic_inject) * 1000 < self._refractory_ms:
            return
        self._last_acoustic_inject = now

        from agents._impingement import Impingement, ImpingementType

        signals = acoustic.get("signals", {})
        energy = signals.get("energy", 0.0)
        if energy < 0.1:
            return

        imp = Impingement(
            source="daimonion.acoustic",
            type=ImpingementType.SALIENCE_INTEGRATION,
            timestamp=time.time(),
            strength=min(1.0, energy),
            content={
                "metric": "acoustic_impulse",
                "dimensions": {
                    "intensity": energy * 0.5,
                    "temporal_distortion": energy * 0.3,
                },
            },
        )
        self._apply_shader_impingement(imp)
        log.debug("Injected acoustic impingement: energy=%.2f", energy)

    def _write_visual_salience(
        self,
        path: Path | None = None,
        salience: float = 0.0,
        content_density: int = 0,
        satellites_active: int = 0,
    ) -> None:
        """Write visual salience for Daimonion cross-modal coupling."""
        p = path or VISUAL_SALIENCE_FILE
        data = {
            "source": "reverie",
            "timestamp": time.time(),
            "signals": {
                "salience": salience,
                "content_density": content_density,
                "satellites_active": satellites_active,
                "regime_shift": False,
            },
        }
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            tmp.rename(p)
        except OSError:
            log.debug("Failed to write visual salience", exc_info=True)

    # --- Actuation methods ---

    def _update_trace(self, imagination: dict | None, dt: float) -> None:
        from agents.reverie._uniforms import update_trace

        self._last_salience, self._trace_strength, self._trace_radius, self._trace_center = (
            update_trace(
                imagination,
                self._last_salience,
                self._trace_strength,
                self._trace_radius,
                self._trace_center,
                self._trace_decay_rate,
                dt,
            )
        )

    def _apply_shader_impingement(self, imp: Impingement) -> None:
        content = imp.content or {}
        strength = imp.strength
        dims = content.get("dimensions", {})
        if dims:
            for dim_name, level in dims.items():
                self._visual_chain.activate_dimension(
                    f"visual_chain.{dim_name}", imp, level * strength
                )
        else:
            self._visual_chain.activate_dimension("visual_chain.intensity", imp, strength * 0.6)
            self._visual_chain.activate_dimension("visual_chain.coherence", imp, strength * 0.4)
        log.debug("Applied shader impingement: source=%s strength=%.2f", imp.source, strength)
