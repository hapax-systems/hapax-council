# Voice UX: Acknowledgment, Transparency, and Chime Design

**Goal:** Eliminate the silent gap after wake word detection, establish varied acknowledgment patterns, and implement state transparency so the operator is never left wondering what the system is doing.

**Decision:** Three-layer feedback system — pre-rendered chime at wake word detection (<50ms), LLM-driven verbal bridges for tool calls, and a disclosure pattern for passive actions — with a coherent earcon family for all state transitions.

---

## Architecture Overview

```
Wake word detected
  → Immediate chime playback (pre-rendered WAV, <50ms via PyAudio)
  → Pipeline starts (async, 1-4s to first speech)
    → LLM emits verbal bridge ("Let me check...") before tool calls
    → TTS streams bridge text WHILE tool executes (Pipecat parallel)
    → Tool result arrives → LLM synthesizes response → TTS plays

Session end
  → Deactivation chime plays after final TTS

Error / not understood
  → Error chime plays instead of silence
```

The chime layer is completely independent of Pipecat. It plays through PipeWire directly via PyAudio (already in the stack). The LLM verbal layer uses Pipecat's existing streaming — text chunks reach TTS before tool calls finish executing.

---

## 1. Chime Family: "Crystal Tap"

Four earcons sharing a consistent inharmonic bell timbre, pre-rendered as 48kHz/16-bit mono WAVs.

### 1.1 Activation Chime ("Crystal Tap")

Two-note ascending bell, played immediately on wake word detection.

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Note 1 | D6 (1175 Hz) | Mid-range, high perceptibility zone |
| Note 2 | G6 (1568 Hz) | Ascending perfect fourth — "attention" interval |
| Partial ratios | 1.0 : 2.406 : 3.758 | Inharmonic (bell-like, not musical instrument) |
| Partial levels | 0 dB : -6 dB : -12/-14 dB | Balanced harmonic content |
| Note 1 envelope | 15ms attack, exponential decay (τ=60ms) | Bell-like, non-harsh |
| Note 2 envelope | 15ms attack, exponential decay (τ=80ms) | Slightly longer ring |
| Note 2 onset | 80ms after Note 1 | 100ms overlap creates blend |
| Total duration | 350ms | Perceptible but not intrusive |
| Peak amplitude | 0.7 / 0.85 | Second note louder (reinforces ascending) |

**Why this works in a studio:** Inharmonic partials (2.406x, 3.758x) don't exist in any instrument in the production chain. The 1175-1568 Hz range sits between kick/bass (20-500 Hz) and hi-hat (5000+ Hz). The perfect fourth avoids harmonic association with the music being produced (no key/chord implication in boom bap context).

### 1.2 Deactivation Chime ("Crystal Release")

Descending perfect fourth (G6→D6). Same timbre, shorter (280ms), quieter (0.6 peak), faster decay (τ=40-60ms). Signals "session ended."

### 1.3 Error Chime ("Crystal Halt")

Single note A5 (880 Hz). Same inharmonic partials. 200ms, faster attack (10ms), 0.5 peak. Signals "something went wrong."

### 1.4 Completion Earcon ("Crystal Resolve")

Brief resolved interval — D6 alone, 150ms, 0.4 peak. Signals "action complete" (e.g., after SMS sent). Subtle enough to not interrupt.

### Technical Spec

```
Sample rate:    48000 Hz (PipeWire native, no resampling)
Bit depth:      16-bit signed integer
Channels:       Mono (centered phantom image)
Format:         WAV (PCM)
File sizes:     ~17-34 KB each
Storage:        ~/.local/share/hapax-voice/chimes/
  activation.wav
  deactivation.wav
  error.wav
  completion.wav
```

### Generation

Python script using numpy generates all four WAVs. The script IS the source code for the chimes — deterministic, versionable, re-runnable. No external audio tools needed.

---

## 2. Immediate Wake Word Acknowledgment

### Current Problem

`_on_wake_word()` in `__main__.py:291-298` does this:
1. Opens session
2. Emits event log entry
3. Creates async task for pipeline startup

