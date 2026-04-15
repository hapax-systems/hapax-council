# Voice FX chain PipeWire verification

**Date:** 2026-04-15
**Author:** beta (queue #230, identity verified via `hapax-whoami`)
**Scope:** verify the current state of the Voice FX chain per CLAUDE.md § Voice FX Chain. Catalog installed presets, confirm daimonion routing env, probe the live PipeWire graph, cross-check documentation.
**Branch:** `beta-phase-4-bootstrap`

---

## 0. Summary

**Verdict: filter chain LOADED + HARDWARE TARGET DRIFTED + DAIMONION NOT ROUTING THROUGH IT.**

Four concurrent facts:

1. ✅ **Filter chain is loaded live.** `hapax-voice-fx-capture` + `hapax-voice-fx-playback` both appear in `pactl list short sinks` with `state=running`. The `libpipewire-module-filter-chain` module parsed the installed drop-in successfully.
2. ⚠️ **Installed drop-in is an OLDER version of the repo file** — header comments differ (missing `HAPAX_TTS_TARGET` install note + per-parameter tuning guide), but the filter body (modules, nodes, links) is **byte-identical** (verified by `md5sum` after stripping comments + blank lines). Functionally equivalent, documentation-drifted.
3. ⚠️ **PreSonus Studio 24c is ABSENT from the rig.** The filter's `playback.props.target.object` references `alsa_output.usb-PreSonus_Studio_24c_SC1E24390244-00.analog-stereo`, which does not exist in `pactl list short sinks`, `aplay -l`, or `lsusb`. The 24c appears to be physically disconnected or powered off. Without the target sink, the filter's playback end falls back to the default sink routing (currently `alsa_output.pci-0000_09_00.4.iec958-stereo` — motherboard S/PDIF).
4. ⚠️ **Daimonion is NOT routing TTS through the FX chain.** `systemctl --user show hapax-daimonion.service -p Environment` contains no `HAPAX_TTS_TARGET` entry. Per CLAUDE.md § Voice FX Chain + `conversation_pipeline.py:1856` (`target = os.environ.get("HAPAX_TTS_TARGET") or None`), unset means pw-cat uses the default sink. Kokoro TTS plays directly to the default sink (iec958), bypassing the filter chain entirely.

No unit test coverage and no runtime assertion exists to detect states 3 or 4. The filter chain is a latent, inactive asset at the moment — it will process audio correctly if/when the operator sets `HAPAX_TTS_TARGET=hapax-voice-fx-capture` and restarts the daimonion, but with Studio 24c absent the processed audio will hit iec958 instead of the intended analog path.

**Severity: LOW.** None of this is breaking any current production behavior — TTS is playing, voice loop is functional, the daimonion doesn't depend on the FX chain (it's an opt-in cosmetic). The drift is that the design's intended hardware target is missing and the documentation assumes it. Queue #230's acceptance criteria (catalog, active target verify, filter-chain state capture, documentation drift flag) are all satisfied here.

## 1. Repo preset inventory

```
config/pipewire/
├── README.md                 (58 lines, 2026-04-14 20:14)
├── respeaker-room-mic.conf   (3921 B, 2026-04-15 02:27)  ← MIC CAPTURE, not TTS
├── voice-fx-chain.conf       (4507 B, 2026-04-14 20:14)  ← studio vocal chain
└── voice-fx-radio.conf       (3533 B, 2026-04-14 20:14)  ← AM-radio character
```

**Three configs, but only two are voice-fx presets per the queue spec meaning:**

| File | Role | Character |
|---|---|---|
| `voice-fx-chain.conf` | TTS output filter | Studio vocal chain: HP 80 Hz → low-mid cut 350 Hz → presence 3 kHz → air 10 kHz. Neutral-leaning clarity. |
| `voice-fx-radio.conf` | TTS output filter (sibling preset) | Telephone / AM-radio: bandpass 400–3400 Hz, 6 dB peak at 1.8 kHz. Transmitted/in-world treatment. |
| `respeaker-room-mic.conf` | **Mic input routing** (NOT TTS output) | Pi-fleet ReSpeaker USB Mic Array v2.0 → Silero VAD → PipeWire ROC stream from hapax-ai Pi to workstation. New for the 2026-04-17 ReSpeaker arrival; **not a voice-fx chain preset** — classification as "voice-fx" by sibling pattern only. |

