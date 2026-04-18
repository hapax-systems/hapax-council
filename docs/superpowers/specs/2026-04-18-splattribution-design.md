# SPLATTRIBUTION: No-Vinyl State Detection

Status: stub
Follow-on task: #127 (HOMAGE dossier)
Source: `docs/superpowers/research/2026-04-18-homage-follow-on-dossier.md` § Music → #127

## 1. Goal

Operator directive: **music featuring must be decoupled from vinyl playback**. Today the album-overlay, track-ID, and attribution-emission paths assume a vinyl is on the turntable whenever the compositor is alive, so they publish stale or false attribution during silence, between sides, or while Hapax draws from a local music repository (#130). We need a single authoritative boolean — `vinyl_playing` — that every downstream consumer gates on, so when vinyl is absent the system opens the path for Hapax-drawn music (#130) and SoundCloud passthrough (#131) without misattributing a vinyl.

## 2. Primary signal — `transport_state`

- Source: OXI One sending MIDI `start` / `stop` / `continue` messages into `MidiClockBackend._on_message()` (`agents/hapax_daimonion/backends/midi_clock.py:102-122`). `start` → `TransportState.PLAYING`; `stop` → `STOPPED`; `continue` → `PLAYING`.
- Exposed on `perceptual_field.audio.midi.transport_state: Literal["PLAYING", "STOPPED", "PAUSED"] | None` (`shared/perceptual_field.py:65-71`).
- Authoritative: callback-driven, <20ms latency, no polling.
- Twitch director already gates narrative lines on `field.audio.midi.transport_state == "PLAYING"` (`agents/studio_compositor/twitch_director.py:150, 244`) — this spec generalizes that gate into a single derived boolean.

## 3. Secondary signal — `beat_position_rate`

- Source: `TendencyField.beat_position_rate: float | None` (beats/sec), computed in `shared/perceptual_field.py:519` via the tendency sampler. Non-zero ⇒ beat position is actually advancing.
- Guards against a stale `transport_state` that declares PLAYING when the clock source has silently stopped ticking (docstring at `perceptual_field.py:184-200` explicitly calls this case out).

## 4. Derived signal

```python
vinyl_playing: bool = (
    audio.midi.transport_state == "PLAYING"
    and (tendency.beat_position_rate or 0.0) > 0.0
)
```

Exposed on `PerceptualField` as `audio.midi.vinyl_playing: bool` (computed property) and mirrored into `perception-state.json` for consumers that don't import the perceptual field.

## 5. Integration with #143 (IR vinyl cadence) / #142 (rate float)

#143 (IR cadence research) produces `vinyl_playback_rate: float` — measured rotational cadence of the turntable from IR frames. `vinyl_playing` must **also be False** when the rate is anomalous, because a mis-paced platter (e.g. hand-braked, power-bumped, slip-cue held) would produce garbage track-ID and misattribution:

```python
vinyl_playing &= 0.85 <= vinyl_playback_rate <= 1.15   # 33⅓ ±15% band
```

Threshold band lives alongside the #142 rate float; this spec owns the gate, #143 owns the measurement. When #143 has not landed yet, the gate degrades open (rate unknown ⇒ no veto) so we don't regress vs. today's behavior.

## 6. Consumer gating list

All of the following must consult `vinyl_playing` before acting:

| Consumer | File | Behavior when False |
|---|---|---|
| Album overlay rotation | `agents/studio_compositor/album_overlay.py` | Suspend album-cover crossfades; hold last frame or blank per operator preference. |
| Track-ID attribution emission | `agents/studio_compositor/homage/` (splattribution pipeline) | Do not emit `music-attribution.txt`; clear stale attribution after N seconds. |
| Stimmung music-framing | `agents/stimmung/` music-aware modifiers | Drop music-active bias; treat auditory field as silence. |
| Director "music is playing" stance | `agents/studio_compositor/twitch_director.py:150,244` | Replace the two literal `transport_state == "PLAYING"` checks with `field.audio.midi.vinyl_playing`. |

## 7. Opens downstream paths when False

- **#130 Hapax local music repository** — `LocalMusicRepository.select()` only fires while `vinyl_playing == False`.
- **#131 SoundCloud passthrough** — SoundCloud ingest only attributes itself while `vinyl_playing == False`.

## 8. File-level plan

1. `shared/perceptual_field.py` — Add `vinyl_playing` computed property on `MidiState` (or on `AudioField`, accepting both `self.midi.transport_state` and `self.tendency.beat_position_rate`). Keep the Literal type on `transport_state` untouched.
2. `shared/perception_state_writer.py` (or the writer that serializes `perception-state.json`) — Emit `audio.midi.vinyl_playing` so non-Python consumers can read it.
3. `agents/studio_compositor/twitch_director.py` — Replace the two `transport_state == "PLAYING"` checks with `field.audio.midi.vinyl_playing`.
4. `agents/studio_compositor/album_overlay.py` — Gate the album transition driver on `vinyl_playing`; on False, freeze current frame.
5. `agents/studio_compositor/homage/` — Gate splattribution emission on `vinyl_playing`; clear attribution file after configurable grace (default 5s) when False.
6. `agents/stimmung/` — Treat `vinyl_playing == False` as structurally equivalent to music-absent in the music-framing modifier.
7. Integration point for #143: thread `vinyl_playback_rate` into the derived signal once the IR cadence estimator lands.

## 9. Test strategy

- `tests/shared/test_perceptual_tendency.py` — Add cases: `{transport_state=PLAYING, beat_position_rate=1.0}` → `vinyl_playing == True`; stop message → `{STOPPED, 0.0}` → `False`; `{PLAYING, 0.0}` (transport says PLAYING but beat frozen) → `False`.
- `tests/test_midi_clock_backend.py` — Extend `test_transport_state_machine` with an end-to-end fixture: synthetic MIDI `start` → PLAYING → first tick advances beat → `vinyl_playing` True; synthetic `stop` → STOPPED → False within one sampler tick.
- `tests/studio_compositor/test_twitch_director.py` — Swap the two existing `transport_state="PLAYING"` fixtures to assert gating via `vinyl_playing` so the contract is structural, not string-equality.
- New `tests/studio_compositor/test_album_overlay_vinyl_gate.py` — Freeze album overlay when `vinyl_playing=False`; resume on True.
- New `tests/shared/test_vinyl_playing_rate_gate.py` — When #143 lands, verify anomalous `vinyl_playback_rate` forces False even with PLAYING + beat advancing.

## 10. Open questions

- **Debounce window.** `STOPPED` → `PLAYING` bounce at needle-drop can flap. Do we want hysteresis (e.g. require 2 samples in a row) on the derived signal, or leave consumers to debounce locally? Twitch director currently has no hysteresis; album overlay probably wants some.
- **PAUSED semantics.** The Literal allows `"PAUSED"` but `MidiClockBackend` only writes PLAYING/STOPPED. Confirm PAUSED is dead code we can drop, or define whether PAUSED ⇒ `vinyl_playing=False` (likely yes).
- **Grace period.** How long does `music-attribution.txt` stick around after `vinyl_playing` drops — snap clear, fade, or track-end grace for slow outros?
- **Rate band.** Is 0.85–1.15 correct for the IR cadence veto, or does it need to be stance-aware (e.g. wider during chopping/scratching segments where the operator holds the platter)?

## 11. Related

- **#130** — Local music repository for Hapax (consumes `vinyl_playing == False` as its enable gate).
- **#131** — SoundCloud passthrough attribution (same enable gate).
- **#142** — `vinyl_playback_rate` float surfacing.
- **#143** — IR cadence research that populates #142 and feeds the rate-band veto in §5.
