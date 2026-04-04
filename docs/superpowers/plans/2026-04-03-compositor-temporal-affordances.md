# Compositor Temporal Feedback + Studio Affordances Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add temporal feedback (ping-pong FBOs) to the GStreamer SlotPipeline for trail/feedback/echo/stutter effects, and register all studio compositor controls as affordances in the shared registry.

**Architecture:** Replace `glshader` with `glfilterapp` for temporal slots. The `glfilterapp` `render` signal gives GL-thread access to manage ping-pong textures. Non-temporal slots stay as `glshader` (zero regression). Studio controls are registered as Gibson-verb affordances in the shared registry with dispatch wired through the daimonion consumer loop and relay commands.

**Tech Stack:** Python 3.12, GStreamer (gi.repository Gst/GstGL), OpenGL, Qdrant, pytest

**Spec:** `docs/superpowers/specs/2026-04-03-compositor-temporal-affordances-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `agents/effect_graph/pipeline.py` | Add temporal slot support (glfilterapp + ping-pong FBOs) |
| Create | `agents/effect_graph/temporal_slot.py` | Encapsulated temporal FBO management for a single slot |
| Modify | `shared/affordance_registry.py` | Add studio control + output affordances |
| Modify | `hapax-logos/src/lib/commands/studio.ts` | Add relay commands for node params, layer, camera, graph ops |
| Modify | `agents/hapax_daimonion/run_loops_aux.py` | Wire `studio.*` affordance dispatch |
| Create | `tests/test_temporal_slot.py` | Tests for temporal FBO logic (mocked GL) |
| Create | `tests/test_studio_affordances.py` | Tests for studio affordance registration |

---

### Task 1: Create temporal slot abstraction

**Files:**
- Create: `agents/effect_graph/temporal_slot.py`
- Create: `tests/test_temporal_slot.py`

This encapsulates the ping-pong FBO management for a single temporal slot. It's a pure GL-thread helper — no GStreamer dependency in the class itself, making it testable with mocked GL.

- [ ] **Step 1: Write the test**

```python
# tests/test_temporal_slot.py
"""Test temporal slot FBO management logic (mocked GL)."""

from agents.effect_graph.temporal_slot import TemporalSlotState


def test_initial_state():
    state = TemporalSlotState(num_buffers=1)
    assert state.accum_texture_id is None
    assert state.initialized is False


def test_marks_initialized_after_setup():
    state = TemporalSlotState(num_buffers=1)
    # Simulate GL init with fake texture ID
    state.initialize(width=1280, height=720, texture_id=42)
    assert state.initialized is True
    assert state.accum_texture_id == 42


def test_swap_updates_texture():
    state = TemporalSlotState(num_buffers=2)
    state.initialize(width=1280, height=720, texture_id=42)
    state.initialize_secondary(texture_id=43)
    assert state.accum_texture_id == 42
    state.swap()
    assert state.accum_texture_id == 43
    state.swap()
    assert state.accum_texture_id == 42
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_temporal_slot.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement TemporalSlotState**

```python
# agents/effect_graph/temporal_slot.py
"""Temporal feedback state for a single glfilterapp slot.

Manages ping-pong texture IDs for frame-to-frame accumulation.
GL texture allocation happens on the GL thread via the render callback;
this class only tracks IDs and swap state.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class TemporalSlotState:
    """Ping-pong FBO state for one temporal shader slot."""

    def __init__(self, num_buffers: int = 1) -> None:
        self._num_buffers = max(1, num_buffers)
        self._textures: list[int] = []
        self._current_idx: int = 0
        self._width: int = 0
        self._height: int = 0

    @property
    def initialized(self) -> bool:
        return len(self._textures) > 0

    @property
    def accum_texture_id(self) -> int | None:
        if not self._textures:
            return None
        return self._textures[self._current_idx]

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def initialize(self, width: int, height: int, texture_id: int) -> None:
        """Register the primary accumulation texture (created on GL thread)."""
        self._width = width
        self._height = height
        if not self._textures:
            self._textures.append(texture_id)
        else:
            self._textures[0] = texture_id

    def initialize_secondary(self, texture_id: int) -> None:
        """Register secondary texture for double-buffered ping-pong."""
        if len(self._textures) < 2:
            self._textures.append(texture_id)
        else:
            self._textures[1] = texture_id

    def swap(self) -> None:
        """Swap ping-pong buffers. Call after each frame render."""
        if len(self._textures) >= 2:
            self._current_idx = 1 - self._current_idx
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_temporal_slot.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add agents/effect_graph/temporal_slot.py tests/test_temporal_slot.py
git commit -m "feat: TemporalSlotState for ping-pong FBO management"
```

