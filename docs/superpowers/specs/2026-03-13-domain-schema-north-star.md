# Domain Schema North Star — Hapax Voice

**Date**: 2026-03-13
**Branch**: `feat/multi-role-composition`
**Status**: Living specification

---

## Section 0: Prose Constraint & Notation

Every declarative sentence in this document is a projection of a type sequence.
Sentences that cannot be decomposed are either aspirational (marked `[spec]`) or invalid.

### Status Markers

- `[impl]` — exists in source, referenced by file and line
- `[decl]` — type declared but not wired into a running pipeline
- `[spec]` — specified but unimplemented

### Type Notation

| Notation | Meaning |
|----------|---------|
| `T → U` | Function or transform |
| `T × U` | Product / tuple |
| `T \| None` | Option type |
| `Behavior[T]` | Continuously-available value with monotonic watermark |
| `Event[T]` | Discrete occurrence stream with pub/sub signaling |
| `Stamped[T]` | Immutable snapshot of a value with its freshness watermark |

### Decomposition Example

> "The FreshnessGuard rejects stale perception data before governance reads values."

```
FreshnessGuard.check(ctx: FusedContext, now: float) → FreshnessResult
  where FreshnessResult.fresh_enough = False
  → compose_mc_governance emits None via Event[Schedule | None]
```

Source: `agents/hapax_voice/mc_governance.py:226-230` `[impl]`

---

## Section 1: Domain Registries

### 1.1 Behavior Registry

All `Behavior[T]` instances in the system. Governance chains sample these via `with_latest_from`.

#### PerceptionEngine Core Behaviors

| Name | Type | Source | Status |
|------|------|--------|--------|
| `vad_confidence` | `Behavior[float]` | `perception.py:197` | `[impl]` |
| `operator_present` | `Behavior[bool]` | `perception.py:198` | `[impl]` |
| `face_count` | `Behavior[int]` | `perception.py:199` | `[impl]` |
| `activity_mode` | `Behavior[str]` | `perception.py:187` | `[impl]` |
| `workspace_context` | `Behavior[str]` | `perception.py:188` | `[impl]` |
| `active_window` | `Behavior[WindowInfo \| None]` | `perception.py:191` | `[impl]` |
| `window_count` | `Behavior[int]` | `perception.py:192` | `[impl]` |
| `active_workspace_id` | `Behavior[int]` | `perception.py:193` | `[impl]` |

#### Cross-Role State Behaviors

| Name | Type | Source | Status |
|------|------|--------|--------|
| `mc_state` | `Behavior[GovernanceChainState]` | `chain_state.py:48` | `[impl]` |
| `conversation_state` | `Behavior[ConversationState]` | `chain_state.py:49` | `[impl]` |
| `current_scene` | `Behavior[str]` | `chain_state.py:50` | `[impl]` |
| `conversation_suppression` | `Behavior[float]` | `chain_state.py:51` | `[impl]` |
| `mc_activity` | `Behavior[float]` | `chain_state.py:52` | `[impl]` |
| `monitoring_alert` | `Behavior[float]` | `chain_state.py:53` | `[impl]` |

#### Feedback Behaviors

| Name | Type | Source | Status |
|------|------|--------|--------|
| `last_mc_fire` | `Behavior[float]` | `feedback.py:27` | `[impl]` |
| `mc_fire_count` | `Behavior[int]` | `feedback.py:28` | `[impl]` |
| `last_obs_switch` | `Behavior[float]` | `feedback.py:29` | `[impl]` |
| `last_tts_end` | `Behavior[float]` | `feedback.py:30` | `[impl]` |

#### Musical Position

| Name | Type | Source | Status |
|------|------|--------|--------|
| `musical_position` | `Behavior[MusicalPosition]` | `musical_position.py:62` | `[impl]` |

#### SuppressionField-Wrapped Behaviors

Each SuppressionField exposes a `Behavior[float]` via its `.behavior` property. The three cross-role suppression signals from `chain_state.py` (`conversation_suppression`, `mc_activity`, `monitoring_alert`) are intended targets for SuppressionField wrapping.

| Name | Type | Source | Status |
|------|------|--------|--------|
| `SuppressionField.behavior` | `Behavior[float]` | `suppression.py:42-43` | `[impl]` |

#### Source-Qualified Behaviors (Wiring Layer)

Governance chains read bare names (e.g., `audio_energy_rms`). The wiring layer resolves these to source-qualified Behaviors via `GovernanceBinding`.

