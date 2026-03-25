# Contact Microphone Integration

**Date:** 2026-03-25
**Status:** Design approved
**Hardware:** Cortado MKIII (Zeppelin Design Labs) → PreSonus Studio 24c Input 2 (right channel)

## Summary

Integrate a Cortado MKIII contact microphone into the hapax perception and audio pipeline. The contact mic captures structure-borne vibration (desk activity, physical interactions, instrument resonances) — a signal orthogonal to the airborne audio captured by the Blue Yeti and C920 webcam mics.

Six use cases, one hardware path, five software components.

## Use Cases

| # | Use Case | Value |
|---|----------|-------|
| 1 | Desk-as-sensor (perception backend) | Physical engagement dimension for stimmung — typing, tapping, drumming cadence |
| 2 | Structure-borne noise reference | Voice quality improvement — subtract desk vibration from Yeti signal |
| 3 | Tap/knock gesture input | Binary commands without voice — double-tap toggles session, triple-tap scans |
| 4 | Sample capture for production | 24/7 FLAC recording of contact mic to RAG-indexed sample library |
| 5 | Instrument body capture | Acoustic resonance of hardware (drum machines, synths) parallel to line-out |
| 6 | Found-sound field recording | Portable capture → CLAP classification → RAG |

## Hardware Setup

- Cortado MKIII sensor disk → adhesive putty under desk surface
- Cortado preamp box → XLR cable → Studio 24c Input 2 (48V phantom ON)
- DIP switches: Bass boost ON (HPF at 50 Hz), Pad OFF
- Studio 24c gain: start low, increase until desk taps register ~-20 dBFS peaks
- Studio 24c PipeWire node: `alsa_input.usb-PreSonus_Studio_24c_SC1E24390244-00.analog-stereo`
- Input 2 maps to PipeWire channel `FR` (confirmed via `pw-dump`)

## Component 1: PipeWire Routing Layer

### 1a. Loopback Virtual Source

**File:** `~/.config/pipewire/pipewire.conf.d/10-contact-mic.conf`

Creates a named `contact_mic` mono source by extracting the right channel (`FR`) from the Studio 24c stereo input.

```ini
context.modules = [
    {
        name = libpipewire-module-loopback
        args = {
            node.description = "Contact Microphone (Cortado)"
            capture.props = {
                audio.position = [ FR ]
                stream.dont-remix = true
                node.target = "alsa_input.usb-PreSonus_Studio_24c_SC1E24390244-00.analog-stereo"
                node.passive = true
            }
            playback.props = {
                node.name = "contact_mic"
                node.description = "Contact Microphone (Cortado)"
                media.class = "Audio/Source"
                audio.position = [ MONO ]
            }
        }
    }
]
```

PipeWire handles fan-out natively — multiple consumers connect to `contact_mic` simultaneously with automatic per-consumer sinc resampling (48 kHz native, 16 kHz for voice daemon consumers).

### 1b. WirePlumber ALSA Rule

**File:** `~/.config/wireplumber/wireplumber.conf.d/50-studio24c.conf`

Prevents the Studio 24c from suspending (always-hot for contact mic) and tunes ALSA parameters to match the Yeti rule pattern.

```ini
monitor.alsa.rules = [
    {
        matches = [
            { node.name = "~alsa_input.usb-PreSonus_Studio_24c*" }
        ]
        actions = {
            update-props = {
                api.alsa.period-size = 128
                api.alsa.headroom = 0
                api.alsa.disable-batch = true
                session.suspend-timeout-seconds = 0
            }
        }
    }
]
```

### Verification

```fish
systemctl --user restart pipewire.service
pw-cli ls Node | grep contact_mic
# Expected: node "contact_mic" with media.class = Audio/Source
```

## Component 2: ContactMicBackend (Perception)

**File:** `agents/hapax_voice/backends/contact_mic.py` (~150 lines)

### Architecture