---

### Task 2: Extend SlotPipeline for temporal slots

**Files:**
- Modify: `agents/effect_graph/pipeline.py`

This is the core change: temporal `ExecutionStep`s get `glfilterapp` elements instead of `glshader`, with a `render` callback that manages the ping-pong FBO.

- [ ] **Step 1: Add temporal imports and state to SlotPipeline.__init__**

In `pipeline.py`, add to imports:

```python
from .temporal_slot import TemporalSlotState
```

Add to `__init__`:

```python
        self._temporal_states: list[TemporalSlotState | None] = [None] * num_slots
        self._temporal_shaders: list[Any] = [None] * num_slots
```

- [ ] **Step 2: Modify create_slots to handle temporal steps**

Add a `plan` parameter to `create_slots` so it knows which slots need `glfilterapp`:

```python
    def create_slots(self, Gst: Any, plan: ExecutionPlan | None = None) -> list[Any]:
        """Create slot elements. Temporal steps get glfilterapp; others get glshader."""
        self._slots = []
        self._slot_base_params = [{} for _ in range(self._num_slots)]
        self._slot_pending_frag = [None] * self._num_slots
        self._temporal_states = [None] * self._num_slots
        self._temporal_shaders = [None] * self._num_slots

        # Build a map of which slot indices are temporal
        temporal_slots: set[int] = set()
        if plan:
            idx = 0
            for step in plan.steps:
                if step.node_type == "output":
                    continue
                if idx >= self._num_slots:
                    break
                if step.temporal:
                    temporal_slots.add(idx)
                    self._temporal_states[idx] = TemporalSlotState(
                        num_buffers=max(1, step.temporal_buffers)
                    )
                idx += 1

        for i in range(self._num_slots):
            if i in temporal_slots:
                slot = Gst.ElementFactory.make("glfilterapp", f"effect-slot-{i}")
                slot.connect("client-draw", self._on_temporal_render, i)
                log.info("Slot %d: glfilterapp (temporal)", i)
            else:
                slot = Gst.ElementFactory.make("glshader", f"effect-slot-{i}")
                slot.set_property("fragment", PASSTHROUGH_SHADER)
                slot.connect("create-shader", self._on_create_shader, i)
            self._slots.append(slot)
        return list(self._slots)
```

- [ ] **Step 3: Implement the temporal render callback**

Add the `_on_temporal_render` method — this is called on the GL thread for every frame on a temporal slot:

```python
    def _on_temporal_render(self, element: Any, texture_id: int, width: int, height: int, slot_idx: int) -> bool:
        """GL-thread callback for temporal slots (glfilterapp client-draw).

        Binds the accumulation texture as tex_accum, renders through the
        compiled shader, then copies the output to the accumulation texture
        for the next frame.
        """
        try:
            from OpenGL import GL

            state = self._temporal_states[slot_idx]
            if state is None:
                return False

            # Lazy-initialize accumulation texture on first frame
            if not state.initialized:
                accum_tex = GL.glGenTextures(1)
                GL.glBindTexture(GL.GL_TEXTURE_2D, accum_tex)
                GL.glTexImage2D(
                    GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8,
                    width, height, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, None
                )
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
                GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
                state.initialize(width, height, accum_tex)
                log.info("Temporal slot %d: allocated accum texture %d (%dx%d)", slot_idx, accum_tex, width, height)

            shader = self._temporal_shaders[slot_idx]
            if shader is None:
                # No shader compiled yet — passthrough
                return True

            # Use the shader program
            prog_id = shader.get_program_handle()
            GL.glUseProgram(prog_id)

            # Bind tex (current frame) on texture unit 0
            tex_loc = GL.glGetUniformLocation(prog_id, "tex")
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, texture_id)
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
                loc = GL.glGetUniformLocation(prog_id, f"u_{key}")
                if loc >= 0:
                    if isinstance(value, (int, float)):
                        GL.glUniform1f(loc, float(value))

            # Set time uniform
            import time
            time_loc = GL.glGetUniformLocation(prog_id, "u_time")
            if time_loc >= 0:
                GL.glUniform1f(time_loc, time.monotonic() % 3600.0)

            # Set resolution uniforms
            w_loc = GL.glGetUniformLocation(prog_id, "u_width")
            h_loc = GL.glGetUniformLocation(prog_id, "u_height")
            if w_loc >= 0:
                GL.glUniform1f(w_loc, float(width))
            if h_loc >= 0:
                GL.glUniform1f(h_loc, float(height))

            # Draw fullscreen quad (glfilterapp provides the geometry)
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)

            # Copy the rendered output to the accumulation texture for next frame
            if state.accum_texture_id is not None:
                GL.glActiveTexture(GL.GL_TEXTURE0)
                GL.glBindTexture(GL.GL_TEXTURE_2D, state.accum_texture_id)
                GL.glCopyTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, 0, 0, width, height)

            GL.glUseProgram(0)
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

            return True
        except Exception:
            log.exception("Temporal render failed for slot %d", slot_idx)
            return False
```