Zero audible feedback. Pipeline takes 1-4s to produce first speech. The operator is left in silence, past the 300ms "did it hear me?" cliff.

### Fix

Add chime playback as the FIRST action in `_on_wake_word()`, before session open or pipeline start. The chime must play within 50ms of wake word detection.

```python
def _on_wake_word(self) -> None:
    if not self.session.is_active:
        self._chime_player.play("activation")  # <50ms, non-blocking
        self.session.open(trigger="wake_word")
        # ... rest of existing code
```

### ChimePlayer Design

A minimal class that:
1. Pre-loads all WAV files into memory at daemon startup (total ~100KB)
2. Plays via a dedicated PyAudio output stream (already have PyAudio)
3. Non-blocking — writes PCM bytes to stream callback, returns immediately
4. Uses `media.role=Notification` (not `Assistant`) to avoid triggering voice ducking

```python
class ChimePlayer:
    def __init__(self, chime_dir: Path) -> None: ...
    def load(self) -> None: ...           # Pre-load all WAVs into memory
    def play(self, name: str) -> None: ... # Non-blocking playback
    def close(self) -> None: ...           # Release PyAudio resources
```

**Chime directory auto-generation:** If `~/.local/share/hapax-voice/chimes/` doesn't exist or is empty, the daemon generates the chimes on first startup using the synthesis function. This means the chimes are always available — no manual generation step required.

---

## 3. Varied Verbal Acknowledgments

### Approach: LLM-Native, Not Code Logic

The LLM naturally varies phrasing when prompted correctly. Rather than hardcoding an acknowledgment pool with selection logic, we add instructions to the system prompt.

### System Prompt Addition

```python
"When you need to call a tool, say a brief natural bridge first — "
"'Let me check', 'One moment', 'Looking into that', 'On it', or similar. "
"Vary your phrasing naturally. Don't always start the same way. "
"For simple questions you can answer directly, skip the bridge. "
"For actions (sending messages, etc.), confirm what you're about to do. "
```

### Why This Works with Pipecat

Pipecat streams text to TTS in real-time chunks. When the LLM outputs "Let me check..." followed by a tool call:

1. Text chunks → immediately pushed to TTS → user hears "Let me check"
2. Tool call → executes in parallel (Pipecat default: `run_in_parallel=True`)
3. Tool result → LLM generates response → streams to TTS

The verbal bridge plays WHILE the tool executes. No additional latency.

### Bridge Timing

| Tool | Typical Latency | Bridge Needed? |
|------|----------------|----------------|
| search_documents | ~100ms | Usually no (fast enough) |
| get_calendar_today | ~300ms | At LLM's discretion |
| search_emails | ~200-400ms | Yes, for Gmail API calls |
| send_sms | ~500ms | Yes, plus confirmation flow |
| analyze_scene | ~2s | Always — "Let me look..." |
| get_system_status | ~100ms | Usually no |

The LLM doesn't need to know latencies — it naturally bridges longer operations.

---

## 4. State Transparency

### Three States, Three Signals

| State | Signal | Implementation |
|-------|--------|----------------|
| **Listening** | Activation chime already played; user is speaking | No change needed — silence during user speech is correct |
| **Thinking** | LLM verbal bridge ("Let me check...") | System prompt instruction (Section 3) |
| **Responding** | TTS audio output | Already implemented |

### Extended State Signals

| State | Signal | Implementation |
|-------|--------|----------------|
| **Session end** | Deactivation chime | Play after final TTS in `_close_session()` |
| **Error** | Error chime + verbal explanation | Play on pipeline/tool errors |
| **Action complete** | Completion earcon (optional) | After irreversible actions (SMS sent) |

### Deactivation Chime Placement

When session ends (silence timeout or hotkey close):
1. Final TTS message plays (if any — e.g., "Catch you later.")
2. Brief pause (200ms)
3. Deactivation chime plays
4. Pipeline shuts down

---

## 5. Passive Action Disclosure

### Principle: Observation is Silent, Action Requires Disclosure

The system observes continuously (workspace monitor, presence detection, ambient classification). These observations are silent — they enrich the LLM context but don't require notification.

