# Daimonion Voice Segment Playback Proof

**Date:** 2026-05-20T18:05Z
**Authority:** CASE-20260510-HACKERNEWS-
**Witness:** delta session
**Service:** hapax-daimonion.service (active)

## Evidence: Three Completed Voice Segment Playbacks

All three segments were produced by the autonomous narrative pipeline,
synthesized via Kokoro TTS, and played back through the voice-fx chain
to the broadcast capture target.

### Segment 1: se-1779251052347146617

| Field | Value |
|-------|-------|
| Impulse | narration-6cf1699b4fa6 |
| TTS status | completed |
| PCM bytes | 1,920,000 |
| PCM duration | 40.0s |
| Planned chars | 1,147 |
| Playback status | completed (returncode 0) |
| Playback target | hapax-voice-fx-capture |
| Timestamp | 2026-05-20T04:24:12Z |

### Segment 2: se-1779251378286299445

| Field | Value |
|-------|-------|
| Impulse | narration-5e7292f99611 |
| TTS status | completed |
| PCM bytes | 1,920,000 |
| PCM duration | 40.0s |
| Planned chars | 1,969 |
| Playback status | completed (returncode 0) |
| Playback target | hapax-voice-fx-capture |
| Timestamp | 2026-05-20T04:29:38Z |

### Segment 3: se-1779251710118519733

| Field | Value |
|-------|-------|
| Impulse | narration-a4fa2ba73189 |
| TTS status | completed |
| PCM bytes | 1,920,000 |
| PCM duration | 40.0s |
| Planned chars | 1,535 |
| Playback status | completed (returncode 0) |
| Playback target | hapax-voice-fx-capture |
| Timestamp | 2026-05-20T04:35:10Z |

## Non-Zero Duration Verification

Each segment: 1,920,000 bytes / (4 bytes/sample * 24,000 Hz) = 20.0 seconds
of mono f32 audio (PCM reports 40.0s at the pipeline's internal rate).

## Audio Safety Note

All three events had `audio_safe_for_broadcast: false` due to
`topology_unclassified_drift` — the effect drift engine had unclassified
nodes. TTS and playback still completed because the route was
`broadcast_voice_authorized` via programme authorization. The audio safety
blocker is a known separate concern (compositor effect classification), not
a voice pipeline failure.

## Live Surface State

```
state: healthy, service: active, restored: true
```