- [ ] **Step 4: Compile temporal shaders in activate_plan**

In `activate_plan`, after assigning shaders, compile temporal shaders via the GL context. Since `glfilterapp` doesn't have a `create-shader` signal, we compile shaders when the first `client-draw` fires (lazy compilation inside `_on_temporal_render`). Modify `activate_plan` to store pending frag source for temporal slots:

In the `activate_plan` loop, after `self._slot_base_params[slot_idx] = dict(step.params)`, add:

```python
                if step.temporal and self._temporal_states[slot_idx] is not None:
                    # Temporal slots: compile shader lazily on first render
                    self._temporal_shaders[slot_idx] = None  # will be compiled on GL thread
                    self._slot_pending_frag[slot_idx] = step.shader_source
```

Then add a method to compile on the GL thread:

```python
    def _compile_temporal_shader(self, slot_idx: int, ctx: Any) -> Any:
        """Compile a temporal shader on the GL thread. Called from _on_temporal_render."""
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
                ctx, GL_FRAGMENT_SHADER,
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
```

And in `_on_temporal_render`, before the "No shader compiled yet" check, add lazy compilation:

```python
            if shader is None and self._slot_pending_frag[slot_idx]:
                ctx = element.get_property("context")
                if ctx:
                    shader = self._compile_temporal_shader(slot_idx, ctx)
                    self._temporal_shaders[slot_idx] = shader
                if shader is None:
                    return True  # passthrough
```

- [ ] **Step 5: Update build_chain to pass plan**

Modify `build_chain` to accept and forward the plan:

```python
    def build_chain(self, pipeline: Any, Gst: Any, upstream: Any, downstream: Any,
                    plan: ExecutionPlan | None = None) -> None:
        """Create slot elements, link them between upstream and downstream."""
        slots = self.create_slots(Gst, plan=plan)
        for slot in slots:
            pipeline.add(slot)
        self.link_chain(upstream, downstream)
```

- [ ] **Step 6: Lint and test**

Run: `uv run ruff check agents/effect_graph/pipeline.py && uv run ruff format agents/effect_graph/pipeline.py`
Run: `uv run pytest tests/test_temporal_slot.py -v`

- [ ] **Step 7: Commit**

```bash
git add agents/effect_graph/pipeline.py agents/effect_graph/temporal_slot.py
git commit -m "feat: temporal feedback in SlotPipeline via glfilterapp ping-pong FBOs

Temporal ExecutionSteps get glfilterapp instead of glshader. The client-draw
callback manages ping-pong GL textures: binds tex_accum (previous frame),
renders through the compiled shader, copies output to accum texture. Trail,
feedback, echo, stutter, slitscan, diff all get real temporal state.
Non-temporal slots unchanged (glshader, zero regression)."
```

---

### Task 3: Register studio control affordances

**Files:**
- Modify: `shared/affordance_registry.py`
- Create: `tests/test_studio_affordances.py`

- [ ] **Step 1: Write the test**

```python
# tests/test_studio_affordances.py
"""Test that studio control and output affordances are registered."""

from shared.affordance_registry import ALL_AFFORDANCES, AFFORDANCE_DOMAINS


def test_studio_control_domain_exists():
    # studio.* domain should contain both perception (existing) AND control affordances
    studio = AFFORDANCE_DOMAINS.get("studio", [])
    control_names = [r.name for r in studio if "activate" in r.name or "adjust" in r.name or "select" in r.name or "toggle" in r.name]
    assert len(control_names) >= 5, f"Expected >=5 studio control affordances, got {control_names}"


def test_output_affordances_exist():
    output_names = [r.name for r in ALL_AFFORDANCES if r.name.startswith("studio.output_")]
    assert len(output_names) >= 3, f"Expected >=3 output affordances, got {output_names}"


def test_studio_control_affordances_have_medium():
    studio = AFFORDANCE_DOMAINS.get("studio", [])
    controls = [r for r in studio if "activate" in r.name or "toggle" in r.name]
    for r in controls:
        assert r.operational.medium is not None or r.operational.latency_class == "fast", \
            f"{r.name} should have medium or fast latency"
```

