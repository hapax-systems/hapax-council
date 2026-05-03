# L-12 Evil Pet Capture: Channel-Map Stride Leakage Root Cause Analysis

**Date:** 2026-05-03
**Author:** alpha (focused diagnostic, in vivo, read-only)
**Conf under investigation:** `config/pipewire/hapax-l12-evilpet-capture.conf`
**Live conf:** `~/.config/pipewire/pipewire.conf.d/hapax-l12-evilpet-capture.conf` (identical to repo copy)
**Related task:** `audio-l12-bleed-mitigation-narrow-aware` (PR #2433, the default-mute gain_samp mitigation that landed without resolving the actual stride bug)

## TL;DR

The chain is producing AUX2-flavoured signal at the chain output even though `pw-link -li` shows identity wiring `capture_AUX5 → input_AUX5`. Cause: **the audioconvert layer inside the filter-chain capture node is applying a 14ch → 4ch surround channelmix matrix** (`channelmix.disable=false`, `channelmix.upmix=true`) instead of identity-routing per AUX position. The Cortado contact-mic loopback (`10-contact-mic.conf`) avoids the matrix by setting `stream.dont-remix = true`; the L-12 evilpet capture conf is missing that property.

**One-line fix:** add `stream.dont-remix = true` to `capture.props` in `hapax-l12-evilpet-capture.conf`.

## Reproduction (read-only)

Run all four capture commands within ~10s of each other so the source content is comparable:

```fish
# 1) Raw 14ch from the L-12 multichannel-input source
timeout 5 pw-cat -r --target alsa_input.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.multichannel-input \
    --channels 14 --rate 48000 --raw /tmp/sync_l12_raw.s32 &
P1=$!

# 2) Chain output (post sum_l/sum_r)
timeout 5 pw-cat -r --target hapax-l12-evilpet-playback \
    --channels 2 --rate 48000 --raw /tmp/sync_chain_out.s32 &
P2=$!
wait $P1; wait $P2
```

Then per-channel RMS and synchronized cross-correlation between each raw AUX and chain output:

```python
import numpy as np
raw = np.fromfile('/tmp/sync_l12_raw.s32', dtype=np.int32)
nr = len(raw) // 14
raw = raw[:nr*14].reshape(nr, 14).astype(np.float64) / 2**31
co = np.fromfile('/tmp/sync_chain_out.s32', dtype=np.int32)
nc = len(co) // 2
co = co[:nc*2].reshape(nc, 2).astype(np.float64) / 2**31
target = co[:, 0]
L = min(len(target), nr)
labels = ['AUX0','AUX1','AUX2','AUX3','AUX4','AUX5','AUX6','AUX7','AUX8','AUX9','AUX10','AUX11','AUX12','AUX13']
for ch in range(14):
    src = raw[:L, ch]
    rms_src = np.sqrt(np.mean(src**2))
    if rms_src < 1e-7: continue
    tgt = target[:L]
    best = 0.0; best_lag = 0
    for lag in range(-8000, 8001, 4):
        if lag < 0: a, b = src[-lag:], tgt[:len(src[-lag:])]
        else: a, b = src[:L-lag], tgt[lag:lag+len(src[:L-lag])]
        if len(a) < 100: continue
        ra = np.sqrt(np.mean(a**2)); rb = np.sqrt(np.mean(b**2))
        if ra < 1e-9 or rb < 1e-9: continue
        c = np.mean(a*b) / (ra*rb)
        if abs(c) > abs(best): best = c; best_lag = lag
    print(f'{labels[ch]:6s} corr={best:+.4f} lag={best_lag} src_RMS={20*np.log10(rms_src):.2f}dBFS')
```

### Observed (synchronized recording, 2026-05-03 16:07 CDT)

L-12 source raw RMS per AUX:
| AUX | RMS (dBFS) | Wired to |
|-----|------------|----------|
| AUX0 (CH1)  | -84.56 | reserve |
| AUX1 (CH2)  | -65.87 | Cortado |
| AUX2 (CH3)  | -41.86 | reserve (live signal) |
| AUX3 (CH4)  | -81.80 | Sampler |
| AUX4 (CH5)  | -200.00 | Rode (silent) |
| AUX5 (CH6)  | -29.73 | EvilPet return |
| AUX12 (Master L) | -29.46 | (mirror of AUX5) |

Chain output:
| Channel | RMS (dBFS) |
|---------|-----------|
| L | -41.86 |
| R | -41.74 |

Cross-correlation against chain output L:
| AUX | corr | Note |
|-----|------|------|
| AUX2 | **+0.998** | **near-identity match — chain output ~= AUX2** |
| AUX9 | +0.947 | (AUX9 mirrors AUX2 in the L-12 routing layout) |
| AUX5 | +0.386 | EvilPet return — the channel the conf intends to feed gain_evilpet |
| AUX12 | +0.373 | Master L (also mirrors AUX5) |
| AUX1 | -0.240 | Cortado, anti-correlated |
| AUX0 | +0.192 | reserve |

The chain output is dominated by AUX2 content (-41.86 dBFS, 99.8% correlation), not by AUX5 (-29.73 dBFS). Even though `pw-link -li` reports the AUX positions are wired identity-style:

```text
hapax-l12-evilpet-capture:input_AUX1 ← capture_AUX1
hapax-l12-evilpet-capture:input_AUX3 ← capture_AUX3
hapax-l12-evilpet-capture:input_AUX4 ← capture_AUX4
hapax-l12-evilpet-capture:input_AUX5 ← capture_AUX5
```

…the symbolic link names are not the path the samples take. Inside the audioconvert stage of the capture node, a channelmix matrix transforms the 14ch ALSA source into the 4ch chain layout via surround-aware coefficients, and that matrix is what pumps AUX2 into the slot the chain expects to be AUX5.

## Topology

Live live state from `pw-cli`/`pw-link`/`pactl`:

```text
ALSA source (14ch, s32le, 48kHz, channel-map AUX0..AUX13)
  alsa_input.usb-ZOOM_Corporation_L-12_8253...-00.multichannel-input  (id 243, RUNNING)

  ↓ wireplumber session-mgr links per-AUX (symbolic, not stride-correct):

Stream/Input/Audio: hapax-l12-evilpet-capture  (id 90, RUNNING)
  audio.channels=4
  audio.position=[AUX1,AUX3,AUX4,AUX5]
  Format: F32P 4ch position [AUX1,AUX3,AUX4,AUX5]
  PortConfig.Input.format.position=[AUX1,AUX3,AUX4,AUX5]
  audioconvert Props (full from pw-dump):
    channelmix.disable=false       ← BUG ROOT
    channelmix.upmix=true
    channelmix.normalize=false
    channelmix.mix-lfe=true
    channelmix.upmix-method=none
    resample.disable=false

  ↓ filter-graph nodes (builtin, internal to chain — not exposed as PW Nodes):
    gain_contact (Gain 1=1.0)  ← input_AUX1
    gain_samp    (Gain 1=0.0)  ← input_AUX3   (default-muted by PR #2433)
    gain_rode    (Gain 1=1.0)  ← input_AUX4
    gain_evilpet (Gain 1=1.0)  ← input_AUX5
    sum_l (Gain 1..4=1.0,1.0,1.0,1.0) ← evilpet, contact, rode, samp
    sum_r (Gain 1..4=1.0,1.0,1.0,1.0) ← evilpet, contact, rode, samp

Stream/Output/Audio: hapax-l12-evilpet-playback  (id 91, RUNNING)
  audio.channels=2  audio.position=[FL,FR]
  → target.object = hapax-livestream-tap (sink)
```

The links audited via `pw-link -li`:
```text
input_AUX1 ← alsa_input...:capture_AUX1   (link id 474)
input_AUX3 ← alsa_input...:capture_AUX3   (link id 475)
input_AUX4 ← alsa_input...:capture_AUX4   (link id 476)
input_AUX5 ← alsa_input...:capture_AUX5   (link id 477)
output_FL → hapax-livestream-tap:playback_FL
output_FR → hapax-livestream-tap:playback_FR
```

The links are NOT a guarantee of identity routing — they describe the symbolic mapping at the port-graph level, while audioconvert's channelmix runs as a post-link DSP stage on the input side of the capture node.

## Root Cause

The capture.props block in `hapax-l12-evilpet-capture.conf` declares only `target.object`, `node.name`, `node.description`, `audio.channels`, and `audio.position`:

```hocon
capture.props = {
    node.name = "hapax-l12-evilpet-capture"
    node.description = "..."
    target.object = "alsa_input.usb-ZOOM_Corporation_L-12_..."
    audio.channels = 4
    audio.position = [ AUX1 AUX3 AUX4 AUX5 ]
}
```

There is no `stream.dont-remix = true` and no equivalent override of `channelmix.disable`. With these defaults, the WirePlumber session manager attaches a channelmixer to bridge the source's `[AUX0..AUX13]` layout to the chain's `[AUX1, AUX3, AUX4, AUX5]` layout. PipeWire's `pipewire-props(7)` man page is explicit:

> **stream.dont-remix = false** (default)
> Instruct the session manager to not remix the channels of a stream. Normally the stream channel configuration is changed to match the sink/source it is connected to. With this property set to true, the stream will keep its original channel layout and the session manager won't add a channel mixer.

The Cortado contact-mic loopback in `10-contact-mic.conf` sets `stream.dont-remix = true` on its `audio.position = [aux1]` capture and routes correctly. The mixer-master loopback in the same file sets it on `audio.position = [aux12]`. The L-12 evilpet filter-chain capture is the only L-12-tapping node in the conf-set that DOES NOT set `stream.dont-remix`.

The matrix that audioconvert chose for 14→4 surround-style downmix happens to put a substantial amount of source AUX2 content into output `AUX5` (and AUX5/AUX12 content gets attenuated by ~13 dB). That is why:

- The chain output at -41.86 dBFS = ~AUX2 level rather than -29 dBFS = AUX5 level.
- Cross-correlation with raw AUX2 = 0.998, with raw AUX5 = 0.386.
- Muting `gain_samp` (PR #2433) didn't fix the problem — it removed AUX3 from the sum but the AUX5 slot was already feeding AUX2-flavoured content, not AUX5-flavoured content.

This also explains the prior agent's earlier observation ("Music currently leaks via gain_evilpet even with L-12 AUX5 silent. After audio.channels=14 fix, the leak attenuated by 11dB but didn't fully disappear"): widening to 14ch lets identity routing happen for any AUX-N → audioconvert can pass-through, and downsumming to 4ch re-engages the matrix that pulls in adjacent AUX content.

## Why this masquerades as "L-12 input silent → chain output noise"

The operator-stated baseline ("all 14 AUX channels at -200dB silent") was incorrect. Empirically right now:

- AUX0 (-84 dBFS), AUX1 (-66 dBFS), AUX2 (-42 dBFS), AUX3 (-82 dBFS), AUX5 (-30 dBFS), AUX7 (-84), AUX8 (-66), AUX9 (-42), AUX10 (-82), AUX12 (-30) are all carrying real signal.
- AUX4, AUX6, AUX11, AUX13 are -200 dBFS (true silence).

So the chain isn't manufacturing noise from silence; it's faithfully passing AUX2-via-matrix at unity gain. The pathology is misattribution: the operator hears "AUX5 should be -30 dBFS but I see -42 dBFS" and attributes the discrepancy to chain-internal noise, when it's actually the channelmix matrix collapsing AUX2 into the AUX5 slot.

## Proposed fix

Single-property addition. Diff against `config/pipewire/hapax-l12-evilpet-capture.conf`:

```diff
             capture.props = {
                 node.name = "hapax-l12-evilpet-capture"
                 node.description = "Hapax L-12 → livestream (per-channel pre-fader/post-comp)"
                 target.object = "alsa_input.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.multichannel-input"
+                # 2026-05-03 — disable audioconvert's channelmix on the chain
+                # capture. Without this flag, audioconvert remaps the source's
+                # 14ch surround layout (AUX0..AUX13) onto our requested 4ch
+                # [AUX1 AUX3 AUX4 AUX5] using a surround downmix matrix; the
+                # matrix puts AUX2 content into the AUX5 slot (cross-corr 0.998)
+                # and attenuates real AUX5 to ~0.39 correlation. Pinning identity
+                # per-AUX is the same technique the Cortado / mixer-master
+                # loopbacks in 10-contact-mic.conf use. RCA:
+                # docs/research/2026-05-03-l12-evilpet-stride-leakage-rca.md.
+                stream.dont-remix = true
                 audio.channels = 4
                 audio.position = [ AUX1 AUX3 AUX4 AUX5 ]
             }
```

That single property is the minimum-change fix. Optional defense-in-depth additions:
- `state.restore = false` — avoid stale wireplumber stream-properties drift across PipeWire restarts.
- `node.dont-reconnect = true` — match the Cortado/mixer_master pattern; with `target.object` pinning a single source we don't want fallback semantics.

Both optional changes are idiomatic for L-12-tapping nodes already used in `10-contact-mic.conf` and `hapax-private-monitor-bridge.conf`.

The fix does NOT change `audio.channels` or `audio.position`. The current narrow [AUX1 AUX3 AUX4 AUX5] is the correct channel set per the constitutional anti-feedback invariant; the RCA confirms narrowing was sound — the missing piece is disabling the matrix that runs after the narrowing.

## Verification protocol

After deploying the conf edit + reloading PipeWire:

1. **Re-record synchronized 14ch raw + chain output** using the reproduction script above.
2. **Per-channel cross-correlation** against chain output L should now show:
   - AUX5 corr ≥ 0.95 (currently 0.386)
   - AUX2 corr ≤ 0.20 (currently 0.998)
   - AUX9 / AUX12 corr ≤ 0.20 (currently 0.947 / 0.373)
3. **Chain output RMS** with current source signal levels:
   - Expected: ≈ -29.7 dBFS RMS (matching AUX5 + small contribution from AUX1/AUX3/AUX4 sums; gain_samp default-muted, so AUX3 contributes 0)
   - Currently: -41.86 dBFS (~12 dB low because AUX5 is being attenuated by the matrix)
4. **Stride-mute test:** silence the L-12's CH3 (AUX2) at the hardware mixer; the chain output RMS should not change (it currently DOES change because chain output ~= AUX2).
5. **EvilPet test:** run a known-amplitude signal through the EvilPet (CH6/AUX5 path); chain output peak should match within 1 dB. Currently it lags by ~12 dB.
6. **Audioconvert dump:** `pw-dump | jq` on the chain capture node Props array — expect either `channelmix.disable=true` or the absence of channelmix coefficients. With `stream.dont-remix=true`, audioconvert will refuse the link if the input layout doesn't include all the requested AUX positions — which is fine because the L-12 source carries all 14 positions natively, including the 4 we ask for.

If verification step 2 still shows AUX2 correlation > 0.5 after the fix, escalate to upstream PipeWire bug report (filter-chain capture might not respect `stream.dont-remix` the same way module-loopback does, in which case the workaround is to add `audioconvert.filter-graph.disable = true` AND/OR construct the chain via `module-loopback` per-AUX into the filter-chain instead of relying on the chain node's own audioconvert).

## Why not a wireplumber rule?

The bug is at the chain-node DSP level, not at the link-policy level. WirePlumber rules can rewrite stream properties, but the cleaner fix is to declare the property in the conf where the chain is defined; wireplumber-rule patching makes this less greppable for future operators.

## Why not "mute samp + done"?

PR #2433 (default-mute gain_samp) is orthogonal to this RCA's fix and should remain. Even with the channelmix matrix corrected, AUX3 (sampler) is wired into the chain via `gain_samp` and will still be mixed into the broadcast sum when the operator un-mutes it. The default-mute is the right safety posture for an idle broadcast surface; this RCA fix addresses the separate question of which source channel actually reaches each gain-stage input port.

## References

- `config/pipewire/hapax-l12-evilpet-capture.conf` — file under repair
- `config/pipewire/10-contact-mic.conf` — reference implementation of `stream.dont-remix=true`
- `config/pipewire/hapax-private-monitor-bridge.conf` — additional reference
- `pipewire-props(7)` — `stream.dont-remix`, `channelmix.disable` definitions
- PR #2433 — gain_samp default-mute (orthogonal mitigation, retained)
- Researcher report a09d834c — original 14→4 channel narrowing rationale (sound; RCA does not unwind it)
- Constitutional invariant `feedback_l12_equals_livestream_invariant` — broadcast must NEVER loop back into L-12 capture; the narrow set [AUX1 AUX3 AUX4 AUX5] enforces this regardless of channelmix.