| Bare Name | Qualified Form | Source | Status |
|-----------|----------------|--------|--------|
| `audio_energy_rms` | `audio_energy_rms:{source_id}` | `wiring.py:126` | `[decl]` |
| `audio_onset` | `audio_onset:{source_id}` | `wiring.py:126` | `[decl]` |
| `emotion_valence` | `emotion_valence:{source_id}` | `wiring.py:133` | `[decl]` |
| `emotion_arousal` | `emotion_arousal:{source_id}` | `wiring.py:133` | `[decl]` |
| `emotion_dominant` | `emotion_dominant:{source_id}` | `wiring.py:133` | `[decl]` |
| `timeline_mapping` | (unqualified) | `wiring.py:61` | `[impl]` |
| `vad_confidence` | (unqualified) | `wiring.py:61` | `[impl]` |

#### Backend-Provided Behaviors

| Name | Type | Backend | Tier | Status |
|------|------|---------|------|--------|
| `stream_bitrate` | `Behavior[float]` | StreamHealthBackend | SLOW | `[impl]` |
| `stream_dropped_frames` | `Behavior[float]` | StreamHealthBackend | SLOW | `[impl]` |
| `stream_encoding_lag` | `Behavior[float]` | StreamHealthBackend | SLOW | `[impl]` |
| `timeline_mapping` | `Behavior[TimelineMapping]` | MidiClockBackend | EVENT | `[impl]` |
| `beat_position` | `Behavior[float]` | MidiClockBackend | EVENT | `[impl]` |
| `bar_position` | `Behavior[int]` | MidiClockBackend | EVENT | `[impl]` |
| `heart_rate_bpm` | `Behavior[float]` | WatchBackend | SLOW | `[impl]` |
| `hrv_rmssd_ms` | `Behavior[float]` | WatchBackend | SLOW | `[impl]` |
| `stress_elevated` | `Behavior[bool]` | WatchBackend | SLOW | `[impl]` |
| `physiological_load` | `Behavior[float]` | WatchBackend | SLOW | `[impl]` |
| `watch_activity_state` | `Behavior[str]` | WatchBackend | SLOW | `[impl]` |
| `sleep_quality` | `Behavior[float]` | WatchBackend | SLOW | `[impl]` |
| `system_health_status` | `Behavior[str]` | HealthBackend | SLOW | `[impl]` |
| `system_health_ratio` | `Behavior[float]` | HealthBackend | SLOW | `[impl]` |
| `active_window_class` | `Behavior[str]` | HyprlandBackend | EVENT | `[impl]` |
| `circadian_alignment` | `Behavior[float]` | CircadianBackend | SLOW | `[impl]` |
| `sink_volume` | `Behavior[float]` | PipeWireBackend | FAST | `[impl]` |
| `midi_active` | `Behavior[bool]` | PipeWireBackend | FAST | `[impl]` |

### 1.2 Event Registry

All `Event[T]` streams. Events are discrete occurrences with pub/sub signaling.

| Name | Type | Producer | Consumer(s) | Status |
|------|------|----------|-------------|--------|
| `trigger` (MC) | `Event[float]` | MidiClockBackend tick | `compose_mc_governance` via `with_latest_from` | `[impl]` |
| `trigger` (OBS) | `Event[float]` | Perception tick | `compose_obs_governance` via `with_latest_from` | `[impl]` |
| `fused` (MC) | `Event[FusedContext]` | `with_latest_from(trigger, behaviors)` | MC governance `_on_fused` | `[impl]` |
| `fused` (OBS) | `Event[FusedContext]` | `with_latest_from(trigger, behaviors)` | OBS governance `_on_fused` | `[impl]` |
| `mc_output` | `Event[Schedule \| None]` | `compose_mc_governance` | `_on_mc_schedule` in `__main__.py:296` | `[impl]` |
| `obs_output` | `Event[Command \| None]` | `compose_obs_governance` | `_on_obs_command` in `__main__.py:326` | `[impl]` |
| `actuation_event` | `Event[ActuationEvent]` | `ExecutorRegistry.dispatch` | `wire_feedback_behaviors` | `[impl]` |
| `wake_word_event` | `Event[None]` | `_on_wake_word` | (extension point) | `[impl]` |
| `focus_event` | `Event[FocusEvent]` | Hyprland IPC | (extension point) | `[impl]` |
| `CadenceGroup.tick_event` | `Event[float]` | `CadenceGroup.poll` | `with_latest_from` | `[impl]` |