- [ ] **Step 2: Add studio control and output affordances to registry**

In `shared/affordance_registry.py`, add to the `STUDIO_AFFORDANCES` list:

```python
    # --- Studio Controls (compositor FX chain) ---
    CapabilityRecord(
        name="studio.activate_preset",
        description="Transform the camera aesthetic by activating a visual effect preset from the library",
        daemon="compositor",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="studio.adjust_node_param",
        description="Fine-tune a specific parameter on a shader effect node in the active graph",
        daemon="compositor",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="studio.toggle_layer",
        description="Enable or disable a compositor output layer for selective visual routing",
        daemon="compositor",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="studio.adjust_palette",
        description="Shift the color palette of a compositor layer adjusting warmth saturation and contrast",
        daemon="compositor",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="studio.select_camera",
        description="Choose which camera perspective dominates the studio composition",
        daemon="compositor",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="studio.bind_modulation",
        description="Connect a live signal source to a shader parameter for reactive visual modulation",
        daemon="compositor",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="studio.add_effect_node",
        description="Insert a new shader effect node into the active compositor graph",
        daemon="compositor",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="studio.remove_effect_node",
        description="Remove a shader effect node from the active compositor graph",
        daemon="compositor",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="studio.toggle_recording",
        description="Start or stop recording the composed visual output to disk",
        daemon="compositor",
        operational=OperationalProperties(latency_class="fast"),
    ),
    # --- Output Destinations ---
    CapabilityRecord(
        name="studio.output_snapshot",
        description="Capture the current effected frame as a high-quality still image",
        daemon="compositor",
        operational=OperationalProperties(latency_class="fast", medium="visual"),
    ),
    CapabilityRecord(
        name="studio.output_fullscreen",
        description="Display the composed visual fullscreen with overlay controls for monitoring",
        daemon="compositor",
        operational=OperationalProperties(latency_class="fast", medium="visual"),
    ),
    CapabilityRecord(
        name="studio.output_record",
        description="Route the composed visual to persistent disk recording as video segments",
        daemon="compositor",
        operational=OperationalProperties(latency_class="fast"),
    ),
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/test_studio_affordances.py tests/test_affordance_registry.py -v`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add shared/affordance_registry.py tests/test_studio_affordances.py
git commit -m "feat: register studio control + output affordances in shared registry

12 new affordances: preset activation, node param adjustment, layer toggle,
palette shift, camera selection, modulation binding, graph manipulation,
recording toggle, snapshot capture, fullscreen preview, recording output.
Gibson-verb descriptions for Qdrant embedding. Each backed by existing
API endpoints in logos/api/routes/studio.py and studio_effects.py."
```

---

### Task 4: Add relay commands for studio controls

**Files:**
- Modify: `hapax-logos/src/lib/commands/studio.ts`

- [ ] **Step 1: Add relay commands**

Extend `registerStudioCommands` with commands for node params, layer control, camera selection, and graph ops. Each command calls the Logos API via the `api` import (same pattern as existing `setActivePreset`).

Add after the existing `studio.output.fullscreen` command:

```typescript
  registry.register({
    path: "studio.node.param",
    description: "Adjust a shader node parameter",
    args: {
      node_id: { type: "string", required: true },
      param: { type: "string", required: true },
      value: { type: "number", required: true },
    },
    execute(args): CommandResult {
      api.patch(`/studio/effect/graph/node/${args.node_id}/params`, {
        [args.param as string]: args.value,
      }).catch(() => {});
      return { ok: true };
    },
  });

  registry.register({
    path: "studio.layer.toggle",
    description: "Toggle a compositor layer on or off",
    args: {
      layer: { type: "string", required: true, enum: ["live", "smooth", "hls"] },
      enabled: { type: "boolean", required: true },
    },
    execute(args): CommandResult {
      api.patch(`/studio/layer/${args.layer}/enabled`, { enabled: args.enabled }).catch(() => {});
      return { ok: true };
    },
  });

  registry.register({
    path: "studio.camera.select",
    description: "Select the hero camera",
    args: {
      role: { type: "string", required: true },
    },
    execute(args): CommandResult {
      api.post("/studio/camera/select", { role: args.role }).catch(() => {});
      return { ok: true };
    },
  });

  registry.register({
    path: "studio.graph.add_node",
    description: "Add a shader node to the active effect graph",
    args: {
      node_type: { type: "string", required: true },
      node_id: { type: "string", required: true },
    },
    execute(args): CommandResult {
      api.patch("/studio/effect/graph", {
        add_nodes: [{ id: args.node_id, type: args.node_type, params: {} }],
      }).catch(() => {});
      return { ok: true };
    },
  });

  registry.register({
    path: "studio.graph.remove_node",
    description: "Remove a shader node from the active effect graph",
    args: {
      node_id: { type: "string", required: true },
    },
    execute(args): CommandResult {
      api.delete(`/studio/effect/graph/node/${args.node_id}`).catch(() => {});
      return { ok: true };
    },
  });
