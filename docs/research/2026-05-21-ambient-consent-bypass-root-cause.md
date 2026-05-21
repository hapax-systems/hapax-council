# AMBIENT Voice Register Consent Bypass — Root Cause Analysis

**Date:** 2026-05-21
**Author:** epsilon
**Task:** 202605181934-disconfirm-consen-p0-investigate-ambient-bypass
**Parent request:** REQ-202605181934-disconfirm-consent-ambient-register-bypass
**Source:** CCTV Disconfirmation mode adversarial analysis (2026-05-18)
**Severity:** Critical (P0)

## Finding

AMBIENT narration reaches broadcast without consent filtering. The bypass is **not AMBIENT-specific** — it is a systematic architectural flaw affecting **all voice registers** when stream mode is PUBLIC or PUBLIC_RESEARCH.

## Root Cause

### Primary: `stream_public` master override in `resolve_playback_decision()`

**File:** `agents/hapax_daimonion/cpal/destination_channel.py`

`resolve_playback_decision()` (line 246) enforces 5 safety gates before allowing voice output to reach broadcast. Every gate includes an `and not stream_public` escape clause that disables the gate when stream mode is PUBLIC or PUBLIC_RESEARCH:

| Gate | Line | Condition | Effect when `stream_public=True` |
|------|------|-----------|----------------------------------|
| Broadcast intent | 339 | `not intent["present"] and not stream_public` | Skipped — no explicit intent required |
| Programme auth | 349 | `not programme_auth["authorized"] and not stream_public` | Skipped — no programme authorization required |
| Bridge metadata | 359 | `...not bridge_metadata["authorized"] and not stream_public` | Skipped — autonomous narration unchecked |
| Audio health | 370 | `not audio_health.safe and not stream_public` | Skipped — degraded audio passes |
| TTS permission | 380 | `not tts_permission.allowed and not stream_public` | Skipped — dynamic threshold bypassed |

`_stream_mode_is_public()` (line 74) reads from `get_stream_mode_or_off()` and returns True for `StreamMode.PUBLIC` or `StreamMode.PUBLIC_RESEARCH`.

### Secondary: `classify_destination()` unconditional routing

**File:** `agents/hapax_daimonion/cpal/destination_channel.py`, line 234

```python
if _stream_mode_is_public():
    return DestinationChannel.LIVESTREAM
```

When stream mode is PUBLIC, `classify_destination()` routes **all** voice output to LIVESTREAM before the voice register parameter is even examined. The `voice_register` parameter is explicitly unused (line 241: `_ = voice_register`).

### Tertiary: `prepared_playback_loop()` full gate bypass

**File:** `agents/hapax_daimonion/run_loops_aux.py`, lines 538-544

The prepared playback loop explicitly bypasses `resolve_playback_decision()` entirely, calling `classify_destination()` + `resolve_route()` directly. A synthetic impingement with `public_broadcast_intent=True` is constructed. The comment acknowledges this is intentional to avoid a chicken-and-egg deadlock with `audio_safe_for_broadcast`.

## Why AMBIENT is Especially Vulnerable

While the bypass affects all registers, AMBIENT is uniquely dangerous because:

1. **Operator absent during activation.** AMBIENT activates when BLE/face presence is absent but phone KDE remains connected (`shared/voice_register.py:17`). The operator cannot manually intervene.

2. **Autonomous narration.** AMBIENT produces system-status narration without conversational framing — it speaks without being spoken to.

3. **Content sensitivity.** System status narration may include infrastructure details, health check results, or internal state that should not reach broadcast.

4. **False safety signal.** AMBIENT's content constraints (no social performance, no inner experience claims) create an illusion of safety that masks the lack of consent filtering.

5. **Programme role overlap.** `_BROADCAST_ELIGIBLE_ROLES` (line 667) includes `"ambient"` as a valid programme role, creating a path where programme authorization passes for AMBIENT-context programmes even when the register-level consent check should block.

## Reproduction

The bypass is deterministic and requires no special setup:

1. Set stream mode to PUBLIC: write `public` to `~/.cache/hapax/stream-mode`
2. Generate any voice output (e.g., trigger AMBIENT narration by ensuring phone KDE connected but BLE/face absent)
3. Observe: voice output reaches broadcast (LIVESTREAM channel) without any safety gate blocking it
4. Verify: `resolve_playback_decision()` returns `allowed=True` with `reason_code="broadcast_voice_authorized"` regardless of programme auth, broadcast intent, audio health, or TTS permission state