### 1.3 Executor Registry

All `Executor` handles. Each executor maps action names to physical actuation.

| Name | Domain | Handles | Source | Status |
|------|--------|---------|--------|--------|
| `AudioExecutor` | `audio_output` | `{"vocal_throw", "ad_lib"}` | `__main__.py:279` | `[impl]` |
| `OBSExecutor` | `obs_scene` | `{"wide_ambient", "gear_closeup", "face_cam", "rapid_cut"}` | `__main__.py:314` | `[impl]` |

Executor protocol: `agents/hapax_voice/executor.py:23-46` `[impl]`

```
Executor.name → str
Executor.handles → frozenset[str]
Executor.execute(command: Command) → None
Executor.available() → bool
Executor.close() → None
```

---

## Section 2: Governance Compositions

### 2.1 MC Governance Chain

The MC governance chain evaluates whether and how to interject during a live musical performance. It produces beat-aligned `Schedule` objects for future actuation.

```
Event[float]
  → with_latest_from(trigger, behaviors) → Event[FusedContext]
  → FreshnessGuard.check(ctx, now) → FreshnessResult
  → VetoChain[FusedContext].evaluate(ctx) → VetoResult
  → FallbackChain[FusedContext, MCAction].select(ctx) → Selected[MCAction]
  → TimelineMapping.beat_at_time(timestamp) → float
  → TimelineMapping.time_at_beat(target_beat) → float
  → Command(action, trigger_time, trigger_source, min_watermark, governance_result, selected_by)
  → Schedule(command, domain="beat", target_time, wall_time)
```

Source: `agents/hapax_voice/mc_governance.py:199-272` `[impl]`

**VetoChain** (4 vetoes, deny-wins, order-independent):

| Veto | Predicate | Axiom | Source |
|------|-----------|-------|--------|
| `speech_clear` | `vad_confidence < threshold` | — | `mc_governance.py:62-64` |
| `energy_sufficient` | `audio_energy_rms >= effective_threshold(base, suppression)` | — | `mc_governance.py:67-80` |
| `spacing_respected` | `trigger_time - last_throw_time >= cooldown_s` | — | `mc_governance.py:83-93` |
| `transport_active` | `timeline_mapping.transport is PLAYING` | — | `mc_governance.py:96-99` |

**FallbackChain** (priority-ordered, first eligible wins):

| Priority | Candidate | Condition | Action |
|----------|-----------|-----------|--------|
| 1 | `vocal_throw` | `energy >= 0.7 AND arousal >= 0.6` | `MCAction.VOCAL_THROW` |
| 2 | `ad_lib` | `energy >= 0.3 AND arousal >= 0.3` | `MCAction.AD_LIB` |
| — | default | always | `MCAction.SILENCE` |

### 2.2 OBS Governance Chain

The OBS governance chain selects camera scenes at perception cadence. It produces immediate `Command` objects (no scheduling).

```
Event[float]
  → with_latest_from(trigger, behaviors) → Event[FusedContext]
  → FreshnessGuard.check(ctx, now) → FreshnessResult
  → VetoChain[FusedContext].evaluate(ctx) → VetoResult
  → FallbackChain[FusedContext, OBSScene].select(ctx) → Selected[OBSScene]
  → select_transition(ctx, cfg) → OBSTransition
  → Command(action, params={transition: OBSTransition}, trigger_time, trigger_source,
            min_watermark, governance_result, selected_by)
```

Source: `agents/hapax_voice/obs_governance.py:245-312` `[impl]`

**VetoChain** (4 vetoes, deny-wins, order-independent):

| Veto | Predicate | Axiom | Source |
|------|-----------|-------|--------|
| `dwell_time_respected` | `trigger_time - last_switch_time >= min_dwell_s` | — | `obs_governance.py:80-89` |
| `stream_health_sufficient` | `stream_bitrate >= min_bitrate_kbps` | — | `obs_governance.py:92-94` |
| `encoding_capacity_available` | `stream_encoding_lag <= max_lag_ms` | — | `obs_governance.py:97-99` |
| `transport_active` | `timeline_mapping.transport is PLAYING` | — | `obs_governance.py:102-105` |

**FallbackChain** (priority-ordered, first eligible wins):

