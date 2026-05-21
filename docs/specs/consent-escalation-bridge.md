---
title: "Guest-presence escalation bridge design"
date: 2026-05-21
author: epsilon
status: draft
cc_task: 202605181934-disconfirm-consen-p1-design-escalation-bridge
authority_case: CASE-202605181934-DISCONF
root_cause: docs/research/2026-05-21-consent-overhearing-escalation-root-cause.md
---

# Guest-Presence Escalation Bridge Design

## 1. Problem

`ConsentStateTracker` detects guest presence and sets `persistence_allowed=False`,
but the voice output pipeline never checks this before TTS playback. A guest
can hear private operator data spoken aloud.

## 2. Interface change: ConsentStateTracker

### Existing API (no changes needed)

```python
class ConsentStateTracker:
    @property
    def persistence_allowed(self) -> bool: ...
    @property
    def phase(self) -> ConsentPhase: ...
```

The tracker already exposes `persistence_allowed` as a property. No new method
is needed — the gap is that nobody reads it before audio egress.

### New: state file publication

Add atomic JSON write to `/dev/shm/hapax-consent/guest-presence.json` at each
`tick()`, matching the existing state-file pattern used by audio health witnesses:

```python
{
    "persistence_allowed": bool,
    "phase": str,  # ConsentPhase value
    "guest_count": int,
    "updated_at": str  # ISO-8601
}
```

This decouples the voice output router from the daimonion process — the router
reads a state file rather than importing a class from another daemon.

## 3. Voice output router integration

### Integration point

`shared/voice_output_router.py:resolve_voice_output_route()` (line ~189)

### New check (inserted before route resolution)

```python
def _read_consent_guest_presence(
    path: Path = Path("/dev/shm/hapax-consent/guest-presence.json"),
    max_age_s: float = 30.0,
) -> bool:
    """Returns True if persistence_allowed, False if guest present or state stale."""
    # Fail-closed: stale or missing file → treat as guest present
```

### Route decision when guest present

| `persistence_allowed` | Route decision |
|----------------------|----------------|
| `True` | Normal routing (no change) |
| `False` + PUBLIC stream | Route to private output only (earbuds/headphones) |
| `False` + PRIVATE stream | Suppress TTS entirely |
| Stale/missing state | Fail-closed → suppress TTS |

Rationale: In PUBLIC mode, the operator is livestreaming — redirecting to
private output prevents the guest from hearing but keeps the operator informed.
In PRIVATE mode, there's no broadcast justification, so suppression is
appropriate.

## 4. Thread safety and ordering

### State file approach (chosen)

The state file is written atomically (tmp+rename) by the daimonion process
and read by the voice output router in the same process. No cross-thread
coordination needed — file reads are atomic at the OS level for files smaller
than a page (4KB). The `updated_at` timestamp provides ordering.

### Freshness guarantee

The `tick()` method runs every ~2.5s (perception cycle). The voice output
router uses a `max_age_s=30.0` freshness threshold. If the state file is
older than 30s, the router fails closed (treats as guest present). This
provides a 12× freshness margin.

### Race condition: guest arrives between tick and speak

Worst case: guest arrives immediately after a tick writes
`persistence_allowed=True`. The next tick (2.5s later) will write `False`.
Any TTS utterance started in the 2.5s window will complete before the
next route resolution. This is acceptable — a single utterance completing
is preferable to the current behavior of unlimited unprotected speech.

## 5. Backwards compatibility

### Existing callers of resolve_voice_output_route()

All callers receive a `PlaybackDecision` that already includes route and
suppression fields. Adding the consent check modifies which route is chosen
but does not change the return type. No caller needs modification.

### Existing ConsentStateTracker callers

The only change to the tracker is adding a state-file write inside `tick()`.
The `persistence_allowed` and `phase` properties are unchanged. The
`_perception_state_writer.py` consumer continues to work identically.

### Fallback on missing state file

If the state file does not exist (e.g., daimonion not running), the router
fails closed. This matches the existing "fail-closed on stale health data"
pattern used by the broadcast audio health gate.

## 6. Implementation plan

| Step | File | Change |
|------|------|--------|
| 1 | `agents/hapax_daimonion/consent_state.py` | Add `_write_state_file()` call inside `tick()` |
| 2 | `shared/voice_output_router.py` | Add `_read_consent_guest_presence()` helper |
| 3 | `shared/voice_output_router.py` | Insert consent check before route resolution |
| 4 | `tests/shared/test_voice_output_router.py` | Add tests for guest-present routing |
| 5 | `tests/test_consent_state.py` | Add test for state file publication |

Estimated effort: ~4 hours. No infrastructure changes. No new dependencies.
