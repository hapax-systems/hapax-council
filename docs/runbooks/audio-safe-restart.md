# Audio Safe Restart Runbook

cc-task: hardening **H2** from
`docs/research/2026-05-03-audio-config-hardening-unthought-of-solutions.md`.

Operator runbook for the pre-flight gate + atomic rollback wrapper that
sits in front of `systemctl --user restart` for every audio-touching
service. The wrapper is `scripts/hapax-audio-safe-restart`; this
document is the recovery surface when the wrapper itself reports a
failure mode.

## Why this exists

> "Restart is unsafe by default. Each PipeWire restart re-enumerates
> USB, re-evaluates conf-loaded modules, re-links auto-routed streams,
> and one out of N restarts comes back with a different topology or a
> contaminated chain (white noise, channel mis-routing, suspended
> sink, missing loopback)."
>
> — research doc, §H2

The two operator-defined unacceptable steady states at OBS are:

1. **+20 dB clipping noise** pumped into the livestream
2. **Absolute silence** at OBS

Brief 1-10 s gaps during the legitimate restart window are FINE. The
wrapper enforces a 12 s settling window before its post-probe so
transients aren't mistaken for steady-state-bad.

## What it does

1. **Pre-flight snapshot** (`scripts/hapax-audio-snapshot --phase pre`) — captures `pactl` sinks/sources/modules, `pw-link -l` topology, and a 1 s loudness baseline at all 4 broadcast stages, into `/tmp/hapax-audio-snapshot-<service>-<ts>.pre.json`.
2. **Pre-flight verify** (`scripts/hapax-audio-verify-broadcast-clean`) — same probe shape as the post-flight verify, written to `*-pre.json` for diff reference.
3. **Restart** — `systemctl --user restart` (or `systemctl --user reload` with `--reload`).
4. **Settle** — sleeps 12 s by default (`--settle N` overrides; range 1–60).
5. **Post-flight snapshot + verify** — re-captures topology + signal flow.
6. **Decide** — if the post probe says any broadcast stage went silent (RMS < -75 dBFS) or noise/clipping (crest in [2.5, 5.0] or RMS > -1 dBFS), trigger rollback.
7. **Atomic rollback** — restart-the-restart once; if still bad, replay missing `module-loopback` loads from the pre-snapshot via `pactl load-module`, re-establish links via `pw-link`. Final verify; ntfy operator either way.

## Exit codes

| Code | Meaning |
|------|---------|
| `0`  | Restart clean (post-probe matches expected; or dry-run OK) |
| `1`  | Post-probe degraded; rollback **succeeded** |
| `2`  | Post-probe degraded; rollback **failed** (operator paged via ntfy) |
| `3`  | Post-probe topology-drift; rollback attempted |
| `4`  | Invocation error / probe infrastructure missing |
| `5`  | `systemctl restart` itself returned non-zero |

The verifier (`scripts/hapax-audio-verify-broadcast-clean`) has a
parallel exit-code surface:

| Code | Meaning |
|------|---------|
| `0`  | clean — all probed stages produce real audio (or are intentionally silent) |
| `1`  | silent — at least one broadcast stage was steady-state silent |
| `2`  | noise/clipping — at least one stage degraded into noise or clipping |
| `3`  | topology drift — a snapshot-listed monitor disappeared |
| `4`  | probe failure — measurement infrastructure unavailable |

## Usage

### Manual restart of an audio-touching service

```bash
hapax-audio-safe-restart hapax-music-player.service
hapax-audio-safe-restart hapax-content-resolver.service
hapax-audio-safe-restart --reload hapax-audio-router.service
hapax-audio-safe-restart --settle 20 hapax-broadcast-orchestrator.service
```

### Service list

The six audio-touching services that should always go through the
wrapper:

- `hapax-broadcast-orchestrator.service`
- `hapax-music-player.service`
- `hapax-content-resolver.service`
- `hapax-audio-router.service`
- `hapax-audio-ducker.service`
- `hapax-daimonion.service`

### Dry-run

```bash
hapax-audio-safe-restart --dry-run hapax-music-player.service
```

Snapshots + verifies but does NOT actually restart or roll back. Useful
when validating the wrapper itself or rehearsing a restart.

### Disabling rollback

```bash
hapax-audio-safe-restart --no-rollback hapax-music-player.service
```

Verifies post-probe but never replays loopbacks or re-links. Use only
when manually debugging — the wrapper will still ntfy on degradation.

### Snapshot-only

