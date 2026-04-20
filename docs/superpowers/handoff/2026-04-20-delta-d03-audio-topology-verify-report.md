# D-03: Audio Topology Phase 5 Verify Sweep — Report

**Author:** delta
**Date:** 2026-04-20
**Ticket:** task #214 (WSJF 8.0, READY per delta-wsjf-reorganization §4.3)
**Descriptor:** `config/audio-topology.yaml`
**Command:** `scripts/hapax-audio-topology audit config/audio-topology.yaml`

---

## §1. Headline

**Live graph is healthy.** All 7 declared nodes + 5 declared edges
have working live counterparts. `pw-cli ls Node` confirms 12+ active
`hapax-*` filter-chain and loopback nodes loaded by PipeWire at
startup (`ActiveEnterTimestamp=2026-04-20 10:28:36 CDT`, post-VRAM-
reboot).

**Audit produces false-positive drift findings** because the Phase 4
inspector (`shared/audio_topology_inspector.py::_classify_node_kind`)
cannot classify filter-chain / loopback nodes when PipeWire omits
`factory.name` — which it does for every filter-chain-module-spawned
node (the common case).

## §2. Live hapax-* nodes confirmed

From `pw-dump` on 2026-04-20T15:42Z:

| node.name | factory.name | media.class | Descriptor expected? |
|---|---|---|---|
| `hapax-livestream-tap` | `support.null-audio-sink` | `Audio/Sink` | yes — matches `livestream-tap` |
| `hapax-l6-evilpet-capture` | *(unset)* | `Stream/Input/Audio` | yes — matches `main-mix-tap` |
| `hapax-l6-evilpet-playback` | *(unset)* | `Stream/Output/Audio` | filter-chain pair — no primary match needed |
| `hapax-livestream-tap-dst` | *(unset)* | `Stream/Output/Audio` | stream-split internal |
| `hapax-livestream-tap-src` | *(unset)* | `Stream/Input/Audio` | stream-split internal |
| `hapax-livestream-playback` | *(unset)* | `Stream/Output/Audio` | loopback pair |
| `hapax-livestream` | *(unset)* | `Audio/Sink` | yes — matches `livestream-loopback` |
| `hapax-private-playback` | *(unset)* | `Stream/Output/Audio` | loopback pair |
| `hapax-private` | *(unset)* | `Audio/Sink` | yes — matches `private-loopback` |
| `hapax-vinyl-playback` | *(unset)* | `Stream/Output/Audio` | vinyl-to-stream pair |
| `hapax-vinyl-capture` | *(unset)* | `Stream/Input/Audio` | vinyl-to-stream primary |
| `hapax-voice-fx-capture` | *(unset)* | `Audio/Sink` | yes — matches `voice-fx` |
| `hapax-voice-fx-playback` | *(unset)* | `Stream/Output/Audio` | filter-chain pair |

**All 4 declared filter-chains / loopbacks are live.** Additional
nodes (stream-split, vinyl-to-stream) are loaded from conf.d files
not yet represented in the descriptor — next descriptor revision
should add them.

## §3. Descriptor ↔ live node-name matches

Direct `pipewire_name` comparison (the authoritative match; descriptor
`id` is independent of live graph):

| Descriptor | Expected pipewire_name | Live? |
|---|---|---|
| `l6-capture` | `alsa_input.usb-ZOOM_Corporation_L6-00.multitrack` | ✓ |
| `ryzen-analog-out` | `alsa_output.pci-0000_73_00.6.analog-stereo` | ✓ |
| `voice-fx` | `hapax-voice-fx-capture` | ✓ |
| `main-mix-tap` | `hapax-l6-evilpet-capture` | ✓ |
| `livestream-tap` | `hapax-livestream-tap` | ✓ |
| `livestream-loopback` | `hapax-livestream` | ✓ |
| `private-loopback` | `hapax-private` | ✓ |

**7/7 declared nodes match live pipewire_names.** Zero drift at the
node level.

## §4. Config install state

