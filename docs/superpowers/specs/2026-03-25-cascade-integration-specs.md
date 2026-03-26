# Impingement Cascade Integration — Five Design Specifications

**Status:** Design (implementation specifications)
**Date:** 2026-03-25
**Builds on:** Impingement-Driven Activation Cascade, DMN Architecture, Voice Pipeline Audit

---

## Design Space 1: Spontaneous Speech Path

### Problem
SpeechProductionCapability exists but is dead code. No mechanism to trigger speech without operator address.

### Solution
Wire capability into cognitive loop with impingement consumption.

### Implementation

**Step 1: Instantiate capability in voice daemon** (`__main__.py` ~line 300)
```python
from agents.hapax_voice.capability import SpeechProductionCapability
self._speech_capability = SpeechProductionCapability()
self._cognitive_loop._speech_capability = self._speech_capability
```

**Step 2: Add polling in cognitive loop** (`cognitive_loop.py` after line 183)
```python
if not _pipeline_busy and hasattr(self, '_speech_capability'):
    imp = self._speech_capability.consume_pending()
    if imp is not None:
        # Route directly to LLM generation, bypassing STT
        asyncio.create_task(
            self._pipeline._generate_and_speak_from_impingement(imp)
        )
```

**Step 3: Add impingement-to-speech bridge** (`conversation_pipeline.py`)
```python
async def _generate_and_speak_from_impingement(self, imp: Impingement) -> None:
    """Generate and speak a spontaneous utterance from an impingement."""
    prompt = f"You notice: {imp.content.get('metric', imp.source)}. "
    prompt += f"Strength: {imp.strength:.1f}. "
    prompt += "If this warrants a brief remark to the operator, say it. If not, say nothing."
    # Route through normal LLM → TTS path
```

**Step 4: Turn phase management** — spontaneous speech only during `MUTUAL_SILENCE`. Never interrupt operator or ongoing speech.

### Files Changed
- `agents/hapax_voice/__main__.py` — instantiate + register capability (~10 lines)
- `agents/hapax_voice/cognitive_loop.py` — add polling after line 183 (~15 lines)
- `agents/hapax_voice/conversation_pipeline.py` — add `_generate_and_speak_from_impingement` (~30 lines)

### Tests
- Capability polling returns None when no pending impingements
- Capability polling returns impingement when activated
- Spontaneous speech blocked during non-MUTUAL_SILENCE phases

---

## Design Space 2: Cross-Daemon Impingement Routing

### Problem
CapabilityRegistry is per-daemon. DMN impingements don't reach voice or fortress daemons.

### Solution
Append-only JSONL log at `/dev/shm/hapax-dmn/impingements.jsonl`. Each daemon polls and filters.

### Implementation

**DMN daemon** (`__main__.py._write_output()`):
```python
IMPINGEMENTS_FILE = DMN_STATE_DIR / "impingements.jsonl"

def _write_output(self) -> None:
    # ... existing buffer + status writes ...
    impingements = self._pulse.drain_impingements()
    if impingements:
        with IMPINGEMENTS_FILE.open("a", encoding="utf-8") as f:
            for imp in impingements:
                f.write(imp.model_dump_json() + "\n")
```

**Fortress daemon** — read and broadcast fortress-relevant impingements (replace current self-generated impingements with DMN-emitted ones).

**Voice daemon** — background coroutine polling every 100-500ms:
```python
async def _impingement_consumer_loop(self):
    cursor = 0
    while self._running:
        for line in read_since(IMPINGEMENTS_FILE, cursor):
            imp = Impingement.model_validate_json(line)
            if self._speech_capability.can_resolve(imp) > 0.0:
                self._speech_capability.activate(imp, level)
        await asyncio.sleep(0.1)
```

### Latency
- Fortress: 2.0-2.1s (within 2-5s requirement)
- Voice: 100-500ms (meets sub-second requirement)

### Files Changed
- `agents/dmn/__main__.py` — write impingements.jsonl (~10 lines)
- `agents/fortress/__main__.py` — read from JSONL instead of self-generating (~20 lines)
- `agents/hapax_voice/__main__.py` — background consumer loop (~40 lines)

---

## Design Space 3: Reactive Engine as Cascade Broadcaster

### Problem
The reactive engine (logos/engine/) uses trigger_filter/produce rules. The impingement cascade uses can_resolve/activate capabilities. These are structurally isomorphic but use different protocols.

### Solution
Non-breaking migration: add a ChangeEvent→Impingement converter and RuleCapability wrapper. Existing rules stay as-is.

### Architecture

```
Filesystem event → DirectoryWatcher (unchanged)
    ↓
ChangeEvent (unchanged)
    ↓
[NEW] ChangeEventConverter → Impingement
    ↓
CapabilityRegistry.broadcast() → RuleCapability.can_resolve()
    ↓
RuleCapability.activate() → produce() → Action
    ↓
PhasedExecutor (unchanged)
```

### Structural Mapping

