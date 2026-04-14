# Sprint 4 — Ducking + Routing

**Date:** 2026-04-13 CDT
**Theme coverage:** H1 (TTS ducking), H2 (mic ducking), H3 (sidechain envelope shape), H4 (music source), H5 (stream mix for OBS), H6 (end-to-end ducking latency), H7 (TTS output path)
**Register:** scientific, neutral

## Headline

**Six findings in Sprint 4:**

1. **Music source is `youtube-audio-{slot_id}`** — ffmpeg-driven YouTube audio streams, three concurrent slots, switched via `SlotAudioControl` (`agents/studio_compositor/audio_control.py`). Per-stream volume control via `wpctl set-volume`. Node IDs cached + re-discovered after ffmpeg restart.
2. **Current "ducking" is binary `mute_all()` on TTS speech, not an envelope.** `director_loop.py:705` calls `_audio_control.mute_all()` synchronously before TTS playback, then `mute_all_except(active_slot)` at line 724 after. There is **no attack/release**, no threshold, no smooth ramp. The sound is hard mute → silence → hard restore.
3. **Yeti / operator VAD does NOT duck music.** Grep confirms zero call sites where Yeti VAD or operator-speech detection triggers `SlotAudioControl`. Only TTS playback (Hapax speaking) triggers a mute. **Operator speech with music playing has no audio-side response.**
4. **No PipeWire sidechain compressor anywhere.** Grep across `config/`, `~/.config/pipewire/pipewire.conf.d/`, and `agents/` returns zero `bq_compressor` / sidechain references for music ducking. `voice-fx-chain.conf` is EQ-only (highpass → low-mid cut → presence boost → air shelf). `voice-fx-radio.conf` has a soft-knee compressor but it's an in-band radio-effect treatment on TTS, not a sidechain pump on music.
5. **TTS output path: `pw-cat --target $HAPAX_TTS_TARGET`** (env var, optional). When set to `hapax-voice-fx-capture`, TTS goes through the EQ chain → Studio 24c. Otherwise default wireplumber routing. Live PipeWire shows `hapax-voice-fx-capture` SUSPENDED (not currently in use) and `input.loopback.sink.role.assistant` RUNNING (TTS playing through the role-loopback path now). Two TTS paths exist, only one is wired at a time depending on `HAPAX_TTS_TARGET`.
6. **Stream mix for OBS goes through `mixer_master`.** All three YouTube slots, the Studio 24c hardware inputs (turntables, synths, drum machine), and TTS playback all flow through `mixer_master` (FR channel of the Studio 24c monitor loopback per `10-contact-mic.conf`). OBS reads from `mixer_master` via the compositor's `audio_capture.py`. **There is no separate "voice-only" or "music-only" subgroup for OBS** — the operator cannot independently balance voice vs music in OBS mixing because they're already mixed.

## Data

### H4 — Music source: `youtube-audio-{slot_id}` via ffmpeg + wpctl

`agents/studio_compositor/audio_control.py:1-99`:

```python
class SlotAudioControl:
    """Per-slot YouTube audio volume control via PipeWire."""

    def __init__(self, slot_count: int = 3) -> None:
        self._slot_count = slot_count
        self._node_cache: dict[str, int] = {}

    def _refresh_cache(self) -> None:
        # parses pw-dump, finds props.media.name starting with "youtube-audio-"
        ...

    def set_volume(self, slot_id: int, level: float) -> None:
        stream_name = f"youtube-audio-{slot_id}"
        node_id = self.discover_node(stream_name)
        if node_id is None:
            return
        subprocess.run(["wpctl", "set-volume", str(node_id), str(level)], timeout=2, ...)
        # Re-discovers on wpctl failure (handles ffmpeg restarts)

    def mute_all_except(self, active_slot: int) -> None:
        for slot_id in range(self._slot_count):
            self.set_volume(slot_id, 1.0 if slot_id == active_slot else 0.0)

    def mute_all(self) -> None:
        for slot_id in range(self._slot_count):
            self.set_volume(slot_id, 0.0)
```

**Three slots**, each backed by a separate ffmpeg subprocess that streams a YouTube URL into a PipeWire node. Slot transitions happen on TTS-react-mode advance (`director_loop.py:716`).

### H1 — TTS ducking design (CURRENT vs DESIRED)

`agents/studio_compositor/director_loop.py:692-739`:

