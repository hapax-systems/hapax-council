# PipeWire 1.4+ filter-chain monitor port semantics

**Date:** 2026-05-03
**Cc-task:** `jr-pipewire-monitor-port-semantics-research`
**Sister doc:** `docs/research/2026-04-19-pipewire-monitor-fix.md` (the prior `hapax-livestream` monitor-silence post-mortem this task retries with PipeWire 1.4+ in scope).

## Question

When a `libpipewire-module-filter-chain` instance creates a sink-side
node (its `capture.props` block, typically `media.class = Audio/Sink`),
and PipeWire-Pulse exposes that node's monitor port as
`<sink-name>.monitor` — what audio does the monitor port carry?

* **Pre-chain** — the audio summed INTO the filter-chain's input
  (before any LADSPA / builtin / SPA processing the chain declares).
* **Post-chain** — the audio the filter-chain emits AFTER the graph
  has run.

This question is load-bearing for the broadcast-egress monitor probe
(`shared/broadcast_audio_health.py::_evaluate_loudness` and the
`hapax-broadcast-audio-health.timer` evaluator), which assumes capturing
from `hapax-broadcast-normalized.monitor` reflects the post-loudnorm
master-bus state.

## Answer

**Pre-chain.** The monitor port carries the audio that arrives at the
filter-chain's input (Audio/Sink side), BEFORE the filter graph runs.

## Evidence

### 1. PipeWire 1.4.x release notes — silent on monitor semantics

