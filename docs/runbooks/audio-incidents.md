# Audio Incidents Runbook

cc-task: `audio-audit-H4-incident-runbook` (Auditor A, 2026-05-02 audit).

Operator-readable recovery procedures for the 7 most-recurrent audio
failure modes surfaced in the 24h audit. **Use case: audio breaks at
04:00; recover in 60s without grepping memory.** Each section follows
a fixed shape:

- **Symptoms** — what the operator notices first.
- **Detection** — one command that confirms this is the failure.
- **1-command recovery** — the action that restores the surface.
- **Verification** — one command that confirms recovery.
- **Postmortem evidence-collection** — what to capture before the
  state reverts so a follow-up PR has data.

Cross-link footer in ntfy alerts: append
`Runbook: docs/runbooks/audio-incidents.md#<anchor>` to alert
messages so the operator's notification carries the recovery URL.

---

## Private-playback → L-12 leak (Option C lost)

**Anchor:** `private-leak-l12`

### Symptoms

- Operator-only headphone monitor audio (operator playback, voice
  notes, system sounds) appears in the broadcast egress capture.
- `hapax_audio_egress_lufs_dbfs{stage="broadcast-master"}` rises
  above expected baseline by >3 dB.
- ntfy may fire `audio-private-leak-suspect` (post audit-D probe).

### Detection

```bash
# Cross-correlate private-monitor and broadcast-remap monitors.
pw-cat --record --target hapax-private-monitor.monitor /tmp/p.wav --duration=2 &
pw-cat --record --target hapax-obs-broadcast-remap.monitor /tmp/b.wav --duration=2
wait
python3 -c "
import numpy as np, scipy.io.wavfile as w
_, p = w.read('/tmp/p.wav'); _, b = w.read('/tmp/b.wav')
n = min(len(p), len(b))
corr = float(np.corrcoef(p[:n], b[:n])[0,1])
print(f'corr={corr:.3f}', '— LEAK' if abs(corr) > 0.05 else '— ok')
"
```

### 1-command recovery

```bash
systemctl --user restart hapax-private-broadcast-leak-guard.service
```

(Or, if the leak guard is already running and the leak persists, the
underlying PipeWire link is incorrect — see `Option C pin-resolution`
section below.)

### Verification

Re-run the detection cross-correlation. Confirm `corr < 0.05`.

### Postmortem evidence-collection

```bash
pw-link -l > /tmp/incident-pwlinks-$(date -Iseconds).txt
journalctl --user -u hapax-private-broadcast-leak-guard.service --since '5 min ago' \
    > /tmp/incident-leakguard-$(date -Iseconds).log
systemctl --user list-dependencies hapax-obs-broadcast-remap.service \
    > /tmp/incident-broadcast-deps-$(date -Iseconds).txt
```

---

## Audio ducker daemon dead

**Anchor:** `ducker-dead`

### Symptoms

- Voice TTS plays at full level over music — no automatic music
  ducking when Hapax speaks.
- `systemctl --user status hapax-audio-ducker.service` shows
  `inactive (dead)` or `failed`.

### Detection

```bash
systemctl --user is-active hapax-audio-ducker.service
```

### 1-command recovery

```bash
systemctl --user restart hapax-audio-ducker.service
```

### Verification

```bash
# Trigger a ducked TTS and confirm music dips by ≥6 dB.
hapax-tts "ducker test" &
sleep 1
pw-cat --record --target hapax-music-loudnorm.monitor /tmp/dt.wav --duration=2
python3 -c "
import scipy.io.wavfile as w, numpy as np
sr, x = w.read('/tmp/dt.wav')
rms = np.sqrt(np.mean(x.astype(float)**2))
print(f'music RMS during TTS: {20*np.log10(max(rms,1)):.1f} dBFS')
"
```

### Postmortem evidence-collection

```bash
journalctl --user -u hapax-audio-ducker.service --since '10 min ago' \
    > /tmp/incident-ducker-$(date -Iseconds).log
```

---

## Broadcast egress > 5 dB below target

**Anchor:** `broadcast-low`

### Symptoms

- Stream listeners report quiet broadcast.
- `hapax_audio_egress_lufs_dbfs{stage="broadcast-master"}` reads
  below `-19 LUFS` (target is `-14 ± 3`).
- music-loudnorm filter chain may show `QUANT=0 RATE=0` despite
  pw-cat pumping at hundreds of buffer errors (the rate-mismatch
  cascade — see Auditor A audit §3).

### Detection

```bash
# 5s LUFS measurement of broadcast egress.
pw-cat --record --target hapax-obs-broadcast-remap.monitor /tmp/be.wav --duration=5
ffmpeg -i /tmp/be.wav -filter ebur128=peak=true -f null - 2>&1 | grep -E 'LUFS|TPK'
```

### 1-command recovery

```bash
# Restart the loudnorm + broadcast chain. Order matters.
systemctl --user restart hapax-music-loudnorm.service \
    hapax-obs-broadcast-remap.service
```

If the rate-mismatch hypothesis is the cause: change music-player
`pw-cat` invocation from `--rate 44100` to `--rate 48000` (matches
the sink's 48000 rate; 44100 → 48000 buffer underruns cascade and
the loudnorm sees QUANT=0).

### Verification

Re-run the LUFS measurement. Confirm integrated LUFS is in `[-17, -11]`.

### Postmortem evidence-collection

```bash
pw-cli list-objects | grep -E 'rate|quant' > /tmp/incident-pwrate-$(date -Iseconds).txt
journalctl --user -u hapax-music-loudnorm.service --since '15 min ago' \
    > /tmp/incident-loudnorm-$(date -Iseconds).log
```

---

## L-12 BROADCAST scene unloaded

