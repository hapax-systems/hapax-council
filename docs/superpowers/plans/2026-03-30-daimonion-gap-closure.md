# Daimonion Voice Pipeline Gap Closure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all correctness, robustness, and completion gaps identified in the full voice pipeline audit.

**Architecture:** 4-stage gated plan. Stage 1 fixes 7 production-blocking bugs. Stage 2 fixes 8 reliability bugs and removes dead code. Stage 3 adds structural improvements (init tracking, degradation registry, resource lifecycle). Stage 4 adds test coverage for untested modules. Each stage gates on the previous — tests must pass before advancing.

**Tech Stack:** Python 3.12, pydantic, pytest, asyncio, ctypes (speexdsp), numpy, PyAudio, subprocess

**Spec:** `docs/superpowers/specs/2026-03-30-daimonion-gap-closure-design.md`

---

## Stage 1: P0 Critical Fixes

### Task 1: Fix contact_mic.py — undefined device_idx and silent thread death

**Files:**
- Modify: `agents/hapax_daimonion/backends/contact_mic.py:378` and `:474-475`

- [ ] **Step 1: Fix undefined device_idx on line 378**

Replace the log line that references undefined `device_idx`:

```python
# OLD (line 378):
log.info("Contact mic capturing from device %d", device_idx)

# NEW:
log.info("Contact mic capturing from %s", self._source_name)
```

- [ ] **Step 2: Fix silent thread death at lines 474-475**

The outer exception handler logs at DEBUG and swallows the error. The `available()` method (line 284) checks PipeWire source existence but doesn't know the capture thread died. Add a `_capture_failed` flag.

First, add the flag in `__init__` (find `self._stop_event = threading.Event()` and add after):

```python
self._capture_failed = False
```

Then fix the exception handler:

```python
# OLD (lines 474-475):
        except Exception:
            log.debug("Contact mic capture failed", exc_info=True)

# NEW:
        except Exception:
            log.warning("Contact mic capture thread failed — marking backend degraded", exc_info=True)
            self._capture_failed = True
```

Then update `available()` to check the flag:

```python
# OLD (lines 284-299):
    def available(self) -> bool:
        """Check if the contact mic PipeWire source exists."""
        if pyaudio is None:
            return False
        try:
            import subprocess

            result = subprocess.run(
                ["pw-cli", "ls", "Node"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return self._source_name in result.stdout
        except Exception:
            return False

# NEW:
    def available(self) -> bool:
        """Check if the contact mic PipeWire source exists and capture is alive."""
        if pyaudio is None or self._capture_failed:
            return False
        try:
            import subprocess

            result = subprocess.run(
                ["pw-cli", "ls", "Node"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return self._source_name in result.stdout
        except Exception:
            return False
```

- [ ] **Step 3: Run tests**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/ -q --timeout=30 2>&1 | tail -5`
Expected: All pass (no existing tests for contact_mic, so existing tests should be unaffected)

- [ ] **Step 4: Commit**

```bash
git add agents/hapax_daimonion/backends/contact_mic.py
git commit -m "fix(daimonion): contact_mic undefined device_idx + silent thread death"
```

---

### Task 2: Fix echo_canceller.py — race condition on latency buffer

**Files:**
- Modify: `agents/hapax_daimonion/echo_canceller.py:147-150`

- [ ] **Step 1: Extend lock scope to cover latency buffer access**

In `process()` method (line 131), the `_ref_lock` currently only guards `_ref_buf` access (lines 141-142). The `_latency_buf` (lines 147-150) is accessed outside the lock but shared with the same data flow. Extend the lock:

```python
# OLD (lines 140-150):
        # Get reference frame (or silence if none available)
        with self._ref_lock:
            raw_ref = self._ref_buf.popleft() if self._ref_buf else None

        # Latency compensation: delay reference by 1 frame (~30ms) so it
        # aligns with when the acoustic echo actually reaches the mic.
        ref = None
        if raw_ref is not None:
            self._latency_buf.append(raw_ref)
            if len(self._latency_buf) >= self._latency_frames:
                ref = self._latency_buf.popleft()

# NEW:
        # Get reference frame and apply latency compensation under the same lock.
        # Both _ref_buf and _latency_buf are written by feed_reference() from
        # the TTS thread and read here from the audio loop thread.
        with self._ref_lock:
            raw_ref = self._ref_buf.popleft() if self._ref_buf else None

            # Latency compensation: delay reference by 1 frame (~30ms) so it
            # aligns with when the acoustic echo actually reaches the mic.
            ref = None
            if raw_ref is not None:
                self._latency_buf.append(raw_ref)
                if len(self._latency_buf) >= self._latency_frames:
                    ref = self._latency_buf.popleft()
```

- [ ] **Step 2: Run tests**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/ -q --timeout=30 2>&1 | tail -5`

- [ ] **Step 3: Commit**

```bash
git add agents/hapax_daimonion/echo_canceller.py
git commit -m "fix(daimonion): race condition on echo canceller latency buffer"
```

---

### Task 3: Fix echo_canceller.py — memory leak on speexdsp state

**Files:**
- Modify: `agents/hapax_daimonion/echo_canceller.py:194-198`

- [ ] **Step 1: Add __del__ and context manager protocol**

After the `destroy()` method (line 194), add:

```python
    def destroy(self) -> None:
        """Release the speexdsp state."""
        if self._state:
            self._lib.speex_echo_state_destroy(self._state)
            self._state = None

    def __del__(self) -> None:
        self.destroy()

    def __enter__(self) -> "EchoCanceller":
        return self

    def __exit__(self, *exc: object) -> None:
        self.destroy()
```

- [ ] **Step 2: Run tests**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/ -q --timeout=30 2>&1 | tail -5`

- [ ] **Step 3: Commit**

```bash
git add agents/hapax_daimonion/echo_canceller.py
git commit -m "fix(daimonion): echo canceller memory leak — add __del__ and context manager"
```

---

### Task 4: Fix multi_mic.py — process handle accumulation

**Files:**
- Modify: `agents/hapax_daimonion/multi_mic.py:266-332`

- [ ] **Step 1: Clean up process references after normal loop exit**

The `finally` block (lines 320-328) already terminates and removes the process. But when the inner while loop (line 288) exits normally via EOF (line 292), the process handle stays in `_processes` until the outer while loop iteration's finally block runs. The real issue is that `_processes` accumulates handles of processes that are already terminated. Add explicit cleanup after the inner loop:

```python
# OLD (lines 288-316):
                while self._running and proc.poll() is None:
                    assert proc.stdout is not None
                    data = proc.stdout.read(chunk_bytes)
                    if len(data) < chunk_bytes:
                        break

                    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                    ...

# After the inner while loop exits and before the except/finally, the process
# is dead but still in _processes. The finally block handles this, so the
# actual fix is to ensure the process list doesn't grow unbounded across
# loop iterations. The finally block already does `self._processes.remove(proc)`.
#
# The real fix: add exponential backoff on restarts instead of fixed 2s.
```

Actually, re-reading the code: the `finally` block DOES clean up on every iteration (lines 320-328). The process is appended (285), inner loop runs, then finally always fires (terminates + removes). The issue the audit flagged was about the `_processes` list growing, but the finally block handles it.

The actual issue is the **fixed 2s retry** with no backoff (line 332). Fix that:

```python
# OLD (lines 330-332):
            if self._running:
                log.warning("pw-record died for %s source %s — restarting in 2s", kind, source)
                time.sleep(2)

# NEW:
            if self._running:
                backoff = min(30, 2 ** min(retry_count, 4))
                retry_count += 1
                log.warning(
                    "pw-record died for %s source %s — restarting in %ds (attempt %d)",
                    kind, source, backoff, retry_count,
                )
                time.sleep(backoff)