| Priority | Candidate | Condition | Action |
|----------|-----------|-----------|--------|
| 1 | `rapid_cut` | `energy >= 0.8 AND arousal >= 0.7` | `OBSScene.RAPID_CUT` |
| 2 | `face_cam_mc_bias` | `_mc_fired_recently(ctx) AND energy >= 0.5` | `OBSScene.FACE_CAM` |
| 3 | `face_cam` | `energy >= 0.5 AND arousal >= 0.5` | `OBSScene.FACE_CAM` |
| 4 | `gear_closeup` | `energy >= 0.2` | `OBSScene.GEAR_CLOSEUP` |
| — | default | always | `OBSScene.WIDE_AMBIENT` |

### 2.3 Cross-Chain Interactions

**SuppressionField modulation**: SuppressionField wraps a Behavior[float] with attack/release envelope. Governance reads the suppression value and adjusts thresholds.

```
SuppressionField.set_target(level: float, now: float) → None
  → SuppressionField.tick(now: float) → float
  → Behavior[float].update(new_value, now)
  → effective_threshold(base: float, suppression: float) → float
    where threshold_eff = base + suppression × (1.0 - base)
```

Source: `agents/hapax_voice/suppression.py:14-101` `[impl]`

**Resource contention**: When multiple governance chains claim the same physical resource, the ResourceArbiter resolves by static priority.

```
ResourceClaim(resource, chain, priority, command, hold_until, max_hold_s, created_at)
  → ResourceArbiter.claim(rc) → None
  → ResourceArbiter.drain_winners(now) → list[ResourceClaim]
  → ExecutorRegistry.dispatch(winner.command, schedule) → bool
```

Source: `agents/hapax_voice/arbiter.py:17-125` `[impl]`

Priority map (`resource_config.py:20-29`):

| Resource | Chain | Priority |
|----------|-------|----------|
| `audio_output` | `conversation` | 100 |
| `audio_output` | `mc` | 50 |
| `audio_output` | `tts` | 30 |
| `obs_scene` | `conversation` | 100 |
| `obs_scene` | `obs` | 70 |
| `obs_scene` | `mc` | 40 |

**Feedback loop**: Actuation events feed back into Behaviors that governance chains read on the next tick.

```
ExecutorRegistry.dispatch(command) → bool
  → ActuationEvent(action, chain, wall_time, target_time, latency_ms, params)
  → Event[ActuationEvent].emit(now, event)
  → wire_feedback_behaviors subscriber updates:
    - last_mc_fire: Behavior[float]
    - mc_fire_count: Behavior[int]
    - last_obs_switch: Behavior[float]
    - last_tts_end: Behavior[float]
  → next tick: with_latest_from samples feedback Behaviors into FusedContext
  → OBS FallbackChain reads last_mc_fire via _mc_fired_recently(ctx)
```

Source: `agents/hapax_voice/feedback.py:18-48`, `executor.py:127-154` `[impl]`

---

## Section 3: Constitutional Layer

### 3.1 Axiom → Type Mapping

| Axiom | Weight | Scope | Type-Level Enforcement |
|-------|--------|-------|----------------------|
| `single_user` | 100 | constitutional | No `User` type exists. No auth middleware. `Executor` assumes trusted caller. `PerceptionBackend` assumes single operator. |
| `executive_function` | 95 | constitutional | `SuppressionField` (smooth degradation, not abrupt cutoff). `FallbackChain` (always has default — `MCAction.SILENCE`, `OBSScene.WIDE_AMBIENT`). `FreshnessGuard` (stale → safe: emit `None`, never stale action). `compute_interruptibility` gates proactive delivery. |
| `interpersonal_transparency` | 88 | constitutional | `ConsentContract` gates person-linked Behaviors. `ConsentRegistry.contract_check(person_id, data_category) → bool` enforced at ingestion boundary. |
| `corporate_boundary` | 90 | domain:infrastructure | `get_model()` routes through LiteLLM. No direct provider imports in governance or perception. |
| `management_governance` | 85 | domain:management | No `Feedback` or `CoachingRecommendation` types exist in the voice domain. |

Source: `axioms/registry.yaml:1-80` `[impl]`, `shared/consent.py:24-38` `[impl]`

### 3.2 Consent-Gated Data Flows

The interpersonal_transparency axiom requires explicit consent before the system maintains persistent state about non-operator persons.

```
ConsentContract(id, parties: tuple[str, str], scope: frozenset[str],
                direction, visibility_mechanism, created_at, revoked_at)
  → ConsentRegistry.contract_check(person_id: str, data_category: str) → bool
  → gate on Behavior reads at perception ingestion boundary
```