| Current | Cascade | Similarity |
|---------|---------|------------|
| ChangeEvent | Impingement | 85% — add strength, type |
| trigger_filter → bool | can_resolve → float | 90% — bool becomes score |
| produce → list[Action] | activate → result | 70% — same logic |
| Phase 0/1/2 | activation_cost 0.0/0.5/1.0 | 95% — direct mapping |
| Cooldown | Inhibition of return | 85% — same mechanism |

### What Stays As-Is
- All 13 existing rules (trigger_filter, produce functions)
- PhasedExecutor (semaphore-bounded concurrency)
- Filesystem watcher (inotify/watchdog)
- Audit log + history ring buffer
- Novelty detection + pattern counters

### Files Changed
- `logos/engine/converter.py` — NEW: ChangeEvent→Impingement (~100 lines)
- `logos/engine/rule_capability.py` — NEW: Rule→Capability wrapper (~80 lines)
- `logos/engine/__init__.py` — integrate converter + broadcast (~50 lines modified)
- Tests — converter + registry roundtrip (~200 lines)

### Code Volume
~450 lines new, ~70 lines modified, 0 lines deleted.

---

## Design Space 4: Sensor Backend Protocol

### Problem
14 timer-driven sync agents poll on fixed schedules. They produce data but don't emit impingements. The DMN can't consume their output without filesystem polling.

### Decision
**Sensors stay as sensors** — they are data producers, not capability consumers. They adopt a hybrid SensorBackend protocol parallel to PerceptionBackend.

### Protocol

```python
class SensorBackend(Protocol):
    name: str
    affordance_signature: frozenset[str]
    dimension_keys: dict[str, str]  # affordance → profile dimension
    tier: SensorTier  # FAST | MODERATE | SLOW | EVENT
    shm_write_path: Path | None

    def poll(self) -> dict[str, Any] | None  # None = no change
    def drain_impingements(self) -> list[Impingement]  # change notifications
```

### Key Design Decision
Sensors emit **low-strength impingements** (strength=0.3) on data change. These notify downstream agents (profiler, briefing, nudge engine) that profile data refreshed, without flooding the cascade with high-priority signals.

### /dev/shm Layout
```
/dev/shm/hapax-sensors/
├── gmail.json
├── gcalendar.json
├── chrome.json
└── ... (per-agent state snapshot)
```

### Migration Priority

| Tier | Agents | Effort |
|------|--------|--------|
| 1 (highest impact) | stimmung_sync, gcalendar_sync, chrome_sync | ~7h |
| 2 (medium) | gmail_sync, gdrive_sync, watch_receiver | ~7h |
| 3 (defer) | git, youtube, obsidian, langfuse, claude_code, weather | ~14h |

### Manifest Extension
Add `sensor_metadata` field to AgentManifest YAML with affordance_signature, dimension_keys, tier, shm_write_path, activation_cost.

---

## Design Space 5: Anti-Correlation & Resource Arbitration

### Problem
`set_tpn_active()` exists in DMN but is never called. GPU contention theoretically possible between DMN, voice, and vision.

### Finding
**Anti-correlation is not currently needed for resource safety.** RTX 3090 has 16GB free with all models resident (DMN 3.3GB + Whisper 2.4GB + Kokoro 1GB + vision 2.5GB + embedding 1GB + compositor 2GB = 12.2GB of 24GB = 51% utilization). Existing VRAM watchdog handles overflow at 85%+.

### Minimal Implementation (architecturally valuable, not resource-critical)

**Voice → DMN signal via /dev/shm flag file:**
```python
# Voice daemon: when conversation starts
Path("/dev/shm/hapax-dmn/tpn_active").write_text("1")
# When conversation ends
Path("/dev/shm/hapax-dmn/tpn_active").write_text("0")

# DMN daemon: check each tick
tpn_flag = Path("/dev/shm/hapax-dmn/tpn_active")
active = tpn_flag.exists() and tpn_flag.read_text().strip() == "1"
self._pulse.set_tpn_active(active)
```

**Effect:** DMN slows from 5s→10s sensory, 30s→60s evaluative during voice conversation. Reduces Ollama inference frequency by 50%.

### Files Changed
- `agents/hapax_voice/__main__.py` — write flag on conversation start/end (~10 lines)
- `agents/dmn/__main__.py` — read flag each tick (~5 lines)

### GPU Semaphore Extension (deferred)
Extend GPU semaphore to guard all GPU operations only when VRAM watchdog hits 85%+ in production. Currently unnecessary — 16GB headroom is sufficient.

---

## Implementation Ordering

### Phase 0 (Foundation — DONE)
- ✅ Impingement data type
- ✅ CapabilityRegistry
- ✅ DMN anti-habituation thresholds
- ✅ Fortress governance Capability
- ✅ Speech production Capability (defined, not wired)
- ✅ DMN buffer in voice VOLATILE band
- ✅ DMN buffer in fortress deliberation prompt

### Phase 1 (Critical Path — next)
1. **Cross-daemon routing** (Design Space 2) — DMN writes impingements.jsonl
2. **Spontaneous speech wiring** (Design Space 1) — cognitive loop consumes impingements
3. **Anti-correlation signal** (Design Space 5) — voice→DMN flag file