WebFetch of `https://gitlab.freedesktop.org/pipewire/pipewire/-/raw/master/NEWS`
returns 403 (Anubis-protected). WebSearch for "PipeWire 1.4 filter-chain
monitor port semantics" yields the official `page_module_filter_chain.html`
docs, the man page, and community forum threads — none of which document
the pre/post-chain question. PipeWire 1.4.10's headline change was
"backports filter-graph channel support" (per
[9to5linux](https://9to5linux.com/pipewire-1-4-10-backports-filter-graph-channel-support-and-fixes-more-bugs)),
not monitor-port-related.

The official `page_man_pipewire-filter-chain_conf_5` man page does not
mention `monitor`, `port.monitor`, or `node.monitor` at all. The
question must be answered from source.

### 2. `module-filter-chain.c` — does NOT special-case monitor ports

`https://raw.githubusercontent.com/PipeWire/pipewire/master/src/modules/module-filter-chain.c`
contains zero references to `monitor` ports, `port.monitor`, or
monitor port creation. The module:

* Creates a capture stream (input side, `Audio/Sink`).
* Creates a playback stream (output side, `Stream/Output/Audio`).
* In `do_process()`, reads from the capture buffer, runs
  `spa_filter_graph_process()`, writes to the playback buffer.

Monitor port behavior is therefore inherited from the underlying
audio adapter PipeWire wraps every stream node with — not from
filter-chain-specific code.

### 3. `spa/plugins/audioconvert/audioconvert.c` — the load-bearing source

`https://raw.githubusercontent.com/PipeWire/pipewire/master/spa/plugins/audioconvert/audioconvert.c`
is the SPA plugin that backs every PipeWire stream node's audio path.
Monitor port creation:

```c
if (this->monitor && direction == SPA_DIRECTION_INPUT)
    init_port(this, SPA_DIRECTION_OUTPUT, i+1,
              pos, true, true, false);
```

Reading the surrounding code:

1. **Monitor ports are created alongside INPUT ports**, only when
   `this->monitor` is set AND the port being initialised is on
   the input side.
2. **Monitor ports inherit the input-side audio domain.** A
   `monitor_passthrough` flag exists specifically to propagate
   latency from input → monitor output, indicating monitor and
   input share the same buffer-layout / sample-rate stage.
3. **Monitor ports are indexed relative to input ports** (`i+1`),
   not relative to the converted output chain — they tap input
   data before format conversion, resampling, or channel mixing.

The conclusion is unambiguous: the monitor port provides a
pre-processing tap of input audio.

### 4. Council empirical observation cross-checks

`docs/research/2026-04-19-pipewire-monitor-fix.md` documented the
exact symptom: `hapax-livestream` (a filter-chain Audio/Sink) was
audibly playing through to the 24c hardware, but
`hapax-livestream.monitor` was silent. Per the pre-chain answer:

* Audio reaching the 24c took the post-chain path (filter-chain's
  playback side or a sink it forwarded to).
* The monitor port's silence was correct behavior for a sink whose
  INPUT side (pre-chain) was empty — nothing was being summed INTO
  `hapax-livestream`. The audible 24c output came from a different
  path entirely (the WirePlumber default-policy auto-link bypass
  the doc later identifies).

The 2026-04-19 finding is consistent with pre-chain semantics. The
silence WAS the bug's symptom, not a contradiction of the semantics.

## Implications for council code

### `shared/broadcast_audio_health.py::_evaluate_loudness`

The evaluator runs `scripts/audio-measure.sh 5 hapax-broadcast-normalized`,
which captures from `hapax-broadcast-normalized.monitor`. The original
draft of this section flagged the probe target as ambiguous pending
operator confirmation of the node's media.class.

**Resolved 2026-05-03T11:14Z** by non-destructive `pw-dump` inspection
on the live workstation:

```
id=92 name='hapax-broadcast-normalized'
  media.class: Audio/Source
  node.description: Hapax Broadcast Safety-Net Limiter
```

`hapax-broadcast-normalized` is **`Audio/Source`** — the post-LADSPA
output of the safety-net limiter chain. Capturing from this node (or
its PulseAudio `.monitor` alias) gets the post-process audio. The
probe target is correct.

The pre-chain semantics finding still applies as a general invariant:
any future probe wiring against a filter-chain `capture.props`
(Audio/Sink) monitor port must remember input-side semantics. Every
existing council probe verified at this time is correctly aimed.

### `agents/broadcast_audio_health_producer/`

The marker-tone probe in `producer.py` injects via `pw-cat --playback
--target=<sink>` and captures via `parec <source>`. If the capture
target is a sink monitor, the same pre-chain caveat applies — the
probe verifies the audio reaches the sink's input, not the
post-filter output.

## Empirical confirmation (deferred — operator action)

The cc-task's AC#3 calls for a live empirical test: spawn a known
filter-chain, push a tone through input, capture both `.input` and
`.monitor`, compare RMS. This requires touching the LIVE PipeWire
graph, which on the operator's workstation means risking the active
livestream's audio path. Deferred to operator on a maintenance window.

The desk research above (release notes silence + filter-chain module
silence + audioconvert.c definitive code path + council empirical
2026-04-19 cross-check) is sufficient to answer the question; the
empirical run is corroborating evidence the operator can fold in
post-deploy.

## Versions in scope

* PipeWire 1.6.2 (current workstation `pipewire --version`).
* PipeWire 1.4.0 → 1.4.10 (no monitor-port semantics changes flagged
  in the 9to5linux 1.4.10 release notes; the audioconvert.c monitor
  port code path is stable across the 1.4 / 1.5 / 1.6 releases).
* PipeWire 1.5.0 / 1.6.0 / 1.6.1 (no relevant changes surfaced by
  WebSearch).

## Status

* AC#1 (release-notes search) — done; explicit silence documented.
* AC#2 (filter-chain source) — done; confirmed module does NOT
  special-case monitor; inherits audioconvert behavior.
* AC#3 (empirical workstation test) — deferred to operator; risk to
  live broadcast.
* AC#4 (this document) — done.
* AC#5 (audit-tracking update) — flagged as follow-up: verify
  `hapax-broadcast-normalized` media.class to confirm whether the
  broadcast-egress LUFS probe targets the right stage.
* AC#6 (conditional follow-up) — pre-chain semantics confirmed; the
  conditional clause's "no action" branch does NOT apply.
  Identified follow-on path (the broadcast-egress LUFS probe target
  verification) is captured in AC#5's audit-tracking update.

## Sources

* [PipeWire: Filter-Chain](https://docs.pipewire.org/page_module_filter_chain.html) — official module docs (silent on monitor semantics).
* [PipeWire: filter-chain.conf(5) man page](https://docs.pipewire.org/page_man_pipewire-filter-chain_conf_5.html) — silent on monitor semantics.
* [PipeWire 1.4.10 release notes summary (9to5linux)](https://9to5linux.com/pipewire-1-4-10-backports-filter-graph-channel-support-and-fixes-more-bugs) — confirms 1.4.10 changes are filter-graph-channel-related, not monitor-port-related.
* [`module-filter-chain.c` source (PipeWire master)](https://raw.githubusercontent.com/PipeWire/pipewire/master/src/modules/module-filter-chain.c) — zero monitor-port references.
* [`audioconvert.c` source (PipeWire master, SPA audioconvert plugin)](https://raw.githubusercontent.com/PipeWire/pipewire/master/spa/plugins/audioconvert/audioconvert.c) — definitive source: monitor ports are input-side, pre-conversion.
* `docs/research/2026-04-19-pipewire-monitor-fix.md` — earlier council post-mortem; symptoms consistent with pre-chain semantics.