Source: `shared/consent.py:24-99` `[impl]`

**Enforcement boundary**: `contract_check()` must be called at ingestion, not downstream. Any `PerceptionBackend` or data pathway handling non-operator person data must call `contract_check()` before persisting state.

**Revocation**: `ConsentRegistry.purge_subject(person_id) → list[str]` marks contracts as revoked. Contract records are retained for audit (immutable `revoked_at` timestamp). Data purge is the caller's responsibility.

---

## Section 4: Perception Backends as Domain Providers

Each `PerceptionBackend` populates a subset of the Behavior registry. Registration is availability-gated: `backend.available() → False` skips registration silently.

| Backend | Behaviors Provided | Tier | Cadence | Status |
|---------|--------------------|------|---------|--------|
| `PipeWireBackend` | `sink_volume`, `midi_active` | FAST | ~2.5s | `[impl]` |
| `HyprlandBackend` | `active_window_class` | EVENT | IPC-driven | `[impl]` |
| `WatchBackend` | `heart_rate_bpm`, `hrv_rmssd_ms`, `stress_elevated`, `physiological_load`, `watch_activity_state`, `sleep_quality` | SLOW | ~12s | `[impl]` |
| `HealthBackend` | `system_health_status`, `system_health_ratio` | SLOW | ~12s | `[impl]` |
| `CircadianBackend` | `circadian_alignment` | SLOW | ~12s | `[impl]` |
| `MidiClockBackend` | `timeline_mapping`, `beat_position`, `bar_position` | EVENT | MIDI clock | `[impl]` |
| `StreamHealthBackend` | `stream_bitrate`, `stream_dropped_frames`, `stream_encoding_lag` | SLOW | ~12s | `[impl]` |
| Audio energy backend | `audio_energy_rms:{src}`, `audio_onset:{src}` | FAST | wiring-layer cadence | `[decl]` |
| Emotion backend | `emotion_valence:{src}`, `emotion_arousal:{src}`, `emotion_dominant:{src}` | FAST | wiring-layer cadence | `[decl]` |
| Face identity resolver | `operator_identity` | FAST | per-frame | `[spec]` |
| Spatial backend | `spatial_frame` | EVENT | sensor-driven | `[spec]` |

PerceptionBackend protocol: `agents/hapax_voice/perception.py:34-71` `[impl]`

```
PerceptionBackend.name → str
PerceptionBackend.provides → frozenset[str]
PerceptionBackend.tier → PerceptionTier
PerceptionBackend.available() → bool
PerceptionBackend.contribute(behaviors: dict[str, Behavior]) → None
PerceptionBackend.start() → None
PerceptionBackend.stop() → None
```

Registration in `__main__.py:354-402` `[impl]`:
- PipeWireBackend, HyprlandBackend, WatchBackend, HealthBackend, CircadianBackend, MidiClockBackend — all availability-gated with try/except.

---

## Section 5: Validation Traces

### Trace 1: MC fires during conversation suppression

SuppressionField raises the effective energy threshold. If audio energy is below the raised threshold, the VetoChain denies MC actuation.

```
SuppressionField.set_target(0.8, t0) → None
  → SuppressionField.tick(t1) → 0.4    [attack ramp: 0.0 → 0.8, partial at t1]
  → Behavior[float].update(Stamped(0.4, t1))
  → with_latest_from(tick, behaviors) → Event[FusedContext]
  → FusedContext.get_sample("conversation_suppression") → Stamped(0.4, t1)
  → energy_sufficient(ctx, effective_threshold(0.3, 0.4))
    where effective_threshold = 0.3 + 0.4 × (1.0 - 0.3) = 0.58
  → ctx.get_sample("audio_energy_rms").value = 0.45 < 0.58
  → VetoChain.evaluate(ctx) → VetoResult(allowed=False, denied_by=("energy_sufficient",))
  → compose_mc_governance emits None via Event[Schedule | None]
```

Types exercised: `SuppressionField`, `Behavior[float]`, `Stamped[float]`, `FusedContext`, `VetoChain[FusedContext]`, `VetoResult`, `Event[Schedule | None]`

### Trace 2: Resource contention between MC and OBS

Both governance chains fire simultaneously. The ResourceArbiter resolves by priority: MC wins `audio_output`, OBS wins `obs_scene`.

