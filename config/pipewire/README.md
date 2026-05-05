# Hapax PipeWire Configs

User-configurable PipeWire `filter-chain` presets for the hapax-daimonion
TTS output path. Each preset exposes the same sink name
(`hapax-voice-fx-capture`) so the daimonion-side wiring does not change
when you swap presets — only the filter graph does.

## Presets

| File | Character |
|---|---|
| `hapax-voice-fx-chain.conf` | Studio vocal chain: HP 80 Hz, low-mid cut 350 Hz, presence 3 kHz, air 10 kHz. Neutral-leaning clarity (workspace default). |
| `hapax-voice-fx-vinyl-warmth.conf` | Warm tube/vinyl signature: HP 60 Hz, low-shelf +3 dB at 200 Hz (warmth), wide tube body lift at 800 Hz, gentle high-shelf -3 dB above 8 kHz (analog roll-off). Warm-conversation register. |
| `hapax-voice-fx-telephone-narrowband.conf` | G.711 / POTS telephone band: HP 300 Hz + LP 3400 Hz constrains to telephone band; +6 dB peak at 1.5 kHz for POTS resonance; -2 dB hollow midrange at 500 Hz. Vintage / institutional / "agent on the line" register. |
| `hapax-voice-fx-am-radio.conf` | AM broadcast aesthetic: HP 200 Hz + LP 5 kHz (AM band); +4 dB intelligibility lift at 1.8 kHz; -2 dB low-shelf at 250 Hz; +2 dB high-shelf fizz at 4 kHz. Announcement / spectacle / nostalgic-broadcast register. |
| `hapax-voice-fx-lo-fi.conf` | Lo-fi hip-hop / cassette character: mild HP 100 Hz; cassette warmth +2 dB at 180 Hz; mid-emphasis +3 dB at 1.5 kHz; cassette dropout notch at 3.2 kHz; high-shelf -4 dB above 8 kHz (cassette frequency loss). Contemplative / studied register. |
| `hapax-voice-fx-sci-fi-tunneled.conf` | Long-tunnel / spacial: HP 100 Hz; three-band tunnel resonance at 800/1200/2400 Hz with formant-shift notch at 1500 Hz; thin bright layer at 5 kHz. Builtin-only (no LADSPA). Contemplative-distant / system-error / inner-monologue register. |

All 5 aesthetic presets (vinyl-warmth → sci-fi-tunneled) share `node.name = "hapax-voice-fx"` and capture sink `hapax-voice-fx-capture` so swapping does NOT require restarting the daimonion service — only the filter graph differs. Per cc-task `voice-fx-chain-aesthetic-presets-tranche` (JR packet evidence base: `voice-fx-broadcast-best-practices-2026-05-04`). Supersedes the 2026-05-03 `hapax-voice-fx-radio.conf` removal note (the AM-radio + telephone aesthetics now live as their own presets without the dead PreSonus Studio 24c hardware target).

Add new presets by dropping another `hapax-voice-fx-*.conf` next to these, keeping the capture sink name `hapax-voice-fx-capture`.

## Naming Rule

Deployable hand-authored PipeWire files in this directory must be named
`hapax-*.conf`. The pre-commit hook `audio-conf-names` runs
`scripts/check-audio-conf-names.py` against top-level
`config/pipewire/*.conf` files, so load-order knobs and special-purpose
rules use descriptive Hapax names such as `hapax-quantum.conf`,
`hapax-contact-mic.conf`, and `hapax-s4-usb-sink.conf`. Generated
compiler artifacts under `config/pipewire/generated/` are intentionally
outside this rule; the audio-routing compiler owns those filenames.

## Install

Only **one** preset may be installed at a time — they collide on the sink
name. To install a preset:

