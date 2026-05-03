# Audio signal-flow assertion daemon — runbook

cc-task: H1 hardening from
`docs/research/2026-05-03-audio-config-hardening-unthought-of-solutions.md`.

Operator-readable recovery procedures for the failure modes the
signal-flow assertion daemon (`hapax-audio-signal-assertion.service`)
detects. The daemon probes the broadcast chain's monitor ports every
30s, classifies the captured PCM as
`silent | tone | music_voice | noise | clipping`, and ntfys the
operator on transition into a bad steady state at the OBS-bound stage.

The daemon is **READ-ONLY** with respect to the audio runtime: it does
not load PipeWire modules, does not restart services, does not modify
confs, does not auto-mute. It surfaces the failure; the operator (or
a separate hardening pass H2/H3) acts on it.

## Architecture at a glance

```
parecord --device=<sink>.monitor (raw s16le, 2s, 48 kHz, stereo)
  → numpy s16 → mono downmix → measure_pcm (RMS / peak / crest / ZCR)
  → classify (silent | tone | music_voice | noise | clipping)
  → TransitionDetector (hysteresis: 2s clipping/noise, 5s silence-on-air)
  → ntfy + textfile-collector gauges + /dev/shm/hapax-audio/signal-flow.json
```

## Stages probed by default

| Stage | Role | OBS-bound? |
|---|---|---|
| `hapax-broadcast-master` | safety-net limiter capture | no |
| `hapax-broadcast-normalized` | post-limiter source | no |
| `hapax-obs-broadcast-remap` | OBS's binding-stable handle | **yes** |

Discovery is automatic: `pactl list sinks short | grep -E '^[^\t]+\thapax-.*broadcast'`
finds additional broadcast-named sinks at startup. Override with
`HAPAX_AUDIO_SIGNAL_STAGES` (comma-separated) if the topology
diverges.

## ntfy decoder

ntfy fires only on a transition into a bad steady-state at
`hapax-obs-broadcast-remap` (the OBS-bound stage). Title shape:

```
Audio signal-flow: hapax-obs-broadcast-remap → <classification>
```

Body shape:

```
hapax-obs-broadcast-remap → <new_state> (was <prev_state>) sustained <Ns>s.
Upstream: hapax-broadcast-master=<class>, hapax-broadcast-normalized=<class>
Runbook: docs/runbooks/audio-signal-assertion.md#bad-classification-at-stage
```

The upstream-context line tells the operator *where the bad signal
entered* — `noise` upstream from a `clipping` event at OBS means the
filter chain or limiter took an already-corrupted input and clipped
it; `music_voice` upstream from `clipping` means the OBS-bound stage
itself introduced the failure (post-limiter remap most likely).

## Bad classification at stage

### Silent at OBS during livestream

**Symptoms:** RMS < -55 dBFS at `hapax-obs-broadcast-remap.monitor` for
≥ 5 seconds while the livestream is active.

**Detection one-liner:**
```
parecord --device=hapax-obs-broadcast-remap.monitor --raw \
    --rate=48000 --channels=2 --format=s16le \
    --latency-msec=2000 | head -c $((48000 * 2 * 2 * 2)) | \
    od -An -t d2 -N 32
```
A run of zeros confirms silence.

**1-command recovery (operator action; daemon does not auto-act):**
```
systemctl --user restart pipewire-pulse.service wireplumber.service
```
Reload the OBS broadcast-remap loopback module if pulse restart did
not restore signal:
```
~/.local/bin/hapax-obs-monitor-load
```

**Verification:**
```
~/.local/bin/uv run python -m agents.audio_signal_assertion --once --print
```
Look for `"classification": "music_voice"` (or `"tone"`) at the OBS
stage.

**Postmortem evidence-collection:**
```
cat /dev/shm/hapax-audio/signal-flow.json | jq '.stages, .recent_events'
journalctl --user -u hapax-audio-signal-assertion.service --since '5min ago'
```