```
compose_mc_governance → Schedule(command=Command(action="vocal_throw", ...), domain="beat", ...)
  → ScheduleQueue.enqueue(schedule) → None
  → ScheduleQueue.drain(now) → list[Schedule]
  → ResourceClaim(resource="audio_output", chain="mc", priority=50, command=cmd)
  → ResourceArbiter.claim(rc) → None

compose_obs_governance → Command(action="face_cam", params={transition: "cut"}, ...)
  → ResourceClaim(resource="obs_scene", chain="obs", priority=70, command=cmd)
  → ResourceArbiter.claim(rc) → None

ResourceArbiter.drain_winners() → [rc_audio_mc, rc_obs_scene]
  → ExecutorRegistry.dispatch(rc_audio_mc.command, schedule) → True
  → ExecutorRegistry.dispatch(rc_obs_scene.command) → True
  → ActuationEvent(action="vocal_throw", chain="mc", wall_time=t, ...) emitted
  → ActuationEvent(action="face_cam", chain="obs", wall_time=t, ...) emitted
```

Types exercised: `Schedule`, `Command`, `ScheduleQueue`, `ResourceClaim`, `ResourceArbiter`, `ExecutorRegistry`, `ActuationEvent`, `Event[ActuationEvent]`

### Trace 3: Feedback loop closes (MC fire → OBS face_cam bias)

An MC actuation event feeds back into Behaviors. On the next OBS governance tick, the `face_cam_mc_bias` candidate gains eligibility because `_mc_fired_recently` returns True.

```
ExecutorRegistry.dispatch(Command(action="vocal_throw", ...)) → True
  → ActuationEvent(action="vocal_throw", chain="mc", wall_time=t)
  → Event[ActuationEvent].emit(t, event)
  → wire_feedback_behaviors._on_actuation:
    → last_mc_fire: Behavior[float].update(t, t)
    → mc_fire_count: Behavior[int].update(count + 1, t)

  [next OBS tick at t + 1.5s]
  → with_latest_from(obs_tick, behaviors) → FusedContext
  → FusedContext.get_sample("last_mc_fire") → Stamped(t, t)
  → _mc_fired_recently(ctx, window_s=2.0):
    → ctx.trigger_time - t = 1.5 <= 2.0 → True
  → face_cam_mc_bias Candidate.predicate(ctx) → True
  → FallbackChain.select(ctx) → Selected(action=OBSScene.FACE_CAM, selected_by="face_cam_mc_bias")
```

Types exercised: `ActuationEvent`, `Event[ActuationEvent]`, `Behavior[float]`, `Behavior[int]`, `FusedContext`, `Stamped[float]`, `FallbackChain[FusedContext, OBSScene]`, `Selected[OBSScene]`

### Trace 4: Consent gate blocks person-linked perception

A face identity resolver (when implemented) detects a non-operator person. The ConsentRegistry blocks persisting their biometric data.

```
  [spec] face_identity_resolver detects person_id="visitor_1"
  → ConsentRegistry.contract_check("visitor_1", "biometric") → False
  → Behavior[OperatorIdentity] NOT updated with visitor data
  → governance chains see only operator-identified signals
```

Types exercised: `ConsentRegistry`, `ConsentContract` `[impl]`, face identity resolver `[spec]`

---

## Section 6: Domain Completeness

### 6.1 Coverage Matrix

| Behavior | Sourced by Backend | Read by Governance | Validated by Trace |
|----------|--------------------|--------------------|--------------------|
| `vad_confidence` | PerceptionEngine (VAD) | MC: `speech_clear` | — |
| `audio_energy_rms` | (wiring layer) | MC: `energy_sufficient`, FallbackChains | Trace 1 |
| `emotion_arousal` | (wiring layer) | MC + OBS FallbackChains | — |
| `emotion_valence` | (wiring layer) | — | — |
| `emotion_dominant` | (wiring layer) | — | — |
| `timeline_mapping` | MidiClockBackend | MC + OBS: `transport_active` | — |
| `stream_bitrate` | StreamHealthBackend | OBS: `stream_health_sufficient` | — |
| `stream_encoding_lag` | StreamHealthBackend | OBS: `encoding_capacity_available` | — |
| `conversation_suppression` | cross-role state | MC: `effective_threshold` | Trace 1 |
| `last_mc_fire` | feedback loop | OBS: `_mc_fired_recently` | Trace 3 |
| `mc_fire_count` | feedback loop | — | Trace 3 |
| `last_obs_switch` | feedback loop | — | — |
| `last_tts_end` | feedback loop | — | — |
| `mc_state` | cross-role state | — | — |
| `conversation_state` | cross-role state | — | — |
| `current_scene` | cross-role state | — | — |
| `mc_activity` | cross-role state | — | — |
| `monitoring_alert` | cross-role state | — | — |
| `musical_position` | `update_musical_position` | — | — |
| `operator_present` | PerceptionEngine | `compute_interruptibility` | — |
| `heart_rate_bpm` | WatchBackend | — | — |
| `physiological_load` | WatchBackend | `compute_interruptibility` | — |
| `circadian_alignment` | CircadianBackend | `compute_interruptibility` | — |
| `system_health_ratio` | HealthBackend | `compute_interruptibility` | — |
| `sleep_quality` | WatchBackend | proactive delivery threshold | — |
| `sink_volume` | PipeWireBackend | — | — |
| `midi_active` | PipeWireBackend | — | — |