```python
def _speak_activity(self, text: str, activity: str) -> None:
    self._state = "SPEAKING"
    self._reactor.set_text(text)
    self._reactor.set_speaking(True)

    def _do_speak_and_advance():
        with self._transition_lock:
            try:
                pcm = self._synthesize(text)
                if pcm:
                    if self._audio_control:
                        self._audio_control.mute_all()       # ← HARD MUTE before TTS
                    self._reactor.feed_pcm(pcm)
                    self._play_audio(pcm)
                    time.sleep(0.3)
            except Exception:
                log.exception("TTS error")

            # ... slot advance logic ...

            if self._audio_control:
                self._audio_control.mute_all_except(self._active_slot)  # ← HARD UNMUTE after
```

**Behavior**: `mute_all()` issues `wpctl set-volume <node> 0.0` for every YouTube audio node. ZERO ATTACK TIME. The volume cliff is whatever PipeWire applies internally between the wpctl call and the node's volume update — likely on the order of one quantum (~10 ms at 480-frame quantum/48k). Then TTS plays. Then on completion the inverse cliff restores the new active slot to 1.0.

**Desired**: musical ducking. -8 to -12 dB attenuation on speech detection, 30 ms attack, 200-400 ms release back to unity. Implemented either via:

- **Option A (PipeWire sidechain)**: PipeWire `filter-chain` with `sc4_1882` (LADSPA mono compressor with sidechain) or a custom builtin. Sidechain input = TTS sink monitor + Yeti monitor (mixed). Signal path = each YouTube slot's audio → compressor → mixer_master.
- **Option B (Python envelope on wpctl)**: A 100Hz tick thread that linearly interpolates `wpctl set-volume` across the duck/restore window. Cheap, no plugin dependency, but `wpctl set-volume` has IPC latency (~5-10ms per call) so per-tick updates would saturate the wire.
- **Option C (gst-launch element)**: Move music ducking inside the GStreamer compositor: every YouTube slot becomes a `pulsesrc` → `audiocheblimit` → custom envelope element → mixer. Audio stays in GStreamer, ducking is sample-accurate. Cost: re-architecting the music source (3 ffmpeg subprocesses become 3 GStreamer pipelines).

**Recommendation**: Option A. PipeWire builtin filter-chain or LADSPA sidechain compressor lives in `~/.config/pipewire/pipewire.conf.d/`, requires a single `systemctl --user restart pipewire`, no Python changes. Operator-tunable via .conf control values.

### H2 — Mic ducking (NOT WIRED)

```bash
$ grep -rn "yeti\|vad\|operator.*speak" agents/studio_compositor/ | grep -i "mute\|duck\|volume"
(empty)
```

The Yeti is the operator's mic. Its VAD signal exists in `audio_capture.py` (the compositor reads `mixer_master`, which sums the Yeti). But the VAD signal is consumed by the **visual** layer (modulation tags via `_default_modulations.json`), NOT routed back to `SlotAudioControl`.

**Path to fix**: subscribe `director_loop.py` to `audio_capture._signals["mixer_energy"]` or a dedicated `voice_active` flag (does not yet exist), debounce via `SuppressionField`-style attack/release (already exists in `agents/hapax_daimonion/`), and call `SlotAudioControl.duck_all(level)` (not yet implemented).

### H7 — TTS output path

Two paths confirmed live, switched at startup via `$HAPAX_TTS_TARGET`:

```text
$ pactl list short sinks | grep -E "voice-fx|assistant|multimedia"
55  hapax-voice-fx-capture                          PipeWire  float32le 2ch 48000Hz  SUSPENDED
118 input.loopback.sink.role.multimedia             PipeWire  float32le 2ch 48000Hz  RUNNING
123 input.loopback.sink.role.assistant              PipeWire  float32le 2ch 48000Hz  RUNNING
```

**Path A** (default): TTS → `pw-cat --target` default → wireplumber resolves to `input.loopback.sink.role.assistant` → Studio 24c. Currently RUNNING. EQ NOT applied.

**Path B** (env var set): TTS → `pw-cat --target hapax-voice-fx-capture` → `hapax-voice-fx` filter-chain (highpass → low-mid → presence → air) → Studio 24c. Currently SUSPENDED. EQ applied.

The compositor's `daimonion.service` unit determines which is live by whether `HAPAX_TTS_TARGET` is exported in its environment. As of measurement: not exported (Path A active).

### H5 — Stream mix for OBS: single `mixer_master` bus

`~/.config/pipewire/pipewire.conf.d/10-contact-mic.conf`:

```text
loopback Studio 24c FL channel → contact_mic node    (Cortado contact mic)
loopback Studio 24c FR channel → mixer_master node   (everything else)
```

