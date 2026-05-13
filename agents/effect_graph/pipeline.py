"""Slot-based GStreamer shader pipeline — assigns graph nodes to numbered slots."""

from __future__ import annotations

import logging
from typing import Any

from .compiler import ExecutionPlan
from .registry import ShaderRegistry

log = logging.getLogger(__name__)

PASSTHROUGH_SHADER = """#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
void main() { gl_FragColor = texture2D(tex, v_texcoord); }
"""

GL_FRAGMENT_SHADER = 0x8B30


class SlotPipeline:
    """Manages a fixed chain of N glshader slots with runtime shader hot-swap.

    Uses the ``create-shader`` signal to compile shaders on the GL thread,
    which is the only way to hot-swap shaders on a PLAYING pipeline.
    ``set_property("fragment", ...)`` is ignored after pipeline start.
    """

    def __init__(self, registry: ShaderRegistry, num_slots: int = 16) -> None:
        self._registry = registry
        self._num_slots = num_slots
        self._slots: list[Any] = []
        self._slot_assignments: list[str | None] = [None] * num_slots
        self._slot_base_params: list[dict[str, Any]] = [{} for _ in range(num_slots)]
        self._slot_preset_params: list[dict[str, Any]] = [{} for _ in range(num_slots)]
        self._slot_pending_frag: list[str | None] = [None] * num_slots
        self._slot_last_frag: list[str | None] = [None] * num_slots
        self._slot_is_temporal: list[bool] = [False] * num_slots

    def _bounded_params(self, node_type: str, params: dict[str, Any]) -> dict[str, Any]:
        """Clamp params to manifest bounds plus live-surface safety bounds."""
        out = dict(params)
        defn = self._registry.get(node_type)
        if defn:
            for key, value in list(out.items()):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                pdef = defn.params.get(key)
                if pdef is None:
                    continue
                bounded = float(value)
                if pdef.min is not None:
                    bounded = max(bounded, float(pdef.min))
                if pdef.max is not None:
                    bounded = min(bounded, float(pdef.max))
                out[key] = bounded

        try:
            from agents.studio_compositor.preset_policy import (
                apply_live_surface_param_bounds,
            )

            out = apply_live_surface_param_bounds(node_type, out)
        except ImportError:
            log.debug("live-surface param policy unavailable for %s", node_type, exc_info=True)
        return out

    def create_slots(self, Gst: Any, plan: ExecutionPlan | None = None) -> list[Any]:
        """Create N glfeedback slot elements.

        All slots use glfeedback which applies shaders instantly via property
        (no create-shader signal timing issues) and provides tex_accum for
        temporal effects.  Falls back to glshader if glfeedback not installed.
        """
        self._slots = []
        self._slot_base_params = [{} for _ in range(self._num_slots)]
        self._slot_pending_frag = [None] * self._num_slots
        self._slot_last_frag = [None] * self._num_slots
        self._slot_is_temporal = [False] * self._num_slots

        has_glfeedback = Gst.ElementFactory.find("glfeedback") is not None

        for i in range(self._num_slots):
            if has_glfeedback:
                slot = Gst.ElementFactory.make("glfeedback", f"effect-slot-{i}")
                slot.set_property("fragment", PASSTHROUGH_SHADER)
                # Beta audit pass 2 L-01 fix: keep the Python memo in
                # sync with the actual GStreamer element state. Without
                # this, the first ``activate_plan`` after startup sees
                # ``frag=PASSTHROUGH_SHADER != _slot_last_frag[i]=None``
                # and over-counts ``COMP_GLFEEDBACK_RECOMPILE_TOTAL`` by
                # one per slot (up to 24 at num_slots=24). The Rust side
                # correctly no-ops via its own diff check, so no real
                # work happens — this is metric hygiene only.
                self._slot_last_frag[i] = PASSTHROUGH_SHADER
                self._slot_is_temporal[i] = True
            else:
                slot = Gst.ElementFactory.make("glshader", f"effect-slot-{i}")
                slot.set_property("fragment", PASSTHROUGH_SHADER)
                slot.connect("create-shader", self._on_create_shader, i)
            self._slots.append(slot)

        log.info("Created %d glfeedback slots", self._num_slots)
        return list(self._slots)

    def _on_create_shader(self, element: Any, slot_idx: int) -> Any:
        """GL-thread callback: compile pending fragment shader for a slot."""
        frag = self._slot_pending_frag[slot_idx]
        if frag is None:
            return None  # use default

        try:
            import gi

            gi.require_version("GstGL", "1.0")
            from gi.repository import GstGL

            ctx = element.get_property("context")
            if ctx is None:
                log.error("No GL context for slot %d", slot_idx)
                return None

            shader = GstGL.GLShader.new(ctx)
            vert_stage = GstGL.GLSLStage.new_default_vertex(ctx)
            frag_stage = GstGL.GLSLStage.new_with_string(
                ctx,
                GL_FRAGMENT_SHADER,
                GstGL.GLSLVersion.NONE,
                GstGL.GLSLProfile.ES | GstGL.GLSLProfile.COMPATIBILITY,
                frag,
            )
            shader.compile_attach_stage(vert_stage)
            shader.compile_attach_stage(frag_stage)
            shader.link()
            node = self._slot_assignments[slot_idx] or "?"
            log.info("GL compiled shader for slot %d (%s)", slot_idx, node)
            return shader
        except Exception:
            log.exception("Failed to compile shader for slot %d", slot_idx)
            return None

    def link_chain(self, pipeline: Any, Gst: Any, upstream: Any, downstream: Any) -> None:
        """Link slots with per-slot leaky queues between them.

        Defense-in-depth for the GL chain stall scenario: a single glfeedback
        slot blocking the shared GL command stream could otherwise serial-block
        the entire chain (12 serial elements, one stuck = full chain freeze).
        Inserting ``queue(leaky=downstream, max-size-buffers=1)`` between each
        consecutive slot pair caps blast radius — the leaky queue drops the
        oldest queued buffer when full, so upstream slots are never blocked by
        downstream stalls.

        The 2026-04-14 GLib.idle_add fix addresses the root cause of the GL
        chain deadlock at the preset-activation layer. This adds defense-in-
        depth at the GStreamer linking layer: if the root cause re-emerges via
        a different path, the inter-slot queues localise the stall to a single
        slot rather than the entire 12-slot chain.

        Latency cost: at most 1 buffer per queue. Acceptable for live-stream
        purposes where dropping a stale frame is preferable to blocking on a
        stuck slot. ``max-size-bytes`` and ``max-size-time`` are zeroed so
        only the buffer count gates the queue.
        """
        self._inter_slot_queues: list[Any] = []
        prev = upstream
        for i, slot in enumerate(self._slots):
            if not prev.link(slot):
                log.error("Failed to link %s → %s", prev.get_name(), slot.get_name())
            prev = slot
            if i < len(self._slots) - 1:
                queue = Gst.ElementFactory.make("queue", f"effect-slot-queue-{i}")
                # leaky=downstream (2): when full, drop the oldest queued buffer.
                queue.set_property("leaky", 2)
                queue.set_property("max-size-buffers", 1)
                queue.set_property("max-size-bytes", 0)
                queue.set_property("max-size-time", 0)
                pipeline.add(queue)
                if not prev.link(queue):
                    log.error("Failed to link %s → %s", prev.get_name(), queue.get_name())
                prev = queue
                self._inter_slot_queues.append(queue)
        if not prev.link(downstream):
            log.error("Failed to link %s → %s", prev.get_name(), downstream.get_name())
        log.info(
            "Built %d-slot shader pipeline with %d inter-slot leaky queues",
            self._num_slots,
            len(self._inter_slot_queues),
        )

    def build_chain(
        self,
        pipeline: Any,
        Gst: Any,
        upstream: Any,
        downstream: Any,
        plan: ExecutionPlan | None = None,
    ) -> None:
        """Create slot elements, link them between upstream and downstream."""
        slots = self.create_slots(Gst, plan=plan)
        for slot in slots:
            pipeline.add(slot)
        self.link_chain(pipeline, Gst, upstream, downstream)

    def activate_plan(self, plan: ExecutionPlan) -> None:
        """Assign graph nodes to slots in topological order."""
        if not self._slots:
            log.warning("No slots built — skipping plan activation")
            return

        self._slot_assignments = [None] * self._num_slots
        self._slot_base_params = [{} for _ in range(self._num_slots)]
        self._slot_preset_params: list[dict[str, Any]] = [{} for _ in range(self._num_slots)]

        # Default all slots to passthrough
        for i in range(self._num_slots):
            self._slot_pending_frag[i] = PASSTHROUGH_SHADER

        # Assign actual shaders to used slots sequentially
        slot_idx = 0
        for step in plan.steps:
            if step.node_type == "output":
                continue
            if slot_idx >= self._num_slots:
                log.warning("More nodes than slots (%d) — truncating", self._num_slots)
                break
            if step.shader_source:
                params = self._bounded_params(step.node_type, step.params)
                self._slot_pending_frag[slot_idx] = step.shader_source
                self._slot_assignments[slot_idx] = step.node_type
                self._slot_base_params[slot_idx] = params
                self._slot_preset_params[slot_idx] = dict(params)
                slot_idx += 1

        # Apply changes to each slot. Diff against last-set fragment so
        # byte-identical re-sets (typical for passthrough slots across
        # plan activations) do not trigger a GL recompile + accum clear.
        fragment_set_count = 0
        for i in range(self._num_slots):
            if self._slot_is_temporal[i]:
                frag = self._slot_pending_frag[i] or PASSTHROUGH_SHADER
                node = self._slot_assignments[i] or "passthrough"
                if frag != self._slot_last_frag[i]:
                    log.info("Slot %d (%s): setting fragment (%d chars)", i, node, len(frag))
                    self._slots[i].set_property("fragment", frag)
                    self._slot_last_frag[i] = frag
                    fragment_set_count += 1
                self._apply_glfeedback_uniforms(i)
            else:
                self._set_uniforms(i, self._slot_base_params[i])
                self._slots[i].set_property("update-shader", True)

        # Phase 10 / delta metric-coverage-gaps C7 + C8 — proof-of-fix
        # counters. Every post-diff-check real fragment set triggers
        # exactly one Rust-side recompile, and every recompile clears
        # both accum FBOs. The two counters therefore track in lockstep
        # at real-change rate. Before the Phase 10 PR #1 diff check,
        # these would have read ~24 per activate_plan; with the fix in
        # place they read only real changes. Import inside the function
        # so the compositor metrics module can be absent in unit tests.
        if fragment_set_count > 0:
            try:
                from agents.studio_compositor import metrics as _comp_metrics

                if _comp_metrics.COMP_GLFEEDBACK_RECOMPILE_TOTAL is not None:
                    _comp_metrics.COMP_GLFEEDBACK_RECOMPILE_TOTAL.inc(fragment_set_count)
                if _comp_metrics.COMP_GLFEEDBACK_ACCUM_CLEAR_TOTAL is not None:
                    _comp_metrics.COMP_GLFEEDBACK_ACCUM_CLEAR_TOTAL.inc(fragment_set_count)
            except Exception:
                log.debug("glfeedback recompile counters unavailable", exc_info=True)

        # Drop #37 FX-1: publish the passthrough-slot count per plan
        # activation. Counts slots whose assignment is `None` after the
        # sequential assignment pass. Drives the FX-2 / FX-3 decision on
        # whether to ship dynamic `num_slots = max_preset_size + 3`.
        try:
            from agents.studio_compositor import metrics as _comp_metrics

            if _comp_metrics.COMP_FX_PASSTHROUGH_SLOTS is not None:
                passthrough = sum(1 for a in self._slot_assignments if a is None)
                _comp_metrics.COMP_FX_PASSTHROUGH_SLOTS.set(passthrough)
        except Exception:
            log.debug("passthrough slot gauge unavailable", exc_info=True)

        log.info(
            "Activated plan '%s': %d/%d slots used, %d fragment set_property calls",
            plan.name,
            slot_idx,
            self._num_slots,
            fragment_set_count,
        )

    def find_slot_for_node(self, node_type: str) -> int | None:
        """Find which slot a node type is assigned to.

        Drop #47 DR-4: previously also handled prefixed IDs from merged
        chains ('p0_bloom' → 'bloom') via a second pass that split on '_'
        and compared the trailing base. No production preset uses that
        chain composition path; the exact-match first pass handles every
        real preset.
        """
        for i, assigned in enumerate(self._slot_assignments):
            if assigned == node_type:
                return i
        return None

    def update_node_uniforms(self, node_type: str, params: dict[str, Any]) -> None:
        """Update uniforms for a node — ADDITIVE on top of preset base values.

        Modulated params are added to the preset's compiled defaults,
        then clamped to the param's declared min/max bounds to prevent
        audio reactivity from blowing out effects (e.g. brightness to white).
        Non-numeric params (time, width, height) replace directly.
        """
        slot_idx = self.find_slot_for_node(node_type)
        if slot_idx is not None:
            preset = (
                self._slot_preset_params[slot_idx] if hasattr(self, "_slot_preset_params") else {}
            )
            assigned = self._slot_assignments[slot_idx] or ""
            defn = self._registry.get(assigned)
            for key, val in params.items():
                if key in ("time", "width", "height") or key not in preset:
                    # Direct set for time/resolution or params not in preset
                    self._slot_base_params[slot_idx][key] = val
                elif isinstance(val, (int, float)) and isinstance(preset.get(key), (int, float)):
                    # Additive: preset_base + modulated_delta, clamped to bounds
                    combined = preset[key] + val
                    if defn and key in defn.params:
                        pdef = defn.params[key]
                        if pdef.min is not None:
                            combined = max(combined, pdef.min)
                        if pdef.max is not None:
                            combined = min(combined, pdef.max)
                    self._slot_base_params[slot_idx][key] = combined
                else:
                    self._slot_base_params[slot_idx][key] = val
            self._slot_base_params[slot_idx] = self._bounded_params(
                assigned,
                self._slot_base_params[slot_idx],
            )
            if self._slot_is_temporal[slot_idx]:
                self._apply_glfeedback_uniforms(slot_idx)
            else:
                self._set_uniforms(slot_idx, self._slot_base_params[slot_idx])

    def _set_uniforms(self, slot_idx: int, params: dict[str, Any]) -> None:
        """Build uniform string from params and set on slot element."""
        parts = []
        for key, value in params.items():
            if isinstance(value, bool):
                parts.append(f"u_{key}=(float){1.0 if value else 0.0}")
            elif isinstance(value, (int, float)):
                parts.append(f"u_{key}=(float){float(value)}")
            elif isinstance(value, str):
                defn = self._registry.get(self._slot_assignments[slot_idx] or "")
                if defn and key in defn.params and defn.params[key].enum_values:
                    vals = defn.params[key].enum_values or []
                    idx = vals.index(value) if value in vals else 0
                    parts.append(f"u_{key}=(float){float(idx)}")
        if not parts:
            return
        slot = self._slots[slot_idx]
        if hasattr(slot, "_mock_name") or not hasattr(slot, "get_factory"):
            return
        try:
            import gi

            gi.require_version("Gst", "1.0")
            from gi.repository import Gst

            uniform_str = "uniforms, " + ", ".join(parts)
            result = Gst.Structure.from_string(uniform_str)
            if result and result[0]:
                slot.set_property("uniforms", result[0])
            else:
                log.warning("Failed to parse uniform string: %s", uniform_str)
        except (ImportError, ValueError):
            log.exception("Failed to set uniforms on slot %d", slot_idx)

    def _apply_glfeedback_uniforms(self, slot_idx: int) -> None:
        """Set uniforms on a glfeedback element via its 'uniforms' property.

        The glfeedback element accepts comma-separated key=value pairs.
        """
        params = self._slot_base_params[slot_idx]
        parts = []
        for key, value in params.items():
            if isinstance(value, bool):
                parts.append(f"u_{key}={1.0 if value else 0.0}")
            elif isinstance(value, (int, float)):
                parts.append(f"u_{key}={float(value)}")
            elif isinstance(value, str):
                defn = self._registry.get(self._slot_assignments[slot_idx] or "")
                if defn and key in defn.params and defn.params[key].enum_values:
                    vals = defn.params[key].enum_values or []
                    idx = vals.index(value) if value in vals else 0
                    parts.append(f"u_{key}={float(idx)}")
        if parts:
            uniform_str = ", ".join(parts)
            node = self._slot_assignments[slot_idx] or "?"
            log.debug("Slot %d (%s) uniforms: %s", slot_idx, node, uniform_str[:200])
            self._slots[slot_idx].set_property("uniforms", uniform_str)

    @property
    def num_slots(self) -> int:
        return self._num_slots

    @property
    def slot_assignments(self) -> list[str | None]:
        return list(self._slot_assignments)