### 6.2 Open Edges

**`[decl]` — typed but unwired**:
- `audio_energy_rms`, `audio_onset` — governance reads these, but no concrete `AudioEnergyBackend` exists. The wiring layer declares source-qualified forms; the `BackendType.AUDIO_ENERGY` enum exists but no class implements it.
- `emotion_valence`, `emotion_arousal`, `emotion_dominant` — same pattern. `BackendType.EMOTION` declared, no implementation.
- `emotion_valence`, `emotion_dominant` — declared in wiring aliases, never read by any governance chain.
- `mc_state`, `conversation_state`, `current_scene`, `mc_activity`, `monitoring_alert` — Behaviors created by `create_cross_role_behaviors()` but no code writes to them at runtime. No publisher exists in `__main__.py`.

**`[spec]` — specified but unimplemented**:
- `SpatialFrame` — hierarchical spatial decomposition analogous to `MusicalPosition`. Specified in `docs/superpowers/specs/2026-03-13-spatial-awareness-research.md`. No source file exists.
- Face identity resolver — referenced in consent gate traces. No `IdentityResolver` type or backend exists.
- `CompoundGoals` — skeletal implementation (`compound_goals.py`). Methods exist but do not wire to governance primitives. `start_live_session` and `end_live_session` are imperative stubs.
- `ResourceArbiter` integration — `ResourceArbiter` and `ResourceClaim` are fully implemented, but `__main__.py` does not instantiate or wire them into the actuation loop. Governance outputs go directly to `ScheduleQueue`/`ExecutorRegistry`.
- Feedback loop wiring — `wire_feedback_behaviors` is implemented but not called in `__main__.py`. The feedback Behaviors exist as types but are not connected to `ExecutorRegistry.actuation_event` at runtime.
- `BackendType.ENERGY_ARC` — enum member declared in `wiring.py:34`, no implementation.

---

## Section 7: Glossary of Type Expressions

