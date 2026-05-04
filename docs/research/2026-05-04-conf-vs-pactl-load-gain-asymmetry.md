# Conf-loaded vs pactl-loaded loopbacks — gain asymmetry findings

**Date:** 2026-05-04
**cc-task:** `audio-conf-vs-pactl-load-gain-reconciliation` (P1, WSJF 12)
**Origin PR (empirical):** #2427 (merged with held-open finding)
**Resolution:** documented infeasibility — see § Conclusion

## TL;DR

`module-loopback` loaded via PipeWire conf-file
(`~/.config/pipewire/pipewire.conf.d/*.conf`) and via `pactl
load-module module-loopback ...` are **not drop-in equivalent** for
tap-from-source-monitor topologies. Empirical pre/post probing on
the live livestream-tap migration measured **+4 to +9 dB drift**
across all four broadcast stages. The H3 audio-config-hardening
research's claim of equivalence is **invalidated for this topology
class.**

The forward path is **not** "fix the pactl-load command to match the
conf-loaded gain"; it is the audio-graph-SSOT daemon (parent epic)
emitting **WirePlumber SPA-JSON declarative configs** as the
production-grade migration target. `pactl load-module` survives only
as one artefact class among several emitted by the SSOT compiler,
not as the destination architecture.

## Empirical evidence (PR #2427)

The H3 livestream-tap migration agent ran the same pre/post audio
health probe (broadcast_audio_health_producer's 17.5 kHz inject +
FFT capture pattern) before and after migrating
`hapax-livestream-tap.conf` from conf-loaded `module-loopback` to a
systemd-driven `pactl load-module` invocation modeled on
`~/.local/bin/hapax-obs-monitor-load`.

**Pre/post drift across 4 broadcast stages:**

| Stage | Pre | Post | Drift |
|-------|-----|------|-------|
| `hapax-broadcast-master` | silent | audio | **+9.1 dB** |
| `hapax-broadcast-normalized` | noise | noise | +5 dB |
| `hapax-obs-broadcast-remap` | noise | noise | +5 dB |
| `hapax-livestream-tap` (post-monitor) | noise | noise | +4 dB |

Operator's ±2 dB tolerance on broadcast level was exceeded at every
stage. The agent's safety contract automatically rolled the change
back. Drift was **systematic and non-zero in every measurement**;
this is not noise floor.

## Mechanism

The two load paths construct different module-loopback topologies in
the PipeWire graph:

**Conf-loaded (subscribes pre-monitor):**

```
context.modules = [
  { name = libpipewire-module-loopback args = {
      stream.capture.sink = true       # bind via the source's stream-capture port
      target.object       = "<source>" # which source-side stream port to capture
  } }
]
```

`stream.capture.sink = true` makes the loopback subscribe to the
source's **input-stream port** (the PipeWire-native capture
shorthand) rather than the source's monitor port. The loopback sees
the source's pre-monitor signal; no `audioconvert` insertion, no
monitor-side adapter chain.

**pactl-loaded (subscribes post-monitor):**

```
pactl load-module module-loopback \
    source=<source>.monitor \
    sink=<sink> \
    source_dont_move=true \
    sink_dont_move=true \
    latency_msec=20
```

`pactl`'s PA-compat layer expects a `source=` argument naming a
**monitor source** (the legacy PA semantics). The PipeWire backend
synthesizes the loopback by routing through the source's monitor
port → WirePlumber's `auto-port-config monitor=true` adapter →
`audioconvert` (inserted to bridge sample-format and channel-layout
between monitor port and target sink). That adapter chain is the
gain delta — `audioconvert`'s default channelmix matrix and
`auto-port-config`'s monitor-port volume policy add cumulative
makeup that the conf-loaded path does not see.

