"""Reverie actuation loop — visual expression via impingement cascade.

Structural peer of Daimonion's actuation loop. Consumes impingements from
ShaderGraphCapability and VisualChainCapability, translates them into
shader uniform updates written to /dev/shm/hapax-imagination/pipeline/.

Tick cadence: 1s (governance rate, not frame rate). The Rust binary
interpolates smoothly between ticks via SmoothedParams, exactly like
TTS smoothly renders audio between LLM token arrivals.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents._impingement import Impingement
    from agents.effect_graph.capability import ShaderGraphCapability
    from agents.visual_chain import VisualChainCapability

log = logging.getLogger("reverie.actuation")

UNIFORMS_FILE = Path("/dev/shm/hapax-imagination/pipeline/uniforms.json")

MATERIAL_MAP = {"water": 0, "fire": 1, "earth": 2, "air": 3, "void": 4}


class ReverieActuationLoop:
    """Visual actuation — consumes impingements, writes uniforms.

    Operates at 1s tick cadence. Each tick:
    1. Consume pending impingements from capabilities
    2. Activate visual chain dimensions from impingement content
    3. Decay all dimensions (compressor release envelope)
    4. Read imagination state (material, salience, dimensions)
    5. Read stimmung state (stance, color_warmth)
    6. Compute merged uniforms and write to SHM
    7. Write visual chain state for Rust StateReader
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
        self._trace_center = (0.5, 0.5)
        self._trace_radius = 0.0
        self._trace_strength = 0.0
        self._trace_decay_rate = 0.15  # strength decays ~7s to zero
        self._last_salience = 0.0

    @property
    def shader_capability(self) -> ShaderGraphCapability:
        return self._shader_cap

    @property
    def visual_chain(self) -> VisualChainCapability:
        return self._visual_chain

    async def tick(self) -> None:
        """One actuation cycle."""
        now = time.monotonic()
        dt = now - self._last_tick
        self._last_tick = now
        self._tick_count += 1

        # 0. Assemble shared context (same snapshot for governance + actuation)
        from agents._capability import SystemContext
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
            if self._tick_count % 30 == 1:  # log once per 30s
                log.info(
                    "Visual actuation vetoed: denied_by=%s axiom_ids=%s",
                    result.denied_by,
                    result.axiom_ids,
                )
            self._write_uniforms(None, ctx.stimmung_raw)  # write minimal uniforms
            return

        # Guest reduction factor (0.6 when guest present, 1.0 when alone)
        reduction = self._guest_reduction(consent_phase)

        # 1. Consume shader graph impingements
        while self._shader_cap.has_pending():
            imp = self._shader_cap.consume_pending()
            if imp is None:
                break
            self._apply_shader_impingement(imp)

        # 2. Decay visual chain dimensions (compressor release)
        self._visual_chain.decay(dt)

        # 3. Read imagination state from shared context
        imagination = ctx.imagination_fragments[0] if ctx.imagination_fragments else None

        # 4. Stimmung from shared context
        stimmung = ctx.stimmung_raw

        # 5. Imagination's 9 expressive dimensions are handled by the Rust
        # StateReader (reads current.json directly, lerps at 60fps with 2s
        # time constant). The actuation loop does NOT override these — it
        # handles what StateReader doesn't: material, salience, trace, and
        # impingement-driven visual chain activations.

        # 6. Guest reduction applied at output time (see _write_uniforms)

        # 7. Update trace state (Amendment 2: dwelling and trace)
        self._update_trace(imagination, dt)

        # 8. Write visual chain state (for Rust StateReader)
        self._visual_chain.write_state()

        # 9. Write merged uniforms
        self._write_uniforms(imagination, stimmung, reduction)

    # Per-slot approximate centers (matches content_layer.wgsl immensity_entry directions)
    _SLOT_CENTERS = {0: (0.4, 0.4), 1: (0.6, 0.4), 2: (0.4, 0.6), 3: (0.6, 0.6)}

    def _update_trace(self, imagination: dict[str, object] | None, dt: float) -> None:
        """Update trace state for dwelling/trace effect (Bachelard Amendment 2).

        When content salience drops (fading out), the trace activates at the
        content's approximate position based on its slot index.
        """
        current_salience = float(imagination.get("salience", 0.0)) if imagination else 0.0

        # Detect salience drop → activate trace
        if self._last_salience > 0.2 and current_salience < self._last_salience * 0.5:
            self._trace_strength = min(1.0, self._last_salience)
            self._trace_radius = 0.3 + self._last_salience * 0.2

            # Approximate center from primary content slot
            slot_idx = 0
            if imagination:
                refs = imagination.get("content_references", [])
                if isinstance(refs, list) and len(refs) > 0:
                    slot_idx = 0  # primary (highest-salience) slot
            self._trace_center = self._SLOT_CENTERS.get(slot_idx, (0.5, 0.5))

            log.info(
                "Trace activated: strength=%.2f radius=%.2f center=%s (salience %.2f→%.2f)",
                self._trace_strength,
                self._trace_radius,
                self._trace_center,
                self._last_salience,
                current_salience,
            )

        # Decay trace strength over time
        if self._trace_strength > 0:
            self._trace_strength = max(0.0, self._trace_strength - self._trace_decay_rate * dt)

        self._last_salience = current_salience

    def _apply_shader_impingement(self, imp: Impingement) -> None:
        """Translate a shader graph impingement into visual chain activations."""
        content = imp.content or {}
        strength = imp.strength

        # If impingement carries dimension targets, apply them directly
        dims = content.get("dimensions", {})
        if dims:
            for dim_name, level in dims.items():
                full_name = f"visual_chain.{dim_name}"
                self._visual_chain.activate_dimension(full_name, imp, level * strength)
        else:
            # Generic impingement — boost intensity and coherence proportionally
            self._visual_chain.activate_dimension("visual_chain.intensity", imp, strength * 0.6)
            self._visual_chain.activate_dimension("visual_chain.coherence", imp, strength * 0.4)

        log.info(
            "Applied shader impingement: source=%s strength=%.2f",
            imp.source,
            strength,
        )

    # Imagination and stimmung state now read via shared ContextAssembler

    @staticmethod
    def _build_slot_opacities(
        imagination: dict[str, object] | None, fallback_salience: float
    ) -> list[float]:
        """Build slot opacities from content references or fallback to single-slot."""
        opacities = [0.0, 0.0, 0.0, 0.0]
        if not imagination:
            return opacities
        refs = imagination.get("content_references", [])
        if isinstance(refs, list) and refs:
            for i, ref in enumerate(refs[:4]):
                if isinstance(ref, dict):
                    opacities[i] = float(ref.get("salience", fallback_salience))
                else:
                    opacities[i] = fallback_salience
        elif fallback_salience > 0:
            opacities[0] = fallback_salience
        return opacities

    # in tick(), ensuring both systems see identical context at the same moment.

    def _write_uniforms(
        self,
        imagination: dict[str, object] | None,
        stimmung: dict[str, object] | None,
        reduction: float = 1.0,
    ) -> None:
        """Compute and write merged uniforms to pipeline/uniforms.json."""
        material = "water"
        salience = 0.0
        if imagination:
            material = str(imagination.get("material", "water"))
            salience = float(imagination.get("salience", 0.0))

        material_val = float(MATERIAL_MAP.get(material, 0))

        # Visual chain param deltas (additive on stimmung baseline)
        chain_params = self._visual_chain.compute_param_deltas()

        # Build uniforms dict consumed by Rust DynamicPipeline
        uniforms: dict[str, object] = {
            "custom": [material_val],
            "slot_opacities": self._build_slot_opacities(imagination, salience),
        }

        # Add chain-derived params as node.param overrides (with guest reduction)
        for key, value in chain_params.items():
            uniforms[key] = value * reduction if isinstance(value, (int, float)) else value

        # Add trace state for feedback shader (Amendment 2: dwelling)
        if self._trace_strength > 0:
            uniforms["fb.trace_center_x"] = self._trace_center[0]
            uniforms["fb.trace_center_y"] = self._trace_center[1]
            uniforms["fb.trace_radius"] = self._trace_radius
            uniforms["fb.trace_strength"] = self._trace_strength

        # Add stimmung-derived signals
        if stimmung:
            stance = stimmung.get("stance", "nominal")
            stance_map = {"nominal": 0.0, "cautious": 0.25, "degraded": 0.5, "critical": 1.0}
            uniforms["signal.stance"] = stance_map.get(stance, 0.0)
            uniforms["signal.color_warmth"] = stimmung.get("color_warmth", 0.5)

        try:
            UNIFORMS_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = UNIFORMS_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(uniforms))
            tmp.rename(UNIFORMS_FILE)
        except OSError:
            log.debug("Failed to write uniforms", exc_info=True)