| Type | Module | Definition |
|------|--------|------------|
| `ActuationEvent` | `agents/hapax_voice/actuation_event.py:15` | Immutable record of a completed actuation with latency tracking |
| `Behavior[T]` | `agents/hapax_voice/primitives.py:26` | Continuously-available value with monotonic watermark |
| `BackendType` | `agents/hapax_voice/wiring.py:29` | Enum of known backend types for source instantiation |
| `CadenceGroup` | `agents/hapax_voice/cadence.py:22` | Group of backends polled at a shared interval, emits tick Event |
| `Candidate[C, T]` | `agents/hapax_voice/governance.py:129` | Candidate action with eligibility predicate and optional nested VetoChain |
| `Command` | `agents/hapax_voice/commands.py:19` | Inspectable, governable, immutable action description |
| `CompoundGoals` | `agents/hapax_voice/compound_goals.py:16` | Sequences multi-step operational workflows via daemon reference |
| `ConsentContract` | `shared/consent.py:24` | Bilateral consent agreement between operator and subject |
| `ConsentRegistry` | `shared/consent.py:45` | Runtime registry of consent contracts with enforcement boundary |
| `ConversationState` | `agents/hapax_voice/chain_state.py:24` | Enum: IDLE, LISTENING, SPEAKING, PROCESSING |
| `EnvironmentState` | `agents/hapax_voice/perception.py:122` | Immutable snapshot of fused audio-visual environment |
| `Event[T]` | `agents/hapax_voice/primitives.py:59` | Discrete occurrence with pub/sub signaling |
| `Executor` | `agents/hapax_voice/executor.py:23` | Protocol for actuators that handle Commands |
| `ExecutorRegistry` | `agents/hapax_voice/executor.py:98` | Maps action names to Executors, emits ActuationEvent on dispatch |
| `FallbackChain[C, T]` | `agents/hapax_voice/governance.py:143` | Priority-ordered action selection, first eligible candidate wins |
| `FreshnessGuard` | `agents/hapax_voice/governance.py:190` | Rejects decisions made on stale perception data |
| `FreshnessRequirement` | `agents/hapax_voice/governance.py:174` | Minimum freshness required for a specific signal |
| `FreshnessResult` | `agents/hapax_voice/governance.py:182` | Outcome of a FreshnessGuard check |
| `FusedContext` | `agents/hapax_voice/governance.py:21` | Combinator output: trigger event fused with current Behavior values |
| `GatedResult[T]` | `agents/hapax_voice/governance.py:47` | Value wrapped with its VetoResult |
| `GovernanceBinding` | `agents/hapax_voice/wiring.py:51` | Maps bare governance behavior names to source-qualified Behaviors |
| `GovernanceChainState` | `agents/hapax_voice/chain_state.py:15` | Enum: IDLE, ACTIVE, SUPPRESSED, FIRING |
| `MCAction` | `agents/hapax_voice/mc_governance.py:28` | Enum: VOCAL_THROW, AD_LIB, SILENCE |
| `MCConfig` | `agents/hapax_voice/mc_governance.py:37` | Tunable thresholds for MC governance constraints |
| `MusicalPosition` | `agents/hapax_voice/musical_position.py:17` | Hierarchical musical time decomposition (beat, bar, phrase, section) |
| `OBSConfig` | `agents/hapax_voice/obs_governance.py:49` | Tunable thresholds for OBS governance constraints |
| `OBSScene` | `agents/hapax_voice/obs_governance.py:31` | Enum: WIDE_AMBIENT, GEAR_CLOSEUP, FACE_CAM, RAPID_CUT, HOLD |
| `OBSTransition` | `agents/hapax_voice/obs_governance.py:41` | Enum: CUT, DISSOLVE, FADE |
| `PerceptionBackend` | `agents/hapax_voice/perception.py:34` | Protocol for pluggable perception backends |
| `PerceptionEngine` | `agents/hapax_voice/perception.py:165` | Fuses sensor signals into EnvironmentState snapshots |
| `PerceptionTier` | `agents/hapax_voice/perception.py:25` | Enum: FAST, SLOW, EVENT |
| `ResourceArbiter` | `agents/hapax_voice/arbiter.py:33` | Priority-based resource contention resolver |
| `ResourceClaim` | `agents/hapax_voice/arbiter.py:17` | Immutable claim on a physical resource by a governance chain |
| `Schedule` | `agents/hapax_voice/commands.py:40` | Command bound to a specific time in a specific domain |
| `ScheduleQueue` | `agents/hapax_voice/executor.py:49` | Priority queue drained by wall-clock time |
| `Selected[T]` | `agents/hapax_voice/governance.py:122` | Output of a FallbackChain selection |
| `SourceSpec` | `agents/hapax_voice/wiring.py:38` | Declaration of a physical source and its backend type |
| `SpatialFrame` | — | `[spec]` Hierarchical spatial decomposition analogous to MusicalPosition |
| `Stamped[T]` | `agents/hapax_voice/primitives.py:18` | Immutable snapshot of a value with its freshness watermark |
| `SuppressionField` | `agents/hapax_voice/suppression.py:14` | Smooth-ramping suppression signal with attack/release envelope |
| `TimelineMapping` | `agents/hapax_voice/timeline.py:23` | Bijective affine map between wall-clock and an alternate time domain |
| `TransportState` | `agents/hapax_voice/timeline.py:15` | Enum: PLAYING, STOPPED |
| `Veto[C]` | `agents/hapax_voice/governance.py:58` | Single governance constraint with predicate |
| `VetoChain[C]` | `agents/hapax_voice/governance.py:68` | Order-independent deny-wins constraint composition |
| `VetoResult` | `agents/hapax_voice/governance.py:37` | Outcome of a VetoChain evaluation |
| `WiringConfig` | `agents/hapax_voice/wiring.py:65` | Complete wiring specification for multi-source perception |