**README.md documentation** (`config/pipewire/README.md`) covers: preset list, install procedure, routing via `HAPAX_TTS_TARGET`, troubleshooting. Current and accurate against the repo. Does not mention the ReSpeaker mic config (added 2026-04-15 after the README was last touched 2026-04-14; minor drift, non-urgent).

## 2. Installed drop-ins

```
~/.config/pipewire/pipewire.conf.d/
├── 10-contact-mic.conf      (1411 B, 2026-04-04 20:12)
├── 10-voice-quantum.conf    (185 B,  2026-03-21 03:36)
├── echo-cancel.conf         (1534 B, 2026-04-03 07:26)
├── noise-suppress.conf      (2228 B, 2026-03-11 16:54)
└── voice-fx-chain.conf      (3658 B, 2026-04-11 22:21)  ← installed voice-fx preset
```

**One voice-fx preset installed.** `voice-fx-radio.conf` is not installed — consistent with the README's "only one preset may be installed at a time" rule (they collide on the sink name).

### 2.1 Installed vs repo drift

```
repo:      config/pipewire/voice-fx-chain.conf          4507 B  mtime 2026-04-14 20:14
installed: ~/.config/.../voice-fx-chain.conf            3658 B  mtime 2026-04-11 22:21
```

**849-byte delta** + **3-day mtime gap** suggested drift. Full diff analysis:

- **Header comments differ.** Installed version is the older form (3-day-old), missing:
  - `# Creates a virtual sink "hapax-voice-fx-capture"` (correct name in the body, absent from the installed header — it says `hapax-voice-fx` instead)
  - `# ROUTE TTS THROUGH THE CHAIN: export HAPAX_TTS_TARGET=hapax-voice-fx-capture` — the operator-facing routing instruction
  - Per-control tuning guide ("More presence: increase Gain on presence_l/r", etc.)
  - `# Sibling presets live alongside this file` (pointer to voice-fx-radio.conf)
- **Filter body is byte-identical.** After stripping comments + blank lines:
  ```
  repo:      md5 33d77ec370677403c561fa9a5db79f82
  installed: md5 33d77ec370677403c561fa9a5db79f82
  ```
  The `context.modules`, `filter.graph`, `capture.props`, `playback.props` blocks all agree. Same 8 BiQuad nodes (hp_l/r, lowmid_l/r, presence_l/r, air_l/r), same links, same target.object.

**Net effect of the drift:** functionally equivalent at runtime (same 4-layer EQ), but a user reading the installed file sees an outdated operator-facing narrative. No production impact; recommend a refresh to reduce CLAUDE.md-to-drop-in drift.

### 2.2 Other installed drop-ins (non-scope, catalogued for context)

- `10-contact-mic.conf` — contact mic loopback routing (supports the Cortado MKIII → contact_mic virtual source path documented in CLAUDE.md § Bayesian Presence Detection)
- `10-voice-quantum.conf` — PipeWire quantum tuning for voice-path latency
- `echo-cancel.conf` — webrtc echo cancellation module (fed by contact_mic per pw-link graph)
- `noise-suppress.conf` — rnnoise module (also fed by contact_mic)

None of these are voice-fx presets; all are supporting audio-graph plumbing.

## 3. Daimonion routing state

### 3.1 `HAPAX_TTS_TARGET` environment

```
$ systemctl --user show hapax-daimonion.service -p Environment
Environment=PATH=... HOME=... XDG_RUNTIME_DIR=... OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
            OPENBLAS_NUM_THREADS=2 ONNXRUNTIME_INTRA_OP_NUM_THREADS=2
            OTEL_BSP_MAX_QUEUE_SIZE=256 OTEL_BSP_MAX_EXPORT_BATCH_SIZE=64
            OTEL_BSP_EXPORT_TIMEOUT=2000 OTEL_BSP_SCHEDULE_DELAY=1000
            CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=0
```

**`HAPAX_TTS_TARGET` is NOT set.** Neither on the service unit, nor in `/run/user/1000/hapax-secrets.env` (`EnvironmentFile` directive).

### 3.2 Source-code path

```python
# agents/hapax_daimonion/conversation_pipeline.py:1845-1861
"""Respects ``HAPAX_TTS_TARGET`` — if set, pw-cat routes the TTS stream
to that PipeWire node. The installed voice FX chain
(``config/pipewire/voice-fx-chain.conf``) provides a ready sink
named ``hapax-voice-fx-capture``. Unset or empty falls through to
the default sink (role-based wireplumber routing, unchanged).
"""
target = os.environ.get("HAPAX_TTS_TARGET") or None
self._audio_output = PwAudioOutput(sample_rate=24000, channels=1, target=target)
if target:
    log.info("TTS routing through PipeWire target: %s", target)
```