```bash
hapax-audio-snapshot --service ad-hoc --phase pre --output /tmp/snap.json
```

For postmortem capture before manually performing a destructive
operation (e.g. wiping `~/.config/pipewire/pipewire.conf.d/`).

## Anchors for ntfy alerts

The wrapper's ntfy alerts cite these anchors:

### `recovered-on-retry`

The first restart degraded broadcast; a single retry restored clean
state. **No operator action required.** Snapshots are kept in
`/tmp/hapax-audio-snapshot-<service>-<ts>.{pre,post}.json` for forensic
reference.

### `recovered-on-rollback`

Restart degraded broadcast; retry didn't help; the wrapper replayed
missing module-loopback rows + re-linked nodes from the pre-snapshot,
and the chain came back clean. Operator should review the replay log
at `/tmp/hapax-audio-rollback-<service>-<ts>.log` to understand which
loopbacks didn't survive the restart — that's the signal H3 needs
(conf→pactl migration, per the research doc).

### `rollback-failed`

The terminal failure mode. The wrapper could not restore the chain.
Recovery procedure:

1. Capture the live state immediately:
   ```bash
   pactl list short modules > /tmp/post-failure-modules-$(date -Iseconds).txt
   pw-link -l > /tmp/post-failure-pwlinks-$(date -Iseconds).txt
   ```
2. Cross-reference with `/tmp/hapax-audio-snapshot-<service>-<ts>.pre.json` — what's missing?
3. If broadcast is silent (`classification=silent`): see `audio-incidents.md#broadcast-low`.
4. If broadcast is noise/clipping (`classification=noise-or-clipping`): see `audio-incidents.md#broadcast-white-noise`.
5. If topology drift (`classification=topology-drift`): a sink or source node disappeared. Run `pactl list sinks short` / `pactl list sources short` and confirm the snapshot's expected nodes are present. If a USB device dropped, see `audio-incidents.md#xhci-l12-channel-drop`.
6. Last resort:
   ```bash
   systemctl --user restart pipewire pipewire-pulse wireplumber
   sleep 5
   hapax-audio-safe-restart <original-service>
   ```

## Tuning

The classifier thresholds inside
`scripts/hapax-audio-verify-broadcast-clean` are intentionally
conservative:

```
SILENT_FLOOR_DBFS=-75.0
CLIP_CEILING_DBFS=-1.0
NOISE_BAND_LOW=2.5
NOISE_BAND_HIGH=5.0
```

The noise band [2.5, 5.0] catches PipeWire format-conversion white
noise (crest 3.5–4.5) and similar artefacts; real broadcast (music +
voice + room ambience) sits at crest 5.5+ at the master, 8+ post-limiter.
These thresholds are duplicated in the H1 signal-flow daemon — when H1
ships, this script should reuse H1's classifier rather than maintaining
a parallel implementation.

## Integration with `rebuild-services.timer`

Not yet wired. The intended integration is a `--audio-safe` flag on
`scripts/rebuild-service.sh`: when set, the rebuild script calls
`hapax-audio-safe-restart` instead of `systemctl --user restart`. The
flag is currently a no-op in the wrapper (so callers can pass it
unconditionally during the migration window). See follow-up cc-task
`audio-safe-restart-rebuild-services-integration` for the rebuild-side
plumbing.

## Failure modes the wrapper does NOT catch

By design:

- **Audio drift in OBS itself** (sample-rate negotiation, OBS audio
  monitor mute). The wrapper probes the PipeWire side; OBS-side
  failures need OBS-side instrumentation.
- **Latency / xrun bursts.** H2.B (`pw-top -b` continuous metric
  ingest, research doc §2.B) covers this.
- **Per-app target.object pin drift.** H2.C (WirePlumber stream-
  restore policies, research doc §2.C) covers this.
- **L-12 hardware-side faults** (USB renegotiation, channel collapse).
  The Ryzen pin-glitch detector (`hapax-audio-topology pin-check
  --auto-fix`) covers this.

## References

- Research source: `docs/research/2026-05-03-audio-config-hardening-unthought-of-solutions.md` §H2
- Cross-reference: `docs/runbooks/audio-incidents.md` (the 7-anchor recovery surface)
- Cross-reference: `docs/runbooks/audio-topology.md` (canonical operator audio map)
- iLoud loader template: `~/.local/bin/hapax-obs-monitor-load`
- Audit history: `docs/audit-tracking/24h-audio-audit-2026-05-02.md`