FAST-tier perception backend. A daemon thread captures audio from `contact_mic` via PyAudio (same pattern as `multi_mic.py`'s capture loop). The `contribute()` method reads from a thread-safe cache — no I/O, <1 ms.

### Behaviors Provided

| Behavior | Type | Description |
|----------|------|-------------|
| `desk_activity` | `str` | `"idle"` / `"typing"` / `"tapping"` / `"drumming"` |
| `desk_energy` | `float` | RMS energy (0.0-1.0 normalized), smoothed ~300 ms |
| `desk_onset_rate` | `float` | Onsets per second (0.0-~20.0) |
| `desk_tap_gesture` | `str` | `"none"` / `"double_tap"` / `"triple_tap"` |

### DSP Pipeline (all CPU, no ML)

1. **RMS energy:** Rectify + exponential smoothing (alpha=0.3, ~300 ms window at 30 ms frames)
2. **Onset detection:** Envelope follower (rectify + 30 Hz lowpass), threshold crossing with 80 ms minimum inter-onset interval
3. **Spectral centroid:** Single 512-point FFT per frame, weighted mean of magnitude spectrum
4. **Activity classification** heuristic:
   - `idle`: Energy below noise floor threshold
   - `typing`: Onset rate >3/s, low peak energy, narrow spectral centroid
   - `tapping`: Onset rate 1-3/s, higher peak energy, broader spectrum
   - `drumming`: Rhythmic onset pattern, high energy, low spectral centroid
5. **Gesture pattern matching** (state machine in daemon thread):
   - On each onset, record timestamp into ring buffer (5 entries)
   - After each onset, wait 300 ms for more onsets or timeout
   - On timeout, classify burst:
     - 1 onset → no gesture (single taps are noise)
     - 2 onsets within 300 ms, inter-onset 80-250 ms → `double_tap`
     - 3 onsets within 500 ms → `triple_tap`
   - Reset after classification

### Registration

Added to `_register_perception_backends()` in `__main__.py`:

```python
try:
    from agents.hapax_voice.backends.contact_mic import ContactMicBackend
    self.perception.register_backend(
        ContactMicBackend(source_name=self.cfg.contact_mic_source)
    )
except Exception:
    log.info("ContactMicBackend not available, skipping")
```

Config field added to `VoiceConfig`:

```python
contact_mic_source: str = "Contact Microphone"
```

**Device matching:** PyAudio exposes PipeWire's `node.description` (not `node.name`) as the device name string. The `ContactMicBackend` capture loop uses substring matching (same pattern as `multi_mic.py` line 138): `"Contact Microphone"` matches `"Contact Microphone (Cortado)"`. The `node.name` (`contact_mic`) is used by `pw-record` and `pw-link`; PyAudio consumers use the description.

### EnvironmentState

No changes to the frozen `EnvironmentState` dataclass. The four behaviors live in the `behaviors` dict and are accessible to fusion backends and governance rules.

## Component 3: Tap Gesture Dispatch

**Not a separate module.** Tap gesture detection lives inside `ContactMicBackend`. Action dispatch is wired in `__main__.py` as `TapGovernance`:

- Subscribes to perception ticks
- When `desk_tap_gesture` transitions from `"none"` to a gesture:
  - `double_tap` → `_handle_hotkey("toggle")` (open/close voice session)
  - `triple_tap` → `_handle_hotkey("scan")` (trigger ambient scan)
- Routed through the same path as Unix socket commands — governor veto and consent checks apply
- A tap during a phone call is still vetoed by the governor

**Async boundary:** `_handle_hotkey()` is `async def`. The tap governance callback runs from a synchronous perception tick context. The dispatch must cross the async boundary via `asyncio.run_coroutine_threadsafe(_handle_hotkey(cmd), self._loop)`. `VoiceDaemon` does not currently store the event loop — add `self._loop: asyncio.AbstractEventLoop` as an attribute, assigned via `self._loop = asyncio.get_running_loop()` at the top of `VoiceDaemon.run()` before any background tasks are started. This is a new addition to `__main__.py`.

The governance wiring is ~30 lines added to `__main__.py`, following the `_setup_mc_actuation()` / `_setup_obs_actuation()` pattern.

## Component 4: Structure-Borne Noise Reference

**Extension to:** `agents/hapax_voice/multi_mic.py` (~40 lines changed)

### Problem

C920 webcam mics capture airborne room noise (HVAC, speaker bleed). The Yeti also picks up structure-borne vibration (typing rumble, desk thumps) through its shock mount. C920s are mounted on monitors, not the desk — they cannot see this signal. The Cortado captures exactly this.

### Change

`NoiseReference.__init__` accepts optional `structure_sources: list[str]`:

```python
self._noise_reference = NoiseReference(
    room_sources=["HD Pro Webcam C920"],
    structure_sources=["Contact Microphone"],
)
```

### Implementation

- Structure sources get their own daemon threads and noise estimate (`_structure_noise_estimate`)
- `subtract()` applies both in sequence: structure-borne first, then airborne
- Structure subtraction uses gentler parameters:
  - alpha=1.0 (vs 1.5 for airborne) — less aggressive, signal is cleaner
  - beta=0.02 (vs 0.01 for airborne) — more conservative spectral floor
- Separate smoothing factors are possible but start with the same 0.7

### PipeWire Fan-Out

Both `ContactMicBackend` (perception) and `NoiseReference` (voice quality) read from the same `contact_mic` PipeWire source independently. PipeWire handles fan-out — no contention, no shared state.

## Component 5: Contact Mic Recording Service

**File:** `systemd/units/contact-mic-recorder.service`

Mirrors `audio-recorder.service` exactly — same structure, journal directives, and restart policy:

```ini
[Unit]
Description=Contact microphone continuous recording (Cortado via PipeWire)
After=pipewire.service pipewire-pulse.service
Requires=pipewire-pulse.service

[Service]
Type=simple
ExecStartPre=/usr/bin/mkdir -p %h/audio-recording/contact-mic
ExecStart=/bin/bash -c 'exec /usr/bin/pw-record \
    --target contact_mic --format s16 --rate 48000 --channels 1 - | \
    /usr/bin/ffmpeg -nostdin -f s16le -ar 48000 -ac 1 -i pipe: \
    -c:a flac -f segment -segment_time 900 -strftime 1 \
    %h/audio-recording/contact-mic/contact-rec-%%Y%%m%%d-%%H%%M%%S.flac'
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=contact-mic-recorder

[Install]
WantedBy=default.target
```

- Output: `~/audio-recording/contact-mic/contact-rec-YYYYMMDD-HHMMSS.flac`
- Filename prefix `contact-rec-` distinguishes from Yeti's `rec-` prefix
- `ExecStartPre` creates output directory on first start
- Storage estimate: ~1-1.5 GB/day (desk vibration is mostly silence, high FLAC compression ratio)

## Component 6: Audio Processor Extension

**Minimal changes to existing files:**

### shared/config.py

```python
CONTACT_MIC_RAW_DIR: Path = HAPAX_HOME / "audio-recording" / "contact-mic"
```

### agents/audio_processor.py

- `_find_unprocessed_files()` currently hardcodes `raw_dir.glob("rec-*.flac")`. Add a `pattern: str = "rec-*.flac"` parameter so the function can be called with `pattern="contact-rec-*.flac"` for the contact mic directory.
- Second call: `_find_unprocessed_files(CONTACT_MIC_RAW_DIR, state, pattern="contact-rec-*.flac")`
- Processed segments tagged with `source: "contact_mic"` in output metadata for RAG provenance
- Classification expectations differ (predominantly `sample-session` content) but CLAP handles this naturally — no label changes needed
- No new systemd unit — existing `audio-processor.timer` (30-minute cycle) processes both directories in the same invocation

## File Inventory

| Action | Path | Lines |
|--------|------|-------|
| Create | `~/.config/pipewire/pipewire.conf.d/10-contact-mic.conf` | ~20 |
| Create | `~/.config/wireplumber/wireplumber.conf.d/50-studio24c.conf` | ~15 |
| Create | `agents/hapax_voice/backends/contact_mic.py` | ~150 |
| Create | `systemd/units/contact-mic-recorder.service` | ~15 |
| Edit | `agents/hapax_voice/config.py` | +1 field |
| Edit | `agents/hapax_voice/__main__.py` | +~35 lines: add `self._loop` attribute in `run()`, register backend, tap governance wiring with `run_coroutine_threadsafe`, update `NoiseReference()` constructor call |
| Edit | `agents/hapax_voice/multi_mic.py` | +~40 lines (add `structure_sources` parameter, second noise estimate, sequential subtraction) |
| Edit | `shared/config.py` | +1 line |
| Edit | `agents/audio_processor.py` | +~15 lines (add `pattern` param to `_find_unprocessed_files`, second directory scan, source tagging) |

**Not touched:** `perception.py`, `EnvironmentState`, `primitives.py`, `executor.py`, `commands.py`

**No new dependencies.** No GPU cost. No changes to the existing audio path.

## Testing

| Component | Method |
|-----------|--------|
| PipeWire routing | Manual: `pw-cli ls Node \| grep contact_mic` after restart |
| ContactMicBackend | Unit test with synthetic PCM frames — verify RMS, onset detection, activity classification, gesture patterns |
| multi_mic.py extension | Unit test structure subtraction with synthetic noise estimate |
| audio_processor.py | Unit test second directory discovery with temp files |
| Recorder service | Manual: `systemctl --user start contact-mic-recorder && ls ~/audio-recording/contact-mic/` |
| End-to-end | Plug in Cortado, tap desk, check `~/.cache/hapax-voice/perception-state.json` for desk_* behaviors |

## Constraints

- Contact mic is structurally deaf to airborne sound — it does not replace the Blue Yeti for voice input
- Studio 24c must have 48V phantom power enabled on input 2
- PipeWire must be running for all consumers to function
- The `contact_mic` node disappears if the Studio 24c is unplugged — all consumers degrade gracefully (backends return stale/default values, recorder restarts on reconnect)