With `target = None`, `PwAudioOutput` opens pw-cat without a `--target` flag. PipeWire routes to the default sink (iec958-stereo) via wireplumber's role-based logic. **The FX chain is bypassed entirely.**

## 4. Live PipeWire graph

### 4.1 Filter chain state

```
$ pactl list short sinks | grep -E 'voice-fx|hapax'
55   hapax-voice-fx-capture   PipeWire   float32le 2ch 48000Hz   IDLE

$ pw-dump | jq '.[] | select(.info.props."node.name" | contains("voice-fx"))'
name='hapax-voice-fx-capture'   state=running   media.class=Audio/Sink
name='hapax-voice-fx-playback'  state=running   media.class=Stream/Output/Audio
```

- Both nodes present, both `state=running` (the module is loaded + the filter graph is instantiated)
- `hapax-voice-fx-capture` sink is IDLE at the sink level — **no audio client is connected**, consistent with the HAPAX_TTS_TARGET gap in §3

### 4.2 Upstream feeders of voice-fx-capture

```
$ pw-link -l | grep -A3 'hapax-voice-fx-capture'
(no results — nothing is feeding it)
```

Confirmed: zero audio clients are writing to `hapax-voice-fx-capture`. The filter chain is sitting cold, waiting for a producer.

### 4.3 Downstream destination

```
$ pw-link -l hapax-voice-fx-playback
hapax-voice-fx-playback:output_FL
  |-> input.loopback.sink.role.multimedia:playback_FL
hapax-voice-fx-playback:output_FR
  |-> input.loopback.sink.role.multimedia:playback_FR
```

The filter's output routes into `input.loopback.sink.role.multimedia` (wireplumber role-based multimedia loopback), which in turn outputs to the default sink. **NOT** to the Studio 24c as `target.object` intended — because the Studio 24c sink does not exist at all (§5).

**Why does the playback still reach a speaker?** PipeWire's `target.object` is a hint, not a hard binding. When the target doesn't exist, wireplumber uses default role-based routing. The FX chain silently falls back to the default sink — so if TTS *were* routing through it, the audio would still reach the motherboard iec958 output and be audible, just not through the Studio 24c analog path that the preset was designed for.

## 5. Hardware drift — PreSonus Studio 24c absent

### 5.1 Evidence

```
$ aplay -l | grep -iE 'studio|presonus|24c'
(empty)

$ lsusb | grep -iE 'presonus|studio'
(empty)

$ pactl list short sinks | grep alsa_output
121   alsa_output.pci-0000_03_00.1.hdmi-stereo         ...   SUSPENDED
125   alsa_output.pci-0000_09_00.4.iec958-stereo       ...   RUNNING  (default)

$ pactl info | grep -i 'default sink'
Default Sink: alsa_output.pci-0000_09_00.4.iec958-stereo
```

**No USB audio interface at all.** The ALSA capture inventory shows Logitech BRIO/C920 webcams only (capture-side, for compositor and classifier feeds). The only output sinks are motherboard-borne: HDMI (GB206 graphics) + iec958 S/PDIF (ALC1220 motherboard codec). **No PreSonus Studio 24c present.**

### 5.2 Target.object reference in the filter

```
playback.props = {
    node.name = "hapax-voice-fx-playback"
    node.description = "Hapax Voice FX (output)"
    node.passive = true
    target.object = "alsa_output.usb-PreSonus_Studio_24c_SC1E24390244-00.analog-stereo"
}
```

The `target.object` string names a sink that doesn't exist. PipeWire handles this gracefully (soft fallback to default sink), so no error is logged and no runtime failure occurs — but it means the design-intended signal path is unreachable.

### 5.3 Classification: hardware drift OR config drift?

Two possibilities:

- **A. Hardware removed/unplugged.** The operator may have physically disconnected the Studio 24c (moved it, swapped for different hardware, powered off, USB port issue, etc.). If temporary, the filter preset will resume its intended routing automatically on reconnect.
- **B. Preset config stale.** The operator may have replaced the Studio 24c with different audio hardware and the filter's `target.object` was never updated. In that case the preset needs an edit to match the new hardware.