```fish
cp config/pipewire/hapax-voice-fx-chain.conf ~/.config/pipewire/pipewire.conf.d/
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

`hapax-voice-over-ytube-duck.conf` is a *different shape* from the TTS presets
above — it lives in the same directory for convenience, but it operates
on a separate sink (`hapax-ytube-ducked`) that OBS / browsers target
for the YouTube music bed. A sidechain compressor driven by the operator
mic attenuates the bed when the operator speaks.

Install + verify:

```fish
cp config/pipewire/hapax-voice-over-ytube-duck.conf ~/.config/pipewire/pipewire.conf.d/
systemctl --user restart pipewire pipewire-pulse wireplumber
pactl list short sinks | grep hapax-ytube-ducked
```

Route media through it by selecting **Hapax YouTube Ducker** as the
audio output in OBS (per-source Advanced Audio Properties → Audio
Monitoring device) or in Chromium (via `--alsa-output-device` / PipeWire
sink chooser). Tune `threshold / ratio / attack / release` in the file
header; sensible starting point: `-30 dBFS`, `8:1`, `5 ms`, `300 ms`.

Depends on the `sc4m_1916` LADSPA plugin (``swh-plugins`` on Arch).

## YouTube → backing-mix ducker (CVS #145)

`hapax-backing-ducked.conf` is the symmetric partner of
`hapax-voice-over-ytube-duck.conf`: it creates a `hapax-backing-ducked` sink
that the Python `AudioDuckingController` modulates when YouTube/React
audio is active, so the backing bed ducks under the YT content (operator
has said "pull the backing down while the video plays").

Historical: previously named `hapax-yt-over-24c-duck.conf` (sink
`hapax-24c-ducked`) — renamed 2026-05 with the PreSonus Studio 24c
hardware retirement. The bidirectional ducker concept itself is still
load-bearing; only the dead hardware reference came out of the names.

Install + verify:

```fish
cp config/pipewire/hapax-backing-ducked.conf ~/.config/pipewire/pipewire.conf.d/
systemctl --user restart pipewire pipewire-pulse wireplumber
pactl list short sinks | grep hapax-backing-ducked
```

Route backing sources (DAW returns, synth strip, MPC pads) through
**Hapax Backing Ducker** via per-application audio assignment. Flip
`HAPAX_AUDIO_DUCKING_ACTIVE=1` on the compositor unit env to enable the
state-machine driver; the sink stays at unity gain until then.

See `docs/runbooks/audio-topology.md § 5` for the full ducking matrix.

## Vinyl-on-stream routing

Historical (PreSonus Studio 24c was decommissioned 2026-05): vinyl audio
reached the broadcast via the 24c analog mix — turntable line-out →
Studio 24c hardware input → 24c output mix →
`alsa_output.usb-PreSonus_Studio_24c...` default sink → OBS PipeWire
capture → RTMP egress. No dedicated vinyl filter-chain preset existed
or was required; vinyl shared the 24c mix with DAW returns, synth
strips, and MPC pads.

When the backing-mix ducker is installed (`hapax-backing-ducked.conf`,
CVS #145), backing sources route through `hapax-backing-ducked` so
`AudioDuckingController` can pull the backing bed down while YouTube
content plays. Install path: route the relevant return strip through
**Hapax Backing Ducker** per-application once the preset is active. See
`docs/runbooks/audio-topology.md` §2 (sinks) and §5 (ducking matrix) for
the authoritative routing table.

Verify vinyl reaches the broadcast (HISTORICAL — written when the 24c
was the default sink; verification commands referencing
`PreSonus_Studio_24c` are no longer applicable post-decommission. Use
the current default sink in their place.):

```fish
# 1. Confirm the default sink is live (formerly: the 24c sink).
pactl info | grep 'Default Sink'
pactl list short sinks | grep PreSonus_Studio_24c   # historical

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
#    (Audio Mixer → broadcast capture channel should show non-silent meters).
```

## S-4 USB content loopback (evilpet-s4-routing Phase 1, R3)

`hapax-s4-loopback.conf` exposes a stereo virtual sink
(`hapax-s4-content`) that the Elektron Torso S-4 (or any USB-direct
content source) writes to. The loopback forwards into
`hapax-livestream-tap` so OBS sees S-4 content alongside L6 main mix
and vinyl, without serial processing through the Evil Pet (R3 =
parallel path per spec §4).

Install + verify:

```fish
cp config/pipewire/hapax-s4-loopback.conf ~/.config/pipewire/pipewire.conf.d/
systemctl --user restart pipewire pipewire-pulse wireplumber
pactl list short sinks | grep hapax-s4-content
```

Route S-4 USB output through the loopback by selecting **S-4 Content**
as the sink target in pavucontrol or via a wireplumber rule pinning
`alsa_input.usb-Elektron_*` → `hapax-s4-content`.

## S-4 USB device profile pin (dual-fx-routing Phase 1)

`hapax-s4-usb-sink.conf` is a wireplumber-style `monitor.alsa.rules` block
that pins the Elektron Torso S-4 USB audio device to its `pro-audio`
ALSA profile. Without this rule, the default `analog-stereo` profile
collapses everything to a single stereo pair and the dual-FX router
(`agents/hapax_daimonion/voice_path.py`) cannot address S-4 tracks
1-4 independently.

Install + verify (with the S-4 plugged in):

```fish
cp config/pipewire/hapax-s4-usb-sink.conf ~/.config/pipewire/pipewire.conf.d/
systemctl --user restart pipewire pipewire-pulse wireplumber
pactl list short cards | grep -i torso
pactl list cards | grep -A 3 'Active Profile' | grep -i 'pro-audio'
```

Complementary to `hapax-s4-loopback.conf` (evilpet-s4-routing Phase 1):
that conf wires the S-4 stereo content into the livestream tap;
this conf exposes the underlying device's pro-audio capability so
the router has individually-addressable destinations.

## YT bed loudness normalisation (B2 / H#13)

`hapax-yt-loudnorm.conf` creates a stereo `hapax-yt-loudnorm` sink that
operators route YouTube media-bed sources through BEFORE the
voice-over-ytube ducker. Targets -16 LUFS integrated / -1.5 dBTP
true-peak per audit spec §3.4.

Signal chain:

```
YT browser/OBS media source → hapax-yt-loudnorm (this conf) →
  hapax-ytube-ducked (hapax-voice-over-ytube-duck.conf) → default stereo