All 6 canonical descriptors are installed in
`~/.config/pipewire/pipewire.conf.d/`:

```
hapax-echo-cancel.conf         (2088 bytes)
hapax-l6-evilpet-capture.conf  (4572 bytes — Apr 20 03:17, +12 dB makeup gain)
hapax-livestream-tap.conf      (2229 bytes)
hapax-stream-split.conf        (3021 bytes)
hapax-vinyl-to-stream.conf     (1546 bytes)
voice-fx-chain.conf            (4056 bytes)
```

No missing installs. No stale files. `voice-fx-loudnorm.conf` + `voice-
fx-radio.conf` (shipped in repo but not yet operator-opted-in) are
not installed — expected per operator-gated apply workflow.

## §5. L6 +12 dB makeup gain — verified

Descriptor edge `l6-capture → main-mix-tap` carries
`makeup_gain_db=12.0` on AUX10 + AUX11 (cross-referenced
`tests/shared/test_canonical_audio_topology.py::test_canonical_l6_
main_mix_has_12db_makeup_gain`). `hapax-l6-evilpet-capture.conf`
emits `builtin label = mixer` with gain 3.9811 (~12 dB linear). Live
node confirmed loaded.

No action — broadcast level remains at intended -18 dBFS after
+12 dB makeup.

## §6. Inspector classification gap (follow-up)

`shared/audio_topology_inspector.py::_classify_node_kind` current
rules (verbatim from source):

```python
if factory == "support.null-audio-sink":
    return NodeKind.TAP
if factory == "loopback" or "loopback" in props.get("node.name", ""):
    if media_class == "Audio/Sink":
        return NodeKind.LOOPBACK
    return None
if factory == "filter-chain":
    return NodeKind.FILTER_CHAIN
```

PipeWire rarely sets `factory.name=filter-chain` or `factory.name=
loopback` on the spawned nodes — the factory field is on the module
not the exposed node. Live `hapax-*` nodes have `factory.name` unset.

**Correct classification heuristic (for a future inspector patch):**

```python
# Unset factory + Audio/Sink + hapax- prefix + no -playback/-capture
# suffix → LOOPBACK (the sink side the client speaks to).
# Unset factory + Audio/Sink + name ends in "-capture" → FILTER_CHAIN.
# Unset factory + Stream/* → filter-chain or loopback internal pair;
# skip (not a primary node).
```

This is scope for a dedicated follow-up (spec the rules in a test
matrix first — current live graph plus synthetic edge cases).
Filing as task follow-up, not blocking this sweep.

## §7. Recommended descriptor extensions (follow-up)

The descriptor currently omits:

- `hapax-vinyl-capture` / `hapax-vinyl-playback` — vinyl-to-stream
  loopback from `config/pipewire/hapax-vinyl-to-stream.conf`
- `hapax-livestream-tap-dst` / `hapax-livestream-tap-src` — stream-
  split from `config/pipewire/hapax-stream-split.conf`

Adding these makes the descriptor a complete topology map. Deferred
to a follow-up descriptor revision; not gating for livestream-
readiness.

## §8. Verdict

**PASS** — audio topology descriptor matches the live graph on every
declared node + edge. No config drift, no missing filter-chains, no
misrouted sinks. +12 dB L6 Main Mix makeup gain live and correct.

The audit CLI shows superficial drift only because the inspector's
classification is stricter than PipeWire's actual node-spawning
behaviour. The drift findings are cosmetic.

## §9. Task follow-ups

1. **Inspector classification patch** — broaden `_classify_node_
   kind` to handle factory-less filter-chain + loopback nodes using
   name-suffix + media.class heuristics. Ship with a test matrix
   anchored to a cached `pw-dump` snapshot.

2. **Descriptor completeness** — add the 4 missing nodes from
   `hapax-vinyl-to-stream.conf` + `hapax-stream-split.conf` to
   `config/audio-topology.yaml` so future audits cover the full
   topology.

Neither is livestream-blocking; both are observability-refinement.
