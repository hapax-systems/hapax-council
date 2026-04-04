"""Slot-based GStreamer shader pipeline — assigns graph nodes to numbered slots."""

from __future__ import annotations

import logging
from typing import Any

from .compiler import ExecutionPlan
from .registry import ShaderRegistry
from .temporal_slot import TemporalSlotState

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
        self._temporal_states: list[TemporalSlotState | None] = [None] * num_slots
        self._temporal_shaders: list[object | None] = [None] * num_slots

    def create_slots(self, Gst: Any, plan: ExecutionPlan | None = None) -> list[Any]:
        """Create slot elements. ALL slots use glfilterapp for temporal readiness.

        glfilterapp gives GL-thread access via client-draw callback. The callback
        handles both passthrough (no temporal state) and temporal feedback (ping-pong
        FBOs). This avoids needing to know the plan at pipeline construction time —
        temporal state is set dynamically when activate_plan is called.
        """
        self._slots = []
        self._slot_base_params = [{} for _ in range(self._num_slots)]
        self._slot_pending_frag = [None] * self._num_slots
        self._temporal_states = [None] * self._num_slots
        self._temporal_shaders = [None] * self._num_slots
        self._Gst = Gst  # stored for activate_plan temporal setup

        for i in range(self._num_slots):
            slot = Gst.ElementFactory.make("glfilterapp", f"effect-slot-{i}")
            if slot is None:
                log.warning("glfilterapp unavailable — falling back to glshader for slot %d", i)
                slot = Gst.ElementFactory.make("glshader", f"effect-slot-{i}")
                slot.set_property("fragment", PASSTHROUGH_SHADER)
                slot.connect("create-shader", self._on_create_shader, i)
            else:
                slot.connect("client-draw", self._on_temporal_render, i)
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

    def _compile_temporal_shader(self, slot_idx: int, ctx: Any) -> Any:
        """Compile a temporal shader on the GL thread."""
        frag = self._slot_pending_frag[slot_idx]
        if frag is None:
            return None
        try:
            import gi

            gi.require_version("GstGL", "1.0")
            from gi.repository import GstGL

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
            log.info("GL compiled temporal shader for slot %d (%s)", slot_idx, node)
            return shader
        except Exception:
            log.exception("Failed to compile temporal shader for slot %d", slot_idx)
            return None

    def _on_temporal_render(
        self, element: Any, texture_id: int, width: int, height: int, slot_idx: int
    ) -> bool:
        """GL-thread callback for temporal slots (glfilterapp client-draw).

        Binds the accumulation texture as tex_accum, renders through the
        compiled shader, then copies the output to the accumulation texture.
        """
        try:
            from OpenGL import GL

            state = self._temporal_states[slot_idx]
            shader = self._temporal_shaders[slot_idx]

            # No shader assigned — passthrough (draw input texture directly)
            if shader is None and not self._slot_pending_frag[slot_idx]:
                GL.glActiveTexture(GL.GL_TEXTURE0)
                GL.glBindTexture(GL.GL_TEXTURE_2D, texture_id)
                GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
                return True

            # Non-temporal slot with a shader — render without tex_accum
            if state is None:
                # Lazy compile
                if shader is None and self._slot_pending_frag[slot_idx]:
                    ctx = element.get_property("context")
                    if ctx:
                        shader = self._compile_temporal_shader(slot_idx, ctx)
                        self._temporal_shaders[slot_idx] = shader
                if shader is None:
                    # Still no shader — passthrough
                    GL.glActiveTexture(GL.GL_TEXTURE0)
                    GL.glBindTexture(GL.GL_TEXTURE_2D, texture_id)
                    GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
                    return True
                # Render with shader but no tex_accum
                prog_id = shader.get_program_handle()
                GL.glUseProgram(prog_id)
                tex_loc = GL.glGetUniformLocation(prog_id, "tex")
                GL.glActiveTexture(GL.GL_TEXTURE0)
                GL.glBindTexture(GL.GL_TEXTURE_2D, texture_id)
                if tex_loc >= 0:
                    GL.glUniform1i(tex_loc, 0)
                # Set uniforms
                params = self._slot_base_params[slot_idx]
                for key, value in params.items():
                    if isinstance(value, (int, float)):
                        loc = GL.glGetUniformLocation(prog_id, f"u_{key}")
                        if loc >= 0:
                            GL.glUniform1f(loc, float(value))
                import time as time_mod

                time_loc = GL.glGetUniformLocation(prog_id, "u_time")
                if time_loc >= 0:
                    GL.glUniform1f(time_loc, time_mod.monotonic() % 3600.0)
                for uname, uval in [("u_width", float(width)), ("u_height", float(height))]:
                    loc = GL.glGetUniformLocation(prog_id, uname)
                    if loc >= 0:
                        GL.glUniform1f(loc, uval)
                GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
                GL.glUseProgram(0)
                return True

            # Lazy-init accumulation texture on first frame
            if not state.initialized:
                accum_tex = GL.glGenTextures(1)
                GL.glBindTexture(GL.GL_TEXTURE_2D, accum_tex)
                GL.glTexImage2D(
                    GL.GL_TEXTURE_2D,
                    0,
                    GL.GL_RGBA8,
                    width,
                    height,
                    0,
                    GL.GL_RGBA,
                    GL.GL_UNSIGNED_BYTE,
                    None,
                )
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
                GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
                state.initialize(width, height, accum_tex)
                log.info(
                    "Temporal slot %d: allocated accum texture %d (%dx%d)",
                    slot_idx,
                    accum_tex,
                    width,
                    height,
                )

            # Lazy-compile shader on GL thread
            shader = self._temporal_shaders[slot_idx]
            if shader is None and self._slot_pending_frag[slot_idx]:
                ctx = element.get_property("context")
                if ctx:
                    shader = self._compile_temporal_shader(slot_idx, ctx)
                    self._temporal_shaders[slot_idx] = shader
            if shader is None:
                return True  # passthrough

            # Use the shader program
            prog_id = shader.get_program_handle()
            GL.glUseProgram(prog_id)

            # Bind tex (current frame) on texture unit 0
            tex_loc = GL.glGetUniformLocation(prog_id, "tex")
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, texture_id)
            if tex_loc >= 0:
                GL.glUniform1i(tex_loc, 0)

            # Bind tex_accum (previous frame) on texture unit 1
            accum_loc = GL.glGetUniformLocation(prog_id, "tex_accum")
            if accum_loc >= 0 and state.accum_texture_id is not None:
                GL.glActiveTexture(GL.GL_TEXTURE1)
                GL.glBindTexture(GL.GL_TEXTURE_2D, state.accum_texture_id)
                GL.glUniform1i(accum_loc, 1)

            # Set float uniforms
            params = self._slot_base_params[slot_idx]
            for key, value in params.items():
                if isinstance(value, (int, float)):
                    loc = GL.glGetUniformLocation(prog_id, f"u_{key}")
                    if loc >= 0:
                        GL.glUniform1f(loc, float(value))
                elif isinstance(value, str):
                    defn = self._registry.get(self._slot_assignments[slot_idx] or "")
                    if defn and key in defn.params and defn.params[key].enum_values:
                        vals = defn.params[key].enum_values or []
                        idx = vals.index(value) if value in vals else 0
                        loc = GL.glGetUniformLocation(prog_id, f"u_{key}")
                        if loc >= 0:
                            GL.glUniform1f(loc, float(idx))

            # Set time uniform
            import time as time_mod

            time_loc = GL.glGetUniformLocation(prog_id, "u_time")
            if time_loc >= 0:
                GL.glUniform1f(time_loc, time_mod.monotonic() % 3600.0)

            # Set resolution uniforms
            for uname, uval in [("u_width", float(width)), ("u_height", float(height))]:
                loc = GL.glGetUniformLocation(prog_id, uname)
                if loc >= 0:
                    GL.glUniform1f(loc, uval)

            # Draw fullscreen quad
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)

            # Copy rendered output to accum texture for next frame
            if state.accum_texture_id is not None:
                GL.glActiveTexture(GL.GL_TEXTURE0)
                GL.glBindTexture(GL.GL_TEXTURE_2D, state.accum_texture_id)
                GL.glCopyTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, 0, 0, width, height)

            # Clean up GL state
            GL.glUseProgram(0)
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

            return True
        except Exception:
            log.exception("Temporal render failed for slot %d", slot_idx)
            return True

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
        self.link_chain(upstream, downstream)

    def activate_plan(self, plan: ExecutionPlan) -> None:
        """Assign graph nodes to slots in topological order."""
        if not self._slots:
            log.warning("No slots built — skipping plan activation")
            return

        self._slot_assignments = [None] * self._num_slots
        self._slot_base_params = [{} for _ in range(self._num_slots)]

        # Reset all slots: clear pending frag (passthrough) and temporal state
        for i in range(self._num_slots):
            self._slot_pending_frag[i] = None  # None = passthrough in render callback
            self._temporal_states[i] = None
            self._temporal_shaders[i] = None

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
                if step.temporal:
                    self._temporal_states[slot_idx] = TemporalSlotState(
                        num_buffers=max(1, step.temporal_buffers)
                    )
                    log.info(
                        "Slot %d (%s): temporal with %d buffers",
                        slot_idx,
                        step.node_type,
                        step.temporal_buffers,
                    )
                # Shader compiled lazily on GL thread in _on_temporal_render
                self._temporal_shaders[slot_idx] = None
                slot_idx += 1

        # All slots are glfilterapp — no GStreamer update-shader needed.
        # Shaders compile lazily on the GL thread in _on_temporal_render.
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
        """Store uniform params for the render callback to apply.

        All slots are glfilterapp — uniforms are set via direct GL calls
        in _on_temporal_render, not via GStreamer's uniforms property.
        This method resolves enum values to float indices and stores the
        result in _slot_base_params for the callback to read.
        """
        resolved: dict[str, Any] = {}
        for key, value in params.items():
            if isinstance(value, bool):
                resolved[key] = 1.0 if value else 0.0
            elif isinstance(value, (int, float)):
                resolved[key] = float(value)
            elif isinstance(value, str):
                defn = self._registry.get(self._slot_assignments[slot_idx] or "")
                if defn and key in defn.params and defn.params[key].enum_values:
                    vals = defn.params[key].enum_values or []
                    idx = vals.index(value) if value in vals else 0
                    resolved[key] = float(idx)
        self._slot_base_params[slot_idx].update(resolved)

    @property
    def num_slots(self) -> int:
        return self._num_slots

    @property
    def slot_assignments(self) -> list[str | None]:
        return list(self._slot_assignments)