`mixer_master` is the FR (right channel) of the Studio 24c **monitor**, which means it carries:

1. The Studio 24c's playback (TTS, YouTube via role-loopback, system audio)
2. The Studio 24c's hardware inputs (turntables, synths, drum machine, Yeti via wireplumber routing)

These are summed in hardware on the Studio 24c monitor mix bus. The compositor reads the result via `pw-cat --record --target mixer_master` (`audio_capture.py:79` approx).

**OBS implication**: OBS's `mixer_master` capture is a single mono summed bus. There's no way for OBS to attenuate music vs voice independently because they're already pre-mixed. The only knob OBS has is total `mixer_master` gain.

**Subgroup design for the future**: split into three PipeWire null sinks — `stream-music`, `stream-voice`, `stream-instruments` — each receiving the appropriate sources via wireplumber rules. OBS captures each separately, mixes for stream output, and the operator gains independent voice/music balance live. Cost: rewrite Studio 24c routing in `~/.config/pipewire/pipewire.conf.d/`. Effort: medium. **This is a Sprint 7 polish item, not a P0 fix.**

### H3 — Sidechain envelope target

For musical ducking that doesn't sound mechanical:

| param | value | rationale |
|---|---|---|
| **threshold** | -30 dB (sidechain trigger level) | Yeti and TTS RMS sit around -25 to -18 dB, plenty of headroom |
| **ratio** | 4:1 | Audible but not extreme. 8 dB of duck on -25 dB voice |
| **attack** | 30 ms | Fast enough that the first syllable isn't lost over loud music; slow enough to avoid clicks |
| **release** | 350 ms | Sustains across word gaps so music doesn't pump on every comma. Releases fully between sentences |
| **knee** | 6 dB soft | Avoids the on/off character |
| **lookahead** | 5 ms | If the compressor supports it; mitigates the 30 ms attack on plosives |
| **makeup** | 0 dB | Music doesn't need post-duck level boost |

Result: when voice arrives, music drops ~8 dB within 30 ms, sustains through the speech, releases over 350 ms when voice stops.

These values are starting points. Tune by ear with a representative track + 30 seconds of TTS.

### H6 — End-to-end ducking latency (CURRENT)

Measurement: instrumentation needed (not yet shipped). But a back-of-envelope from the code path:

```text
Operator speaks → Yeti capture (10.7 ms quantum)
              → audio_capture.py reads mixer_master (10.7 ms chunk)
              → emits mixer_energy signal (background thread, 10.7 ms tick)
              → modulation reaches visual chain                   ← visual side, current
              → ??? would need to reach SlotAudioControl.set_volume()  ← audio side, MISSING
              → wpctl set-volume IPC                              (~5-10 ms one-shot)
              → PipeWire applies new volume (next quantum)        (~10 ms)
TOTAL (audio side, theoretical if wired): 35-45 ms target ceiling
```

**Visual side is already at 10-30 ms** (sidechain_kick from Sprint 3). Audio side **does not exist yet** for operator speech. For TTS speech the latency is 0 ms (mute is called *before* play_audio so the duck precedes the sound).

**Target for H6**: ≤50 ms operator-speech-to-music-duck. Achievable with PipeWire sidechain (zero latency, sample-accurate). Achievable with a Python wpctl envelope at ~30-50 ms (within budget).

## Findings + fix proposals

### F1 (HIGH): no audio-side ducking on operator speech

**Finding**: Yeti VAD does not duck music. Operator can be speaking at full volume into a loud track and the music does not dip. Either the operator manually pulls a fader on the Studio 24c monitor mix, or the stream goes out unbalanced.

**Fix proposal**: ship a PipeWire `filter-chain` filter-chain at `~/.config/pipewire/pipewire.conf.d/15-music-sidechain.conf` with a sidechain compressor. Sidechain input = mixer_master monitor (which already includes TTS + Yeti). Signal input = each `youtube-audio-*` stream → compressor → mixer_master sink path. Single restart of pipewire required.

**Alternative fix** (lower cost, lower quality): wire `audio_capture._signals["mixer_energy"]` → director_loop → `SlotAudioControl.set_volume()` Python tick at 100 Hz. Cheap; ~30 ms latency; pumpy character.

**Priority**: HIGH. Without this, livestream voice is regularly buried under music.

### F2 (HIGH): TTS ducking is binary mute, not envelope

**Finding**: TTS speech triggers `mute_all()` which is `wpctl set-volume <node> 0.0` — an instantaneous cliff. There's no fade-out, fade-in, or partial duck. The sonic effect is silent gap → voice → silent gap → music.

