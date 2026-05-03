---
title: Audio Graph SSOT — Alignment Audit (spec ↔ existing reality)
date: 2026-05-03
author: alpha (operator-commissioned; URGENT pre-P1 schema lock)
audience: P1 implementation agent + operator + alpha
register: scientific, engineering-normative
status: audit complete; gap list at §7 is the load-bearing output
related:
  - docs/superpowers/specs/2026-05-03-audio-graph-ssot-and-router-daemon-design.md (the spec being audited)
  - docs/research/2026-05-03-audio-config-hardening-unthought-of-solutions.md (sister hardening research)
  - shared/audio_topology.py (existing schema_version=3)
  - shared/audio_topology_generator.py (existing compiler)
  - shared/audio_topology_inspector.py (existing live-graph reader + invariants)
  - config/audio-topology.yaml (current descriptor; schema 3)
  - shared/audio_topology_typed_params.py (existing typed chain params)
constraint: |
  Read-only audit. NO edits to confs, services, or live audio chain.
  Output: this doc + PR for review.

---

# §0. Executive verdict

The spec is **largely aligned** with existing reality but has **17 gaps** the P1
implementation must fold into the schema design. None of the gaps invalidate
the spec's architectural shape (single applier, lock+transaction, breaker).
However, two gaps are blocking for P1 schema lock and several reveal
spec-cited assets that don't behave as the spec assumes.