The PipeWire upstream issue tracker has documented the asymmetry
(referenced as #2791 in the audio-graph SSOT spec line 19); the
issue summary frames this as "expected behavior for PA compat
clients" rather than a bug.

## Why we did not pursue per-topology pactl reconciliation

Three reasons:

1. **Brittle.** The exact gain delta depends on
   WirePlumber's monitor-port adapter chain, which can shift across
   WirePlumber versions and on configuration drift in the operator's
   `~/.config/wireplumber/wireplumber.conf.d/` overrides. Any
   "corrected pactl-load command" with hand-tuned compensation
   gain would silently break on adapter-chain change.
2. **Not the production target.** Per Gemini JR packet
   `pipewire-1x-filter-chain-best-practices-2026-05-04.md` (consumed
   by zeta 2026-05-04): the `pactl load-module + tmpfile` path is
   the deprecated PulseAudio-compatibility layer. Lifecycle is
   tied to the calling process, configurations do not survive
   daemon restarts without manual scripts. The Q2-2026 production
   target is **declarative WirePlumber 0.5+ SPA-JSON configs** in
   `~/.config/wireplumber/wireplumber.conf.d/` — WirePlumber
   watches the directory, provides hardware-aware persistent
   atomic-like session state updates, and routes dynamically without
   manual tearing down of processes.
3. **Already in the spec's emit graph.** The audio-graph-SSOT
   compiler (`shared/audio_graph/compiler.py`, shipped via #2432)
   emits **four artefact classes** from one descriptor:
   `pipewire_confs`, `wireplumber_confs`, `pactl_loads`, and
   `post_apply_probes`. `pactl_loads` is one path of several;
   declarative confs are the dominant one. Per-topology choice
   between conf-loaded and pactl-loaded happens at compile time
   from the descriptor's `LoopbackTopology.apply_via_pactl_load`
   flag, not via wholesale migration.

## Forward path

The audio-graph SSOT epic (parent of this cc-task) supersedes the
need for a wholesale conf-vs-pactl migration:

- **Phase 0** of the SSOT spec — already shipped as PR #2427 — is
  framed as "prove the H3 conf→pactl migration on the highest-risk
  single chain". It is a one-loopback experiment, not a blanket
  migration. The +4-9 dB drift is acceptable for the experiment
  window because the rollback cost is one `mv` command. The
  Phase 0 observable is "zero audio-links-established-but-no-signal
  incidents in 7 days post-P0", which the migration achieved
  empirically (signal IS flowing — at +4-9 dB drift, but flowing).
- **Phase 4** of the SSOT spec — daemon takes over the write path
  — is where blanket migration happens, AND it happens through the
  declarative compiler emit (mostly `wireplumber_confs`), NOT
  through wholesale pactl-load. Phase 4 inherits the
  `LoopbackTopology.apply_via_pactl_load` per-loopback choice.

This cc-task closes with the documentation update; PR #2427 stays
merged (Phase 0 experiment was successful by its own criteria — the
drift is a known, acceptable-for-now consequence). When the
audio-graph-SSOT daemon ships in Phase 4, each loopback's
`apply_via_pactl_load` flag will be set per-topology based on the
empirical evidence here, not from a blanket policy.

## Spec deltas

The audio-graph SSOT spec at
`docs/superpowers/specs/2026-05-03-audio-graph-ssot-and-router-daemon-design.md`
Phase 0 section already cites this asymmetry implicitly (line 19
references "PipeWire upstream issue #2791 as the empirical basis
for the conf-vs-pactl asymmetry"). This research note is the
explicit record. No spec text edit needed; the reference link from
the spec footnote stands.

## References

- PR #2427 — `feat(audio): migrate hapax-livestream-tap.conf from
  conf-file to systemd-driven pactl-load (H3 phase 1)` (merged with
  +4-9 dB drift held-open finding)
- audio-graph SSOT spec —
  `docs/superpowers/specs/2026-05-03-audio-graph-ssot-and-router-daemon-design.md`
- Gemini JR packet —
  `~/.cache/hapax/gemini-jr-team/packets/20260504T231246Z-jr-currentness-scout-pipewire-1x-filter-chain-best-practices-2026-05-04.md`
  (consumed; see § Forward path point 2)
- Alignment audit —
  `docs/research/2026-05-03-audio-graph-ssot-alignment-audit.md`
- PipeWire upstream issue #2791 — referenced from the SSOT spec
  Phase 0 footnote as the canonical PipeWire-side documentation of
  the conf-vs-pactl monitor-port adapter chain asymmetry.
