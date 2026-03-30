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
from typing import Any

log = logging.getLogger("reverie.actuation")

IMAGINATION_CURRENT = Path("/dev/shm/hapax-imagination/current.json")
STIMMUNG_STATE = Path("/dev/shm/hapax-stimmung/state.json")
UNIFORMS_FILE = Path("/dev/shm/hapax-imagination/pipeline/uniforms.json")
VISUAL_CHAIN_STATE = Path("/dev/shm/hapax-visual/visual-chain-state.json")

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
        from agents.effect_graph.capability import ShaderGraphCapability
        from agents.reverie.governance import build_default_veto_chain, guest_reduction_factor
        from agents.visual_chain import VisualChainCapability

        self._shader_cap = ShaderGraphCapability()
        self._visual_chain = VisualChainCapability(decay_rate=0.02)
        self._veto_chain = build_default_veto_chain()
        self._guest_reduction = guest_reduction_factor
        self._last_tick = time.monotonic()
        self._tick_count = 0

    @property
    def shader_capability(self) -> Any:
        return self._shader_cap

    @property
    def visual_chain(self) -> Any:
        return self._visual_chain

    async def tick(self) -> None:
        """One actuation cycle."""
        now = time.monotonic()
        dt = now - self._last_tick
        self._last_tick = now
        self._tick_count += 1

        # 0. Governance gate — check vetoes before any actuation
        from agents.reverie.governance import read_consent_phase

        stimmung = self._read_stimmung()
        consent_phase = read_consent_phase()
        gov_ctx = {
            "consent_phase": consent_phase,
            "stance": stimmung.get("stance", "nominal") if stimmung else "nominal",
        }
        allowed, reason = self._veto_chain.evaluate(gov_ctx)
        if not allowed:
            if self._tick_count % 30 == 1:  # log once per 30s
                log.info("Visual actuation vetoed: %s", reason)
            self._write_uniforms(None, stimmung)  # write minimal uniforms
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

        # 3. Read imagination state
        imagination = self._read_imagination()

        # 4. Read stimmung state
        stimmung = self._read_stimmung()

        # 5. Apply imagination dimensions to visual chain
        if imagination:
            dims = imagination.get("dimensions", {})
            for dim_name, level in dims.items():
                full_name = f"visual_chain.{dim_name}"
                if full_name in self._visual_chain._levels:
                    # Imagination dimensions set a floor — don't override higher impingement levels
                    current = self._visual_chain.get_dimension_level(full_name)
                    salience = imagination.get("salience", 0.0)
                    target = level * salience  # scale by fragment salience
                    if target > current:
                        self._visual_chain._levels[full_name] = target

        # 6. Apply guest reduction to all chain levels
        if reduction < 1.0:
            for name in self._visual_chain._levels:
                self._visual_chain._levels[name] *= reduction

        # 7. Write visual chain state (for Rust StateReader)
        self._visual_chain.write_state()

        # 8. Write merged uniforms
        self._write_uniforms(imagination, stimmung)

    def _apply_shader_impingement(self, imp: Any) -> None:
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

    def _read_imagination(self) -> dict[str, Any] | None:
        """Read current imagination fragment from SHM."""
        try:
            if IMAGINATION_CURRENT.exists():
                return json.loads(IMAGINATION_CURRENT.read_text())
        except (OSError, json.JSONDecodeError):
            pass
        return None

    def _read_stimmung(self) -> dict[str, Any] | None:
        """Read stimmung state from SHM."""
        try:
            if STIMMUNG_STATE.exists():
                return json.loads(STIMMUNG_STATE.read_text())
        except (OSError, json.JSONDecodeError):
            pass
        return None

    def _write_uniforms(
        self,
        imagination: dict[str, Any] | None,
        stimmung: dict[str, Any] | None,
    ) -> None:
        """Compute and write merged uniforms to pipeline/uniforms.json."""
        material = "water"
        salience = 0.0
        if imagination:
            material = imagination.get("material", "water")
            salience = imagination.get("salience", 0.0)

        material_val = float(MATERIAL_MAP.get(material, 0))

        # Visual chain param deltas (additive on stimmung baseline)
        chain_params = self._visual_chain.compute_param_deltas()

        # Build uniforms dict consumed by Rust DynamicPipeline
        uniforms: dict[str, Any] = {
            "custom": [material_val],
            "slot_opacities": [salience, 0.0, 0.0, 0.0],
        }

        # Add chain-derived params as node.param overrides
        for key, value in chain_params.items():
            uniforms[key] = value

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
