# ControlSignal Extension to All Backends

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend ControlSignal health reporting from 2 components (IR perception, stimmung) to all 14 S1 units, completing mesh-wide perceptual health coverage.

**Architecture:** Each backend's `contribute()` method (or equivalent tick function) computes a ControlSignal measuring its controlled perception vs reference. Published to `/dev/shm/hapax-{component}/health.json`. The existing `aggregate_mesh_health()` automatically picks up new signals.

**Tech Stack:** Python 3.12+, shared/control_signal.py (existing)

---

### Task 1: DMN Pulse ControlSignal

**Files:** `agents/dmn/pulse.py`

- [ ] **Step 1: Add health signal after each tick**

After DMN pulse completes a sensory tick, publish a ControlSignal:
- Component: "dmn"
- Reference: 1.0 (expects to produce observations every tick)
- Perception: 1.0 if observation produced, 0.0 if Ollama failed

```python
from shared.control_signal import ControlSignal, publish_health

# After sensory tick:
sig = ControlSignal(
    component="dmn",
    reference=1.0,
    perception=1.0 if observation_produced else 0.0,
)
publish_health(sig)
```

- [ ] **Step 2: Commit**

```bash
git commit -m "feat(dmn): publish ControlSignal for observation production health"
```

---

### Task 2: Imagination ControlSignal

**Files:** `agents/imagination_daemon/__main__.py`

- [ ] **Step 1: Add health signal measuring fragment resolution**

- Component: "imagination"
- Reference: 1.0 (expects to produce a fragment each tick when observations are fresh)
- Perception: 1.0 if fragment produced, 0.5 if skipped (stale), 0.0 if failed

- [ ] **Step 2: Commit**

```bash
git commit -m "feat(imagination): publish ControlSignal for fragment production health"
```

---

### Task 3: Voice Daemon ControlSignal

**Files:** `agents/hapax_daimonion/perception_loop.py` (or wherever the perception tick runs)

- [ ] **Step 1: Add health signal measuring perception freshness**

- Component: "voice_daemon"
- Reference: 1.0 (expects fresh perception data from all FAST backends)
- Perception: fraction of FAST backends that produced fresh data this tick

- [ ] **Step 2: Commit**

```bash
git commit -m "feat(voice): publish ControlSignal for perception pipeline health"
```

---

### Task 4: Remaining Components (batch)

For each of: content_resolver, reverie, compositor, temporal_bonds, apperception, reactive_engine, consent_engine, contact_mic, voice_pipeline:

- [ ] **Step 1: Add ControlSignal to each component**

Pattern for each:
```python
from shared.control_signal import ControlSignal, publish_health

sig = ControlSignal(
    component="{name}",
    reference=1.0,  # expected: producing output
    perception={actual_health},  # 1.0=healthy, 0.0=failed
)
publish_health(sig)
```

The `perception` value for each:
- content_resolver: fraction of fragments successfully resolved (trailing 10)
- reverie: 1.0 if frame written within last 100ms, 0.0 otherwise
- compositor: 1.0 if cameras detected, 0.0 if no input
- temporal_bonds: 1.0 if perception ring non-empty
- apperception: coherence value from self-model (already computed)
- reactive_engine: 1.0 if rules executing without timeout
- consent_engine: 1.0 if contracts loaded, 0.0 if fail-closed
- contact_mic: 1.0 if audio stream active
- voice_pipeline: 1.0 if ASR model loaded

- [ ] **Step 2: Commit**

```bash
git commit -m "feat: extend ControlSignal to all remaining S1 components"
```
