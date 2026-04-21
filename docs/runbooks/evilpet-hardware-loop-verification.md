# Evil Pet Hardware-Loop Verification Runbook

**Purpose.** When the livestream sounds "dry" or TTS reaches broadcast without the expected Evil Pet character, follow this runbook to diagnose the hardware loop.

**Context.** After Phase A1 of `docs/superpowers/plans/2026-04-21-evilpet-s4-dynamic-dual-processor-plan.md`, the software filter-chain no longer has the AUX10/AUX11 raw-PC bypass path. The only route for PC audio to reach broadcast is the Evil Pet hardware loop:

```
Ryzen HDA analog-out  →  L-12 CH11/12  →  L-12 MONITOR A bus  →  Evil Pet IN (1/4" TS)
                                                                     │
                                                                     ▼
                                      L-12 CH6 input  ◀──  Evil Pet OUT  →  CH1 XLR
                                            │
                                            ▼
                                      AUX5 in 14-ch USB capture
                                            │
                                            ▼
                                      gain_evilpet → sum_l/sum_r → hapax-livestream-tap → OBS
```

If any link in the chain is broken, voice reaches the broadcast silently (no dry fallback under §9 governance — FORTRESS stance overrides only).

**Trigger conditions.** Run this runbook when:

1. The Phase A1 software fix has landed but the livestream reports "no voice" or "thin voice".
2. An operator power cycles the L-12 (may reset the front-panel MONITOR A routing).
3. An SD card BROADCAST scene is recalled that doesn't preserve MONITOR A → CH1 → CH6 wiring.
4. A PSU or grounding event (hum, click, silence) suggests cable integrity problem.
5. After any physical re-plugging of Evil Pet or the XLR/TS cables.

---

## Procedure

### Step 1 — L-12 MONITOR A level on CH11/12

- On the L-12 strip for CH11 and CH12, confirm the **MONITOR A rotary knob** is at **~-3 dB** (about 9-o'clock past detent for the standard scene).
- Both CH11 and CH12 should be feeding MONITOR A at the same level (stereo PC pair).
- **Expect:** the MONITOR A meter on the L-12 front panel should pulse when PC audio (TTS, vinyl-playback-through-Ryzen, YT, etc.) plays.

### Step 2 — Evil Pet input signal

- With PC audio playing (e.g., `paplay ~/Music/test.wav` or any TTS emission), confirm the **Evil Pet IN** 1/4" TS cable from L-12 MONITOR A OUT is seated firmly at both ends.
- Visually check the Evil Pet OLED meter (if active with a preset that shows input level) — should register incoming signal.
- If Evil Pet has an input-clip LED, it should not be solid-on (gain too high) or perpetually dark (no signal).

### Step 3 — Evil Pet output to CH1 XLR

- The Evil Pet **OUT** 1/4" TS connects to **L-12 CH1 XLR via a TS-to-XLR adapter** (or TRS-to-XLR cable).
- **Phantom OFF on CH1** (Evil Pet output is line-level; phantom would damage the output stage).
- Operator's CH1 fader is typically up (audible on broadcast via the hardware return path).
- **Expect:** the CH1 signal LED on the L-12 front panel pulses when Evil Pet is processing audio.

### Step 4 — CH6 input (the capture tap)

- CH6 is wired to receive the same Evil Pet output on its XLR input (either via a splitter on CH1, or via a dedicated second cable from Evil Pet).
- **Phantom OFF on CH6.**
- **Expect:** the CH6 signal LED on the L-12 front panel pulses when Evil Pet is processing audio.
- If CH6 LED is dark but CH1 LED is active, the CH1-to-CH6 physical split or second cable is broken.

### Step 5 — SD card BROADCAST scene state

- Press the **L-12 front panel scene recall** for the BROADCAST scene.
- Scene should preserve:
  - MONITOR A routing for CH11/12 at the documented level.
  - CH1 fader at the documented level.
  - CH6 input routing (if any channel-specific routing is part of the scene).
  - Phantom settings (OFF on CH1 and CH6).
- After recall, re-run Steps 1–4 to confirm state is as documented.

---

## What the software will tell you

Live audit on the host:

```bash
# Is the L-12 multichannel-input source emitting anything on AUX5 (CH6)?
pw-cat --record --target "alsa_input.usb-ZOOM_Corporation_L-12_*.multichannel-input" \
       --channels 14 --rate 48000 --format s32le - 2>/dev/null | head -c 4096 | hexdump -C | head -5
```

Non-zero bytes in the AUX5 slice indicate CH6 is receiving signal. All-zero indicates CH6 has no input (which means the hardware loop is broken somewhere between Evil Pet OUT and CH6 IN).

```bash
# Quick pipewire graph sanity check
pw-link -l | grep -B1 -A3 "hapax-livestream-tap:playback"
```

**Expect** `hapax-l12-evilpet-playback:output_FL/FR -> hapax-livestream-tap:playback_FL/FR` as the only producer (plus `hapax-s4-tap` if the S-4 is plugged and its USB bridge is wired).

---

## Common failure modes

| Symptom | Likely cause | Fix |
|---------|--------------|------|
| CH1 LED dark, CH6 LED dark | Evil Pet powered off or 1/4" cable at Evil Pet OUT loose | Power cycle Evil Pet, re-seat TS cable |
| CH1 LED pulses, CH6 LED dark | Split cable / second XLR from Evil Pet broken | Check physical split or replace second cable |
| CH1 LED + CH6 LED pulse, but broadcast still silent | Software path broken — filter-chain not loaded or routed to wrong target | `systemctl --user restart pipewire pipewire-pulse wireplumber`, then `pw-link -l | grep hapax-l12-evilpet-playback` |
| Broadcast has voice but no Evil Pet character | Evil Pet preset not recalled (stuck in bypass, grains=0, mix=0) | Check Erica MIDI Dispatch MIDI 1 port reachable; try `hapax-evilpet-recall hapax-broadcast-ghost` |
| Intermittent silence, signal returns after a few seconds | Ground loop / phantom-power transient | Passive DI between L-12 and Evil Pet (e.g., Radial J-ISO) |

---

## If the runbook doesn't resolve it

1. Emit FORTRESS stance via `hapax-working-mode fortress` — gates the broadcast into pure-dry fallback mode (operator monitor only).
2. Escalate to the operator with a summary of which step failed first.
3. Consider temporarily restoring the AUX10/11 bypass path as a *governance-gated* emergency fallback (not routine; requires §10 Phase A rollback):

   ```bash
   # Only in emergency — reverts the Phase A1 drift fix
   git -C ~/projects/hapax-council revert <phase-a1-commit-sha>
   cp config/pipewire/hapax-l12-evilpet-capture.conf ~/.config/pipewire/pipewire.conf.d/
   systemctl --user restart pipewire pipewire-pulse wireplumber
   ```

## References

- Plan: `docs/superpowers/plans/2026-04-21-evilpet-s4-dynamic-dual-processor-plan.md` Task A2
- Spec: `docs/superpowers/specs/2026-04-21-evilpet-s4-dynamic-dual-processor-design.md` §4.1 hardware affordances
- Research: `docs/research/2026-04-21-evilpet-s4-dynamic-dual-processor-research.md` §2.1
- Prior runbook (ZOOM USB recovery, different failure class): `docs/runbooks/zoom-livetrak-usb-recovery.md`