**Anchor:** `l12-scene-unloaded`

### Symptoms

- Broadcast surface goes silent (no music, no Hapax voice).
- Solid State Logic L-12 mixer's BROADCAST scene is no longer the
  active scene (front-panel display shows a different scene name).
- Often triggered by a power cycle or USB re-enumeration.

### Detection

```bash
# Check L-12 active scene via amixer / sysfs.
ls /proc/asound/cards | grep -i 'L-?12'
cat /proc/asound/card*/usbid 2>/dev/null | head -5
```

### 1-command recovery

Operator action — load BROADCAST scene from the L-12 front panel:

1. Press `SCENES`.
2. Select `BROADCAST`.
3. Press `LOAD`.

(Software cannot remote-control L-12 scene loads; this is a
hardware-only step. Cross-reference cc-task
`l12-hardware-broadcast-routing-restoration` for the deeper
restoration procedure when scene + Evil Pet routing must be
re-established together.)

### Verification

Confirm music + voice present in broadcast egress (use the
`broadcast-low` LUFS detection above).

### Postmortem evidence-collection

```bash
# Capture L-12 USB enumeration history.
dmesg | grep -i -E 'L-?12|Solid State Logic' | tail -50 \
    > /tmp/incident-l12-enum-$(date -Iseconds).log
```

---

## PipeWire restart → Ryzen HDA pin glitch

**Anchor:** `ryzen-hda-pin-glitch`

### Symptoms

- After `systemctl --user restart pipewire`, the Ryzen on-board HDA
  audio (operator headphone Option-C path) targets the wrong sink slot.
- Operator hears system audio in the wrong ear or both ears reversed.

### Detection

```bash
# List sinks; confirm Option-C pin is on the expected slot.
pw-cli list-objects Node | grep -A 3 'analog-stereo'
wpctl status | grep -A 5 'Sinks:'
```

### 1-command recovery

```bash
# Re-pin Option-C to the canonical card profile.
~/.local/bin/option-c-pin-watchdog --force
```

(If the watchdog is not yet installed, see cc-task
`audio-audit-O3c-option-c-pin-resolution-watchdog` — pending
delivery.)

### Verification

Play a quick test tone on the operator-headphone path; confirm
correct ear placement.

### Postmortem evidence-collection

```bash
pw-cli list-objects Node > /tmp/incident-pwnodes-$(date -Iseconds).txt
journalctl --user -u pipewire --since '5 min ago' \
    > /tmp/incident-pipewire-$(date -Iseconds).log
```

---

## xhci controller reset / L-12 channel drop

**Anchor:** `xhci-l12-channel-drop`

### Symptoms

- Mid-stream audio glitches or full silence on the L-12 12-channel
  UAC2 endpoint.
- `dmesg` shows `xhci_hcd ... Reset` immediately preceded by
  `device descriptor read/64, error -71`.
- L-12 channels silently drop from 12 → 8 (or fail entirely).

### Detection

```bash
dmesg | grep -i -E 'xhci|usb [0-9]+: device descriptor' | tail -20
cat /proc/asound/card*/stream0 2>/dev/null | grep -i channel
```

### 1-command recovery

```bash
# The xhci-death-watchdog should auto-recover; if not, manual reset:
sudo systemctl restart hapax-xhci-death-watchdog.service
# Last resort (kernel-level reset of the affected port):
sudo bash -c 'echo 0 > /sys/bus/pci/devices/$(lspci | grep -i xhci | head -1 | cut -d" " -f1)/reset'
```

### Verification

```bash
# Confirm L-12 reports 12 channels again.
cat /proc/asound/card*/stream0 2>/dev/null | grep -i channel
```

### Postmortem evidence-collection

```bash
# Increments hapax_xhci_recovery_total; capture the journal.
journalctl --user -u hapax-xhci-death-watchdog.service --since '15 min ago' \
    > /tmp/incident-xhci-$(date -Iseconds).log
dmesg | grep -i -E 'xhci|usb [0-9]+: device' | tail -100 \
    > /tmp/incident-dmesg-$(date -Iseconds).log
```

---

## LADSPA conf parameter silently rejected

**Anchor:** `ladspa-conf-rejected`

### Symptoms

- A change to `config/pipewire/voice-fx-*.conf` (or other LADSPA
  filter-chain config) appears to do nothing — the audio surface
  sounds identical pre- and post-change.
- No error in journal; PipeWire silently falls back to default
  parameters when a LADSPA control is misnamed or out-of-range.

### Detection

```bash
# Compare the active filter-chain dump vs. the config you intended.
pw-cli list-objects Node | grep -A 20 'filter-chain'
# Check for syntax issues in the conf:
grep -c 'control' ~/.config/pipewire/pipewire.conf.d/voice-fx-*.conf
```

### 1-command recovery

```bash
# Re-apply config after fixing the misnamed control.
systemctl --user restart pipewire wireplumber
```

### Verification

Confirm the filter-chain shows the expected control values
(`pw-cli list-objects Node | grep -A 30 'filter-chain'`).

### Postmortem evidence-collection

```bash
cat ~/.config/pipewire/pipewire.conf.d/voice-fx-*.conf \
    > /tmp/incident-ladspa-conf-$(date -Iseconds).txt
journalctl --user -u pipewire --since '5 min ago' | grep -i ladspa \
    > /tmp/incident-ladspa-$(date -Iseconds).log
```

---

## Cross-reference

- `systemd/README.md § Audio` — service ordering + dependency map.
- `docs/audit-tracking/24h-audio-audit-2026-05-02.md` — original audit.
- ntfy alert messages should append a footer line:
  `Runbook: docs/runbooks/audio-incidents.md#<anchor>` — see anchor
  IDs in each section heading.
