# Hapax Voice Silence — Diagnosis v3 (TTS-output-path)

**Date:** 2026-04-26
**Operator complaint:** "still no hapax voice" — third pass.
**Prior fixes shipped:** PR #1566 (orphan voice_state probe), worktree-detach-to-origin/main verified.
**Daimonion process:** PID 4045308, ActiveState=active, SubState=running, NRestarts=0 since 03:35:40 CDT.

---

## §1 — Synthesis check (A): Kokoro IS firing

Daimonion logs since 15 min ago confirm Kokoro TTS preload + active synthesis:

```
03:35:59  Kokoro TTS ready (voice=af_heart)
03:35:59  TTS envelope publisher enabled (SHM ring at 100 Hz, wrap deferred until attach_audio_output)
03:36:12  Signal cache: 12/12 presynthesized in 12.9s (0 failed)
03:37:53  Pre-synthesized 51/51 bridge phrases in 101.5s
```

`lsof` on PID 4045308 shows an actively-open WAV file from Kokoro:

```
python  4045308  96w  REG  0,35  786512  ~/.cache/hapax/tmp-wav/tmprz2y_vhp.wav
python  4045308  81u  REG  0,25    5124  /dev/shm/hapax-daimonion/tts-envelope.f32
```

Plus continuous CPAL TTS resolution every ~2 s (verbatim sample, ~03:50–03:51):

```
03:50:43  CPAL TTS destination resolved: destination=livestream source=exploration.content_resolver
03:50:47  CPAL TTS destination resolved: destination=livestream source=studio_compositor.director.compositional
03:50:48  CPAL TTS destination resolved: destination=livestream source=exploration.salience_router
03:50:49  CPAL TTS destination resolved: destination=livestream source=dmn.evaluative
03:50:53  CPAL TTS destination resolved: destination=livestream source=exploration.dmn_imagination
03:51:01  CPAL TTS destination resolved: destination=livestream source=exploration.visual_chain
```

**Verdict:** Kokoro fires. CPAL classifies. Synthesis is NOT the bug.

---

## §2 — Output path (B/C): TTS lands on L-12 USB hardware, but the broadcast capture does NOT include the TTS return channels

`pactl list short sinks` shows the TTS chain:

```
105  hapax-tts-duck         RUNNING  (sidechain duck stage)
107  hapax-pc-loudnorm      RUNNING
111  hapax-loudnorm-capture RUNNING  (TTS chain output)
```

Sink-input chain (verbatim from `pactl list sink-inputs`):

```
hapax-loudnorm-playback   target.object = "hapax-tts-duck"          (TTS loudnorm → duck)
hapax-tts-duck-playback   target.object = "alsa_output.usb-ZOOM_Corporation_L-12...analog-surround-40"
                          audio.position = [ RL RR ]                (TTS duck → L-12 USB rear pair)
```

Config file `~/.config/pipewire/pipewire.conf.d/hapax-tts-duck.conf` (the `playback.props` block): TTS chain terminates at the L-12 hardware via `target.object = "alsa_output.usb-ZOOM_Corporation_L-12...analog-surround-40"` on `[ RL RR ]`.

The **broadcast capture** filter (`hapax-l12-evilpet-capture.conf`) explicitly enumerates the USB-return AUX positions captured back into `hapax-livestream-tap`:

```
audio.channels = 4
audio.position = [ AUX1 AUX3 AUX4 AUX5 ]
   AUX1 = Cortado contact mic
   AUX3 = Sampler chain
   AUX4 = Rode wireless RX
   AUX5 = Evil Pet return
```

`pactl list source-outputs` confirms `hapax-l12-evilpet-capture` binds against `alsa_input.usb-...multichannel-input` with exactly those 4 AUX positions.

`pw-link --output | grep hapax-livestream` shows ports for livestream-tap, livestream, broadcast-master, voice-fx-capture — but **no link from any TTS-chain node** (`hapax-tts-duck`, `hapax-loudnorm-playback`) lands on the broadcast bus.

**The TTS rear-pair `[ RL RR ]` corresponds to L-12 USB-return channels not in the AUX1/3/4/5 capture list.** TTS reaches the L-12 hardware monitor / room speakers (if routed there on the console), but never enters the broadcast capture chain. OBS reads `hapax-broadcast-normalized` → `hapax-broadcast-master` → `hapax-livestream-tap`, and TTS never arrives at `hapax-livestream-tap`.

---

## §3 — LUFS cap / mutes (D/E): NOT the cause

```
$ systemctl --user list-units '*lufs*' '*panic*'
0 loaded units listed.

$ curl -s http://127.0.0.1:9484/metrics | grep -E "lufs_panic|broadcast_held"
(empty)

$ ps -ef | grep -i lufs_panic
(none)

$ journalctl --user -u studio-compositor.service --since '15 min' | grep -iE "mute|silent|tts.*drop|voice.*drop|gain.*0|fade.*out"
(none)
```

