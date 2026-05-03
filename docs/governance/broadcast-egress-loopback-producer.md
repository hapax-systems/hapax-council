# Broadcast egress loopback witness producer

## Why

PR [#2209](https://github.com/ryanklee/hapax-council/pull/2209) added a 7th
evaluator to `BroadcastAudioHealth` that probes whether the broadcast egress
is *actually carrying audio*, not just whether configuration is correct.
That evaluator reads a witness file at
`/dev/shm/hapax-broadcast/egress-loopback.json` and validates it against:

- freshness (`loopback_max_age_s = 60.0`s)
- silence ratio (`silence_ratio_max = 0.85`)
- RMS level floor (`rms_dbfs_floor = -55.0` dBFS, warning only)

Without something writing the witness file, the evaluator stays in the
`witness missing → blocking → unknown` state forever and
`broadcast_audio_health.safe` never goes `true`. The evaluator's PR body
explicitly noted "PRODUCER side is the natural follow-up" — that's this
daemon.

## What it does

`agents/broadcast_egress_loopback_producer/` is a long-running Python
daemon that:

1. Captures 5 seconds of int16 mono PCM via `parec` from
   `hapax-broadcast-normalized` (the OBS-bound broadcast egress source per
   `config/pipewire/hapax-broadcast-master.conf`).
2. Computes RMS dBFS, peak dBFS, and silence_ratio (fraction of samples
   below the -60 dBFS floor) using only Python stdlib (`array.array` +
   `math.sqrt` + `math.log10` — no numpy / librosa / pyaudio).
3. Constructs an `EgressLoopbackWitness` Pydantic model and writes it
   atomically (tmp file in same directory + rename) to
   `/dev/shm/hapax-broadcast/egress-loopback.json`.
4. Sleeps for the residual to the next 1s tick boundary and repeats.

On capture failure (parec missing, sink missing, short read) the producer
still writes a witness — but with the `error` field set to a structured
token like `parec_failed:exit_2` or `parec_missing:...`. The evaluator
short-circuits on `error` first, so the operator sees a real cause rather
than a misleading silence/staleness cascade.

## Install

The systemd unit `hapax-broadcast-egress-loopback-producer.service` is
deployed by the post-merge deploy chain after this PR merges. Operator
verification:

```bash
systemctl --user enable --now hapax-broadcast-egress-loopback-producer
systemctl --user status hapax-broadcast-egress-loopback-producer
```

Resource limits: `MemoryHigh=128M`, `MemoryMax=256M`. CUDA isolated
(`CUDA_VISIBLE_DEVICES=`) — the producer never touches GPU.

## Verify

```bash
# Witness file should exist and update at least every second.
cat /dev/shm/hapax-broadcast/egress-loopback.json | jq

# Should show recent timestamp + RMS/peak/silence_ratio.
# Re-run after 2 seconds — checked_at must advance.

# Daemon should report no errors.
journalctl --user -u hapax-broadcast-egress-loopback-producer | tail -20
```

After the daemon is running, the broadcast audio health evaluator should
publish:

```bash
cat /dev/shm/hapax-broadcast/audio-safe-for-broadcast.json | \
  jq '.audio_safe_for_broadcast.evidence.egress_loopback'
```

`status: "live"` means the producer is healthy AND the broadcast egress
is actually carrying audio.

## Configuration

All optional, all via environment variables (drop into a systemd unit
override file or `~/.config/hapax/broadcast-egress-loopback.env`):

| Var | Default | Purpose |
|-----|---------|---------|
| `HAPAX_LOOPBACK_SOURCE` | `hapax-broadcast-normalized` | PipeWire source name to probe |
| `HAPAX_LOOPBACK_WINDOW_S` | `5.0` | Capture window length in seconds |
| `HAPAX_LOOPBACK_TICK_S` | `1.0` | Tick cadence — must be < `loopback_max_age_s` |
| `HAPAX_LOOPBACK_WITNESS_PATH` | `/dev/shm/hapax-broadcast/egress-loopback.json` | Output path |

The default source `hapax-broadcast-normalized` is the canonical OBS
binding per `config/pipewire/hapax-broadcast-master.conf`:
"OBS audio source MUST bind to `hapax-broadcast-normalized`". Probing the
same source the broadcast actually consumes is the only way to witness
that egress is live — probing further upstream would miss
limiter/chain breakage.

## Cross-references

- Evaluator: PR [#2209](https://github.com/ryanklee/hapax-council/pull/2209)
- cc-task: `broadcast-audio-health-producer-loopback-monitor` (WSJF 7.2)
- Spec: `hapax-research/specs/2026-04-29-audio-reference-world-surface.md`
- Pydantic model: `shared/broadcast_audio_health.py::EgressLoopbackWitness`
- Threshold defaults: `BroadcastAudioHealthThresholds.{loopback_max_age_s, silence_ratio_max, rms_dbfs_floor}`