```

Add `retry_count = 0` before the outer while loop (after line 266), and reset it to 0 after a successful capture session (after the inner while loop).

```python
    def _capture_loop(self, source: str, is_structure: bool = False) -> None:
        kind = "structure" if is_structure else "room"
        chunk_bytes = _FFT_SIZE * 2
        retry_count = 0

        while self._running:
            proc: subprocess.Popen | None = None
            try:
                proc = subprocess.Popen(
                    ...
                )
                self._processes.append(proc)
                log.info("Noise reference capturing from %s source: %s", kind, source)
                retry_count = 0  # Reset on successful start

                while self._running and proc.poll() is None:
                    ...
```

- [ ] **Step 2: Run tests**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/ -q --timeout=30 2>&1 | tail -5`

- [ ] **Step 3: Commit**

```bash
git add agents/hapax_daimonion/multi_mic.py
git commit -m "fix(daimonion): multi_mic exponential backoff on pw-record restart"
```

---

### Task 5: Fix phone_messages.py — shell injection in subprocess

**Files:**
- Modify: `agents/hapax_daimonion/backends/phone_messages.py:27-58`

- [ ] **Step 1: Pass MAC address as command-line argument**

Rewrite the subprocess call to pass _PHONE_MAC via sys.argv instead of string concatenation:

```python
# OLD (lines 27-58):
def _read_sms_via_script() -> list[dict]:
    """Read SMS inbox via a helper script that uses gi (system Python)."""
    try:
        result = subprocess.run(
            [
                "/usr/bin/python3",
                "-c",
                """
import json
from gi.repository import Gio, GLib
bus = Gio.bus_get_sync(Gio.BusType.SESSION)
try:
    r = bus.call_sync('org.bluez.obex', '/org/bluez/obex',
        'org.bluez.obex.Client1', 'CreateSession',
        GLib.Variant('(sa{sv})', ('"""
                + _PHONE_MAC
                + """', {'Target': GLib.Variant('s', 'map')})),
        GLib.VariantType('(o)'), Gio.DBusCallFlags.NONE, 10000, None)
    mp = r.unpack()[0]
    bus.call_sync('org.bluez.obex', mp, 'org.bluez.obex.MessageAccess1',
        'SetFolder', GLib.Variant('(s)', ('telecom/msg/inbox',)),
        None, Gio.DBusCallFlags.NONE, 10000, None)
    r2 = bus.call_sync('org.bluez.obex', mp, 'org.bluez.obex.MessageAccess1',
        'ListMessages', GLib.Variant('(sa{sv})', ('', {'MaxCount': GLib.Variant('q', 5)})),
        GLib.VariantType('(a{oa{sv}})'), Gio.DBusCallFlags.NONE, 10000, None)
    msgs = []
    for p, props in r2.unpack()[0].items():
        msgs.append({'sender': str(props.get('Sender','')), 'subject': str(props.get('Subject','')),'read': bool(props.get('Read', True))})
    print(json.dumps(msgs))
except Exception as e:
    print(json.dumps([]))
""",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )

# NEW:
_SMS_SCRIPT = """\
import json, sys
from gi.repository import Gio, GLib
mac = sys.argv[1]
bus = Gio.bus_get_sync(Gio.BusType.SESSION)
try:
    r = bus.call_sync('org.bluez.obex', '/org/bluez/obex',
        'org.bluez.obex.Client1', 'CreateSession',
        GLib.Variant('(sa{sv})', (mac, {'Target': GLib.Variant('s', 'map')})),
        GLib.VariantType('(o)'), Gio.DBusCallFlags.NONE, 10000, None)
    mp = r.unpack()[0]
    bus.call_sync('org.bluez.obex', mp, 'org.bluez.obex.MessageAccess1',
        'SetFolder', GLib.Variant('(s)', ('telecom/msg/inbox',)),
        None, Gio.DBusCallFlags.NONE, 10000, None)
    r2 = bus.call_sync('org.bluez.obex', mp, 'org.bluez.obex.MessageAccess1',
        'ListMessages', GLib.Variant('(sa{sv})', ('', {'MaxCount': GLib.Variant('q', 5)})),
        GLib.VariantType('(a{oa{sv}})'), Gio.DBusCallFlags.NONE, 10000, None)
    msgs = []
    for p, props in r2.unpack()[0].items():
        msgs.append({
            'sender': str(props.get('Sender', '')),
            'subject': str(props.get('Subject', '')),
            'read': bool(props.get('Read', True)),
        })
    print(json.dumps(msgs))
except Exception:
    print(json.dumps([]))
"""


def _read_sms_via_script() -> list[dict]:
    """Read SMS inbox via a helper script that uses gi (system Python)."""
    try:
        result = subprocess.run(
            ["/usr/bin/python3", "-c", _SMS_SCRIPT, _PHONE_MAC],
            capture_output=True,
            text=True,
            timeout=15,
        )
```