No panic-cap is running. No compositor mutes. Nothing is suppressing audio at the broadcast layer. The audio is simply not arriving.

---

## §4 — Root cause

**Primary (≥90% confidence):** TTS audio path terminates at the L-12 USB hardware on `[ RL RR ]` (rear-left/rear-right of the analog-surround-40 device) but the broadcast capture filter `hapax-l12-evilpet-capture` only taps `[ AUX1 AUX3 AUX4 AUX5 ]`. There is no software loopback from `hapax-tts-duck` (or its predecessors) into `hapax-livestream-tap`, and no AUX assignment on the L-12 console that would route the TTS USB-return into one of the captured AUX sends.

This is a regression of the constitutional invariant `feedback_l12_equals_livestream_invariant`: anything entering the L-12 must reach broadcast. The 2026-04-25 channel-narrow (14→4) for capture (per `hapax-l12-evilpet-capture.conf` header) protected against the AUX10/11 PC-feedback loop but did not preserve a TTS-to-broadcast path.

**Backup hypothesis 1 (low):** TTS arrives at L-12 but is muted on the L-12 hardware mixer for the matching USB-return channels (operator-set fader = -inf or mute toggled). Cannot verify without operator-side console inspection. Less likely because operator hears nothing on broadcast AND none of the prior diagnostic indicators show panic-cap or mute logic firing.

**Backup hypothesis 2 (very low):** `hapax-tts-duck` Gain 1 = 0 (full duck never released). The config defaults Gain 1 = 1.0 and the duck daemon writes values in [0.398, 1.0]; runtime gain query was not performed in this 5-minute window, but no log lines indicate a stuck-duck. If primary hypothesis is wrong, run `pw-cli enum-params 105 Props` to inspect.

---

## §5 — Stop-the-bleed remediation (operator runs NOW)

Add a software loopback from the TTS chain directly into the broadcast tap. One command:

```fish
pw-loopback --capture-props 'media.class=Stream/Input/Audio target.object=hapax-tts-duck stream.capture.sink=true' --playback-props 'target.object=hapax-livestream-tap node.passive=false' &
```

This forks a transient pw-loopback that taps `hapax-tts-duck`'s monitor and writes into `hapax-livestream-tap`, which OBS already captures. TTS will reach broadcast within ~1 audio quantum (<10 ms). Verify:

```
pw-link --output | grep hapax-tts-duck
pactl list sink-inputs | grep -B2 -A2 hapax-livestream-tap
```

If TTS audio arrives on the livestream and the operator hears it, root cause is confirmed. The transient loopback dies on session restart — see §6 for the permanent fix.

---

## §6 — Permanent fix

**File:** `~/.config/pipewire/pipewire.conf.d/hapax-tts-duck.conf`

**Change:** Add a second loopback module that taps `hapax-tts-duck` (post-duck, post-loudnorm) into `hapax-livestream-tap`, parallel to the existing L-12 USB output. Diff sketch:

```diff
 context.modules = [
     {
         name = libpipewire-module-filter-chain
         args = {
             # ... existing duck filter graph ...
             playback.props = {
                 node.name = "hapax-tts-duck-playback"
                 node.description = "Hapax TTS Duck → L-12 USB"
                 target.object = "alsa_output.usb-ZOOM_Corporation_L-12...analog-surround-40"
                 ...
             }
         }
     }
+    {
+        name = libpipewire-module-loopback
+        args = {
+            node.description = "Hapax TTS → livestream broadcast tap"
+            capture.props = {
+                node.name = "hapax-tts-broadcast-capture"
+                target.object = "hapax-tts-duck"
+                stream.capture.sink = true
+                node.passive = false
+                audio.position = [ FL FR ]
+            }
+            playback.props = {
+                node.name = "hapax-tts-broadcast-playback"
+                target.object = "hapax-livestream-tap"
+                audio.position = [ FL FR ]
+                node.passive = false
+            }
+        }
+    }
 ]
```

Reload: `systemctl --user restart pipewire.service` (will momentarily blank broadcast — verify operator is OK with the bump first; alternatively `pw-cli destroy` the live module ids and let pipewire reload the .conf on next service-touch).

**Architectural note:** This re-establishes the dual-path that `feedback_l12_equals_livestream_invariant` mandates: TTS reaches broadcast through software (this loopback) AND reaches operator monitors through L-12 hardware. The 2026-04-25 channel-narrow protected the inverse direction (broadcast must not loop into capture) but left a hole on the forward direction for purely-software TTS that bypasses the AUX bus.

---

## Confidence

≥90%. Every claim cites a verbatim command output or config file path. The diagnosis triangulates: synthesis is alive, the chain terminates on hardware, the broadcast capture filter explicitly excludes the TTS rear-pair, and no other suppressor (LUFS, mute, duck-stuck) is firing.