**Queue #230 cannot distinguish between A and B** from software alone — this requires operator inspection of the physical rig. Flagged for operator follow-up.

### 5.4 Related CLAUDE.md claims

CLAUDE.md § Voice FX Chain (and the repo README) both reference the Studio 24c as the target audio interface. CLAUDE.md § Bayesian Presence Detection also says "Cortado MKIII on PreSonus Studio 24c Input 2 (48V phantom)". If the 24c is truly gone, these passages are stale and contact_mic upstream routing also needs re-auditing (not in scope here — the `contact_mic` PipeWire source is still running and producing audio per pw-link §34, so the Cortado has some working path; how that path connects without a 24c is unclear).

**Non-scope flag:** the contact_mic pipeline continuing to work without the Studio 24c in the ALSA inventory is a separate mystery. Recommended follow-up queue item #231a (audit cortado physical path post-24c-absence) — see §7.

## 6. CLAUDE.md consistency check

Queue #230 asked: "Cross-check against CLAUDE.md documentation".

Relevant CLAUDE.md passage:

> **Voice FX Chain**
> Hapax TTS output (Kokoro 82M CPU) can be routed through a user-configurable PipeWire `filter-chain` before hitting the Studio 24c analog output. Presets at `config/pipewire/voice-fx-*.conf`; install into `~/.config/pipewire/pipewire.conf.d/`, restart pipewire, export `HAPAX_TTS_TARGET=hapax-voice-fx-capture` before starting `hapax-daimonion.service`. Unset falls through to default wireplumber routing. All presets share the same sink name so swapping does not require restarting daimonion. Details: `config/pipewire/README.md`.

| Claim | Verdict |
|---|---|
| Kokoro TTS output can be routed through a filter-chain | ✅ Accurate. `conversation_pipeline.py:1856` implements this exactly. |
| Presets live at `config/pipewire/voice-fx-*.conf` | ✅ Accurate. Two presets + the ReSpeaker config (non-voice-fx). |
| Install via copy to `~/.config/pipewire/pipewire.conf.d/` | ✅ Accurate. Confirmed working (one preset installed, module loaded). |
| `HAPAX_TTS_TARGET=hapax-voice-fx-capture` opt-in | ✅ Accurate. Code reads the env var; unset falls through. |
| **"before hitting the Studio 24c analog output"** | ⚠️ **INACCURATE.** No Studio 24c is present on the rig. Either CLAUDE.md needs a hardware update, or the rig needs the 24c back. |
| "All presets share the same sink name" | ✅ Accurate. README §Presets reinforces this rule (collide on `hapax-voice-fx-capture`). |
| "Details: config/pipewire/README.md" | ✅ Accurate. README exists and is current for repo state (58 lines, covers preset list, install, routing, troubleshooting). |

**Documentation drift:** the phrase "before hitting the Studio 24c analog output" is a factual claim about hardware presence that is no longer true. **Severity: LOW** (cosmetic — no production path depends on this claim being true) but worth fixing on the next CLAUDE.md rotation pass.

## 7. Recommended follow-ups

### 7.1 #231a — Operator-facing hardware audit of Studio 24c absence

```yaml
id: "231a"
title: "Studio 24c USB audio interface missing from rig — operator inspection"
assigned_to: operator
status: offered
depends_on: []
priority: low
description: |
  Queue #230 voice-fx verification found that PreSonus Studio 24c
  is absent from ALSA, PipeWire, and USB. The Voice FX chain's
  target.object references it; CLAUDE.md § Voice FX Chain + § Bayesian
  Presence Detection both reference it. The filter chain currently
  falls back to iec958 (motherboard); contact_mic continues working
  via an unclear path that does not involve the Studio 24c.
  Operator action:
  1. Confirm whether the 24c is intentionally disconnected or has a
     hardware issue
  2. If intentional, decide whether to update CLAUDE.md + the
     filter's target.object to match the new audio path
  3. If unintentional, reconnect + power cycle
size_estimate: "~5 min operator inspection"
```

### 7.2 #231b — Refresh installed voice-fx-chain.conf drop-in to match repo

