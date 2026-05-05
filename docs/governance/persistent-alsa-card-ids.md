# Persistent ALSA card IDs by serial+vid:pid

## Why

On 2026-05-02 the operator's audio topology drifted across reboots:

- A BRIO that had been `hw:11` came back as `hw:12`, then `hw:13` after a
  later replug — the first-letter card-id ALSA auto-assigns
  (`Webcam`, `Webcam_1`, `Webcam_2`) is order-of-enumeration dependent.
- The Zoom LiveTrak L-12 ended up at card 12 vs whatever it was earlier.
- The Torso S-4 was at card 15 one session and card 14 the next.
- `config/audio-topology.yaml` had `hw:11`, `hw:14`, `hw:1` hardcoded
  against the L-12, the Yeti monitor, and the S-4 respectively. Every
  hardcoded numeric index broke.

The numeric ALSA card index is determined by enumeration order at boot. It
has no stable relationship to a physical device. The operator's audio
topology graph (broadcast invariant L-12 = livestream) cannot tolerate
drift here.

The fix: pin every USB-Audio device to a stable symbolic id by `vid:pid`
and (where multiple instances of the same model exist) `serial`. After the
udev rule is installed, `/proc/asound/cards` shows `[L12]`, `[S4]`,
`[Yeti]` regardless of order. Configs reference `hw:CARD=L12` and never
break across reboots.

## What ships in this PR

- `config/udev/rules.d/50-hapax-alsa-card-ids.rules` — the pinning rule.
  Covers L-12, S-4, Yeti, M8, ReSpeaker XVF3800, Erica MIDI Dispatch, three
  BRIOs (by serial), three C920/C920 PROs (by serial across both vid:pid
  revisions).
- `config/audio-topology.yaml` — `schema_version` bumped to 2; all `hw:`
  fields rewritten to symbolic `hw:CARD=<id>` form.
- `scripts/hapax-show-stable-card-ids` — operator helper that reports
  which expected card-ids are present in `/proc/asound/cards` and which
  are missing (rule not installed, device not plugged in, or serial
  drift).
- `tests/scripts/test_alsa_card_id_rules.py` — contract tests pinning the
  rule structure and the audio-topology.yaml symbolic-id migration.
- `docs/governance/persistent-alsa-card-ids.md` — this file.

## Install (operator action)

The PR ships the files; nothing on the system is touched. To activate:

```bash
# 1. Install the rule
sudo install -m 644 \
    config/udev/rules.d/50-hapax-alsa-card-ids.rules \
    /etc/udev/rules.d/

# 2. Reload udev's in-memory ruleset
sudo udevadm control --reload

# 3. Trigger sound subsystem so existing cards are re-evaluated
sudo udevadm trigger --subsystem-match=sound

# 4. Verify
cat /proc/asound/cards
scripts/hapax-show-stable-card-ids
```

After step 3 the expected card ids appear in `/proc/asound/cards` as
`[L12]`, `[S4]`, `[Yeti]`, `[M8]`, `[XVF3800]`, `[Dispatch]`,
`[Brio0..2]`, `[C920a..c]`.

If `udevadm trigger` does not pick up an already-bound card, unbind and
rebind it:

```bash
echo "<card_n>" | sudo tee /sys/class/sound/cardN/.../unbind
# or simply unplug + replug the USB cable
```

A reboot also reliably refreshes the assignments.

## Verify

```bash
# Pinned ids present?
cat /proc/asound/cards
# Expect lines like:
#  11 [L12            ]: USB-Audio - L-12
#  12 [S4             ]: USB-Audio - S-4
#  14 [Yeti           ]: USB-Audio - Yeti Stereo Microphone
#  15 [XVF3800        ]: USB-Audio - ReSpeaker XVF3800

# Self-check helper
scripts/hapax-show-stable-card-ids
# Exit code 0 = all expected pinned ids present
# Exit code 1 = at least one missing (script enumerates which)

# audio-topology.yaml symbolic — should print 0 numeric refs
grep -nE 'hw:[0-9]|surround[0-9]+:[0-9]|front:[0-9]' config/audio-topology.yaml
```

## How to add a new device

1. Plug the device in.
2. Find the `controlC<N>` for it:

   ```bash
   cat /proc/asound/cards
   # 13 [Webcam_1       ]: USB-Audio - SomeNewMic
   ```

3. Discover vid/pid/serial:

   ```bash
   udevadm info /dev/snd/controlC13 | grep -E 'idVendor|idProduct|serial'
   # E: ID_VENDOR_ID=abcd
   # E: ID_MODEL_ID=1234
   # E: ID_SERIAL_SHORT=ABC12345
   ```

4. Add a rule line to
   `config/udev/rules.d/50-hapax-alsa-card-ids.rules`:

   ```
   ATTRS{idVendor}=="abcd", ATTRS{idProduct}=="1234", ATTR{id}="MyDevice"
   ```

   Or, if multiple instances of the same model exist, also constrain by
   serial:

   ```
   ATTRS{idVendor}=="abcd", ATTRS{idProduct}=="1234", ATTRS{serial}=="ABC12345", ATTR{id}="MyDevice0"
   ```

5. Pick a short alphanumeric id (max 15 chars; ALSA truncates beyond).

6. Reload + trigger:

   ```bash
   sudo install -m 644 \
       config/udev/rules.d/50-hapax-alsa-card-ids.rules \
       /etc/udev/rules.d/
   sudo udevadm control --reload
   sudo udevadm trigger --subsystem-match=sound
   ```

7. Add a test entry under `EXPECTED_DEVICES` in
   `tests/scripts/test_alsa_card_id_rules.py` so the CI surface keeps it
   honest.

8. If the new device appears in `audio-topology.yaml` `hw:` fields, use
   the symbolic form `hw:CARD=MyDevice` — never numeric.

## Why this doesn't touch PipeWire configs

PipeWire/WirePlumber sink/source names already include serial numbers
(e.g. `alsa_output.usb-ZOOM_Corporation_L-12_8253FFFF...-00.analog-surround-40`).
Anything that references devices via PipeWire node names is already
stable. The instability was at the ALSA card-index layer
(`hw:11`, `hw:14`), which is what `audio-topology.yaml` and any other
ALSA-direct caller (alsamixer, `arecord -D hw:CARD=...`, `aplay -l`) sees.

This change touches only the udev rule, the topology yaml, the helper
script, and tests. No `~/.config/pipewire/` files are modified.

## References

- ALSA wiki — Changing card IDs with udev:
  <https://www.alsa-project.org/wiki/Changing_card_IDs_with_udev>
- `tomtom215/usb-audio-mapper` — same pattern in the wild.
- `/tmp/usb-hardening-research-2026-05-02.md` §5 — research lineage for
  this PR.
- `docs/runbooks/usb-s4-l12-topology-hardening.md` — broader USB topology
  hardening surface that this rule is one layer of.