### Clipping at OBS

**Symptoms:** Peak ≥ -1 dBFS, OR crest < 5 with RMS > -10 dBFS,
sustained ≥ 2 seconds. The +20 dB OBS clipping pathology from the
source research §0 lands here.

**Detection one-liner:**
```
~/.local/bin/uv run python -m agents.audio_signal_assertion --once --print | \
    jq '.stages[] | select(.stage == "hapax-obs-broadcast-remap")'
```

**1-command recovery (operator action):**
The clipping pathology is usually upstream gain misconfiguration.
Check `MASTER_INPUT_MAKEUP_DB` in `shared/audio_loudness.py` and the
`hapax-broadcast-master` filter-chain `master_makeup_gain` LADSPA
constant before assuming OBS-side. **If clipping is at OBS but the
upstream-context line shows `master=music_voice, normalized=music_voice`,
the obs-broadcast-remap loopback itself is at fault** — restart it via
`hapax-obs-monitor-load`.

**Verification:** Same as above; expect `"classification": "music_voice"`.

**Postmortem evidence-collection:** Same as silent. Additionally:
```
pactl list sinks | grep -A 30 hapax-obs-broadcast-remap
```

### Noise at OBS

**Symptoms:** Crest factor 2.5–5.0 with ZCR ≥ 0.25 sustained ≥ 2s.
This is the white-noise floating-point bleed pathology from the
source research §1 H1 — the broadcast-master crest factor jumping
from 5.7 (clean) to 3.7 (white noise) without service intervention.

**Detection:** Same `--once --print` output; classification will be
`"noise"`.

**1-command recovery (operator action):** Restart the entire PipeWire
stack — noise of this kind is invariably a stale buffer-state issue:
```
systemctl --user restart pipewire pipewire-pulse wireplumber
sleep 5
~/.local/bin/hapax-livestream-tap-load 2>/dev/null || true
~/.local/bin/hapax-obs-monitor-load
```

**Verification:** As above, expect `music_voice` post-restart.

## Tuning

Every threshold is env-tunable without redeploy. Drop overrides into
`~/.config/hapax/audio-signal-assertion.env`:

| Env var | Default | Tunes |
|---|---|---|
| `HAPAX_AUDIO_SIGNAL_PROBE_INTERVAL_S` | 30.0 | Cycle period. |
| `HAPAX_AUDIO_SIGNAL_PROBE_DURATION_S` | 2.0 | Capture window. |
| `HAPAX_AUDIO_SIGNAL_SILENCE_FLOOR_DBFS` | -55.0 | Silent classifier RMS floor. |
| `HAPAX_AUDIO_SIGNAL_CLIPPING_PEAK_DBFS` | -1.0 | Clipping classifier peak ceiling. |
| `HAPAX_AUDIO_SIGNAL_CLIPPING_RMS_DBFS` | -10.0 | Clipping classifier RMS floor. |
| `HAPAX_AUDIO_SIGNAL_TONE_CREST_MAX` | 2.0 | Tone classifier crest ceiling. |
| `HAPAX_AUDIO_SIGNAL_NOISE_CREST_MIN` | 2.5 | Noise classifier crest floor. |
| `HAPAX_AUDIO_SIGNAL_NOISE_CREST_MAX` | 5.0 | Noise classifier crest ceiling. |
| `HAPAX_AUDIO_SIGNAL_NOISE_ZCR_MIN` | 0.25 | Noise classifier ZCR floor. |
| `HAPAX_AUDIO_SIGNAL_MUSIC_CREST_MIN` | 5.0 | Music/voice classifier crest floor. |
| `HAPAX_AUDIO_SIGNAL_MUSIC_ZCR_MAX` | 0.15 | Music/voice classifier ZCR ceiling. |
| `HAPAX_AUDIO_SIGNAL_CLIPPING_SUSTAIN_S` | 2.0 | Clipping hysteresis window. |
| `HAPAX_AUDIO_SIGNAL_NOISE_SUSTAIN_S` | 2.0 | Noise hysteresis window. |
| `HAPAX_AUDIO_SIGNAL_SILENCE_SUSTAIN_S` | 5.0 | Silence-on-air hysteresis window. |
| `HAPAX_AUDIO_SIGNAL_RECOVERY_SUSTAIN_S` | 10.0 | Continuous good window before re-arm. |
| `HAPAX_AUDIO_SIGNAL_ENABLE_NTFY` | true | Disable to suppress notifications. |
| `HAPAX_AUDIO_SIGNAL_DISCOVER_STAGES` | true | Disable to use static stages only. |
| `HAPAX_AUDIO_SIGNAL_STAGES` | (unset) | Comma-separated override. |
| `HAPAX_AUDIO_SIGNAL_LIVESTREAM_FLAG_PATH` | `/dev/shm/hapax-broadcast/livestream-active` | Touch-file gating silence-on-air. |
| `HAPAX_AUDIO_SIGNAL_SNAPSHOT_PATH` | `/dev/shm/hapax-audio/signal-flow.json` | Snapshot output. |
| `HAPAX_AUDIO_SIGNAL_LOG_LEVEL` | INFO | Log level. |

