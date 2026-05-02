# Option C — private-monitor track-fenced via S-4 (operator runbook)

Phase 0 wiring for the Option C resolution of the NO-DRY-HAPAX vs
PRIVATE-NEVER-BROADCASTS contradiction. This document is the operator-
facing runbook for the wiring shipped in this PR. It does NOT cover
S-4 scene programming (operator-side firmware action) and does NOT
cover hardware patch validation beyond a basic post-merge smoke test.

## What Phase 0 ships

1. WirePlumber pin retargeting from Yeti monitor sink to S-4 USB IN
   (`config/wireplumber/56-hapax-private-pin-s4-track-1.conf`). The
   prior Yeti pin is preserved as
   `56-hapax-private-pin-yeti.conf.disabled-2026-05-02-option-c` so
   the operator can revert if needed.
2. Leak-guard rule update in
   `scripts/hapax-private-broadcast-leak-guard`. The S-4 USB OUT pair
   (`alsa_input.usb-Torso_Electronics_S-4_*.multichannel-input` and
   `hapax-s4-content` / `hapax-s4-tap`) is forbidden as a private
   target; the S-4 USB IN sink (`alsa_output.usb-Torso_Electronics_S-4
   _*.multichannel-output`) is allowed (this is the new wet private
   path).
3. Audio-topology descriptor entries for the S-4 USB IN Track 1 input
   slot and the S-4 analog OUT 1/2 endpoint, with the canonical
   private-monitor edges.
4. New runtime-edge classification `private-track-fenced-via-s4-out-1`
   so the topology audit doesn't flag the new edge as unclassified.

## What Phase 0 does NOT ship

- S-4 internal scene programming. The S-4 scene
  `HAPAX-PRIVATE-MONITOR` that wires `Track 1: input = USB IN <pair>,
  output = analog OUT 1/2, slots = <Bypass · Mosaic · Ring · Deform ·
  Vast or operator-chosen wet character>` is operator-side firmware
  action. The implementation cc-task notes this as out-of-scope for
  this PR.
- Operator hardware patch action. The S-4 analog OUT 1/2 patch into a
  non-broadcast monitor sink is operator-confirmed
  (2026-05-02T~17:00Z) and is not enforced or verified by this PR.
- Track-allocation changes for broadcast roles 2-4. The dual-processor
  spec §3.1 source-→-engine contract is unchanged.

## Operator post-merge actions

### 1. Install the new WirePlumber conf

```fish
# Remove the old Yeti-pin conf from the active WirePlumber config dir.
rm -f ~/.config/wireplumber/wireplumber.conf.d/56-hapax-private-pin-yeti.conf

# Copy the new S-4 pin into the active WirePlumber config dir.
cp <repo>/config/wireplumber/56-hapax-private-pin-s4-track-1.conf \
   ~/.config/wireplumber/wireplumber.conf.d/

# Restart WirePlumber so the new policy takes effect.
systemctl --user restart wireplumber.service
```

If something goes wrong and you want to revert to the Yeti pin, copy
the disabled file back and rename it:

```fish
cp <repo>/config/wireplumber/56-hapax-private-pin-yeti.conf.disabled-2026-05-02-option-c \
   ~/.config/wireplumber/wireplumber.conf.d/56-hapax-private-pin-yeti.conf
rm -f ~/.config/wireplumber/wireplumber.conf.d/56-hapax-private-pin-s4-track-1.conf
systemctl --user restart wireplumber.service
```

### 2. Program the S-4 internal scene

Configure the S-4 scene `HAPAX-PRIVATE-MONITOR` with:

- Track 1 input: USB IN <pair> (the host-side multichannel-output sink
  that WirePlumber pins private streams to lands on this USB IN slot
  as the S-4 sees it).
- Track 1 output: analog OUT 1/2.
- Track 1 slots: `Bypass · Mosaic · Ring · Deform · Vast` (the existing
  `VOCAL-MOSAIC` scene shape is the default proposal; pick any wet
  character that destabilizes the dry-voice default — the constitutional
  ground is anti-anthropomorphism, not a specific timbre).

Refer to the S-4 manual (Torso Electronics S-4 Reference Manual, §3
Track Routing and §4 Slot Programming) for scene-mode operation. The
cc-task notes that `shared/s4_scenes.py` already carries 10 scenes; the
new scene's PC and per-slot CC burst should follow that delivery
mechanism (Phase 1 work, not Phase 0).

### 3. Verify the S-4 analog OUT 1/2 patch

The operator's analog patch is operator-confirmed at the spec level
(2026-05-02T~17:00Z). To verify the patch lands on a non-broadcast
monitor sink and not on any L-12 channel input:

```fish
# Audit the live PipeWire graph for the private-monitor route.
hapax-audio-topology verify

# Sample the broadcast tap during a private TTS emission (≥10s).
# The signal should NOT appear on `hapax-livestream-tap`.
pw-cat --record --target hapax-livestream-tap --rate 48000 --channels 2 \
       --format s16 /tmp/livestream-tap-sample.wav &
sleep 10
kill %1
sox /tmp/livestream-tap-sample.wav -n stat 2>&1 | head -5

# Confirm the runtime leak guard reports no new violations.
hapax-private-broadcast-leak-guard --no-repair
```

Acceptable analog patch destinations (per spec §5):

- Standalone headphone amp dedicated to operator monitoring (small
  TR-input headphone amp with no further outputs).
- Motherboard HDA analog OUT (Ryzen onboard codec) to operator monitor
  speaker / headphones.
- Separate USB headphone interface (e.g., Zoom AMS-22) whose output is
  operator monitor only.
- L-12 MONITOR B return ONLY IF that bus is hardware-fenced from the
  L-12 MASTER (and therefore from L-12 USB IN).

Forbidden analog patch destinations:

- Any L-12 channel input (CH1..CH12 or stereo PC IN) whose fader can
  be opened to MASTER.
- Any S-4 USB IN pair (would loop the private signal back through S-4
  USB OUT and into `s4-loopback` → `hapax-livestream-tap`).
- Any other USB capture surface that participates in the broadcast
  graph.

### 4. Test private TTS emission

Once the WirePlumber conf is installed and the S-4 scene is programmed,
emit a test TTS via `role.assistant`:

```fish
# Send a test TTS through the private path. (Exact CLI depends on
# whether a private-emitting consumer is wired today; the role-assistant
# chain is wired but no code path is currently observed emitting
# role.assistant-targeted TTS — see spec §12 open question 3.)
echo 'private monitor test' | hapax-tts --role assistant
```

Expected outcome:

- Operator hears the test phrase on the monitor amp (via S-4 OUT 1/2
  patch) with the chosen wet character applied by the S-4 internal
  scene.
- Broadcast chain shows zero increase: `pw-cat --record --target
  hapax-livestream-tap` for ≥10s during emission samples silence.
- Runtime leak guard reports no new violations.

## References

- Spec: `docs/superpowers/specs/2026-05-02-hapax-private-monitor-track-fenced-via-s4.md`
- Spec (parent): `docs/superpowers/specs/2026-04-21-evilpet-s4-dynamic-dual-processor-design.md`
- Privacy SSOT: `docs/superpowers/specs/2026-04-28-broadcast-audio-safety-ssot-design.md`
- NO-DRY-HAPAX origin: `docs/superpowers/specs/2026-04-23-livestream-audio-unified-architecture-design.md`
- Cc-task: `~/Documents/Personal/20-projects/hapax-cc-tasks/active/private-hapax-s4-track-fenced-implementation.md`
- 3-layer leak guard origin: PR #2221
- Option C amendment merge: PR #2225
