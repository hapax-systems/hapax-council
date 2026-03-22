# Voice Audio Input Loop Design

**Goal:** Wire continuous microphone audio into the hapax-voice daemon so wake word detection, VAD presence scoring, and Gemini Live streaming all function in real time.

**Decision:** PyAudio stream on the PipeWire echo-cancelled virtual source (`echo_cancel_capture`), with an async distribution loop fanning frames to all consumers.

---

## Part A: Audio Input Module

New module `agents/hapax_voice/audio_input.py`. Single class `AudioInputStream`.

### API Surface

```python
class AudioInputStream:
    def __init__(self, source_name: str = "echo_cancel_capture",
                 sample_rate: int = 16000, frame_ms: int = 30) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    async def get_frame(self, timeout: float = 1.0) -> bytes | None: ...
    @property
    def is_active(self) -> bool: ...
```

### Behavior

- Opens a PyAudio input stream in callback mode on the echo-cancelled source.
- Frame size: 30ms at 16kHz mono int16 = 480 samples = 960 bytes.
- PyAudio callback writes frames to a `queue.Queue` (thread-safe). `get_frame()` is an async wrapper that pulls from it using `asyncio.get_event_loop().run_in_executor()`.
- Device selection: iterate PyAudio device list, find one whose name contains `source_name`. Fall back to default input device if not found (log warning).
- `stop()` closes the stream and terminates the PyAudio instance. Idempotent.

---

## Part B: Audio Distribution Loop

New async method `VoiceDaemon._audio_loop()` runs as a background task.

### Frame Distribution

Every 30ms frame is distributed to:

1. **WakeWordDetector.process_audio()** — always-on, CPU <10ms, triggers session open on detection.
2. **PresenceDetector.process_audio_frame()** — always-on, CPU <1ms, feeds VAD sliding window.
3. **GeminiLiveSession.send_audio()** — only when Gemini backend session is active.

### Not Consuming From This Loop

- **Pipecat LocalAudioTransport** — manages its own PyAudio stream when a local pipeline session is active. Two concurrent PyAudio streams on the same PipeWire source is supported.
- **AmbientClassifier** — stays on-demand via `pw-record` subprocess when the context gate checks it. No change needed.

### Error Handling

- If a consumer raises an exception, log it and continue distributing to other consumers. One bad consumer must not kill the loop.
- If `get_frame()` returns None (timeout), continue the loop (no audio available).
- If the audio stream dies, log a warning and attempt to reopen after a 5-second delay.

---

## Part C: Daemon Wiring

### Config Addition

```python
audio_input_source: str = "echo_cancel_capture"
```

### Lifecycle

- **Init:** `AudioInputStream` created in `VoiceDaemon.__init__()`.
- **Startup:** `audio_input.start()` called in `run()` before entering the main loop. `_audio_loop()` added as a background task.
- **Shutdown:** `audio_input.stop()` called in the `finally` block.
- **Graceful degradation:** If PyAudio can't open the stream (device not found, PipeWire not running), log a warning and continue. The daemon operates in visual-only mode — workspace analysis, face detection, and hotkey activation still work.

### Event Log

- `audio_input_started` — emitted on successful stream open.
- `audio_input_failed` — emitted if stream cannot be opened (includes error string).
- No per-frame events (33 frames/sec would be too noisy).

---

## Part D: Testing

### Unit Tests (mocked PyAudio)

- Device selection finds echo_cancel_capture by name.
- Falls back to default input when echo_cancel not found.
- `get_frame()` returns bytes from queue.
- `get_frame()` returns None on timeout.
- `stop()` is idempotent.
- Callback handles PyAudio errors gracefully.

### Audio Loop Tests (mocked AudioInputStream)

- Frames distributed to wake_word and presence on every iteration.
- Wake word callback fires `_on_wake_word` and opens session.
- Loop continues after consumer exception.
- Loop exits cleanly when `_running` is False.
- Audio input failure degrades gracefully.

### Hardware Integration Tests (@pytest.mark.hardware)

- Real PyAudio stream opens on echo_cancel_capture.
- Frames are non-zero bytes of correct length (960).
- Stream survives 5 seconds without crash.

---

## Out of Scope

- Audio output / TTS playback routing (handled by Pipecat transport or separate path).
- Ambient classifier refactor (stays on-demand via pw-record).
- Pipecat LocalAudioTransport changes (manages its own stream).
- Audio recording for RAG (separate always-on ffmpeg service).