After editing:
```
systemctl --user daemon-reload
systemctl --user restart hapax-audio-signal-assertion.service
```

## Prometheus query examples

Surface the per-stage classification in Grafana:

```promql
# Active classification at OBS stage (1.0 == active)
hapax_audio_signal_health{stage="hapax-obs-broadcast-remap"}

# Quick "are we good?" — should be 1 always while broadcasting:
sum by (stage) (
  hapax_audio_signal_health{classification="music_voice"}
)
```

Surface the raw measurements:

```promql
hapax_audio_signal_rms_dbfs{stage="hapax-obs-broadcast-remap"}
hapax_audio_signal_peak_dbfs{stage="hapax-obs-broadcast-remap"}
hapax_audio_signal_crest_factor{stage="hapax-broadcast-master"}
```

Alert (Prometheus `alert.yml`):

```yaml
- alert: HapaxAudioSignalCorrupted
  expr: |
    (hapax_audio_signal_health{
      stage="hapax-obs-broadcast-remap",
      classification=~"clipping|noise"
    } == 1) and on() (hapax_audio_signal_livestream_active == 1)
  for: 30s
  annotations:
    runbook: "docs/runbooks/audio-signal-assertion.md#bad-classification-at-stage"
```

## Stage discovery details

`pactl list sinks short` is parsed for sink names that start with
`hapax-` and contain `broadcast`. The default 3 stages
(`hapax-broadcast-master`, `hapax-broadcast-normalized`,
`hapax-obs-broadcast-remap`) are always probed, even if pactl
discovery returns no matches — the daemon ships a static fallback.

## Constraints honoured

* **Read-only.** No PipeWire module loads, no service restarts, no
  conf modifications, no auto-mute.
* **No false-positive auto-mute.** `silent` only fires during
  livestream; clipping and noise only fire after the 2s sustain.
* **Brief restart blips do not page.** Sub-sustain transients are
  absorbed by the hysteresis state machine.
* **Low overhead.** 30s cycle, 2s capture per stage, < 1 % CPU
  sustained on the workstation.

## Cross-references

* H1 source spec: `docs/research/2026-05-03-audio-config-hardening-unthought-of-solutions.md` §1 H1.
* Existing audio LUFS health surface (compatible, complementary):
  `agents/broadcast_audio_health_producer/__main__.py`.
* Topology assertion (graph-shape, not signal-flow):
  `scripts/hapax-audio-topology-assertion-runner`.
* Filter chain monitor-port semantics:
  `docs/research/2026-05-03-pipewire-filter-chain-monitor-semantics.md`.
* Audio incidents runbook (broader recovery surface):
  `docs/runbooks/audio-incidents.md`.