**Fix proposal**: same as F1. Sidechain compressor will smoothly duck during TTS too — TTS plays through the same `assistant`/`hapax-voice-fx-capture` sink whose monitor will appear in the sidechain. No special-casing needed; one compressor handles both TTS and operator speech.

**Priority**: HIGH. Even if F1 is deferred, fixing F2 alone improves the on-stream experience markedly.

### F3 (HIGH): no voice/music separation for OBS

**Finding**: `mixer_master` carries everything. OBS cannot independently fade voice vs music. The operator's only mix knob is "louder" or "quieter."

**Fix proposal**: redesign Studio 24c PipeWire routing into three subgroup sinks (`stream-music`, `stream-voice`, `stream-instruments`). Wireplumber rules route each source to the appropriate group. Compositor captures from each. OBS sees three sources and mixes them independently.

**Priority**: HIGH for stream production quality, MEDIUM for current operation (operator can compensate manually).

### F4 (INFO): TTS output path is env-var-gated

**Finding**: `$HAPAX_TTS_TARGET` controls whether TTS goes through the EQ chain or default routing. Currently unset → Path A (default routing, no EQ). Operator may not know they have an EQ chain installed but unwired.

**Fix proposal**: document in CLAUDE.md (already partially documented under "Voice FX Chain" section). Optionally make `hapax-voice-fx-capture` the default by setting the env var in the daimonion systemd unit drop-in.

**Priority**: INFO.

### F5 (MEDIUM): three-slot YouTube ffmpeg architecture is fragile

**Finding**: `SlotAudioControl` re-discovers node IDs on `wpctl` failure to handle ffmpeg restarts. The fact that this code path exists implies ffmpeg-restart-on-stream-end is the normal lifecycle. Each YouTube URL change = ffmpeg subprocess teardown + spawn = ~200-500 ms gap with no audio + a node ID rotation.

**Fix proposal**: replace the three-ffmpeg model with a single GStreamer pipeline per slot using `souphttpsrc` + `decodebin` + `pulsesink` + `volume`. GStreamer handles URL switching as a stream restart on a single element graph, eliminating the subprocess churn. Or: keep ffmpeg but reuse the same process for sequential URLs via a control protocol (named pipe, REST, etc.).

**Priority**: MEDIUM. Functional but lossy on slot transitions.

## Sprint 4 backlog additions (items 186+)

186. **`feat(pipewire): sidechain compressor for music ducking under voice`** [Sprint 4 F1+F2] — single `15-music-sidechain.conf` filter-chain with sidechain compressor. Sidechain input = mixer_master monitor (TTS + Yeti both present). Signal path = youtube-audio-* streams. Threshold -30 dB, 4:1, 30 ms attack, 350 ms release. ONE pipewire restart, ZERO Python changes.
187. **`refactor(director-loop): remove SlotAudioControl.mute_all() from speech path`** [Sprint 4 F2 followup] — once F1/F2 ships via PipeWire sidechain, the binary mute in `_do_speak_and_advance` becomes redundant and harmful (the cliff overrides the sidechain envelope). Remove `mute_all()` calls; let the sidechain compressor handle ducking.
188. **`feat(pipewire): voice/music/instrument subgroup sinks for OBS`** [Sprint 4 F3] — split `mixer_master` into three null sinks. Wireplumber rules route Yeti+TTS → `stream-voice`, youtube-audio-* → `stream-music`, Studio 24c hardware inputs → `stream-instruments`. OBS sees three sources. Cross-ref Sprint 7 polish backlog.
189. **`docs(claude.md): document HAPAX_TTS_TARGET env var and EQ chain default`** [Sprint 4 F4] — already partially documented; add a note that current default is unset (no EQ). Operator can opt in or set as system default.
190. **`feat(metrics): publish voice_active + music_ducked gauges`** [Sprint 4 H6 instrumentation] — new Prometheus gauges so the duck pipeline is observable end to end. Track latency from speech-detect to music-attenuated.
191. **`research(youtube-audio): replace ffmpeg subprocesses with GStreamer pipeline`** [Sprint 4 F5] — eliminate the ffmpeg restart cycle on URL change. Sprint 5 dovetails with output rework.
192. **`feat(audio): mixer_energy → director_loop subscription for VAD-based duck`** [Sprint 4 F1 alternative path] — if the PipeWire sidechain approach is rejected, wire the Python path. Tick at 100 Hz, envelope shape in code.
