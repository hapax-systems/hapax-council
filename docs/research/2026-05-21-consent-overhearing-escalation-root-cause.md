---
title: "Root Cause: ConsentStateTracker / ConsentGatedReader communication gap"
date: 2026-05-21
author: epsilon
status: confirmed
source: CCTV disconfirmation audit 2026-05-18
cc_task: 202605181934-disconfirm-consen-p0-investigate-root-cause
authority_case: CASE-202605181934-DISCONF
---

# Root Cause: ConsentStateTracker / ConsentGatedReader communication gap

## Finding — CONFIRMED

The original adversarial finding is confirmed. Guest-presence state
(`ConsentStateTracker.persistence_allowed`) is never consulted before audio
egress. The gap is **architectural**: no API call connects the tracker to the
voice output pipeline.

## Architecture

Two independent consent subsystems exist:

| System | Gates | Checks |
|--------|-------|--------|
| `ConsentStateTracker` | Data persistence (person-adjacent fields in perception state) | Guest presence via IR/face/speaker detection |
| `ConsentGatedReader` | Text content surfaced to tool results | Contract registry (per-person consent contracts) |

Neither system gates **audio/video egress**. TTS playback, camera frames, and
broadcast audio flow based on stream mode and broadcast authorization, not
guest presence.

## Trace

### ConsentStateTracker

**File**: `agents/hapax_daimonion/consent_state.py`

- `phase` property (line 68): Returns `ConsentPhase` enum
  (`NO_GUEST | GUEST_DETECTED | CONSENT_PENDING | CONSENT_GRANTED | CONSENT_REFUSED`)
- `persistence_allowed` property (line 72): `True` only in `NO_GUEST` or
  `CONSENT_GRANTED` states — this is the veto predicate
- `tick()` (line 84): Called every perception cycle with face_count/guest_count
- Wired into: `agents/hapax_daimonion/daemon.py` (line 160)

**Where `persistence_allowed` is actually checked:**
- `_perception_state_writer.py` (line 472): Redacts person-adjacent fields
  from the persisted perception state JSON when `False`
- `studio_compositor/consent_live_egress.py` (line 64): Layout-swap gate — but
  this module is **disabled by default** since 2026-04-18, superseded by
  face-obscure (#129) at capture time

### ConsentGatedReader

**File**: `agents/_governance/consent_reader.py`

- `filter()` (line 148): Checks person IDs against contract registry
- `filter_tool_result()` (line 193): Called from `conversation_pipeline.py`
  (line 1610) during tool-result processing
- **Does not import or reference `ConsentStateTracker`**
- **Does not check guest presence** — only checks static contract state

### Voice output pipeline (the gap)

**File**: `agents/hapax_daimonion/conversation_pipeline.py`

`_speak_sentence()` (line 2047) calls:
1. `_resolve_direct_playback_route()` (line 1700)
2. → `resolve_playback_decision()` in `cpal/destination_channel.py` (line 246)
3. → `resolve_voice_output_route()` in `shared/voice_output_router.py` (line 189)

**None of these check `ConsentStateTracker.persistence_allowed`.**

The voice output router checks only:
- Stream mode (PUBLIC/PRIVATE)
- Broadcast intent tokens
- Private monitor status
- Audio health state

### The overhearing scenario

1. Guest arrives → IR detection fires `ConsentStateTracker.tick(guest_count=1)`
2. Phase transitions: `NO_GUEST → GUEST_DETECTED → CONSENT_PENDING`
3. `persistence_allowed` flips to `False`
4. Person-adjacent data fields are redacted from persistence ✓
5. **TTS continues playing to speakers without any gate** ✗
6. Guest hears Hapax speaking about operator's schedule, health data, etc.

## Classification

**Architectural gap**, not integration bug. No API exists to connect
`ConsentStateTracker.persistence_allowed` to the voice output routing
decision. The tracker gates *data persistence* (what gets written to disk);
it does not gate *data egress* (what gets spoken aloud or shown on screen).

## Remediation direction

The voice output router (`shared/voice_output_router.py`) or the playback
decision function (`cpal/destination_channel.py:resolve_playback_decision()`)
needs a new input: a callable or state-file check that reads
`persistence_allowed` and, when `False`, either:
- Suppresses TTS entirely (level 4)
- Switches to a content-safe utterance ("I'll wait until we have privacy")
- Routes to private output only (earbuds/headphones)

The choice depends on the escalation policy design (downstream task
`202605181934-disconfirm-consen-p1-design-escalation-bridge`).