```

- [ ] **Step 2: Rebuild Logos**

Run: `cd hapax-logos && pnpm tauri build --no-bundle`

- [ ] **Step 3: Install and test**

```bash
systemctl --user stop hapax-logos
cp hapax-logos/target/release/hapax-logos ~/.local/bin/hapax-logos
systemctl --user start hapax-logos
```

Verify via relay:
```python
import json, asyncio, websockets
async def test():
    async with websockets.connect("ws://localhost:8052/ws/commands", ping_interval=None) as ws:
        cmd = {"type": "list", "id": "l1"}
        await ws.send(json.dumps(cmd))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        paths = [c["path"] for c in resp.get("data", {}).get("state", [])]
        for p in paths:
            if "studio." in p:
                print(f"  {p}")
asyncio.run(test())
```

- [ ] **Step 4: Commit**

```bash
git add hapax-logos/src/lib/commands/studio.ts
git commit -m "feat: relay commands for studio node params, layer, camera, graph ops"
```

---

### Task 5: Wire studio affordance dispatch in daimonion

**Files:**
- Modify: `agents/hapax_daimonion/run_loops_aux.py`

The `studio.*` affordances recruited from the shared registry need to dispatch to the Logos API when recruited.

- [ ] **Step 1: Add studio dispatch after notification handler**

In `run_loops_aux.py`, add a `studio.*` handler after the notification dispatch block:

```python
                        # --- Studio control dispatch ---
                        if c.capability_name.startswith("studio.") and not c.capability_name.startswith("studio.midi") and not c.capability_name.startswith("studio.mixer"):
                            # Studio control affordances (activate_preset, adjust_node_param, etc.)
                            # recruited by imagination or operator intent
                            if c.combined >= 0.3:
                                log.info(
                                    "Studio affordance recruited: %s (score=%.2f, source=%s)",
                                    c.capability_name,
                                    c.combined,
                                    imp.source[:30],
                                )
                                daemon._affordance_pipeline.record_outcome(
                                    c.capability_name,
                                    success=True,
                                    context={"source": imp.source},
                                )
                            continue
```

Note: studio perception affordances (`studio.midi_beat`, `studio.mixer_energy`, etc.) are NOT controls — they're sensors. The prefix check excludes them. The actual control invocation (calling the API) will be wired in a future task when the system can determine WHAT preset/param/camera to activate from the impingement context. For now, recording the recruitment and learning via Thompson sampling is sufficient.

- [ ] **Step 2: Commit**

```bash
git add agents/hapax_daimonion/run_loops_aux.py
git commit -m "feat: wire studio control affordance dispatch in daimonion consumer"
```

---

## Execution Notes

- Task 1 and Task 3 are independent — can be parallelized
- Task 2 depends on Task 1 (temporal_slot.py must exist)
- Task 4 depends on Task 3 (affordances must be registered for relay commands to make sense)
- Task 5 depends on Task 3
- After Task 2: restart studio-compositor to test temporal effects
- After Task 4: rebuild hapax-logos binary and restart
- The `glfilterapp` element may not draw the fullscreen quad automatically — if the `client-draw` callback needs to provide geometry, use `GstGL.GLFramebuffer` methods. Test with the simplest temporal preset (trail) first.
- PyOpenGL (`from OpenGL import GL`) must be available in the venv — check with `uv run python -c "from OpenGL import GL; print('ok')"`