The spec's "9 of 11 prevented" claim **does NOT survive audit unmodified**:
two failures (#5 channel-count and #6 hardware-bleed-guard) trace into a
schema field (`ChannelDownmix`, `GainStage.declared_bleed_db`) that the spec
documents but for which no live descriptor today carries the data — coverage
is conditional on a data-population step the spec calls out only in passing.
Operator-facing line: **the spec is aligned; needs 17 gap-folds before P1
locks the schema (12 schema-additive, 4 spec-revisions, 1 scope-creep)**.

---

# §1. Conf inventory + classification

## 1.1 PipeWire confs (~/.config/pipewire/pipewire.conf.d/)

29 .conf files. 5 are disabled (`.disabled-*` suffix). 24 active. 6 are
session-generated `.bak-*` snapshots (not loaded). Active set decomposes
as follows (one row per loaded conf):

| Conf | Module type | Node(s) declared | Inputs / target | Channels / format / position | Spec model class |
|---|---|---|---|---|---|
| 10-contact-mic.conf | 2x loopback | `contact_mic` (Audio/Source), `mixer_master` (Audio/Source) | `node.target=alsa_input.usb-…L-12…multichannel-input`, AUX1 / AUX12 | 1ch MONO / passive=true / dont-reconnect | Node(LOOPBACK) ×2 + LoopbackTopology(apply_via_pactl_load=False) ×2 |
| 10-voice-quantum.conf | (context.properties only) | — | quantum knobs | clock 128/64/1024 @{16k,44.1k,48k} | **NO MODEL** — global tunable, not in Pydantic schema today (gap G-1) |
| 99-hapax-quantum.conf | (context.properties only) | — | quantum knobs | clock 1024/512/2048 @48k only | **NO MODEL** — global tunable (gap G-1) |
| s4-usb-sink.conf | monitor.alsa.rules | (rule, not node) | matches `alsa_card.usb-Torso_Electronics_S-4*` | sets pro-audio profile + priority.session/driver=1500 | **NO MODEL** — WirePlumber-style rule in PipeWire confd; spec's `wireplumber_confs` covers this if the daemon emits it (gap G-2) |
| hapax-broadcast-master.conf | loopback + filter-chain | `hapax-broadcast-master-capture` (lb) → `hapax-broadcast-master` (Source); `hapax-broadcast-normalized-capture` (fc, fast_lookahead_limiter_1913 +14dB / -1dB) → `hapax-broadcast-normalized` (Source) | `target.object=hapax-livestream-tap`, then chain via filter | 2ch / FL FR / passive=false | 2× Node(filter_chain), 2× Edge, 2× LoopbackTopology |
| hapax-l12-evilpet-capture.conf | filter-chain | `hapax-l12-evilpet-capture` (Audio/Sink) → `hapax-l12-evilpet-playback` (Source) | `target.object=alsa_input.usb-…L-12…multichannel-input`, capture 14ch → 2ch via per-channel mixer sum | 14ch capture (AUX0..AUX13) → 2ch FL/FR; `stream.dont-remix=true`; gain_samp=0.0; gain_evilpet/contact/rode=1.0 | Node(filter_chain) + ChannelDownmix(strategy=channel-pick, map={"FL": "AUX1+AUX5", ...}) — **complex 4-source mixdown that ChannelDownmix's current pseudocode does not express** (gap G-3) |
| hapax-livestream-duck.conf | filter-chain | `hapax-livestream-duck` (Audio/Sink) | `node.target=alsa_output.usb-…L-12…analog-surround-40` | 2ch FL/FR → 2ch RL/RR; builtin mixer ducker (Gain 1=1.0); `stream.dont-remix=true` | Node(filter_chain, chain_kind=duck) + Edge with channel remap |
| hapax-livestream-tap.conf | null-sink + loopback | `hapax-livestream-tap` (null-sink, Audio/Sink) + loopback `hapax-livestream-tap-src` → `hapax-livestream-tap-dst` (`target.object=hapax-livestream`, passive=true) | source: `target.object=hapax-livestream-tap` (capture from sink) | 2ch FL/FR; null-sink has monitor.passthrough | Node(TAP) + LoopbackTopology(apply_via_pactl_load=True per P0 — see §6) |
| hapax-m8-loudnorm.conf | filter-chain + loopback | `hapax-m8-loudnorm` (Audio/Sink) + `hapax-m8-instrument-capture` (lb) | sc4m+plate+limiter chain → `target.object=alsa_output.usb-…L-12…analog-surround-40`; lb captures from `alsa_input.usb-Dirtywave_M8…analog-stereo` → m8-loudnorm | 2ch FL/FR → 2ch FL/FR; `stream.dont-remix=true`; **NOT a chain_kind=loudnorm template** — has plate reverb stage; uses `dry/wet mix=0.18` | Node(filter_chain) — **chain_kind taxonomy needs `loudnorm-wet` or similar** (gap G-4) |
| hapax-music-duck.conf | filter-chain | `hapax-music-duck` (Audio/Sink) | `target.object=alsa_output.usb-…L-12…analog-surround-40` | 2ch RL/RR → 2ch RL/RR; duck mixer | Node(filter_chain, chain_kind=duck) |
| hapax-music-loudnorm.conf | filter-chain | `hapax-music-loudnorm` (Audio/Sink) | `target.object=hapax-music-duck` | 2ch FL/FR; fast_lookahead_limiter -18dB | Node(filter_chain, chain_kind=loudnorm) |
| hapax-notification-private.conf | null-sink (factory=adapter, support.null-audio-sink) | `hapax-notification-private` | (no target — fail-closed null sink) | 2ch FL/FR; monitor.passthrough; `monitor.channel-volumes=true` | Node(TAP) — **schema lacks `fail_closed_endpoint=True` boolean as a typed field** (today it's encoded in `params.fail_closed=true` per audio-topology.yaml line 127 — gap G-5) |
| hapax-obs-broadcast-remap.conf | loopback (used as "remap-source" via metadata) | `hapax-obs-broadcast-remap-capture` (lb capture, passive=true) → `hapax-obs-broadcast-remap` (Audio/Source, `device.class=filter`, `node.virtual=true`) | `target.object=hapax-broadcast-normalized` | 2ch FL/FR | Node(filter_chain) + LoopbackTopology — **but conceptually this is a "remap-source" which the spec doesn't enumerate** (gap G-6) |
| hapax-pc-loudnorm.conf | filter-chain | `hapax-pc-loudnorm` (Audio/Sink) | `target.object=alsa_output.pci-0000_73_00.6.analog-stereo` | 2ch FL/FR; sc4m+sc4m+fast_lookahead_limiter -1dB | Node(filter_chain, chain_kind=loudnorm — but compound: 2× sc4m + limiter) — **chain_kind=loudnorm is too coarse for the actual multi-stage shape** (gap G-7) |
| hapax-private-monitor-bridge.conf | 2× loopback | `hapax-private-monitor-capture` (lb cap), `hapax-private-playback` (lb pb); `hapax-notification-private-monitor-capture` (lb cap), `hapax-notification-private-playback` (lb pb) | both pb: `target.object=alsa_output.usb-Torso_Electronics_S-4-…multichannel-output`; both have `node.dont-fallback`, `node.dont-reconnect`, `node.dont-move`, `node.linger` | 2ch FL/FR; `stream.dont-remix=true`; `state.restore=false` | 2× Node(loopback) + 2× LoopbackTopology(source_dont_move=True, sink_dont_move=True, fail_closed_on_target_absent=True) — the spec's LoopbackTopology has `source_dont_move`+`sink_dont_move` but **lacks `dont_reconnect`, `dont_move`, `linger`, `state.restore`** (gap G-8) |
| hapax-s4-loopback.conf | loopback | `hapax-s4-content` (Audio/Sink) → `hapax-s4-tap` | `target.object=hapax-livestream-tap` | 2ch FL/FR; `audio.format=S32`, rate=48000 | Node(loopback) + LoopbackTopology — **spec's FormatSpec field is in §0 promise but not in §2 model classes** (gap G-9 — see also §1.4) |
| hapax-stream-split.conf | 2× null-sink | `hapax-livestream` (null), `hapax-private` (null, fail-closed) | (no targets — pure tap fan-out) | 2ch FL/FR; `monitor.channel-volumes=true`, `monitor.passthrough=true` (private only) | 2× Node(TAP); same gap G-5 (typed fail-closed) |
| hapax-tts-duck.conf | filter-chain + loopback | `hapax-tts-duck` (Audio/Sink), `hapax-tts-broadcast-capture` (lb), `hapax-tts-broadcast-playback` (lb) | duck → `target.object=alsa_output.usb-…L-12…analog-surround-40`; broadcast lb → `target.object=hapax-livestream-tap` | duck: 2ch FL/FR → 2ch RL/RR; broadcast lb: 2ch FL/FR | Node(filter_chain, chain_kind=duck) + 2× Node(loopback). **TTS-broadcast loopback fan-out (one filter feeds two destinations) is not idiomatic in current schema** (gap G-10) |
| hapax-pc-loudnorm.conf | filter-chain | `hapax-pc-loudnorm` (Audio/Sink) | `target.object=alsa_output.pci-0000_73_00.6.analog-stereo` (Ryzen analog) | 2ch FL/FR; sc4m_l + sc4m_r + fast_lookahead_limiter | Node(filter_chain) — same gap G-7 |
| hapax-private-monitor-bridge.conf | (covered above) | | | | |
| hapax-livestream-tap.conf.replaced-by-systemd-2026-05-03 | (snapshot of pre-P0 conf, NOT loaded) | — | — | — | — |
| hapax-obs-monitor-analog.conf.disabled-while-using-pactl | (disabled — superseded by `~/.local/bin/hapax-obs-monitor-load` pactl-load) | — | — | — | — |
| hapax-yt-to-s4-bridge.conf.disabled | (disabled) | — | — | — | — |
| hapax-echo-cancel.conf.disabled | (disabled) | — | — | — | — |
| voice-fx-chain.conf | filter-chain | `hapax-voice-fx` (Audio/Sink) | `target.object=hapax-loudnorm-capture` | 2ch FL/FR; biquad chain (hp/lowmid/presence/air, L+R parallel) | Node(filter_chain) — **biquad chain shape is a third chain_kind today not enumerated** (gap G-7 extension) |
| voice-fx-loudnorm.conf | filter-chain | `hapax-loudnorm` (Audio/Sink) | `target.object=hapax-tts-duck` | 2ch FL/FR; fast_lookahead_limiter -18dB | Node(filter_chain, chain_kind=loudnorm) |
| voice-over-ytube-duck.conf | filter-chain | `hapax-ytube-ducker` (Audio/Sink) | (no target — terminal duck) | 2ch FL/FR; sc4m_l + sc4m_r as sidechain compressors (no sidechain link declared) | Node(filter_chain) — **declared as a "ducker" but uses sidechain compressors not the builtin `mixer` shape that `chain_kind=duck` emits** (gap G-7 extension) |
| yt-loudnorm.conf | filter-chain | `hapax-yt-loudnorm` (Audio/Sink) | `target.object=hapax-ytube-ducked` | 2ch FL/FR; sc4m_l + sc4m_r → fast_lookahead_limiter | Node(filter_chain, chain_kind=loudnorm) — same gap G-7 |

## 1.2 Project-source confs (`config/pipewire/`)

26 .conf files in `config/pipewire/`. These mirror the deployed set — the
`config/` copy is the source-of-truth checked into git, and operator scripts
copy them to `~/.config/pipewire/pipewire.conf.d/`. Drift between the two
copies exists today (e.g. `config/pipewire/hapax-broadcast-master.conf` vs
`~/.config/pipewire/.../hapax-broadcast-master.conf` are both 6865 bytes
but the git copy and live copy can drift independently). The spec's
"sole writer" claim implicitly resolves this drift by making the daemon
the only thing that writes the live copy. **Gap G-11: the spec doesn't
explicitly address whether `config/pipewire/` (the git copy) is
authoritative or derived; today it's neither (operator hand-edits both).**

Additional confs in `config/pipewire/` not deployed:

- `hapax-l6-evilpet-capture.conf` (legacy, replaced by L-12 v2)
- `hapax-pc-router.conf` (descriptor mentions `pc-router` node but live
  graph does not have it — dormant per descriptor `dormant_until_pr_b`
  param; deployed conf would activate Phase B of pc-volume-isolation)
- `hapax-backing-ducked.conf`, `hapax-backing-ducked-sidechain.conf`
  (not deployed; presumably retired)

## 1.3 WirePlumber confs (`~/.config/wireplumber/wireplumber.conf.d/`)

19 .conf files. 3 are disabled (`.disabled-*`). 16 active. Classified by
WirePlumber rule type:

| Conf | Rule type | Targets / Effects | Spec model |
|---|---|---|---|
| 10-default-sink-ryzen.conf | monitor.alsa.rules | priority.session/driver pin: L-12 surround40 = 1500; Yeti output = 100 | `wireplumber_confs` content (spec's `compile_descriptor` emits these) — but **schema for "priority pin" is implicit, not typed** (gap G-12) |
| 20-yeti-capture-gain.conf | monitor.alsa.rules | volume.default = 0.73 on Yeti capture (persistence anchor) | spec's `wireplumber_confs` — same gap G-12 |
| 50-hapax-voice-duck.conf | wireplumber.profiles + .settings + .components.rules + .components | Role-based loopback infrastructure: 4 loopback sinks (multimedia/notification/assistant/broadcast), node.stream.default-media-role = "Multimedia", duck-level = 0.3, role priorities, preferred-target pins | This is the **single most architecturally load-bearing wireplumber conf** and the spec's data model has no clean place to land it. Multiple LoopbackTopology instances + role-priority/duck-level globals + per-role preferred-target pins (gap G-13 — major) |
| 50-voice-alsa.conf | monitor.alsa.rules | Yeti capture: rate=48000, allowed-rates=[48000], suspend-timeout=0 | global rule, not node-level — gap G-12 |
| 51-no-suspend.conf | monitor.alsa.rules | All ALSA: suspend-timeout=86400, pause-on-idle=false | global; gap G-12 |
| 52-iloud-no-suspend.conf | monitor.bluez.rules | iLoud BT: suspend-timeout=0 | bluez rules — **spec doesn't enumerate bluez at all** (gap G-14) |
| 53-hapax-l12-alsa.conf | monitor.alsa.rules | L-12: rate=48000, allowed-rates=[48000], suspend-timeout=0 | gap G-12 |
| 54-hapax-m8-instrument.conf | monitor.alsa.rules | M8: priority.driver/session=100, dont-reconnect=true (deprioritise) | gap G-12 |
| 55-hapax-private-no-restore.conf | wireplumber.settings.restore-stream.rules | Private streams: state.restore-target/props/= false | restore-stream rule — **spec's data model doesn't enumerate restore-stream rules at all** (gap G-15) |
| 55-hapax-voice-role-retarget.conf.disabled-2026-04-28-wsjf004 | (disabled) | — | — |
| 56-bluez-codec-priority.conf | monitor.bluez.properties | iLoud BT: codec ordering, AAC bitratemode | gap G-14 |
| 56-hapax-private-pin-s4-track-1.conf | stream.rules + node.rules | Private streams: target.object=S-4 multichannel-output; dont-fallback/reconnect/move/linger; priority.session=-1 | stream.rules → close to LoopbackTopology props (G-8) but applied via WP rule — **spec describes pin behaviour via per-loopback flags, not per-stream rules** (gap G-16) |
| 60-ryzen-analog-always.conf | monitor.alsa.rules | Ryzen HDA: api.alsa.use-acp=true, device.profile="output:analog-stereo" | profile pin — **spec §7 #9 acknowledges "kernel codec / driver state" as out of model**, but profile pin IS configurable from WirePlumber and should be in the schema (gap G-17) |
| 70-iloud-never-default.conf | monitor.bluez.rules | iLoud BT: priority.driver/session=100, intended-roles="" | gap G-14 |
| 90-hapax-audio-no-suspend.conf | monitor.alsa.rules | All USB ALSA: suspend-timeout=0 | gap G-12 |
| 91-hapax-webcam-mic-no-autolink.conf | monitor.alsa.rules | BRIO/C920 webcam mics: passive=true, dont-reconnect=true | gap G-12 — and the underlying rule "prevent auto-link to default-source" is its own pattern |
| 92-hapax-notification-private.conf | wireplumber.settings | node.routing.notification.role = "hapax-notification-private" | global routing rule — gap G-12 |

## 1.4 Project-source wireplumber confs (`config/wireplumber/`)

12 .conf files. Mirrors the deployed set with similar drift potential as §1.2.
Notable: `56-hapax-private-pin-yeti.conf.disabled-2026-05-02-option-c` is
the prior pin (Yeti) that was superseded by the S-4 pin — kept on disk for
revert capability per the option-c spec.

---

# §2. Runtime pactl modules — actual loaded state at audit time

22 user-loaded modules (IDs 29-50). Cross-referenced against confs:

| pactl ID | Module type | Node name(s) | Source conf | apply_via_pactl_load? |
|---|---|---|---|---|
| #29 | loopback | contact_mic | 10-contact-mic.conf | False (conf-loaded) |
| #30 | loopback | mixer_master | 10-contact-mic.conf | False |
| #31 | loopback | hapax-broadcast-master-capture / hapax-broadcast-master | hapax-broadcast-master.conf | False |
| #32 | filter-chain | hapax-broadcast-normalized-capture / hapax-broadcast-normalized | hapax-broadcast-master.conf | False |
| #33 | filter-chain | hapax-l12-evilpet-capture / hapax-l12-evilpet-playback | hapax-l12-evilpet-capture.conf | False |
| #34 | filter-chain | hapax-livestream-duck | hapax-livestream-duck.conf | False |
| #35 | loopback | hapax-livestream-tap-src / hapax-livestream-tap-dst | hapax-livestream-tap.conf | **MIGRATION TARGET — P0 ships pactl-load via `~/.local/bin/hapax-livestream-tap-load` + `hapax-livestream-tap-loopback.service`** |
| #36 | filter-chain | hapax-m8-loudnorm / hapax-m8-loudnorm-playback | hapax-m8-loudnorm.conf | False |
| #37 | loopback | hapax-m8-instrument-capture / hapax-m8-instrument-playback | hapax-m8-loudnorm.conf | False |
| #38 | filter-chain | hapax-music-duck | hapax-music-duck.conf | False |
| #39 | filter-chain | hapax-music-loudnorm / hapax-music-loudnorm-playback | hapax-music-loudnorm.conf | False |
| #40 | loopback | hapax-obs-broadcast-remap-capture / hapax-obs-broadcast-remap | hapax-obs-broadcast-remap.conf | False |
| #41 | filter-chain | hapax-pc-loudnorm / hapax-pc-loudnorm-playback | hapax-pc-loudnorm.conf | False |
| #42 | loopback | hapax-private-monitor-capture / hapax-private-playback | hapax-private-monitor-bridge.conf | False (but has `dont-fallback/reconnect/move/linger` — spec-incomplete LoopbackTopology, gap G-8) |
| #43 | loopback | hapax-notification-private-monitor-capture / hapax-notification-private-playback | hapax-private-monitor-bridge.conf | False |
| #44 | loopback | hapax-s4-content / hapax-s4-tap | hapax-s4-loopback.conf | False (but has `audio.format=S32` — gap G-9 FormatSpec) |
| #45 | filter-chain | hapax-tts-duck / hapax-tts-duck-playback | hapax-tts-duck.conf | False |
| #46 | loopback | hapax-tts-broadcast-capture / hapax-tts-broadcast-playback | hapax-tts-duck.conf (parallel block) | False |
| #47 | filter-chain | hapax-voice-fx / hapax-voice-fx-capture / hapax-voice-fx-playback | voice-fx-chain.conf | False |
| #48 | filter-chain | hapax-loudnorm / hapax-loudnorm-capture / hapax-loudnorm-playback | voice-fx-loudnorm.conf | False |
| #49 | filter-chain | hapax-ytube-ducker / hapax-ytube-ducked / hapax-ytube-ducker-playback | voice-over-ytube-duck.conf | False |
| #50 | filter-chain | hapax-yt-loudnorm / hapax-yt-loudnorm-playback | yt-loudnorm.conf | False |

**One pactl-loaded module (out-of-band): `hapax-obs-monitor-load` script
loads `module-loopback source=hapax-broadcast-normalized
sink=alsa_output.usb-CalDigit_…analog-stereo` — does NOT show in the
range above because it's loaded via a separate systemd unit
(`hapax-obs-monitor-loopback.service`) not the pipewire conf.d
infrastructure. This is the "OBS-monitor-to-Caldigit-analog-jack"
broadcast monitor patch the operator uses for room speakers/headphones.
It is the precedent the spec cites in §1 line 33.**

After P0 lands (Phase 0 in flight), `hapax-livestream-tap-src/dst` (#35)
will move to a parallel pattern — a second pactl-loaded loopback alongside
the OBS monitor one. **Net result post-P0: 2 of 22 loopbacks are pactl-loaded;
the remaining 20 are conf-loaded.** This shapes what `LoopbackTopology.apply_via_pactl_load`
must select — see §6 for the alignment trace.

---

# §3. Audio-touching service map

Per workspace CLAUDE.md and `systemd/units/`:

| Service | Audio-graph decision at runtime | How decisions land in the graph | Spec model alignment |
|---|---|---|---|
| `hapax-broadcast-orchestrator.service` | YouTube egress lifecycle (start/stop OBS publish, manage RTMP keys) | Reads broadcast state; does NOT mutate the audio graph | OK — spec §4.6 explicitly preserves it as graph-reader |
| `hapax-broadcast-audio-health.service` (consumer) | Reads probe results from JSONL; emits Prometheus + ntfy on failure | No graph writes | OK |
| `hapax-broadcast-audio-health-producer.timer` (60s, contends) | **Injects 17.5 kHz tone via pw-cat into broadcast sinks; captures from monitor via parec** | Calls pw-cat (write) + parec (read); does NOT pactl/pw-link | Spec §4.6 says this becomes "in-process callee" of breaker. But the producer **today is timer-driven and uses pw-cat for inject + parec for capture** — the breaker spec uses **parec only** (`capture_short_window`). The inject path isn't in the breaker design — only continuous capture. **Verify: spec §4.2 only continuously CAPTURES; does it also need to INJECT tones?** Checked — spec uses passive RMS/crest measurement, no tone injection in breaker. Producer's tone-inject role becomes a "boot+recover" probe per spec §5 Phase 5; OK, but the spec needs to make explicit that the breaker is passive-only. (clarification gap, not blocking) |
| `hapax-music-player.service` | Routes music via `hapax-music-loudnorm` sink | Does NOT mutate the graph; selects sink by name | OK |
| `hapax-music-loudnorm-driver.service` | Writes runtime gain to `hapax-music-loudnorm` filter via pw-cli set-param | Runtime control plane; spec §4.6 explicitly delegates control-plane to existing services | OK |
| `hapax-content-resolver.service` | Reads sink list to know which content sinks exist | No graph writes | OK |
| `hapax-audio-router.service` | 5 Hz MIDI arbiter (Evil-Pet/S-4 program changes) — DOES NOT TOUCH THE PIPEWIRE GRAPH | MIDI only | OK (spec §4 line 17 explicitly disambiguates this name vs `hapax-pipewire-graph`) |
| `hapax-audio-ducker.service` | Writes duck gain via pw-cli set-param to `hapax-music-duck`/`hapax-tts-duck` mixers | Runtime control plane (filter-chain control values, NOT topology) | OK — spec §4.6 explicitly preserves |
| `hapax-audio-safety.service` | Reads L-12 capture, detects vinyl+evil-pet co-activity, fires ntfy | Read-only | OK |
| `hapax-audio-signal-assertion.service` (NEW, this branch) | Probes broadcast monitor stages every 30s, classifies, ntfy on bad-state transition | parec only (read); does NOT auto-mute or rollback | **Spec doesn't mention this daemon at all (gap G-spec-1).** Spec § 4.2 + § 4.3 describes a circuit breaker that DOES auto-mute. The new audio-signal-assertion daemon **explicitly does NOT auto-mute** ("False-positive auto-mute is explicitly forbidden by the operator framing"). These are coexisting designs by different authors. **Critical gap: the spec's circuit-breaker auto-mute and the new daemon's explicit no-auto-mute are in tension. The P1 implementer must reconcile or the operator must decide.** (gap G-spec-2 — see §7) |
| `hapax-daimonion.service` | TTS audio output to `hapax-voice-fx-capture` or `hapax-private` (role-based) | Sets media.role on its own stream; does NOT mutate graph | OK |
| `studio-compositor.service` | Reads `hapax-obs-broadcast-remap.monitor` for VAD ducking | Read-only graph consumer | OK |
| `hapax-obs-monitor-loopback.service` (oneshot) | Loads OBS-broadcast→Caldigit pactl loopback (`hapax-obs-monitor-load`) | pactl load-module — **graph-mutating** | Spec §4.6 says "DEPRECATED, daemon takes over" — confirmed plan |
| `hapax-livestream-tap-loopback.service` (NEW, P0) | Loads livestream-tap→livestream pactl loopback | pactl load-module — **graph-mutating** | Spec §5 Phase 0 — covered |
| `hapax-private-broadcast-leak-guard.service` (timer) | Detects + tears down forbidden private→broadcast pw-links | **CALLS pw-link -d (destructive!)** | **Spec §4.1 claims "Sole caller of pactl load-module" but doesn't address pw-link mutations** — this guard tears down pw-links on detection, which is graph-mutating. Spec needs to address this (gap G-spec-3) |

---

# §4. Code-site inventory — every audio-CLI invocation

60 files invoke pactl/pw-cli/pw-link/pw-cat/pw-dump/pw-metadata/parec/parecord
(per `grep -rln` across agents/ scripts/ shared/ systemd/).

## 4.1 Graph-mutating call-sites (must migrate to daemon API in P4)

| File | Tool | Operation | Spec coverage |
|---|---|---|---|
| `~/.local/bin/hapax-obs-monitor-load` | pactl | load-module module-loopback | §4.6 deprecates → migrate via LoopbackTopology(apply_via_pactl_load=True) |
| `scripts/hapax-livestream-tap-load` | pactl | load-module module-loopback | §5 Phase 0 — same migration template |
| `scripts/option-c-repin.sh` | pactl | set-card-profile | §7 #9 acknowledges "partial coverage at best"; spec doesn't model card profiles (gap G-17) |
| `scripts/audio-leak-guard.sh` | pw-link -d | destroy forbidden links | **NOT covered by spec** — runtime backstop that mutates graph (gap G-spec-3) |
| `scripts/usb-router.py` | pw-link, pw-link -d | create + destroy links | NOT covered by spec |
| `agents/local_music_player/player.py:310` | pw-link | create cross-channel link (FL→RL etc.) | NOT covered by spec — runtime link creation |
| `agents/audio_ducker/__main__.py:209` | pw-cli set-param | runtime gain value (control plane) | OK — §4.6 control plane stays |
| `agents/audio_ducker/pw_writer.py:85` | pw-cli set-param | runtime gain value | OK |
| `agents/studio_compositor/audio_ducking.py:125` | pw-cli set-param | runtime gain | OK |
| `shared/audio_topology_switcher.py` | pactl move-sink-input, set-default-sink | runtime sink switch | Switcher folded into daemon `apply()` per §9 |
| `shared/audio_route_switcher.py` | pactl set-default-sink | default-sink switch | Same — folded into apply |
| `shared/audio_working_mode_couplings.py` | (consumer; gates other writers) | refers to set-default-sink | OK |
| `agents/hapax_daimonion/init_actuation.py` | pw-cli | (need to read) | likely runtime-control |

## 4.2 Read-only call-sites (continue to coexist)

55+ sites use parec/parecord/pw-cat/pw-dump/pw-link -l (read-only). All
spec-compatible. Notable:

- `agents/broadcast_audio_health_producer/producer.py` — pw-cat (inject) + parec (capture); spec reuses primitives
- `agents/audio_safety/vinyl_pet_detector.py` — pw-cat L-12 capture
- `agents/hapax_daimonion/backends/contact_mic.py` — pw-record contact_mic
- `shared/audio_topology_inspector.py` — pw-dump
- `agents/audio_signal_assertion/probes.py` (new) — parecord
- `scripts/usb-router.py` — pw-link -l (also -d, see above)

---

# §5. Failure-mode coverage trace (verify spec §7)

Walked each of the 11 failure rows. Findings:

| # | Failure | Spec claim | Trace status | Confidence call |
|---|---|---|---|---|
| 1 | FL/FR vs RL/RR mismatch | P1 PORT_COMPATIBILITY invariant | Schema does not yet have port-pair declarations on Edge — `Edge.source_port`/`target_port` are `str` strings, no compat checker. Pseudocode exists in spec §2.1. Schema needs port-vocabulary enum. | spec's "high confidence" requires the checker code — the data shape is OK. Confirm |
| 2 | 8s probe contending with L-12 | P5 breaker in-process; timer 30 min | Producer today fires every 60s (`hapax-broadcast-audio-health-producer.timer`); spec moves it to "30 min boot+recover". The new `audio-signal-assertion` daemon at 30s is **a third probe surface** the spec did not anticipate. **Confidence-revising**: spec's claim of "becomes 30-min, low-contention" only holds if audio-signal-assertion is integrated or retired. Else there are 3 probe surfaces (today's producer, breaker, signal-assertion) all parec-ing the same monitor. (gap G-spec-2 cont.) | Confidence drops from "high" → "medium-high", contingent on 3-way reconciliation |
| 3 | private→L-12 leak | P1 PRIVATE_NEVER_BROADCASTS pre-apply blocking | Inspector already enforces this statically on the descriptor (`check_l12_forward_invariant` in `audio_topology_inspector.py:835`); spec lifts it to apply-time blocking. Reachability checker is implementable from existing Edge data. **Confidence holds: very high.** | Confirm |
| 4 | conf-file loopback fails / pactl-load works | P1 LoopbackTopology.apply_via_pactl_load expressible per-loopback | Schema has the field. Generator/compiler does NOT yet emit pactl-load artefacts (today: only confs). P0 ships the script-based migration as a one-shot pattern. **Confidence holds**, but the pactl-load emit path needs writing as part of P1, not just the schema bit. | Confirm |
| 5 | audio.channels=2 vs 14 ch capture (silent downmix) | P1 FORMAT_COMPATIBILITY + CHANNEL_COUNT_TOPOLOGY_WIDE invariants | The current `hapax-l12-evilpet-capture.conf` declares `audio.channels = 14` AND `audio.channels = 2` (capture vs playback) with explicit per-AUX gain stages summing to L+R. **The spec's `ChannelDownmix` model with `strategy="channel-pick"` and a flat `map: dict[str, str]` does NOT express the ACTUAL summed mixdown** (4 AUX channels each routed to gain stages, then summed via 2 mixer nodes to 2 output ports). The schema needs `strategy="ladspa-mixdown"` or a richer expression. (gap G-3) **This was THE failure that motivated the spec; coverage as-described is partial only.** | Confidence drops from "very high" → "medium". Schema design must absorb gap G-3 first |
| 6 | gain_samp=1.0 with -27 dB hardware bleed | P1 HARDWARE_BLEED_GUARD invariant + GainStage.declared_bleed_db | Spec §2.1 acknowledges "depends on operator declaring the bleed values; the model surfaces the missing data." **Today's descriptor has zero `declared_bleed_db` populated.** The bleed values exist only in the conf comments (e.g. `hapax-l12-evilpet-capture.conf` line 87: "L-12 hardware preamps on CH3 (AUX2) and CH4 (AUX3) carry audio at -25 dB to -28 dB"). The schema is correct; the data is absent. P1's CI gate would NOT catch today's #6 because no descriptor declares bleed. | Confidence "medium-high" matches spec; needs operator-driven measurement step explicit in P1 |
| 7 | pipewire restart breaks links (auto-link reorder) | P4 apply path includes settling + post-apply probes; rollback if links fail | Settling + probes are P5 (not P4). Spec §5 Phase 4 says "apply()" runs probes; Phase 5 is "circuit breaker hardening." Mild inconsistency between which phase covers this. Confidence holds — but the phase ordering is muddled (gap G-spec-4) | Confirm; ordering nit |
| 8 | concurrent session edit → BT hijack | P3 applier lock | flock(2) on `~/.cache/hapax/pipewire-graph/applier.lock`. Hook gates Edit/Write tool calls. Confidence holds: very high. | Confirm |
| 9 | pro-audio + HP pin codec mux re-route | P4 descriptor includes profile/pin state; verify_live diffs against current | The schema **today has no profile/pin field** (gap G-17). `60-ryzen-analog-always.conf` is a WirePlumber rule pinning `device.profile="output:analog-stereo"` — the spec emits wireplumber confs but the typed shape of "card profile pin" isn't in the model. Spec's "medium" confidence is honest. | Confirm "medium" |
| 10 | service-restart cascade | P5 snapshot before restart, post-restart verify, rollback if drift | Daemon owns systemd restart in apply path per §4.4 step 5. **But not all audio-touching services restart through the daemon today** — many have their own After=pipewire.service ordering and restart independently. The daemon's "snapshot before restart" only catches the 4 services it controls (pipewire, wireplumber, pipewire-pulse, plus its own loopback units). External restarts are still uncoordinated. | Confidence "high" only for daemon-orchestrated restarts; external restarts (pavucontrol drag-drop, manual systemctl) bypass — partial |
| 11 | conf-file links established but no signal | P5 post-apply probes assert detection | This is the same pattern as #4 (probe asserts signal flow). If P5 ships post-apply probes per §3.1 and #4's pactl-load artefact emits, this failure class IS caught. **Confidence holds: very high.** | Confirm |

**Updated coverage rollup:** 6 of 11 high+ confidence (1, 3, 4, 8, 11; #7 with phase-order nit). 3 of 11 medium-confidence (5, 6, 9). 2 of 11 conditional on cross-daemon reconciliation (2, 10). The spec's "9 of 11 high confidence" claim does NOT survive this audit — closer to "5-6 of 11 high, 3 medium, 2 conditional".

---

# §6. Reused-asset alignment (verify spec §9)

| Asset | Spec claim | Actual state | Alignment |
|---|---|---|---|
| `shared/audio_topology.py` | reused unchanged | Schema v3 (302 lines); has Node/Edge/ChannelMap/TopologyDescriptor + typed chain params | Spec is correct. **But** the spec's new model classes (`BroadcastInvariant`, `ChannelDownmix`, `GainStage`, `LoopbackTopology`) live in a NEW file `shared/audio_topology_invariants.py`, and the Edge model **today has only `makeup_gain_db`** — the spec's `GainStage` is a separate parallel type. Migration must clearly say "Edge.makeup_gain_db is preserved; GainStage is the per-channel-aware overlay" or unify. (clarification gap, not blocking) |
| `shared/audio_topology_generator.py::generate_confs()` | becomes internal of `compile_descriptor()` | 581 lines; emits per-Node conf fragments, dispatches by `chain_kind` (loudnorm/duck/usb-bias). Has `ConfigError`, LADSPA range clamps. | Aligned. **But generator emits ONLY pipewire confs, not wireplumber confs.** Spec §3.1 ships `wireplumber_confs` as a NEW capability (not reused). Honest framing missing in §9. |
| `shared/audio_topology_inspector.py` | check_* fns become BroadcastInvariant checkers | 838 lines. Has `check_tts_broadcast_path`, `check_l12_forward_invariant`. The `_PRIVATE_FORBIDDEN_REACHABILITY` set and `_PRIVATE_ONLY_ROOTS` set match spec's pseudo-code structure. | Aligned. The inspector's existing reachability checker IS what `check_private_never_broadcasts` (spec §2.3) describes. **Lift, don't rewrite.** |
| `shared/audio_topology_switcher.py` | folded into daemon's `apply()` | 246 lines. `switch_voice_path()` runs pactl move-sink-input + set-default-sink for live route switches. **NARROW SCOPE** — switches between sinks for daimonion's voice path; does NOT do snapshot/transaction/rollback. The spec's `apply()` is a 5-tuple compile + atomic write + probes + rollback. Switcher is one input to that. | Spec's "folded into" is correct directionally but **understates the LOC delta**: switcher is ~250 LOC, spec's apply() is closer to 1500-2000 LOC of new logic. The reuse is one helper among many. Honest reframe: reuse is asset-shape, not asset-volume. |
| `scripts/hapax-audio-topology` (CLI) | subcommands apply/lock/current added | 1100+ lines; current subcommands: describe / generate / diff / verify / audit / l12-forward-check / pin-check / watchdog. Spec §5 Phase 3 wraps a NEW `hapax-pipewire-graph` CLI for daemon API. Note: spec aspires to add subcommands to **existing** CLI ("Stays as a CLI; subcommands `apply`/`lock`/`current` added (replaces today's `switch`)") but in §4 introduces a separate `hapax-pipewire-graph` daemon name. The script-vs-daemon naming may collide. | Naming ambiguity (gap G-spec-5). Recommendation: clarify whether `hapax-audio-topology` and `hapax-pipewire-graph` are the same CLI or two. |
| `agents/broadcast_audio_health_producer/producer.py` | inject+capture+FFT primitives drive both breaker and PostApplyProbe | producer.py + `shared/audio_marker_probe_fft.py` exist. Inject (pw-cat) + capture (parec) + FFT detector (numpy) all present. **But the breaker spec only USES capture+RMS+crest+ZCR (no FFT, no inject).** Reuse of inject path is for PostApplyProbe (post-apply verify), not the breaker. Honest framing. | OK once that distinction is made explicit |
| `scripts/audio-leak-guard.sh` | folded into PRIVATE_NEVER_BROADCASTS checker | bash script that calls `pw-link -l` to detect runtime forbidden links + `pw-link -d` to tear them down on detection. **Mutating script** — see gap G-spec-3. Spec says "folded into checker" which is non-mutating. Mismatch: today's leak-guard MUTATES; the spec's checker only DETECTS. The mutation must move somewhere (daemon emergency rollback path?). | Confidence: medium. Spec's framing is non-mutating; reality is mutating. |
| `~/.local/bin/hapax-obs-monitor-load` | pattern lifted into PactlLoad artefact emission; deprecated in P4 | 96 lines bash; idempotent pactl load-module pattern with hot-plug wait. P4 lifts → emit. | Aligned. Phase 0's livestream-tap-load (also deployed) is a second instance of the same pattern. |
| `config/audio-topology.yaml` | becomes generative — every conf and pactl-load is derived from it | 628 lines; schema v3; covers most live nodes (33 nodes, 14 edges). Contains placeholders like `dormant_until_pr_b: true`. **Today the YAML is descriptive — the live confs are still hand-edited and the inspector audits a diff.** Generator emits confs from YAML but operator does not run it as the source-of-truth pipeline today. | Aligned conceptually; reality is "descriptive, not generative." Spec's transition is the load-bearing migration. |
| `agents/audio_safety/` | exists, what does it do today? | Yes — `vinyl_pet_detector.py` + systemd service. Detects vinyl+evilpet co-activity from L-12 capture, fires ntfy/impingement. **READ-ONLY, does NOT mutate graph.** | Aligned. Coexists per §4.6. |

---

# §7. GAPS — load-bearing list (P1 must fold these BEFORE schema lock)

Total gaps surfaced: **17**. Classification:

- 12 schema-additive (need new fields/types in P1)
- 4 spec-revisions (need spec text updates before P1 schema lock)
- 1 scope-creep (acknowledged, must be punted explicitly)

## Schema-additive (P1 schema must add these)

**G-1: Global tunables (quantum knobs).** `10-voice-quantum.conf`,
`99-hapax-quantum.conf` declare `default.clock.quantum`, `min-quantum`,
`max-quantum`, `allowed-rates`. No model class. Spec §8 OQ-2 mentions this:
"those become first-class descriptor fields (`schema_version=4`)". P1 must
ship `GlobalTunables` model class or `TopologyDescriptor.tunables: dict[str, str|int|float|list]`.

**G-2: ALSA card profile pinning.** `s4-usb-sink.conf` (in pipewire confd
even though it's wireplumber-style) and `60-ryzen-analog-always.conf`
declare `monitor.alsa.rules` matching cards by name and pinning
`device.profile`, `api.alsa.use-acp`. No model class. P1 must ship
`AlsaProfilePin` (card_match: str, profile: str, use_acp: bool, priority: int).

**G-3: ChannelDownmix `strategy="channel-pick"` is too narrow for the L-12
14→2 mixdown.** Today the descriptor has `params.capture_positions = "AUX1
AUX3 AUX4 AUX5"` and the live conf has 4 per-channel gain stages summing
to 2 mixers. Spec's `map: dict[str, str]` shape `{"FL": "AUX1+AUX5"}` is
prose-illustrative, not Pydantic-valid (the Field type is `dict[str, str]`,
not `dict[str, list[tuple[str, float]]]` for gain-controlled mixdown).
**P1 must add `strategy="ladspa-mixdown"` with a typed sub-model
`MixdownGraph(stages: list[GainStage], routes: list[MixerRoute])`** — or
admit that `ChannelDownmix` can't express the L-12 case and add a separate
`FilterChainMixdown` Node-attached model.

**G-4: `chain_kind="loudnorm-wet"` (or richer template taxonomy).** M8's
loudnorm chain includes `plate_1423` reverb (`Reverb time=3.5`,
`Damping=0.40`, `Dry/wet mix=0.18`). Today schema has only `loudnorm` /
`duck` / `usb-bias`. P1 must extend the `Literal[...]` enum, OR replace
`chain_kind` with a more general `FilterChainTemplate` discriminated union.

**G-5: `fail_closed_endpoint: bool` typed field on Node(TAP).**
`hapax-private`, `hapax-notification-private`, `hapax-private-monitor-bridge`
are all "fail-closed" today via `params.fail_closed=True`. Promotes a
behavioral invariant from a string param to a typed field. Important
because PRIVATE_NEVER_BROADCASTS reachability check uses this signal.

**G-6: "remap-source" loopback variant.** `hapax-obs-broadcast-remap.conf`
is a `module-loopback` whose playback-side advertises `media.class =
Audio/Source`, `device.class = filter`, `node.virtual = true` so OBS's
plugin persists the selection. This is functionally a remap-source (the
spec says it's "Equivalent to `pactl load-module module-remap-source`").
P1 must either (a) extend `LoopbackTopology` with `as_source: bool` /
`virtual_source_metadata: dict[str, str]`, or (b) add a `RemapSource`
model class.

**G-7: `chain_kind="loudnorm"` is too coarse.** `hapax-pc-loudnorm`,
`hapax-yt-loudnorm`, `hapax-music-loudnorm` all carry distinct chain
shapes (sc4m+sc4m+limiter vs single limiter vs single limiter w/ different
ceiling). Today the generator infers from minimal `limit_db` + `release_s`
typed params; that doesn't cover compound shapes (sc4m before limiter).
**Either expand to `chain_kind = ["loudnorm-simple",
"loudnorm-with-comp", "loudnorm-with-comp-and-reverb",
"voice-fx-biquad", "ducker-sidechain"]`** OR replace with a general
`filter_graph: list[FilterStage]` typed model.

**G-8: `LoopbackTopology` lacks `dont_reconnect`, `dont_move`, `linger`,
`state_restore`.** Today `hapax-private-playback` and
`hapax-notification-private-playback` carry these props (per
`hapax-private-monitor-bridge.conf` lines 54-58, 83-87). The spec's
LoopbackTopology has `source_dont_move`/`sink_dont_move` only. P1 must
add the four missing fields.

**G-9: `FormatSpec` model class is referenced in audit prompt but NOT
defined in spec §2.** The spec promises 4 new model classes (`AudioNode`,
`AudioLink`, `ChannelMap`, `FormatSpec`) and 7 total when including
`GainStage`/`LoopbackTopology`/`BroadcastInvariant`. Inventory check:
spec §2.1 defines 4 classes (`BroadcastInvariant`, `ChannelDownmix`,
`GainStage`, `LoopbackTopology`). `FormatSpec` is referenced in the audit
brief but does NOT appear in the spec body. `hapax-s4-loopback.conf`
declares `audio.format=S32`, `audio.rate=48000` — without `FormatSpec`,
this is in `params: dict[str, str|int|float|bool]` today. P1 must define
`FormatSpec(rate_hz: int, format: Literal["S16","S24","S32","F32"], channels: int)`.

**G-10: TTS-broadcast loopback fan-out (one capture, two destinations).**
`hapax-tts-duck.conf` defines a filter-chain whose output goes to BOTH
`alsa_output...analog-surround-40` (via filter playback) AND
`hapax-livestream-tap` (via separate parallel `module-loopback`
`hapax-tts-broadcast-capture/playback`). Today's schema represents this
as 2 separate edges from `tts-duck`. The spec doesn't have an explicit
"fan-out" or "tap" pattern beyond NodeKind.TAP. Verify P1 sees the
2-edge representation as adequate, OR add a `Fanout` model class.

**G-11: Drift between `config/pipewire/` (git) and
`~/.config/pipewire/pipewire.conf.d/` (deployed).** Spec §4.1 says daemon
owns deployed-conf manifest. **Spec is silent on whether `config/pipewire/`
remains operator-editable** (today: yes; postP4: ?). Recommendation: spec
must declare `config/pipewire/` as legacy-snapshot-or-retired post P4.

**G-12: WirePlumber non-loopback rules (priority pins, suspend timeouts,
volume defaults, codec ordering).** The 16 deployed wireplumber confs
include `monitor.alsa.rules`, `monitor.bluez.rules`,
`monitor.bluez.properties`, `wireplumber.settings.restore-stream.rules`,
`stream.rules`, `node.rules`, plus standalone settings blocks. Spec §3.1's
`wireplumber_confs: dict[str, str]` opaquely emits string content; that
doesn't TYPE the rule structure. P1 must define typed rule models OR
explicitly punt typing those (just emit strings) — but the punt should
be acknowledged as `wireplumber_confs` being un-validated.

**G-spec-1 / G-13: Role-based loopback infrastructure (50-hapax-voice-duck.conf).**
This conf alone defines 4 critical loopbacks (multimedia, notification,
assistant, broadcast) as `wireplumber.components`, with role-priority,
ducking levels (`linking.role-based.duck-level=0.3`), `default-media-role`
global, and per-role `policy.role-based.preferred-target` pins. **None of
these primitives have a typed shape in the current spec model.** This is
the second-largest semantic gap (after G-3). P1 must add `RoleLoopback`
or `MediaRoleSink` model class with `role`, `priority`, `duck_level`,
`preferred_target`, `intended_roles`, fields.

## Spec-revisions needed (must clarify before P1 locks schema)

**G-spec-2: Auto-mute vs no-auto-mute conflict between spec and the new
`hapax-audio-signal-assertion` daemon.** The spec's §4.2 EgressCircuitBreaker
auto-mutes within 2s on detection. The new
`agents/audio_signal_assertion/daemon.py` (deployed THIS branch) explicitly
forbids auto-mute: "False-positive auto-mute is explicitly forbidden by
the operator framing." These are different design philosophies arrived
at by different audit threads. **Both can't ship as-is.** Operator
decides. The spec was written 2026-05-03 13:36; the assertion daemon is
older but covers the same concern. Reconciliation options:

1. Ship the assertion daemon as the "P2 shadow-mode breaker" per spec
   §5 Phase 2 (observe-only, ntfy on transition) and add auto-mute as
   the P5 promotion. Keeps both designs alive.
2. Drop one. Operator picks which.
3. Assertion daemon stays at signal-flow stage classification (not
   egress band breaker); breaker is a separate concern at the OBS-bound
   monitor only. Two probes, two purposes.

P1 implementer cannot lock schema until this is resolved — the
`EgressCircuitBreaker` thresholds (CLIPPING_CREST_THRESHOLD=5.0 etc.)
and `auto-mute` action are spec-load-bearing.

**G-spec-3: pw-link mutations are not addressed.** `audio-leak-guard.sh`
calls `pw-link -d` to tear down forbidden runtime links. `usb-router.py`
calls both `pw-link` (create) and `pw-link -d`. `agents/local_music_player/player.py`
creates pw-links at runtime. Spec §4.1 says daemon is "Sole writer to
~/.config/{pipewire,wireplumber}/" and "Sole caller of pactl load-module"
— but doesn't address pw-link. P1 must clarify:
- Is pw-link a control-plane concern (allowed by external services)?
- Or is the daemon also the sole pw-linker?
- If sole pw-linker, the leak-guard's mutating role moves into the daemon.

**G-spec-4: P4 vs P5 phase boundary for restart-handling.** Spec §5 Phase
4 says "apply() runs probes" but Phase 5 is "circuit breaker hardening +
post-apply probes." Failure #7 (pipewire restart breaks links) is claimed
to be caught at "P4." The post-apply probes are introduced in P5. This
is a phase-attribution conflict — the schema field is fine, but operator
expectations get mis-set. P1 implementer should get a clean spec.

**G-spec-5: `hapax-audio-topology` vs `hapax-pipewire-graph` CLI naming.**
Spec §9 says "Stays as a CLI; subcommands `apply`/`lock`/`current` added
(replaces today's `switch`)." But spec §4 introduces a NEW daemon named
`hapax-pipewire-graph`. Are these the same CLI? Different binaries? Need
operator/spec author resolution.

## Scope-creep (acknowledged, explicitly punted)

**G-17: ALSA card pin / kernel codec state.** Spec §7 #9 explicitly calls
this out as "partial coverage at best" and §7 residual-failures #1 as
"the operator should be aware of." This is honest. But the descriptor
COULD model card profiles (it's not kernel state — it's a user-space
configurable). Recommendation: punt explicitly to a Phase 6 OR add a
minimal `CardProfilePin` (gap G-2's twin) at P1.

---

# §8. RECOMMENDATIONS — concrete schema additions / spec edits

## Priority 1 — must land before P1 schema lock

1. **Define `FormatSpec`** model class as audit brief promised:
   ```python
   class FormatSpec(BaseModel, frozen=True):
       rate_hz: Literal[16000, 44100, 48000] = 48000
       format: Literal["S16LE", "S24LE", "S32LE", "F32LE"] = "S32LE"
       channels: int = Field(..., ge=1, le=64)
   ```
   Attach to Node, LoopbackTopology, ChannelDownmix.

2. **Replace `ChannelDownmix.strategy` with a discriminated union:**
   - `channel-pick` (1:1 position pick — what spec has today)
   - `mixdown-equal` (sum N positions to one with equal gain)
   - `ladspa-mixdown` (per-source GainStage list + sum mixer routes — required for L-12 case)
   - `broadcast-fan-out` (1:N — for tap/livestream cases)

3. **Extend `LoopbackTopology`** with the four missing flags
   (`dont_reconnect`, `dont_move`, `linger`, `state_restore`).

4. **Resolve G-spec-2** auto-mute conflict before locking the
   `EgressCircuitBreaker` thresholds. Operator decision OR three-design
   reconciliation.

5. **Clarify G-spec-3 pw-link policy** (is daemon sole pw-linker, or
   does control plane retain it?).

## Priority 2 — schema-additive but not blocking P1

6. **`GlobalTunables`** (rate/quantum knobs) typed model.
7. **`AlsaProfilePin`** (card profile + use-acp + priority).
8. **`MediaRoleSink`** / `RoleLoopback` typed model for the role-based
   loopback infrastructure (`50-hapax-voice-duck.conf`).
9. **`AlsaCardRule`** + `BluezRule` typed models for the various
   `monitor.alsa.rules` patterns (suspend, priority, audio.rate).
10. **`StreamRestoreRule`** typed model (for `55-hapax-private-no-restore`).
11. **`StreamPin`** typed model (for `56-hapax-private-pin-s4-track-1`).
12. **`fail_closed: bool`** typed field on Node(TAP).
13. **`RemapSource`** model (or extend LoopbackTopology with `as_source`+`virtual_metadata`).
14. **Promote `chain_kind`** to a richer discriminated union OR generic
    `filter_graph: list[FilterStage]`.

## Priority 3 — spec text edits

15. Clarify **G-spec-4 P4/P5 phase split** for restart vs post-apply probe.
16. Resolve **G-spec-5 CLI naming** (`hapax-audio-topology` vs `hapax-pipewire-graph`).
17. State explicitly: **`config/pipewire/` becomes legacy snapshot
    post P4**; daemon owns `~/.config/pipewire/...` only.

## Priority 4 — operator-action-required (data population)

18. **Populate `declared_bleed_db` for L-12 AUX2/AUX3** (today's #6 is
    not actually preventable until this measurement step lands in the
    descriptor). Schema has the field; operator measurement is the
    blocker. P1 should ship a `hapax-audio-topology measure-bleed` CLI
    helper.

---

# §9. Confidence on the "9 of 11 prevented" claim

**This audit cannot endorse the 9-of-11 claim as stated.** Honest reread:

- **5 of 11 prevented at HIGH confidence** (#1, #3, #4, #8, #11) — all
  schema-already-aligned cases.
- **2 of 11 prevented at MEDIUM-HIGH confidence** (#7, #10) — both
  contingent on phase-attribution clarification.
- **2 of 11 prevented at MEDIUM confidence** (#5, #9) — both contingent
  on schema gaps (G-3, G-17) that P1 must close.
- **1 of 11 prevented CONDITIONAL on operator data** (#6) — schema OK,
  data absent.
- **1 of 11 prevented CONDITIONAL on cross-daemon reconciliation** (#2)
  — three probe surfaces today (60s producer, 30s assertion daemon,
  proposed breaker) need consolidation.

Mapping spec's "very high" to "high+", we get **5 high + 4 conditional/medium
+ 2 contingent**. The spec is correct that the architecture catches 9
failure classes; it overstates that all 9 are caught at high confidence
*today*. After the 17 gap-folds, 9-of-11 high-confidence is achievable.

---

# §10. One-line operator verdict

**The spec is aligned; needs 17 revisions before P1 implementation locks
the schema (12 schema-additive, 4 spec-revisions, 1 acknowledged-punt).**

The three highest-impact gaps:

1. **G-3 ChannelDownmix can't express L-12 14→2 mixdown** — the very
   failure that motivated the spec.
2. **G-spec-2 auto-mute philosophy conflict** — `audio-signal-assertion`
   daemon (just shipped this branch) explicitly forbids auto-mute; spec
   §4.2 mandates it. Operator decides.
3. **G-13 role-loopback infrastructure** (`50-hapax-voice-duck.conf` —
   the most architecturally load-bearing wireplumber conf) has zero
   typed shape in the spec model.

P1 implementation agent should treat §7 as a checklist and §8 as the
priority-ordered close-out.