### Phase 2 (Architecture Migration)
4. **Reactive engine migration** (Design Space 3) — converter + wrapper, non-breaking
5. **Sensor Tier 1 migration** (Design Space 4) — stimmung, gcalendar, chrome

### Phase 3 (Expression + Perception)
6. **Perception backends as impingement sources** (Design Space 6)
7. **Shader graph as expression capability** (Design Space 7)

### Phase 4 (Completeness)
8. Sensor Tier 2+3 migration
9. GPU semaphore extension (if needed)
10. Thompson Sampling feedback loop
11. Affordance landscape pre-computation

---

## Design Space 6: Perception Backends as Impingement Sources

### Problem
23 perception backends produce EnvironmentState snapshots but no typed Impingements. BOCPD already detects statistical deviations. Presence transitions are already tracked. But none emit Impingement objects for the cascade.

### Solution
Each backend tracks previous state and emits Impingements at its `contribute()` call site on deviation, threshold breach, or state transition.

### Backend Classification

**PATTERN_MATCH emitters (state transitions) — 5 backends, trivial migration:**
- presence_engine: PRESENT↔AWAY → `operator_arrival`, `operator_departure`
- phone_calls: active flag flip → `phone_call_incoming`
- midi_clock: transport start/stop → `music_production_started/stopped`
- input_activity: idle timeout → `user_idle_state`
- watch: stress_elevated flip → `physiological_stress_spike`

**ABSOLUTE_THRESHOLD emitters (out-of-bounds) — 3 backends, moderate:**
- phone_awareness: battery < 10% → `phone_battery_critical`
- stream_health: dropped_frames > 2% → `stream_quality_degraded`
- health: health_ratio < 0.9 → `system_health_degraded`

**STATISTICAL_DEVIATION emitters (change from running mean) — 5 backends, moderate:**
- speech_emotion: emotion change → `emotion_state_change`
- studio_ingestion: activity mode shift → `activity_mode_change`
- attention: engagement drop → `attention_disengagement`
- watch: HR spike > 20bpm → `heart_rate_spike`
- local_llm: confidence drop → `activity_uncertain`

### Implementation
Add `_pending_impingements` list to PerceptionEngine. Each backend's `contribute()` appends impingements when state changes. After each tick, drain and write to `/dev/shm/hapax-dmn/impingements.jsonl` (same transport as cross-daemon routing).

### Files Changed
- `agents/hapax_voice/perception.py` — add impingement drain (~20 lines)
- 5 trivial backends — ~10-20 lines each
- 6 moderate backends — ~30-60 lines each

---

## Design Space 7: Shader Graph as Expression Capability

### Problem
The compositor's effects system is disconnected from the impingement cascade. Stimmung dimensions don't drive shader parameters. The effect node graph (40 shaders, uniform modulation, crossfade engine) has no impingement input.

### Solution
Register `ShaderGraphCapability` with dual affordances: parameter modulation (continuous) and topology mutation (discrete transitions). The uniform modulation system maps impingement strength directly to shader parameters.

### Capability Profile
```
name: "shader_graph"
affordances: visual_expression, visual_calm, visual_alert,
             visual_fatigue_response, visual_energy_alignment,
             visual_resource_shedding, preset_switch
activation_cost: 0.3
consent_required: False
```

### Stimmung → Shader Parameter Matrix

| Dimension | Parameters | Effect |
|-----------|-----------|--------|
| operator_stress | warmth +0.1, speed ×0.7, brightness -0.05 | Warm, slow, dim (restorative) |
| operator_energy | speed ×(1-e×0.2), hue +e×10 | Low energy = slow + warm |
| health (failing) | saturation +0.2, breathing 1.5s | Oversaturate + alert |
| resource_pressure | shed bloom/pixsort, reduce resolution | GPU constraint = simplify |
| grounding_quality (poor) | reduce modulation range ×0.7 | Conservative, smooth |

### Stimmung Stance → Layer Palette
NOMINAL → CAUTIOUS → DEGRADED → CRITICAL mapped to saturation (1.0→0.5), brightness (1.0→0.85), sepia (0→0.2). Lerped over 300ms via crossfade engine.

### Graduated Activation
`level` (0.0-1.0) scales all modulation ranges: `actual = baseline + (target - baseline) × level`. Ensures smooth graduation, not binary switching.

### Integration with Effect Node Graph Phase 1
UniformModulator's binding registry maps impingement signals to shader uniforms directly. Crossfade engine handles topology transitions. Three persistent layers provide state continuity. ShaderGraphCapability registers bindings at initialization — no per-frame impingement processing needed.

### Files Changed
- `agents/effect_graph/capability.py` — NEW: ShaderGraphCapability (~150 lines)
- UniformModulator — add impingement-sourced bindings (~30 lines)
- Compositor init — register capability (~10 lines)

### Design Language Compliance
- §6 breathing periods match severity ladder ✓
- §3.4 palette values match stance definitions ✓
- §2.2 shaders driven by stimmung, not mode ✓
