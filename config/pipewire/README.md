# Hapax PipeWire Configs

User-configurable PipeWire `filter-chain` presets for the hapax-daimonion
TTS output path. Each preset exposes the same sink name
(`hapax-voice-fx-capture`) so the daimonion-side wiring does not change
when you swap presets — only the filter graph does.

## Presets

| File | Character |
|---|---|
| `voice-fx-chain.conf` | Studio vocal chain: HP 80 Hz, low-mid cut 350 Hz, presence 3 kHz, air 10 kHz. Neutral-leaning clarity. |
| `voice-fx-radio.conf` | Telephone / AM-radio: bandpass 400–3400 Hz, 6 dB peak at 1.8 kHz. Transmitted/in-world treatment. |

Add new presets by dropping another `voice-fx-*.conf` next to these, keeping
the capture sink name `hapax-voice-fx-capture`.

## Install

Only **one** preset may be installed at a time — they collide on the sink
name. To install a preset:

```fish
cp config/pipewire/voice-fx-chain.conf ~/.config/pipewire/pipewire.conf.d/
systemctl --user restart pipewire pipewire-pulse wireplumber
pactl list short sinks | grep hapax-voice-fx
```

To swap presets, delete the currently-installed file from
`~/.config/pipewire/pipewire.conf.d/` before copying a new one, then
restart PipeWire.

## Routing TTS through the chain

The daimonion conversation pipeline reads the `HAPAX_TTS_TARGET` environment
variable when it opens its audio output. Set it to the sink name:

```fish
set -Ux HAPAX_TTS_TARGET hapax-voice-fx-capture
systemctl --user restart hapax-daimonion.service
```

Unset or empty falls through to the default role-based wireplumber
routing — the FX chain is fully opt-in.

## Operator-voice-over-YouTube ducker (LRR Phase 9 §3.8)

`voice-over-ytube-duck.conf` is a *different shape* from the TTS presets
above — it lives in the same directory for convenience, but it operates
on a separate sink (`hapax-ytube-ducked`) that OBS / browsers target
for the YouTube music bed. A sidechain compressor driven by the operator
mic attenuates the bed when the operator speaks.

Install + verify:

```fish
cp config/pipewire/voice-over-ytube-duck.conf ~/.config/pipewire/pipewire.conf.d/
systemctl --user restart pipewire pipewire-pulse wireplumber
pactl list short sinks | grep hapax-ytube-ducked
```

Route media through it by selecting **Hapax YouTube Ducker** as the
audio output in OBS (per-source Advanced Audio Properties → Audio
Monitoring device) or in Chromium (via `--alsa-output-device` / PipeWire
sink chooser). Tune `threshold / ratio / attack / release` in the file
header; sensible starting point: `-30 dBFS`, `8:1`, `5 ms`, `300 ms`.

Depends on the `sc4m_1916` LADSPA plugin (``swh-plugins`` on Arch).

## YouTube → 24c backing ducker (CVS #145)

`yt-over-24c-duck.conf` is the symmetric partner of
`voice-over-ytube-duck.conf`: it creates a `hapax-24c-ducked` sink that
the Python `AudioDuckingController` modulates when YouTube/React audio
is active, so the 24c backing bed ducks under the YT content (operator
has said "pull the backing down while the video plays").

Install + verify:

```fish
cp config/pipewire/yt-over-24c-duck.conf ~/.config/pipewire/pipewire.conf.d/
systemctl --user restart pipewire pipewire-pulse wireplumber
pactl list short sinks | grep hapax-24c-ducked
```

Route backing sources (DAW returns, synth strip, MPC pads) through
**Hapax 24c Ducker** via per-application audio assignment. Flip
`HAPAX_AUDIO_DUCKING_ACTIVE=1` on the compositor unit env to enable the
state-machine driver; the sink stays at unity gain until then.

See `docs/runbooks/audio-topology.md § 5` for the full ducking matrix.

## Vinyl-on-stream routing (HOMAGE Phase D1 verification)

Vinyl audio reaches the broadcast via the PreSonus Studio 24c analog mix:
turntable line-out → Studio 24c hardware input → 24c output mix →
`alsa_output.usb-PreSonus_Studio_24c...` default sink → OBS PipeWire
capture → RTMP egress. No dedicated vinyl filter-chain preset exists or
is required; vinyl shares the 24c mix with DAW returns, synth strips, and
MPC pads.

When the YT-over-24c ducker is installed (`yt-over-24c-duck.conf`, CVS
#145), vinyl routes through `hapax-24c-ducked` so `AudioDuckingController`
can pull the backing bed down while YouTube content plays. Install path:
route the turntable return strip through **Hapax 24c Ducker** per-
application once the preset is active. See `docs/runbooks/audio-topology.md`
§2 (sinks) and §5 (ducking matrix) for the authoritative routing table.

Verify vinyl reaches the broadcast:

```fish
# 1. Confirm the 24c sink is live and the default sink.
pactl info | grep 'Default Sink'
pactl list short sinks | grep PreSonus_Studio_24c

# 2. While a record is playing, confirm energy on the default-sink monitor.
pw-cat --record --target @DEFAULT_MONITOR@ --format s16 --rate 48000 \
    --channels 2 --latency 512 /tmp/vinyl-probe.wav &
PID=$!
sleep 3
kill $PID
ffprobe -v error -show_format -show_streams /tmp/vinyl-probe.wav
# Expect non-silent stream, RMS >> 0; a silent recording means the
# turntable strip is not routed to the default sink.

# 3. Confirm OBS sees the same energy on its PipeWire capture source
#    (Audio Mixer → 24c capture channel should show non-silent meters).
```

## Troubleshooting

- **Sink does not appear after install:** verify `pipewire.service` and
  `wireplumber.service` are running under systemd user scope; check
  `journalctl --user -u pipewire` for filter-chain load errors.
- **Hardware target not found:** the `target.object` in each preset points
  at the PreSonus Studio 24c analog output. Edit it to match your own
  `pactl list short sinks` output if you are running on different
  hardware, or remove the `target.object` line to let wireplumber choose
  the default sink.
- **Restart safety:** switching presets at runtime will briefly unhook the
  sink; the daimonion's pw-cat subprocess auto-restarts on broken pipe,
  so an in-flight TTS utterance may stutter but the daemon recovers.
