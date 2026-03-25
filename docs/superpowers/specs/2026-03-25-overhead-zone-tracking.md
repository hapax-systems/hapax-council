# Overhead Camera Zone-Based Hand Tracking

**Date:** 2026-03-25
**Status:** Design approved
**Depends on:** Contact Mic Integration (PR #333), Scratch Detection Enrichment

## Summary

Use the repositioned c920-overhead camera to detect which instrument zone the operator's hands are in (turntable, pads, mixer, keyboard). Fuse this spatial signal with the contact mic's temporal activity classification for high-confidence production activity recognition.

## The Problem

The contact mic detects *what kind* of vibration is happening (scratching vs typing vs pad hits) but not *where* the operator's hands are. The overhead camera sees *where* hands are but not what they're doing acoustically. Fusing both gives confident, specific classifications that neither sensor achieves alone.

## Component 1: Instrument Zone Definitions

**File:** `shared/cameras.py`

Add a frozen dataclass for instrument zones and a zone registry tied to c920-overhead's frame dimensions (1280x720):

```python
@dataclass(frozen=True)
class InstrumentZone:
    """Bounding box for an instrument zone in the overhead frame."""
    name: str
    x1: int
    y1: int
    x2: int
    y2: int

OVERHEAD_ZONES: tuple[InstrumentZone, ...] = (
    InstrumentZone("turntable", 0, 100, 400, 550),
    InstrumentZone("pads", 400, 150, 800, 500),
    InstrumentZone("mixer", 300, 0, 550, 200),
    InstrumentZone("keyboard", 800, 300, 1280, 600),
)
```

**Zone coordinates are approximate estimates** from the overhead snapshot. They must be calibrated against the live feed.

Helper function:

```python
def point_in_zone(x: int, y: int) -> str:
    """Return the instrument zone name for a pixel coordinate, or 'unknown'."""
    for z in OVERHEAD_ZONES:
        if z.x1 <= x <= z.x2 and z.y1 <= y <= z.y2:
            return z.name
    return "unknown"
```

## Component 2: Overhead Hand Detection

**File:** `agents/hapax_voice/backends/vision.py`

### Problem

MediaPipe hand detection runs only on enrichment cameras — gated by `if role in ("operator", "room-brio", "synths-brio")` at line 1613. The c920-overhead is excluded.

### Solution

Add a **separate code path** after the enrichment block:

```python
if role == "overhead":
    try:
        hand_zones = self._run_overhead_hand_zones(frame)
    except Exception:
        log.debug("Overhead hand zone detection failed", exc_info=True)
        hand_zones = []
```

### New Method

Uses the existing `_gesture_recognizer` (lazily initialized in `_run_hand_gesture()` at line 749). The attribute name is `self._gesture_recognizer`, NOT `_hand_recognizer`.

```python
def _run_overhead_hand_zones(self, frame: np.ndarray) -> list[str]:
    """Detect hands in overhead frame and map centroids to instrument zones."""
    from shared.cameras import point_in_zone

    if not getattr(self, "_gesture_recognizer", None):
        self._run_hand_gesture(frame)  # triggers lazy init
    if not getattr(self, "_gesture_available", False):
        return []

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = self._gesture_recognizer.recognize(mp_image)

    zones: list[str] = []
    for hand_landmarks in result.hand_landmarks:
        cx = int(sum(lm.x for lm in hand_landmarks) / len(hand_landmarks) * frame.shape[1])
        cy = int(sum(lm.y for lm in hand_landmarks) / len(hand_landmarks) * frame.shape[0])
        zone = point_in_zone(cx, cy)
        if zone != "unknown":
            zones.append(zone)
    return zones
```

### `num_hands` Configuration

Change `num_hands=1` to `num_hands=2` at line 760. Both hands matter for scratch detection (record + fader). The recognizer is lazily initialized once per process; change takes effect on next daemon restart.

### Per-Camera Behavior Storage

```python
per_cam["hand_zones"] = ",".join(hand_zones)
per_cam["hand_zones_ts"] = time.monotonic()
```

### New Top-Level Behavior

Add `overhead_hand_zones` to `provides` and `contribute()`:

```python
self._b_hand_zones: Behavior[str] = Behavior("")

# In contribute(), read from per-camera cache:
overhead = self._cache._per_camera_behaviors.get("overhead", {})
hand_zones = overhead.get("hand_zones", "")
self._b_hand_zones.update(hand_zones, now)
behaviors["overhead_hand_zones"] = self._b_hand_zones
```

## Component 3: Cross-Modal Fusion

**File:** `agents/hapax_voice/backends/vision.py`

### Where the Fusion Happens

`_infer_cross_modal_activity()` is called from `_VisionCache._fused_read()` at line 275 — NOT from `contribute()`. The desk_activity value must be threaded through the cache, not passed in contribute.

### Wiring desk_activity Into the Cache

Follow the existing `set_audio_context()` pattern (line 190). Add a new method:

```python
def set_desk_context(self, *, desk_activity: str) -> None:
    """Inject desk activity for cross-modal fusion."""
    with self._lock:
        self._desk_activity = desk_activity
```

Initialize `self._desk_activity = ""` in `_VisionCache.__init__`.

In `VisionBackend.contribute()` (after the existing `set_audio_context` call at line 628), add:

```python
desk_activity = str(behaviors.get("desk_activity", Behavior("")).value)
self._cache.set_desk_context(desk_activity=desk_activity)
```

### Signature Change

Add `desk_activity: str = ""` to `_infer_cross_modal_activity()`:

```python
def _infer_cross_modal_activity(
    per_camera_behaviors: dict[str, dict[str, Any]],
    audio_activity: str,
    audio_genre: str,
    audio_energy: float,
    desk_activity: str = "",
) -> tuple[str, float]:
```

In `_fused_read()` at line 275, pass `desk_activity=self._desk_activity`.

### New Fusion Rules

Insert before existing rules:

```python
overhead = per_camera_behaviors.get("overhead", {})
hand_zones = overhead.get("hand_zones", "")

if "turntable" in hand_zones and desk_activity == "scratching":
    return ("scratching", 0.95)
if "pads" in hand_zones and desk_activity in ("drumming", "tapping"):
    return ("playing_pads", 0.90)
if "keyboard" in hand_zones and desk_activity == "typing":
    return ("coding", 0.90)
if "mixer" in hand_zones and desk_activity == "tapping":
    return ("mixing", 0.85)
```

## Component 4: Perception State Export

**File:** `agents/hapax_voice/_perception_state_writer.py`

Add to state dict:

```python
"overhead_hand_zones": str(_bval("overhead_hand_zones", "")),
```

## Component 5: OverlayData Extension

**File:** `agents/studio_compositor.py`

Add to `OverlayData`:

```python
overhead_hand_zones: str = ""
```

## File Inventory

| Action | Path | Scope |
|--------|------|-------|
| Edit | `shared/cameras.py` | Add InstrumentZone, OVERHEAD_ZONES, point_in_zone() |
| Edit | `agents/hapax_voice/backends/vision.py` | Overhead hand zone path, _run_overhead_hand_zones(), set_desk_context(), fusion rules, num_hands=2, new behavior |
| Edit | `agents/hapax_voice/_perception_state_writer.py` | Export overhead_hand_zones |
| Edit | `agents/studio_compositor.py` | Add overhead_hand_zones to OverlayData |
| Create | `tests/test_cameras_zones.py` | InstrumentZone + point_in_zone unit tests |
| Create | `tests/hapax_voice/test_overhead_zones.py` | Fusion rules + behavior tests |

## Testing

| Component | Method |
|-----------|--------|
| Zone mapping | Unit test: point_in_zone with coordinates inside/outside/boundary each zone |
| Hand zone detection | Unit test with mocked MediaPipe, verify centroid → zone |
| Cross-modal fusion | Unit test: desk_activity + hand_zones → expected (activity, confidence) |
| Behavior export | Unit test: overhead_hand_zones in contribute() output |
| End-to-end | Manual: put hand on turntable, check perception-state.json |

## Constraints

- Zone coordinates are initial estimates — require calibration
- Overhead camera cycles every ~18s (8-slot round-robin at 3s). Sufficient for activity classification, not real-time tracking.
- `num_hands=2` doubles MediaPipe inference time (~40ms → ~80ms on CPU). Within budget.
- Zones may overlap — first-match wins in point_in_zone()
