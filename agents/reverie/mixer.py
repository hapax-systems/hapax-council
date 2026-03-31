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

        self._pipeline = self._init_pipeline()

    @staticmethod
    def _init_pipeline():
        from agents._affordance import CapabilityRecord
        from agents._affordance_pipeline import AffordancePipeline

        p = AffordancePipeline()
        for n, d in [
            ("shader_graph", "Activate shader graph effects from imagination"),
            ("visual_chain", "Modulate visual chain from stimmung/evaluative"),
            ("fortress_visual_response", "Visual pipeline for fortress crises"),
        ]:
            p.index_capability(CapabilityRecord(name=n, description=d, daemon="reverie"))
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

        # 4. Decay visual chain dimensions
        self._visual_chain.decay(dt)

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

        # 9. Write cross-modal output
        current_salience = float(imagination.get("salience", 0.0)) if imagination else 0.0
        content_density = len(imagination.get("content_references", [])) if imagination else 0
        self._write_visual_salience(salience=current_salience, content_density=content_density)

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
            type=ImpingementType.SIGNAL,
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
    ) -> None:
        """Write visual salience for Daimonion cross-modal coupling."""
        p = path or VISUAL_SALIENCE_FILE
        data = {
            "source": "reverie",
            "timestamp": time.time(),
            "signals": {
                "salience": salience,
                "content_density": content_density,
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

    # --- Actuation methods (inherited from ReverieActuationLoop) ---

    _SLOT_CENTERS = {0: (0.4, 0.4), 1: (0.6, 0.4), 2: (0.4, 0.6), 3: (0.6, 0.6)}

    def _update_trace(self, imagination: dict | None, dt: float) -> None:
        current_salience = float(imagination.get("salience", 0.0)) if imagination else 0.0
        if self._last_salience > 0.2 and current_salience < self._last_salience * 0.5:
            self._trace_strength = min(1.0, self._last_salience)
            self._trace_radius = 0.3 + self._last_salience * 0.2
            slot_idx = 0
            if imagination:
                refs = imagination.get("content_references", [])
                if isinstance(refs, list) and refs:
                    slot_idx = 0
            self._trace_center = self._SLOT_CENTERS.get(slot_idx, (0.5, 0.5))
            log.info(
                "Trace activated: strength=%.2f radius=%.2f center=%s",
                self._trace_strength,
                self._trace_radius,
                self._trace_center,
            )
        if self._trace_strength > 0:
            self._trace_strength = max(0.0, self._trace_strength - self._trace_decay_rate * dt)
        self._last_salience = current_salience

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