```

Install (deploy both confs together):

```fish
cp config/pipewire/hapax-yt-loudnorm.conf ~/.config/pipewire/pipewire.conf.d/
cp config/pipewire/hapax-voice-over-ytube-duck.conf ~/.config/pipewire/pipewire.conf.d/
systemctl --user restart pipewire pipewire-pulse wireplumber
pactl list short sinks | grep -E "hapax-yt-loudnorm|hapax-ytube-ducked"
```

In OBS / browser: select **Hapax YT Loudnorm** as the YT media source's
audio output. Loudnorm chains automatically into the ducker.

Tuning starts at threshold -14 dB / ratio 4:1 — heavier than the
voice chain because YT inputs land hotter and uploader variance is
wider. Limiter ceiling -1.5 dBTP leaves 0.5 dB headroom under the
voice chain (-1.0 dB) so the bed can never out-peak the operator.

Measure the output LUFS:

```fish
pw-cat --record --target hapax-yt-loudnorm.monitor --format s16 \
    --rate 48000 --channels 2 --latency 1024 /tmp/yt-bed-30s.wav &
PID=$!; sleep 30; kill $PID
ffmpeg -i /tmp/yt-bed-30s.wav -af loudnorm=print_format=summary -f null -
# "Input Integrated" should land near -16 LUFS.
```

## Troubleshooting

- **Sink does not appear after install:** verify `pipewire.service` and
  `wireplumber.service` are running under systemd user scope; check
  `journalctl --user -u pipewire` for filter-chain load errors.
- **Hardware target not found:** historically the `target.object` in
  each preset pointed at the PreSonus Studio 24c analog output (now
  decommissioned). Edit it to match your own `pactl list short sinks`
  output if you are running on different hardware, or remove the
  `target.object` line to let wireplumber choose the default sink.
- **Restart safety:** switching presets at runtime will briefly unhook the
  sink; the daimonion's pw-cat subprocess auto-restarts on broken pipe,
  so an in-flight TTS utterance may stutter but the daemon recovers.
