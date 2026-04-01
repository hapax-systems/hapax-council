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

    def __init__(self, registry: ShaderRegistry, num_slots: int = 8) -> None:
        self._registry = registry
        self._num_slots = num_slots
        self._slots: list[Any] = []
        self._slot_assignments: list[str | None] = [None] * num_slots
        self._slot_base_params: list[dict[str, Any]] = [{} for _ in range(num_slots)]
        self._slot_pending_frag: list[str | None] = [None] * num_slots

    def create_slots(self, Gst: Any) -> list[Any]:
        """Create N glshader slot elements with create-shader callbacks."""
        self._slots = []
        self._slot_base_params = [{} for _ in range(self._num_slots)]
        self._slot_pending_frag = [None] * self._num_slots

        for i in range(self._num_slots):
            slot = Gst.ElementFactory.make("glshader", f"effect-slot-{i}")
            slot.set_property("fragment", PASSTHROUGH_SHADER)
            slot.connect("create-shader", self._on_create_shader, i)
            self._slots.append(slot)
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

    def link_chain(self, upstream: Any, downstream: Any) -> None:
        """Link slots between upstream and downstream. Call after pipeline.add()."""
        prev = upstream
        for slot in self._slots:
            if not prev.link(slot):
                log.error("Failed to link %s → %s", prev.get_name(), slot.get_name())
            prev = slot
        if not prev.link(downstream):
            log.error("Failed to link %s → %s", prev.get_name(), downstream.get_name())
        log.info("Built %d-slot shader pipeline", self._num_slots)

    def build_chain(self, pipeline: Any, Gst: Any, upstream: Any, downstream: Any) -> None:
        """Create N glshader elements, link them between upstream and downstream."""
        slots = self.create_slots(Gst)
        for slot in slots:
            pipeline.add(slot)
        self.link_chain(upstream, downstream)

    def activate_plan(self, plan: ExecutionPlan) -> None:
        """Assign graph nodes to slots in topological order."""
        if not self._slots:
            log.warning("No slots built — skipping plan activation")
            return

        self._slot_assignments = [None] * self._num_slots
        self._slot_base_params = [{} for _ in range(self._num_slots)]

        # Default all slots to passthrough
        for i in range(self._num_slots):
            self._slot_pending_frag[i] = PASSTHROUGH_SHADER

        # Assign actual shaders to used slots
        slot_idx = 0
        for step in plan.steps:
            if step.node_type == "output":
                continue
            if slot_idx >= self._num_slots:
                log.warning("More nodes than slots (%d) — truncating", self._num_slots)
                break
            if step.shader_source:
                self._slot_pending_frag[slot_idx] = step.shader_source
                self._slot_assignments[slot_idx] = step.node_type
                self._slot_base_params[slot_idx] = dict(step.params)
                self._set_uniforms(slot_idx, step.params)
                slot_idx += 1

        # Trigger GL recompilation in a single pass after all assignments are final.
        # Avoids race where GL thread compiles a stale passthrough before the actual
        # shader is assigned (create-shader signals fire asynchronously on GL thread).
        for i in range(self._num_slots):
            self._slots[i].set_property("update-shader", True)

        log.info("Activated plan '%s': %d/%d slots used", plan.name, slot_idx, self._num_slots)

    def find_slot_for_node(self, node_type: str) -> int | None:
        """Find which slot a node type is assigned to."""
        for i, assigned in enumerate(self._slot_assignments):
            if assigned == node_type:
                return i
        return None

    def update_node_uniforms(self, node_type: str, params: dict[str, Any]) -> None:
        """Update uniforms for a node by finding its slot.

        Merges into base params so subsequent _set_uniforms calls include everything.
        """
        slot_idx = self.find_slot_for_node(node_type)
        if slot_idx is not None:
            self._slot_base_params[slot_idx].update(params)
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

    @property
    def num_slots(self) -> int:
        return self._num_slots

    @property
    def slot_assignments(self) -> list[str | None]:
        return list(self._slot_assignments)
