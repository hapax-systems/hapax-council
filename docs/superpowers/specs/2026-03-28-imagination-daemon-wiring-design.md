# Imagination Daemon Wiring — Connect Expressivity Modules

## Summary

Wire the imagination loop, content resolver, context injection, and proactive gate into the running daemons. The imagination loop and resolver run in the DMN daemon (direct buffer access, Qdrant access). Context injection and proactive utterance hook into the voice daemon's existing loops.

## DMN Daemon Changes (`agents/dmn/__main__.py`)

### New Async Tasks

Two new tasks launched via `asyncio.create_task` in `DMNDaemon.run()`:

**Imagination loop task:**
- Creates `ImaginationLoop` with a reference to `DMNBuffer`
- Runs on its own variable cadence (4-12s, managed by `CadenceController`)
- Each tick: extracts observations via `buffer.recent_observations(5)`, reads sensor snapshot via `dmn.sensor.read_all()`, calls `imagination.tick(observations, snapshot)`
- Reads TPN active flag from `/dev/shm/hapax-dmn/tpn_active` and passes to `imagination.set_tpn_active()`
- Fragment publishing to shm is handled internally by `ImaginationLoop`

**Content resolver task:**
- Runs `imagination_resolver` watch loop: polls `/dev/shm/hapax-imagination/current.json` every 500ms
- On new fragment: cleans content dir, resolves slow references (text/qdrant/url) to JPEG
- Independent of imagination loop cadence — resolver runs at fixed 500ms

### Impingement Drain

In `_write_output()`, after draining DMN pulse impingements, also drain imagination impingements:

```python
# Drain imagination impingements into same transport file
imagination_imps = self._imagination.drain_impingements()
if imagination_imps:
    with IMPINGEMENTS_FILE.open("a") as f:
        for imp in imagination_imps:
            f.write(imp.model_dump_json() + "\n")
```

Same file, same format. Voice daemon already reads it. Source field `"imagination"` distinguishes from `"dmn.evaluative"`.

## DMNBuffer Extension (`agents/dmn/buffer.py`)

One new method:

```python
def recent_observations(self, n: int = 5) -> list[str]:
    """Return content strings of the last N observations."""
```

Returns `[obs.content for obs in self._observations[-n:]]`. The imagination loop calls this to build its context.

## Voice Daemon Changes (`agents/hapax_voice/__main__.py`)

### Context Injection

In `__init__` (where `_goals_fn`, `_health_fn`, `_nudges_fn`, `_dmn_fn` are set):

```python
from agents.imagination_context import format_imagination_context
self._imagination_fn = format_imagination_context
```

In `_update_system_context`, add imagination context in the volatile band alongside the other context functions:

```python
# Imagination context: current thoughts from imagination bus
if self._imagination_fn is not None and not _lockdown:
    try:
        section = self._imagination_fn()
        if section:
            updated += "\n\n" + section
    except Exception:
        log.debug("imagination context fn failed (non-fatal)", exc_info=True)
```

Wire through to conversation pipeline same as other fns.

### Proactive Utterance

In `_impingement_consumer_loop`, when processing an impingement with `source == "imagination"` and `salience >= 0.8`:

```python
from agents.proactive_gate import ProactiveGate

# Check proactive gate
gate_state = {
    "perception_activity": self.perception.latest.activity if self.perception.latest else "unknown",
    "vad_active": self.session.is_active and self._conversation_pipeline.state == ConvState.LISTENING,
    "last_utterance_time": self._last_utterance_time,
    "tpn_active": self._conversation_pipeline.state not in (ConvState.IDLE, ConvState.LISTENING),
}
if self._proactive_gate.should_speak(imp_fragment_proxy, gate_state):
    # Generate and speak proactive utterance
    self._proactive_gate.record_utterance()
```

The `ProactiveGate` is initialized once in `__init__`. The `_last_utterance_time` tracks the monotonic time of the last speech act (either direction).

### TTS Active Flag

In the existing TTS playback code (around `buffer.set_speaking(True/False)`), write a `tts_active` field to perception state for audio field reflection. This is a one-line addition to the existing speaking state management.

## File Layout

| File | Change |
|------|--------|
| `agents/dmn/__main__.py` | Launch imagination + resolver tasks, drain imagination impingements |
| `agents/dmn/buffer.py` | Add `recent_observations(n)` method |
| `agents/hapax_voice/__main__.py` | Wire imagination context fn, proactive gate in impingement consumer, tts_active flag |
| `tests/test_dmn_imagination_wiring.py` | Buffer observation extraction, imagination task creation |
| `tests/test_voice_imagination_wiring.py` | Context injection format, proactive gate routing |

## Testing

### DMN-side
- `buffer.recent_observations(5)` returns last 5 observation contents
- `buffer.recent_observations(5)` on empty buffer returns `[]`
- `buffer.recent_observations(3)` with 5 entries returns last 3
- Imagination impingements drain into same list as DMN impingements

### Voice-side
- Context injection produces non-empty string when stream.jsonl has fragments
- Context injection returns gracefully when no stream file exists
- Proactive gate integration: imagination impingement with salience ≥ 0.8 triggers gate check
- Proactive gate integration: non-imagination impingements skip gate check