**Existing test confirms:** `test_stream_mode_public_classifies_no_intent_as_livestream` (`tests/hapax_daimonion/test_destination_channel.py:532`) asserts that content without broadcast intent gets classified as LIVESTREAM when stream mode is PUBLIC.

## Related Bypass Vectors

### Vector 1: Mixed-register inputs

If a programme transitions between registers (e.g., CONVERSING to AMBIENT during a stream), the transition does not trigger re-evaluation of consent. The voice_register parameter is unused in `classify_destination()`, so register changes have no effect on routing.

### Vector 2: Autonomous narration via endogenous sources

Bridge metadata authorization (gate 3) checks for `endogenous.*` prefixed sources. When stream_public is True, this gate is skipped entirely, so autonomous narration from any source reaches broadcast.

### Vector 3: Stale audio health

Audio health signal freshness is checked but the entire gate is bypassed when stream_public is True. A stale or false audio health signal cannot block broadcast in PUBLIC mode.

### Vector 4: Livestream toggle dispatch

`impingement_consumer_loop()` (`run_loops_aux.py:1325-1347`) dispatches livestream toggles that write control files without invoking `resolve_playback_decision()`.

## Data Flow

```
Voice Capture (any register)
    |
    v
classify_destination()
    +-- sidechat/debug/operator sources --> PRIVATE (exits early)
    +-- explicit broadcast intent --> LIVESTREAM
    +-- stream_mode PUBLIC --> LIVESTREAM  <-- BYPASS POINT A
    +-- default --> PRIVATE
    |
    v
resolve_playback_decision()
    +-- Gate 1: broadcast intent   ... and not stream_public <-- BYPASS B
    +-- Gate 2: programme auth     ... and not stream_public <-- BYPASS C
    +-- Gate 3: bridge metadata    ... and not stream_public <-- BYPASS D
    +-- Gate 4: audio health       ... and not stream_public <-- BYPASS E
    +-- Gate 5: TTS permission     ... and not stream_public <-- BYPASS F
    +-- Gate 6: route state        (no stream_public bypass)
    |
    v
broadcast_voice_authorized --> LIVESTREAM output
```

## Why Other Registers Are Also Affected

The finding title says "AMBIENT voice register consent bypass" but the root cause is register-agnostic:

- **CONVERSING**: Also reaches broadcast without consent filtering in PUBLIC mode
- **ANNOUNCING**: Also bypasses all gates (and is the default register under `public_research`)
- **TEXTMODE**: Also bypasses; only sidechat provenance triggers PRIVATE routing

The difference is observational: AMBIENT is the register most likely to produce unsupervised, autonomous output because it activates when the operator is absent. Other registers typically require operator presence or interaction.

## Recommended Fix Direction

1. Remove `and not stream_public` from safety gates that should always enforce (programme auth, bridge metadata, TTS permission)
2. Retain the stream_public bypass **only** for broadcast intent (gate 1) — PUBLIC mode reasonably implies broadcast intent
3. Add register-aware filtering in `classify_destination()` or `resolve_playback_decision()` so AMBIENT output requires explicit consent/authorization even in PUBLIC mode
4. Audit `prepared_playback_loop()` for equivalent gate skips
5. Add negative test cases: AMBIENT + PUBLIC mode should still require programme auth and bridge metadata

## File Reference

| File | Lines | Role |
|------|-------|------|
| `agents/hapax_daimonion/cpal/destination_channel.py` | 74-80, 234-235, 338-390, 667-689 | Primary bypass location |
| `agents/hapax_daimonion/run_loops_aux.py` | 538-544 | Secondary bypass (prepared playback) |
| `shared/voice_register.py` | 33-39 | Register enum definition |
| `agents/hapax_daimonion/cpal/register_bridge.py` | 147-149 | AMBIENT content constraints |
| `agents/hapax_daimonion/consent_state.py` | 34-82 | Consent state tracker (persistence only, not broadcast) |
| `tests/hapax_daimonion/test_destination_channel.py` | 532-564 | Existing tests confirming bypass behavior |