If the system **acts** on an observation (changes state, logs an event, triggers behavior), it must disclose at the next natural interaction point.

### Disclosure Patterns

**During active session:**
- Workspace context injection → silent (enriches LLM context, LLM can reference if relevant)
- Presence change → LLM is informed via system prompt update, may reference naturally

**At session start (deferred disclosure):**
- "By the way, while you were away, [thing happened]" — if there are pending noteworthy events
- This uses the existing notification queue + proactive delivery system

**No new code needed** for passive disclosure in MVP. The existing system prompt + workspace context injection handles the "during session" case. The notification queue handles the "between sessions" case.

---

## 6. TTS Tier Map Update

### Current Problem

`tts.py` routes `"chime"` and `"short_ack"` use cases to Piper ONNX:

```python
_TIER_MAP: dict[str, str] = {
    "chime": "piper",        # WRONG — chimes should be pre-rendered WAVs
    "short_ack": "piper",    # WRONG — acks are LLM-driven verbal, not TTS tier
    ...
}
```

Piper is a speech synthesis engine trained on human voice. It's wrong for tonal/bell content. And `"short_ack"` is never actually called anywhere.

### Fix

Remove unused/incorrect tier entries. Chimes bypass TTS entirely (pre-rendered WAV playback via ChimePlayer). Acknowledgments are LLM-generated text that goes through the normal `"conversation"` tier.

```python
_TIER_MAP: dict[str, str] = {
    "conversation": "kokoro",
    "notification": "kokoro",
    "briefing": "kokoro",
    "proactive": "kokoro",
}
```

The `"chime"`, `"confirmation"`, and `"short_ack"` entries are deleted — they are no longer TTS concerns.

---

## 7. Config Additions

New fields in `VoiceConfig`:

```python
# Chime settings
chime_enabled: bool = True
chime_volume: float = 0.7       # 0.0-1.0, relative to system volume
chime_dir: str = "~/.local/share/hapax-voice/chimes"
```

---

## 8. Emerging Axiom Candidates

Two patterns from this design are general enough to be constitutional axioms:

### Interaction Transparency Axiom

> Every state transition in a human-system interaction must be signaled within 300ms. Silence after engagement is a signal of failure.

Applies to: voice (chime/verbal), visual (cockpit state indicators), any future modality.

### Action Disclosure Axiom

> The system must disclose any action it takes, at the next natural interaction point. Observation is silent; action requires disclosure.

Applies to: voice passive actions, background agent actions, automated maintenance, notification delivery.

**These should be discussed and potentially added to `hapaxromana/axioms/` after the implementation validates their utility.**

---

## Out of Scope

- **Visual indicators** — COSMIC/Wayland visual feedback (tray icon, notification LED) is a separate feature. The principles apply but the implementation is independent.
- **Barge-in / interruption handling** — Pipecat supports it but it's orthogonal to acknowledgment UX.
- **Chime volume auto-adjustment based on monitoring level** — future enhancement, requires PipeWire volume sensing.
- **Spearcons (compressed speech snippets)** — research shows they can outperform earcons for recognition, but adds complexity. Future work.
- **Multiple chime themes** — one theme ("Crystal Tap") is enough. Avoid choice paralysis.

---

## Testing Strategy

### Unit Tests
- Chime synthesis: WAV generation produces valid audio (correct sample rate, duration, frequency content)
- ChimePlayer: loads WAVs, plays without error, handles missing files gracefully
- TTS tier map: removed entries don't route to Piper, remaining entries unchanged
- System prompt: contains acknowledgment instructions

### Integration Tests
- Wake word → chime playback timing (mock PyAudio, verify play called before pipeline start)
- Session close → deactivation chime (verify chime plays after TTS)
- ChimePlayer auto-generation: empty chime dir triggers synthesis

### Manual Validation
- End-to-end: say "hapax", hear chime within ~200ms, hear varied verbal response
- Studio test: play music at monitoring level, say "hapax", verify chime cuts through without being annoying
- Session end: verify deactivation chime plays after closing message