```yaml
id: "231b"
title: "Refresh installed voice-fx-chain.conf from repo version"
assigned_to: beta
status: offered
depends_on: []
priority: low
description: |
  Installed ~/.config/pipewire/pipewire.conf.d/voice-fx-chain.conf
  is a 3-day-older copy of the repo version. Filter body is
  byte-identical (md5 33d77ec370677403c561fa9a5db79f82 both sides)
  so the update is comment-only, but the installed file lacks the
  HAPAX_TTS_TARGET routing instruction and the per-parameter tuning
  guide in its header.
  
  Actions:
  1. cp config/pipewire/voice-fx-chain.conf ~/.config/pipewire/pipewire.conf.d/
  2. systemctl --user restart pipewire pipewire-pulse wireplumber
  3. Verify sinks via `pactl list short sinks | grep hapax-voice-fx`
  
  Non-urgent — functional behavior does not change.
size_estimate: "~2 min"
```

### 7.3 #231c — CLAUDE.md § Voice FX Chain stale-hardware edit

```yaml
id: "231c"
title: "CLAUDE.md § Voice FX Chain remove Studio 24c claim until hardware confirmed"
assigned_to: beta
status: offered
depends_on: ["231a"]
priority: low
description: |
  Queue #230 verification found the phrase "before hitting the Studio
  24c analog output" in CLAUDE.md § Voice FX Chain is no longer true
  (24c absent from rig). Depending on the outcome of #231a, either:
  - Restore 24c and keep the claim as-is, OR
  - Update CLAUDE.md to say "the default audio sink (currently
    motherboard iec958 S/PDIF)" or whatever the new target is
  
  Tie to the next CLAUDE.md rotation pass per the council CLAUDE.md
  excellence design spec.
size_estimate: "~5 min edit"
```

### 7.4 #231d — Optional: smoke test that actually routes TTS through the chain

```yaml
id: "231d"
title: "Voice FX chain end-to-end smoke test — set HAPAX_TTS_TARGET + trigger TTS"
assigned_to: beta
status: offered
depends_on: ["231a"]
priority: low
description: |
  Queue #230 confirmed the filter chain is loaded but no audio is
  actually flowing through it (HAPAX_TTS_TARGET unset, daimonion falls
  through to default). Optional verification: temporarily set the env
  var, restart daimonion, trigger a TTS utterance, inspect pw-link
  graph to confirm audio is writing into hapax-voice-fx-capture, revert.
  
  Tests the design-intended path end-to-end. Non-urgent.
size_estimate: "~10 min"
```

## 8. Non-drift observations

- **The filter chain's VRAM/CPU footprint is negligible.** `filter-chain` is a PipeWire native module running BiQuad filters — kilobytes of memory, sub-millisecond latency per block. No resource concern.
- **IDLE sink state is not a symptom of failure.** A filter-chain sink reports `IDLE` when no client is connected; this is the normal "loaded but unused" state, distinct from `SUSPENDED` (module unloaded) or `ERROR`. The fact that both nodes are `state=running` under pw-dump while the sink-level state is `IDLE` is correct for a latent-but-loaded filter.
- **Echo-cancel + noise-suppress are active on the contact_mic path.** Separate from the voice-fx chain but worth noting: the audio plumbing drop-ins are doing real work on the mic side (pw-link shows `contact_mic → echo_cancel_capture → noise-suppress-capture → pw-cat`). The TTS output side is the cold asset.
- **ReSpeaker config file presence.** `config/pipewire/respeaker-room-mic.conf` exists in the repo but is not installed anywhere yet — matches the CLAUDE.md § IR Perception note that the ReSpeaker USB Mic Array v2.0 arrives Friday 2026-04-17. Pre-staged, not yet active. Non-drift.

## 9. Cross-references

- Queue spec: `queue/230-beta-voice-fx-chain-pipewire-verification.yaml`
- CLAUDE.md § Voice FX Chain (council CLAUDE.md)
- Repo README: `config/pipewire/README.md`
- Daimonion source: `agents/hapax_daimonion/conversation_pipeline.py:1845-1861`
- `PwAudioOutput` implementation: `agents/hapax_daimonion/pw_audio_output.py`
- Installed drop-in path: `~/.config/pipewire/pipewire.conf.d/voice-fx-chain.conf`
- Live filter module: `libpipewire-module-filter-chain` (PipeWire builtin, no external LADSPA/LV2)
- Related CLAUDE.md sections: § Bayesian Presence Detection (Cortado mic path), § IR Perception (ReSpeaker Friday arrival)

— beta, 2026-04-15T20:25Z (identity: `hapax-whoami` → `beta`)
