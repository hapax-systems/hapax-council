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