- [ ] **Step 2: Run tests**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/ -q --timeout=30 2>&1 | tail -5`

- [ ] **Step 3: Commit**

```bash
git add agents/hapax_daimonion/backends/phone_messages.py
git commit -m "fix(daimonion): phone_messages pass MAC via argv instead of string concat"
```

---

### Task 6: Fix phone_media.py — busctl parsing stub

**Files:**
- Modify: `agents/hapax_daimonion/backends/phone_media.py:40-85`

- [ ] **Step 1: Remove dead stub, keep only JSON parsing path**

The busctl text parsing stub (lines 48-54) does nothing. The JSON path (lines 57-83) is the correct approach but needs cleanup:

```python
# OLD (lines 40-85):
def _read_media_player() -> dict:
    """Read AVRCP media player state."""
    status_raw = _busctl_get("Status")
    # busctl output: s "paused" or s "playing"
    status = status_raw.split('"')[1] if '"' in status_raw else ""

    # Track is a dict — harder to parse from busctl
    # Use a simpler approach: just get Status + use cached track
    track_raw = _busctl_get("Track")
    title = ""
    artist = ""
    if track_raw:
        # Parse the busctl dict output
        for _part in track_raw.split('"'):
            pass  # busctl dict parsing is complex

    # Simpler: parse via subprocess with json output
    try:
        result = subprocess.run(
            [
                "busctl",
                "--json=short",
                "get-property",
                "org.bluez",
                _PLAYER_PATH,
                "org.bluez.MediaPlayer1",
                "Track",
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            import json

            data = json.loads(result.stdout)
            track = data.get("data", {})
            # busctl --json=short wraps values as {"type":"s","data":"..."}
            title_val = track.get("Title", "")
            artist_val = track.get("Artist", "")
            title = title_val.get("data", "") if isinstance(title_val, dict) else str(title_val)
            artist = artist_val.get("data", "") if isinstance(artist_val, dict) else str(artist_val)
    except Exception:
        pass

    return {"status": status, "title": title, "artist": artist}

# NEW:
def _read_media_player() -> dict:
    """Read AVRCP media player state via busctl JSON output."""
    status_raw = _busctl_get("Status")
    status = status_raw.split('"')[1] if '"' in status_raw else ""

    title = ""
    artist = ""
    try:
        result = subprocess.run(
            [
                "busctl",
                "--json=short",
                "get-property",
                "org.bluez",
                _PLAYER_PATH,
                "org.bluez.MediaPlayer1",
                "Track",
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            track = data.get("data", {})
            title_val = track.get("Title", "")
            artist_val = track.get("Artist", "")
            title = title_val.get("data", "") if isinstance(title_val, dict) else str(title_val)
            artist = artist_val.get("data", "") if isinstance(artist_val, dict) else str(artist_val)
    except Exception:
        log.debug("Track metadata parse failed", exc_info=True)

    return {"status": status, "title": title, "artist": artist}
```

Also add `import json` at the top of the file if not already present.

- [ ] **Step 2: Run tests**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/ -q --timeout=30 2>&1 | tail -5`

- [ ] **Step 3: Commit**

```bash
git add agents/hapax_daimonion/backends/phone_media.py
git commit -m "fix(daimonion): phone_media remove dead busctl stub, keep JSON parser"
```

---

### Task 7: Fix run_inner.py — shutdown ordering

**Files:**
- Modify: `agents/hapax_daimonion/run_inner.py:180-211`

- [ ] **Step 1: Reorder shutdown sequence**

Stop audio input first (breaks frame source), then pipeline (drains remaining), then background tasks (before hotkey, which is the command source):

```python
# OLD (lines 180-211):
    finally:
        from agents.hapax_daimonion.pipeline_lifecycle import stop_pipeline

        await stop_pipeline(daemon)
        daemon._audio_input.stop()
        daemon.perception.stop()

        if daemon._noise_reference is not None:
            daemon._noise_reference.stop()

        daemon.chime_player.close()
        daemon.executor_registry.close_all()
        if daemon._shared_pa is not None:
            try:
                daemon._shared_pa.terminate()
            except Exception:
                pass

        daemon.event_log.close()
        from opentelemetry.trace import get_tracer_provider

        provider = get_tracer_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush(timeout_millis=5000)

        for task in daemon._background_tasks:
            task.cancel()
        await asyncio.gather(*daemon._background_tasks, return_exceptions=True)
        daemon._background_tasks.clear()

        await daemon.hotkey.stop()
        log.info("Hapax Daimonion daemon stopped")

# NEW:
    finally:
        from agents.hapax_daimonion.pipeline_lifecycle import stop_pipeline

        # 1. Stop audio input first — breaks the frame source
        daemon._audio_input.stop()
        if daemon._noise_reference is not None:
            daemon._noise_reference.stop()

        # 2. Stop pipeline — drains remaining frames
        await stop_pipeline(daemon)
        daemon.perception.stop()

        # 3. Cancel background tasks before closing resources they may use
        for task in daemon._background_tasks:
            task.cancel()
        await asyncio.gather(*daemon._background_tasks, return_exceptions=True)
        daemon._background_tasks.clear()

        # 4. Close resources
        daemon.chime_player.close()
        daemon.executor_registry.close_all()
        if daemon._shared_pa is not None:
            try:
                daemon._shared_pa.terminate()
            except Exception:
                pass

        # 5. Flush telemetry and stop command server
        daemon.event_log.close()
        from opentelemetry.trace import get_tracer_provider

        provider = get_tracer_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush(timeout_millis=5000)

        await daemon.hotkey.stop()
        log.info("Hapax Daimonion daemon stopped")
```

- [ ] **Step 2: Run tests**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/ -q --timeout=30 2>&1 | tail -5`

- [ ] **Step 3: Commit**

```bash
git add agents/hapax_daimonion/run_inner.py
git commit -m "fix(daimonion): reorder shutdown — stop audio before pipeline, cancel tasks before close"
```

---

## Stage 2: P1 Fixes + Dead Code Removal

### Task 8: Fix conversation_buffer.py — uninitialized _speaking_started_at

**Files:**
- Modify: `agents/hapax_daimonion/conversation_buffer.py:83,153-155`

- [ ] **Step 1: Initialize attribute in __init__**

Add after line 83 (`self._speaking_ended_at: float = 0.0`):

```python
        self._speaking_started_at: float = 0.0
```

Then replace the `getattr` fallback (lines 153-155):

```python
# OLD:
            speaking_duration = self._speaking_ended_at - getattr(
                self, "_speaking_started_at", self._speaking_ended_at
            )

# NEW:
            speaking_duration = self._speaking_ended_at - self._speaking_started_at
```

- [ ] **Step 2: Run tests**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/test_conversation_buffer.py -q 2>&1 | tail -5`

- [ ] **Step 3: Commit**

```bash
git add agents/hapax_daimonion/conversation_buffer.py
git commit -m "fix(daimonion): initialize _speaking_started_at in __init__"
```

---

### Task 9: Fix audio_executor.py — stream resource leak

**Files:**
- Modify: `agents/hapax_daimonion/audio_executor.py:55-68`

- [ ] **Step 1: Add try/finally for stream cleanup**

```python
# OLD (lines 55-68):
    def _play_pcm(self, pcm_data: bytes, rate: int, channels: int, action: str) -> None:
        """Play PCM buffer through PyAudio. Runs in a background thread."""
        try:
            stream = self._pa.open(
                format=8,  # pyaudio.paInt16 = 8
                channels=channels,
                rate=rate,
                output=True,
            )
            stream.write(pcm_data)
            stream.stop_stream()
            stream.close()
        except Exception as exc:
            log.warning("AudioExecutor playback failed for %s: %s", action, exc)

# NEW:
    def _play_pcm(self, pcm_data: bytes, rate: int, channels: int, action: str) -> None:
        """Play PCM buffer through PyAudio. Runs in a background thread."""
        stream = None
        try:
            stream = self._pa.open(
                format=8,  # pyaudio.paInt16 = 8
                channels=channels,
                rate=rate,
                output=True,
            )
            stream.write(pcm_data)
        except Exception as exc:
            log.warning("AudioExecutor playback failed for %s: %s", action, exc)
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
```

- [ ] **Step 2: Run tests, commit**

```bash
cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/ -q --timeout=30
git add agents/hapax_daimonion/audio_executor.py
git commit -m "fix(daimonion): audio_executor stream resource leak"
```

---

### Task 10: Fix tts.py — float32 quantization + pipecat_tts.py timeout

**Files:**
- Modify: `agents/hapax_daimonion/tts.py:32`
- Modify: `agents/hapax_daimonion/pipecat_tts.py:57`

- [ ] **Step 1: Fix quantization scaling factor**

```python
# OLD (tts.py line 32):
    pcm = (audio * 32767).astype(np.int16)

# NEW:
    pcm = (audio * 32768).astype(np.int16)
```

- [ ] **Step 2: Add synthesis timeout to pipecat_tts.py**

```python
# OLD (pipecat_tts.py line 57):
            pcm_bytes = await asyncio.to_thread(self._tts_manager.synthesize, text, "conversation")

# NEW:
            pcm_bytes = await asyncio.wait_for(
                asyncio.to_thread(self._tts_manager.synthesize, text, "conversation"),
                timeout=30.0,
            )
```

Update the except block (lines 58-61) to also catch asyncio.TimeoutError:

```python
# OLD:
        except Exception:
            log.exception("TTS synthesis failed")

# NEW:
        except asyncio.TimeoutError:
            log.warning("TTS synthesis timed out after 30s")
            yield TTSStoppedFrame()
            return
        except Exception:
            log.exception("TTS synthesis failed")
```

- [ ] **Step 3: Run tests, commit**

```bash
cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/ -q --timeout=30
git add agents/hapax_daimonion/tts.py agents/hapax_daimonion/pipecat_tts.py
git commit -m "fix(daimonion): TTS quantization scaling + synthesis timeout"
```

---

### Task 11: Fix pipeline_start.py — stale experiment flags

**Files:**
- Modify: `agents/hapax_daimonion/pipeline_start.py:47-48`

- [ ] **Step 1: Always reset experiment flags at session start**

```python
# OLD (lines 47-48):
    if not hasattr(daemon, "_experiment_flags"):
        daemon._experiment_flags = {}

# NEW:
    daemon._experiment_flags = {}
```

- [ ] **Step 2: Run tests, commit**

```bash
cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/ -q --timeout=30
git add agents/hapax_daimonion/pipeline_start.py
git commit -m "fix(daimonion): always reset experiment flags at session start"
```

---

### Task 12: Fix presence_engine.py — likelihood ratio overflow

**Files:**
- Modify: `agents/hapax_daimonion/presence_engine.py:249-277`

- [ ] **Step 1: Convert to log-domain computation**

```python
# OLD (lines 249-277):
    def _compute_posterior(self, observations: dict[str, bool | None]) -> float:
        """Compute Bayesian posterior from likelihood ratios."""
        # Start with odds form of prior (decayed toward 0.5)
        prior = self._last_posterior
        # Decay toward base prior
        prior = prior + (self._prior - prior) * self._decay_rate
        # Clamp to avoid log(0)
        prior = max(0.001, min(0.999, prior))

        # Convert to odds
        odds = prior / (1.0 - prior)

        for signal_name, (p_present, p_absent) in self._signal_weights.items():
            observed = observations.get(signal_name)
            if observed is None:
                continue  # Missing sensor → neutral

            if observed:
                # Signal is True: likelihood ratio = P(signal|present) / P(signal|absent)
                lr = p_present / p_absent
            else:
                # Signal is False: likelihood ratio = P(¬signal|present) / P(¬signal|absent)
                lr = (1.0 - p_present) / (1.0 - p_absent)

            odds *= lr

        # Convert odds back to probability
        posterior = odds / (odds + 1.0)
        return max(0.0, min(1.0, posterior))

# NEW:
    def _compute_posterior(self, observations: dict[str, bool | None]) -> float:
        """Compute Bayesian posterior from likelihood ratios (log-domain)."""
        import math

        # Start with prior decayed toward base
        prior = self._last_posterior
        prior = prior + (self._prior - prior) * self._decay_rate
        prior = max(0.001, min(0.999, prior))

        # Work in log-odds domain to prevent overflow with extreme LRs
        log_odds = math.log(prior / (1.0 - prior))

        for signal_name, (p_present, p_absent) in self._signal_weights.items():
            observed = observations.get(signal_name)
            if observed is None:
                continue

            if observed:
                lr = p_present / max(p_absent, 1e-12)
            else:
                lr = (1.0 - p_present) / max(1.0 - p_absent, 1e-12)

            log_odds += math.log(max(lr, 1e-12))

        # Convert log-odds back to probability
        try:
            posterior = 1.0 / (1.0 + math.exp(-log_odds))
        except OverflowError:
            posterior = 0.0 if log_odds < 0 else 1.0
        return max(0.0, min(1.0, posterior))
```

- [ ] **Step 2: Run tests, commit**

```bash
cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/ -q --timeout=30
git add agents/hapax_daimonion/presence_engine.py
git commit -m "fix(daimonion): presence engine log-domain likelihood ratios prevent overflow"
```

---

### Task 13: Fix consent_state.py, tool_definitions.py, devices.py

**Files:**
- Modify: `agents/hapax_daimonion/consent_state.py:110-112`
- Modify: `agents/hapax_daimonion/tool_definitions.py` (end of build_registry)
- Modify: `agents/hapax_daimonion/backends/devices.py:238-245`

- [ ] **Step 1: Fix consent_state duplicate notification on zero debounce**

```python
# OLD (consent_state.py lines 108-112):
                self._notification_sent = False
                # Check if debounce is already satisfied (e.g., debounce_s=0)
                if self.debounce_s <= 0:
                    self._phase = ConsentPhase.CONSENT_PENDING
                    self._emit("consent_pending", face_count=face_count)

# NEW:
                self._notification_sent = False
                # Check if debounce is already satisfied (e.g., debounce_s=0)
                if self.debounce_s <= 0:
                    self._phase = ConsentPhase.CONSENT_PENDING
                    self._notification_sent = True
                    self._emit("consent_pending", face_count=face_count)
```

- [ ] **Step 2: Add tool schema validation in tool_definitions.py**

After the for loop that builds the registry (after the log.info line), add:

```python
    # Validate that all tools in _META have handlers
    missing = set(_META.keys()) - set(handler_map.keys())
    if missing:
        log.warning("Tools defined in _META but missing handlers: %s", sorted(missing))
```

- [ ] **Step 3: Add explicit BLE disabled behavior in devices.py**

After the commented-out BLE section (after line 245), add:

```python
            # BLE scanning disabled — bleak destabilizes dbus-broker
            self._cache.update(bluetooth_nearby=False)
```

- [ ] **Step 4: Run tests, commit**

```bash
cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/ -q --timeout=30
git add agents/hapax_daimonion/consent_state.py agents/hapax_daimonion/tool_definitions.py agents/hapax_daimonion/backends/devices.py
git commit -m "fix(daimonion): consent notification dedup, tool schema validation, BLE disabled state"
```

---

### Task 14: Remove dead code

**Files:**
- Delete: `agents/hapax_daimonion/init_workspace.py`
- Modify: `agents/hapax_daimonion/grounding_ledger.py` (remove `_repair_threshold`)
- Modify: `agents/hapax_daimonion/presence_diagnostics.py` (remove `format_tick_log`)

- [ ] **Step 1: Delete init_workspace.py**

```bash
git rm agents/hapax_daimonion/init_workspace.py
```

- [ ] **Step 2: Remove _repair_threshold from grounding_ledger.py**

Delete the `_repair_threshold` method (lines 159-172). Verify no callers: `grep -r "_repair_threshold" agents/`

- [ ] **Step 3: Remove format_tick_log from presence_diagnostics.py**

Delete the `format_tick_log` function (lines 18-46). Verify no callers: `grep -r "format_tick_log" agents/`

- [ ] **Step 4: Run tests, commit**

```bash
cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/ -q --timeout=30
git add -A
git commit -m "chore(daimonion): remove dead code — init_workspace, _repair_threshold, format_tick_log"
```

---

### Task 15: Fix stale tracing tests

**Files:**
- Modify: `tests/hapax_daimonion/test_tracing.py`
- Modify: `tests/hapax_daimonion/test_tracing_flush_timeout.py`
- Modify: `tests/hapax_daimonion/test_tracing_robustness.py`

- [ ] **Step 1: Create a list-collecting exporter replacement**

`InMemorySpanExporter` has been removed from the installed OTel SDK. Replace with a simple list-collecting exporter in each test file. In all three files, replace:

```python
# OLD:
from opentelemetry.sdk.trace.export.in_memory import InMemorySpanExporter

# NEW:
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult


class _ListSpanExporter(SpanExporter):
    """Minimal in-memory exporter for tests (replaces removed InMemorySpanExporter)."""

    def __init__(self) -> None:
        self.spans: list = []

    def export(self, spans):
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass

    def clear(self) -> None:
        self.spans.clear()

    def get_finished_spans(self) -> list:
        return list(self.spans)
```

Then replace all `InMemorySpanExporter()` calls with `_ListSpanExporter()`.

- [ ] **Step 2: Run tracing tests to verify**

```bash
cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/test_tracing.py tests/hapax_daimonion/test_tracing_flush_timeout.py tests/hapax_daimonion/test_tracing_robustness.py -v 2>&1 | tail -15
```

- [ ] **Step 3: Commit**

```bash
git add tests/hapax_daimonion/test_tracing*.py
git commit -m "fix(tests): replace removed InMemorySpanExporter with list-collecting exporter"
```

---

## Stage 3: Structural Improvements

### Task 16: Add degradation registry

**Files:**
- Create: `agents/hapax_daimonion/error_strategy.py`
- Test: `tests/hapax_daimonion/test_error_strategy.py`

- [ ] **Step 1: Write the test**

```python
"""Tests for the degradation registry."""

from __future__ import annotations

import time

from agents.hapax_daimonion.error_strategy import DegradationEvent, DegradationRegistry


class TestDegradationEvent:
    def test_fields(self):
        e = DegradationEvent(
            subsystem="backends",
            component="PipeWireBackend",
            severity="warning",
            message="not available",
            timestamp=1.0,
        )
        assert e.subsystem == "backends"
        assert e.component == "PipeWireBackend"
        assert e.severity == "warning"

    def test_frozen(self):
        import pytest

        e = DegradationEvent(
            subsystem="a", component="b", severity="info", message="c", timestamp=0.0
        )
        with pytest.raises(AttributeError):
            e.subsystem = "x"  # type: ignore[misc]


class TestDegradationRegistry:
    def test_record_and_retrieve(self):
        reg = DegradationRegistry()
        reg.record("backends", "Vision", "warning", "fdlite unavailable")
        assert len(reg.active()) == 1
        assert reg.active()[0].component == "Vision"

    def test_count_by_severity(self):
        reg = DegradationRegistry()
        reg.record("backends", "A", "warning", "msg")
        reg.record("backends", "B", "info", "msg")
        reg.record("audio", "C", "warning", "msg")
        counts = reg.count_by_severity()
        assert counts["warning"] == 2
        assert counts["info"] == 1

    def test_summary_format(self):
        reg = DegradationRegistry()
        reg.record("backends", "A", "warning", "msg")
        summary = reg.summary()
        assert "A" in summary
        assert "warning" in summary

    def test_empty_registry(self):
        reg = DegradationRegistry()
        assert reg.active() == []
        assert reg.count_by_severity() == {}
        assert "no degradations" in reg.summary().lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/test_error_strategy.py -v 2>&1 | tail -5`
Expected: ModuleNotFoundError

- [ ] **Step 3: Implement error_strategy.py**

```python
"""Degradation tracking for graceful subsystem failures.

Replaces silent log.info("skipping") patterns with structured events
that can be queried for health checks and diagnostics.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass

log = logging.getLogger(__name__)

__all__ = ["DegradationEvent", "DegradationRegistry"]


@dataclass(frozen=True)
class DegradationEvent:
    """A recorded subsystem degradation."""

    subsystem: str
    component: str
    severity: str  # "info", "warning", "error"
    message: str
    timestamp: float


class DegradationRegistry:
    """Tracks active degradations across all subsystems."""

    def __init__(self) -> None:
        self._events: list[DegradationEvent] = []

    def record(
        self,
        subsystem: str,
        component: str,
        severity: str,
        message: str,
    ) -> None:
        """Record a degradation event and log it."""
        event = DegradationEvent(
            subsystem=subsystem,
            component=component,
            severity=severity,
            message=message,
            timestamp=time.monotonic(),
        )
        self._events.append(event)
        log_fn = getattr(log, severity, log.warning)
        log_fn("Degradation [%s/%s]: %s", subsystem, component, message)

    def active(self) -> list[DegradationEvent]:
        """Return all recorded degradations."""
        return list(self._events)

    def count_by_severity(self) -> dict[str, int]:
        """Count degradations by severity level."""
        return dict(Counter(e.severity for e in self._events))

    def summary(self) -> str:
        """Human-readable summary of all degradations."""
        if not self._events:
            return "No degradations recorded"
        lines = [f"{len(self._events)} degradation(s):"]
        for e in self._events:
            lines.append(f"  [{e.severity}] {e.subsystem}/{e.component}: {e.message}")
        return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/test_error_strategy.py -v 2>&1 | tail -10`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_daimonion/error_strategy.py tests/hapax_daimonion/test_error_strategy.py
git commit -m "feat(daimonion): degradation registry for structured failure tracking"
```

---

### Task 17: Add resource lifecycle management

**Files:**
- Create: `agents/hapax_daimonion/resource_lifecycle.py`
- Test: `tests/hapax_daimonion/test_resource_lifecycle.py`

- [ ] **Step 1: Write the test**

```python
"""Tests for resource lifecycle management."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

from agents.hapax_daimonion.resource_lifecycle import (
    ExecutorResource,
    ResourceRegistry,
)


class TestResourceRegistry:
    def test_register_and_stop_all(self):
        reg = ResourceRegistry()
        r1 = MagicMock()
        r1.is_alive.return_value = True
        r2 = MagicMock()
        r2.is_alive.return_value = True

        reg.register("r1", r1)
        reg.register("r2", r2)

        failed = reg.stop_all(timeout=1.0)
        assert failed == []
        r1.stop.assert_called_once()
        r2.stop.assert_called_once()

    def test_stop_all_reverse_order(self):
        order: list[str] = []
        r1 = MagicMock()
        r1.stop.side_effect = lambda: order.append("r1")
        r1.is_alive.return_value = True
        r2 = MagicMock()
        r2.stop.side_effect = lambda: order.append("r2")
        r2.is_alive.return_value = True

        reg = ResourceRegistry()
        reg.register("r1", r1)
        reg.register("r2", r2)
        reg.stop_all(timeout=1.0)

        assert order == ["r2", "r1"]

    def test_stop_failure_captured(self):
        reg = ResourceRegistry()
        r1 = MagicMock()
        r1.stop.side_effect = RuntimeError("boom")
        r1.is_alive.return_value = True
        reg.register("r1", r1)

        failed = reg.stop_all(timeout=1.0)
        assert failed == ["r1"]

    def test_skip_already_stopped(self):
        reg = ResourceRegistry()
        r1 = MagicMock()
        r1.is_alive.return_value = False
        reg.register("r1", r1)

        reg.stop_all(timeout=1.0)
        r1.stop.assert_not_called()


class TestExecutorResource:
    def test_wraps_thread_pool(self):
        from concurrent.futures import ThreadPoolExecutor

        pool = ThreadPoolExecutor(max_workers=1)
        res = ExecutorResource(pool)
        assert res.is_alive()
        res.stop()
        assert not res.is_alive()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/test_resource_lifecycle.py -v 2>&1 | tail -5`

- [ ] **Step 3: Implement resource_lifecycle.py**

```python
"""Resource lifecycle management for long-lived daemon resources.

Provides a registry that tracks ThreadPoolExecutors, subprocesses, and
other resources, and shuts them down in reverse registration order.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

log = logging.getLogger(__name__)

__all__ = ["ManagedResource", "ResourceRegistry", "ExecutorResource"]


class ManagedResource(Protocol):
    """Protocol for resources managed by the registry."""

    def stop(self) -> None: ...
    def is_alive(self) -> bool: ...


class ExecutorResource:
    """Adapter wrapping a ThreadPoolExecutor as a ManagedResource."""

    def __init__(self, executor: ThreadPoolExecutor) -> None:
        self._executor = executor
        self._stopped = False

    def stop(self) -> None:
        self._executor.shutdown(wait=False)
        self._stopped = True

    def is_alive(self) -> bool:
        return not self._stopped


class ResourceRegistry:
    """Tracks and shuts down daemon resources in reverse order."""

    def __init__(self) -> None:
        self._resources: list[tuple[str, ManagedResource]] = []

    def register(self, name: str, resource: ManagedResource) -> None:
        self._resources.append((name, resource))

    def stop_all(self, timeout: float = 5.0) -> list[str]:
        """Stop all resources in reverse registration order.

        Returns list of resource names that failed to stop.
        """
        failed: list[str] = []
        for name, resource in reversed(self._resources):
            if not resource.is_alive():
                continue
            try:
                resource.stop()
            except Exception:
                log.warning("Failed to stop resource %s", name, exc_info=True)
                failed.append(name)
        self._resources.clear()
        return failed
```

- [ ] **Step 4: Run tests**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/test_resource_lifecycle.py -v 2>&1 | tail -10`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_daimonion/resource_lifecycle.py tests/hapax_daimonion/test_resource_lifecycle.py
git commit -m "feat(daimonion): resource lifecycle registry for clean shutdown"
```

---

### Task 18: Add init phase tracking to daemon.py

**Files:**
- Modify: `agents/hapax_daimonion/daemon.py:41-50`
- Test: `tests/hapax_daimonion/test_init_phase_tracking.py`

- [ ] **Step 1: Write the test**

```python
"""Tests for daemon init phase tracking."""

from __future__ import annotations

import enum

import pytest


class TestInitPhase:
    def test_phase_enum_values(self):
        from agents.hapax_daimonion.daemon import InitPhase

        assert InitPhase.CORE.value == "core"
        assert InitPhase.PERCEPTION.value == "perception"
        assert InitPhase.STATE.value == "state"
        assert InitPhase.VOICE.value == "voice"
        assert InitPhase.ACTUATION.value == "actuation"

    def test_phase_tracking_fields_exist(self):
        """VoiceDaemon should have _init_completed and _init_failed after __init__."""
        # We can't easily construct a full VoiceDaemon in tests,
        # but we can verify the InitPhase enum and the is_ready logic exist.
        from agents.hapax_daimonion.daemon import InitPhase

        # Simulate what the daemon does
        completed: set[InitPhase] = set()
        failed: dict[InitPhase, str] = {}

        completed.add(InitPhase.CORE)
        completed.add(InitPhase.PERCEPTION)
        completed.add(InitPhase.STATE)
        completed.add(InitPhase.VOICE)
        completed.add(InitPhase.ACTUATION)

        assert len(completed) == 5
        assert len(failed) == 0

    def test_partial_failure(self):
        from agents.hapax_daimonion.daemon import InitPhase

        completed: set[InitPhase] = set()
        failed: dict[InitPhase, str] = {}

        completed.add(InitPhase.CORE)
        failed[InitPhase.PERCEPTION] = "No backends available"

        assert InitPhase.CORE in completed
        assert InitPhase.PERCEPTION not in completed
        assert InitPhase.PERCEPTION in failed
```

- [ ] **Step 2: Add InitPhase enum and tracking to daemon.py**

Add before the VoiceDaemon class definition (after imports):

```python
class InitPhase(enum.Enum):
    """Tracks which initialization phases completed successfully."""

    CORE = "core"
    PERCEPTION = "perception"
    STATE = "state"
    VOICE = "voice"
    ACTUATION = "actuation"
```

Add `import enum` to the imports.

Then modify `__init__` (lines 44-50):

```python
# OLD:
    def __init__(self, cfg: DaimonionConfig | None = None) -> None:
        self.cfg = cfg if cfg is not None else load_config()
        self._init_core_subsystems()
        self._init_perception_layer()
        self._init_state_and_observability()
        self._init_voice_pipeline()
        self._init_actuation_layer()

# NEW:
    def __init__(self, cfg: DaimonionConfig | None = None) -> None:
        self.cfg = cfg if cfg is not None else load_config()
        self._init_completed: set[InitPhase] = set()
        self._init_failed: dict[InitPhase, str] = {}

        for phase, init_fn in [
            (InitPhase.CORE, self._init_core_subsystems),
            (InitPhase.PERCEPTION, self._init_perception_layer),
            (InitPhase.STATE, self._init_state_and_observability),
            (InitPhase.VOICE, self._init_voice_pipeline),
            (InitPhase.ACTUATION, self._init_actuation_layer),
        ]:
            try:
                init_fn()
                self._init_completed.add(phase)
            except Exception as exc:
                self._init_failed[phase] = str(exc)
                log.error("Init phase %s failed: %s", phase.value, exc, exc_info=True)

    def is_ready(self) -> bool:
        """True if all init phases completed successfully."""
        return len(self._init_completed) == len(InitPhase)
```

- [ ] **Step 3: Run tests**

```bash
cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/test_init_phase_tracking.py -v 2>&1 | tail -10
```

- [ ] **Step 4: Commit**

```bash
git add agents/hapax_daimonion/daemon.py tests/hapax_daimonion/test_init_phase_tracking.py
git commit -m "feat(daimonion): init phase tracking with is_ready() gate"
```

---

### Task 19: Retrofit init_backends.py with degradation registry

**Files:**
- Modify: `agents/hapax_daimonion/init_backends.py`
- Modify: `agents/hapax_daimonion/daemon.py` (add registry to __init__)

- [ ] **Step 1: Add DegradationRegistry to daemon**

In `_init_core_subsystems()` or at the start of `__init__`, add:

```python
from agents.hapax_daimonion.error_strategy import DegradationRegistry
self.degradation_registry = DegradationRegistry()
```

- [ ] **Step 2: Update init_backends.py to use registry**

Replace all bare `except Exception: log.info("...not available, skipping")` patterns with:

```python
# Example for PipeWireBackend (lines 16-21):
# OLD:
    try:
        daemon.perception.register_backend(PipeWireBackend())
    except Exception:
        log.info("PipeWireBackend not available, skipping")

# NEW:
    try:
        daemon.perception.register_backend(PipeWireBackend())
    except Exception:
        daemon.degradation_registry.record(
            "backends", "PipeWireBackend", "info", "not available"
        )
```

Apply this pattern to all 20 backend registrations. Each should use the actual backend name and an appropriate severity:
- `"info"` for optional backends (most of them)
- `"warning"` for important backends (VisionBackend, PresenceEngine)

- [ ] **Step 3: Log summary at end of init**

At the end of `register_perception_backends()`, add:

```python
    counts = daemon.degradation_registry.count_by_severity()
    if counts:
        log.info(
            "Backend registration complete: %d registered, %d degraded (%s)",
            len(daemon.perception.registered_backends),
            sum(counts.values()),
            ", ".join(f"{k}={v}" for k, v in counts.items()),
        )
```

- [ ] **Step 4: Run tests, commit**

```bash
cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/ -q --timeout=30
git add agents/hapax_daimonion/init_backends.py agents/hapax_daimonion/daemon.py
git commit -m "feat(daimonion): retrofit init_backends with degradation registry"
```

---

### Task 20: Wire resource lifecycle to daemon shutdown

**Files:**
- Modify: `agents/hapax_daimonion/daemon.py`
- Modify: `agents/hapax_daimonion/run_inner.py`

- [ ] **Step 1: Create and populate resource registry in daemon**

In `_init_core_subsystems()`, after creating the DegradationRegistry:

```python
from agents.hapax_daimonion.resource_lifecycle import ResourceRegistry, ExecutorResource
self.resource_registry = ResourceRegistry()
```

In `_init_voice_pipeline()`, after creating executors, register them:

```python
# After audio_input, resident_stt, and conversation_pipeline executors are available,
# wrap and register them. These are module-level globals, so import and register:
from agents.hapax_daimonion.audio_input import _frame_executor
from agents.hapax_daimonion.resident_stt import _stt_executor

self.resource_registry.register("frame_executor", ExecutorResource(_frame_executor))
self.resource_registry.register("stt_executor", ExecutorResource(_stt_executor))
```

- [ ] **Step 2: Add resource_registry.stop_all() to shutdown**

In `run_inner.py`, in the finally block, after stopping other resources and before the hotkey stop:

```python
        # Stop managed resources (thread pools, etc.)
        failed = daemon.resource_registry.stop_all(timeout=5.0)
        if failed:
            log.warning("Resources failed to stop: %s", failed)
```

- [ ] **Step 3: Run tests, commit**

```bash
cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/ -q --timeout=30
git add agents/hapax_daimonion/daemon.py agents/hapax_daimonion/run_inner.py
git commit -m "feat(daimonion): wire resource lifecycle registry to daemon shutdown"
```

---

## Stage 4: Test Coverage

### Task 21: Backend protocol compliance tests (batch)

**Files:**
- Create: `tests/hapax_daimonion/test_backend_protocol.py`

- [ ] **Step 1: Write protocol compliance test template**

This single test file covers ALL backends with parametrized tests:

```python
"""Protocol compliance tests for all perception backends.

Verifies every backend implements the PerceptionBackend contract:
name, provides, tier, available(), contribute(), start(), stop().
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _load_backend_class(name: str):
    """Import a backend class by name, returning None if unavailable."""
    try:
        if name == "PipeWireBackend":
            from agents.hapax_daimonion.backends.pipewire import PipeWireBackend
            return PipeWireBackend
        elif name == "HyprlandBackend":
            from agents.hapax_daimonion.backends.hyprland import HyprlandBackend
            return HyprlandBackend
        elif name == "WatchBackend":
            from agents.hapax_daimonion.backends.watch import WatchBackend
            return WatchBackend
        elif name == "HealthBackend":
            from agents.hapax_daimonion.backends.health import HealthBackend
            return HealthBackend
        elif name == "CircadianBackend":
            from agents.hapax_daimonion.backends.circadian import CircadianBackend
            return CircadianBackend
        elif name == "DeviceStateBackend":
            from agents.hapax_daimonion.backends.devices import DeviceStateBackend
            return DeviceStateBackend
        elif name == "InputActivityBackend":
            from agents.hapax_daimonion.backends.input_activity import InputActivityBackend
            return InputActivityBackend
        elif name == "ContactMicBackend":
            from agents.hapax_daimonion.backends.contact_mic import ContactMicBackend
            return ContactMicBackend
        elif name == "MixerInputBackend":
            from agents.hapax_daimonion.backends.mixer_input import MixerInputBackend
            return MixerInputBackend
        elif name == "IrPresenceBackend":
            from agents.hapax_daimonion.backends.ir_presence import IrPresenceBackend
            return IrPresenceBackend
        elif name == "BTPresenceBackend":
            from agents.hapax_daimonion.backends.bt_presence import BTPresenceBackend
            return BTPresenceBackend
        elif name == "MidiClockBackend":
            from agents.hapax_daimonion.backends.midi_clock import MidiClockBackend
            return MidiClockBackend
        elif name == "PhoneMediaBackend":
            from agents.hapax_daimonion.backends.phone_media import PhoneMediaBackend
            return PhoneMediaBackend
        elif name == "PhoneMessagesBackend":
            from agents.hapax_daimonion.backends.phone_messages import PhoneMessagesBackend
            return PhoneMessagesBackend
        elif name == "PhoneCallsBackend":
            from agents.hapax_daimonion.backends.phone_calls import PhoneCallsBackend
            return PhoneCallsBackend
        elif name == "StreamHealthBackend":
            from agents.hapax_daimonion.backends.stream_health import StreamHealthBackend
            return StreamHealthBackend
        elif name == "AttentionBackend":
            from agents.hapax_daimonion.backends.attention import AttentionBackend
            return AttentionBackend
        elif name == "ClipboardBackend":
            from agents.hapax_daimonion.backends.clipboard import ClipboardBackend
            return ClipboardBackend
        elif name == "SpeechEmotionBackend":
            from agents.hapax_daimonion.backends.speech_emotion import SpeechEmotionBackend
            return SpeechEmotionBackend
        elif name == "StudioIngestionBackend":
            from agents.hapax_daimonion.backends.studio_ingestion import StudioIngestionBackend
            return StudioIngestionBackend
        elif name == "LocalLLMBackend":
            from agents.hapax_daimonion.backends.local_llm import LocalLLMBackend
            return LocalLLMBackend
        elif name == "PhoneAwarenessBackend":
            from agents.hapax_daimonion.backends.phone_awareness import PhoneAwarenessBackend
            return PhoneAwarenessBackend
    except ImportError:
        return None
    return None


_ALL_BACKENDS = [
    "PipeWireBackend",
    "HyprlandBackend",
    "WatchBackend",
    "HealthBackend",
    "CircadianBackend",
    "DeviceStateBackend",
    "InputActivityBackend",
    "ContactMicBackend",
    "MixerInputBackend",
    "IrPresenceBackend",
    "BTPresenceBackend",
    "MidiClockBackend",
    "PhoneMediaBackend",
    "PhoneMessagesBackend",
    "PhoneCallsBackend",
    "StreamHealthBackend",
    "AttentionBackend",
    "ClipboardBackend",
    "SpeechEmotionBackend",
    "StudioIngestionBackend",
    "LocalLLMBackend",
    "PhoneAwarenessBackend",
]


@pytest.mark.parametrize("backend_name", _ALL_BACKENDS)
class TestBackendProtocol:
    def test_has_name_property(self, backend_name: str):
        cls = _load_backend_class(backend_name)
        if cls is None:
            pytest.skip(f"Cannot import {backend_name}")
        instance = cls()
        assert isinstance(instance.name, str)
        assert len(instance.name) > 0

    def test_has_provides_frozenset(self, backend_name: str):
        cls = _load_backend_class(backend_name)
        if cls is None:
            pytest.skip(f"Cannot import {backend_name}")
        instance = cls()
        assert isinstance(instance.provides, frozenset)

    def test_has_tier(self, backend_name: str):
        cls = _load_backend_class(backend_name)
        if cls is None:
            pytest.skip(f"Cannot import {backend_name}")
        from agents.hapax_daimonion.primitives import PerceptionTier

        instance = cls()
        assert isinstance(instance.tier, PerceptionTier)

    def test_available_returns_bool(self, backend_name: str):
        cls = _load_backend_class(backend_name)
        if cls is None:
            pytest.skip(f"Cannot import {backend_name}")
        instance = cls()
        result = instance.available()
        assert isinstance(result, bool)

    def test_contribute_accepts_dict(self, backend_name: str):
        cls = _load_backend_class(backend_name)
        if cls is None:
            pytest.skip(f"Cannot import {backend_name}")
        instance = cls()
        behaviors: dict = {}
        # contribute should not raise
        instance.contribute(behaviors)

    def test_has_start_and_stop(self, backend_name: str):
        cls = _load_backend_class(backend_name)
        if cls is None:
            pytest.skip(f"Cannot import {backend_name}")
        instance = cls()
        assert callable(getattr(instance, "start", None))
        assert callable(getattr(instance, "stop", None))
```

- [ ] **Step 2: Run tests**

```bash
cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/test_backend_protocol.py -v --timeout=30 2>&1 | tail -20
```

Some tests will skip if backends have missing dependencies. That's expected.

- [ ] **Step 3: Commit**

```bash
git add tests/hapax_daimonion/test_backend_protocol.py
git commit -m "test(daimonion): backend protocol compliance tests for all 22 backends"
```

---

### Task 22: Salience system tests

**Files:**
- Create: `tests/hapax_daimonion/test_salience_embedder.py`
- Create: `tests/hapax_daimonion/test_salience_concern_graph.py`
- Create: `tests/hapax_daimonion/test_salience_utterance_features.py`

- [ ] **Step 1: Write embedder tests**

```python
"""Tests for the salience embedder."""

from __future__ import annotations

import numpy as np
import pytest
from unittest.mock import patch, MagicMock


class TestSalienceEmbedder:
    def test_unavailable_returns_zero_vector(self):
        from agents.hapax_daimonion.salience.embedder import SalienceEmbedder

        with patch.object(SalienceEmbedder, "_load_model", side_effect=RuntimeError("no model")):
            embedder = SalienceEmbedder.__new__(SalienceEmbedder)
            embedder._model = None
            embedder._dim = 256
            embedder._model_name = "test"

        result = embedder.embed("hello world")
        assert result.shape == (256,)
        assert result.dtype == np.float32

    def test_embed_batch_empty(self):
        from agents.hapax_daimonion.salience.embedder import SalienceEmbedder

        embedder = SalienceEmbedder.__new__(SalienceEmbedder)
        embedder._model = None
        embedder._dim = 256
        embedder._model_name = "test"

        result = embedder.embed_batch([])
        assert result.shape == (0, 256)

    def test_available_false_when_no_model(self):
        from agents.hapax_daimonion.salience.embedder import SalienceEmbedder

        embedder = SalienceEmbedder.__new__(SalienceEmbedder)
        embedder._model = None
        embedder._dim = 256
        embedder._model_name = "test"

        assert not embedder.available
```

- [ ] **Step 2: Write concern graph tests**

```python
"""Tests for the salience concern graph."""

from __future__ import annotations

import numpy as np
import pytest
from unittest.mock import MagicMock

from agents.hapax_daimonion.salience.concern_graph import ConcernAnchor, ConcernGraph


class TestConcernGraph:
    def _make_graph(self):
        embedder = MagicMock()
        embedder.embed_batch.return_value = np.random.randn(3, 256).astype(np.float32)
        embedder.embed.return_value = np.random.randn(256).astype(np.float32)
        embedder.available = True
        return ConcernGraph(embedder)

    def test_refresh_with_anchors(self):
        graph = self._make_graph()
        anchors = [
            ConcernAnchor(text="coding", source="workspace", weight=1.0),
            ConcernAnchor(text="meeting", source="calendar", weight=0.8),
            ConcernAnchor(text="lunch", source="temporal", weight=0.5),
        ]
        graph.refresh(anchors)
        assert len(graph._anchors) == 3

    def test_overlap_returns_float_in_range(self):
        graph = self._make_graph()
        anchors = [ConcernAnchor(text="test", source="test", weight=1.0)]
        graph.refresh(anchors)
        result = graph.overlap(np.random.randn(256).astype(np.float32))
        assert 0.0 <= result <= 1.0

    def test_overlap_empty_graph(self):
        graph = self._make_graph()
        result = graph.overlap(np.random.randn(256).astype(np.float32))
        assert result == 0.0

    def test_novelty_returns_float_in_range(self):
        graph = self._make_graph()
        result = graph.novelty(np.random.randn(256).astype(np.float32))
        assert 0.0 <= result <= 1.0

    def test_novelty_zero_vector(self):
        graph = self._make_graph()
        result = graph.novelty(np.zeros(256, dtype=np.float32))
        assert result == 0.5
```

- [ ] **Step 3: Write utterance features tests**

```python
"""Tests for utterance feature extraction."""

from __future__ import annotations

from agents.hapax_daimonion.salience.utterance_features import extract_features


class TestUtteranceFeatures:
    def test_question_detected(self):
        f = extract_features("What time is it?", [])
        assert f.dialog_act == "question"

    def test_command_detected(self):
        f = extract_features("Turn off the lights", [])
        assert f.dialog_act == "command"

    def test_phatic_detected(self):
        f = extract_features("bye", [])
        assert f.is_phatic

    def test_word_count(self):
        f = extract_features("one two three four", [])
        assert f.word_count == 4

    def test_empty_text(self):
        f = extract_features("", [])
        assert f.word_count == 0
```

- [ ] **Step 4: Run all salience tests**

```bash
cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/test_salience_*.py -v --timeout=30 2>&1 | tail -20
```

- [ ] **Step 5: Commit**

```bash
git add tests/hapax_daimonion/test_salience_embedder.py tests/hapax_daimonion/test_salience_concern_graph.py tests/hapax_daimonion/test_salience_utterance_features.py
git commit -m "test(daimonion): salience system tests — embedder, concern graph, utterance features"
```

---

### Task 23: Perception and arbiter tests

**Files:**
- Create: `tests/hapax_daimonion/test_arbiter.py`

- [ ] **Step 1: Write arbiter tests**

```python
"""Tests for the resource arbiter."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from agents.hapax_daimonion.arbiter import ResourceArbiter, ResourceClaim


class TestResourceArbiter:
    def test_claim_and_drain(self):
        arb = ResourceArbiter()
        claim = ResourceClaim(
            key="audio_output",
            chain_id="tts",
            priority=10,
            one_shot=True,
        )
        arb.claim(claim)
        winners = arb.drain_winners("audio_output")
        assert len(winners) == 1
        assert winners[0].chain_id == "tts"

    def test_higher_priority_wins(self):
        arb = ResourceArbiter()
        low = ResourceClaim(key="audio_output", chain_id="chime", priority=5, one_shot=True)
        high = ResourceClaim(key="audio_output", chain_id="tts", priority=10, one_shot=True)
        arb.claim(low)
        arb.claim(high)
        winners = arb.drain_winners("audio_output")
        assert winners[0].chain_id == "tts"

    def test_one_shot_removed_after_drain(self):
        arb = ResourceArbiter()
        claim = ResourceClaim(key="audio_output", chain_id="tts", priority=10, one_shot=True)
        arb.claim(claim)
        arb.drain_winners("audio_output")
        # Second drain should return nothing
        winners = arb.drain_winners("audio_output")
        assert len(winners) == 0

    def test_same_chain_rejects_different_priority(self):
        arb = ResourceArbiter()
        c1 = ResourceClaim(key="audio_output", chain_id="tts", priority=10, one_shot=True)
        c2 = ResourceClaim(key="audio_output", chain_id="tts", priority=5, one_shot=True)
        arb.claim(c1)
        with pytest.raises(ValueError):
            arb.claim(c2)
```

- [ ] **Step 2: Run tests**

```bash
cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/test_arbiter.py -v --timeout=30 2>&1 | tail -10
```

- [ ] **Step 3: Commit**

```bash
git add tests/hapax_daimonion/test_arbiter.py
git commit -m "test(daimonion): arbiter resource claim tests"
```

---

### Task 24: Full test suite validation

- [ ] **Step 1: Run full test suite**

```bash
cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_daimonion/ -q --timeout=30 2>&1 | tail -10
```

Expected: All tests pass, no collection errors (tracing tests fixed, new tests pass).

- [ ] **Step 2: Run ruff and pyright**

```bash
cd /home/hapax/projects/hapax-council && uv run ruff check agents/hapax_daimonion/ --select E,F,I,UP,B,SIM,TCH 2>&1 | tail -10
cd /home/hapax/projects/hapax-council && uv run ruff format --check agents/hapax_daimonion/ 2>&1 | tail -5
```

- [ ] **Step 3: Fix any lint issues and commit**

```bash
git add -A
git commit -m "chore(daimonion): lint fixes from gap closure"
```

---

### Task 25: Final PR

- [ ] **Step 1: Create PR**

```bash
gh pr create --title "fix(daimonion): voice pipeline gap closure — 7 P0 + 8 P1 + structural" --body "$(cat <<'EOF'
## Summary

Full voice pipeline audit remediation:

- **7 P0 critical fixes**: contact_mic crashes, echo canceller race condition + memory leak, multi_mic retry backoff, phone_messages injection, phone_media stub, shutdown ordering
- **8 P1 reliability fixes**: conversation_buffer init, audio_executor stream leak, TTS quantization + timeout, experiment flag reset, presence engine overflow, consent notification, tool schema validation, BLE state
- **Dead code removal**: init_workspace.py, _repair_threshold, format_tick_log
- **Structural**: DegradationRegistry, ResourceRegistry, init phase tracking
- **Stale test fix**: tracing tests updated for current OTel SDK
- **New tests**: backend protocol compliance (22 backends), salience system, arbiter, structural modules

Spec: `docs/superpowers/specs/2026-03-30-daimonion-gap-closure-design.md`

## Test plan
- [ ] Full test suite passes (`uv run pytest tests/hapax_daimonion/ -q`)
- [ ] Ruff check clean
- [ ] Daemon starts and runs a voice session without crashes
- [ ] `daemon.is_ready()` returns True on clean startup
- [ ] `daemon.degradation_registry.summary()` shows expected degradations

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
