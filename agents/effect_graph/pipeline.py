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


class SlotPipeline:
    """Manages a fixed chain of N glshader slots with runtime shader hot-swap."""

    def __init__(self, registry: ShaderRegistry, num_slots: int = 8) -> None:
        self._registry = registry
        self._num_slots = num_slots
        self._slots: list[Any] = []
        self._slot_assignments: list[str | None] = [None] * num_slots

    def build_chain(self, pipeline: Any, Gst: Any, upstream: Any, downstream: Any) -> None:
        """Create N glshader elements, link them between upstream and downstream."""
        self._slots = []
        prev = upstream
        for i in range(self._num_slots):
            slot = Gst.ElementFactory.make("glshader", f"effect-slot-{i}")
            slot.set_property("fragment", PASSTHROUGH_SHADER)
            pipeline.add(slot)
            prev.link(slot)
            self._slots.append(slot)
            prev = slot
        prev.link(downstream)
        log.info("Built %d-slot shader pipeline", self._num_slots)

    def activate_plan(self, plan: ExecutionPlan) -> None:
        """Assign graph nodes to slots in topological order."""
        if not self._slots:
            log.warning("No slots built — skipping plan activation")
            return

        self._slot_assignments = [None] * self._num_slots
        for slot in self._slots:
            try:
                slot.set_property("fragment", PASSTHROUGH_SHADER)
            except Exception:
                pass

        slot_idx = 0
        for step in plan.steps:
            if step.node_type == "output":
                continue
            if slot_idx >= self._num_slots:
                log.warning("More nodes than slots (%d) — truncating", self._num_slots)
                break
            if step.shader_source:
                try:
                    self._slots[slot_idx].set_property("fragment", step.shader_source)
                except Exception:
                    log.exception("Failed to set shader for slot %d (%s)", slot_idx, step.node_type)
                self._set_uniforms(slot_idx, step.params)
                self._slot_assignments[slot_idx] = step.node_type
                slot_idx += 1

        log.info("Activated plan '%s': %d/%d slots used", plan.name, slot_idx, self._num_slots)

    def find_slot_for_node(self, node_type: str) -> int | None:
        """Find which slot a node type is assigned to."""
        for i, assigned in enumerate(self._slot_assignments):
            if assigned == node_type:
                return i
        return None

    def update_node_uniforms(self, node_type: str, params: dict[str, Any]) -> None:
        """Update uniforms for a node by finding its slot."""
        slot_idx = self.find_slot_for_node(node_type)
        if slot_idx is not None:
            self._set_uniforms(slot_idx, params)

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
        # Only set uniforms via GstStructure if we have real GStreamer elements
        # (not mocks in test environment)
        slot = self._slots[slot_idx]
        if hasattr(slot, "_mock_name") or not hasattr(slot, "get_factory"):
            return
        try:
            import gi

            gi.require_version("Gst", "1.0")
            from gi.repository import Gst

            result = Gst.Structure.from_string("uniforms, " + ", ".join(parts))
            if result and result[0]:
                slot.set_property("uniforms", result[0])
        except (ImportError, ValueError):
            pass

    @property
    def num_slots(self) -> int:
        return self._num_slots

    @property
    def slot_assignments(self) -> list[str | None]:
        return list(self._slot_assignments)
