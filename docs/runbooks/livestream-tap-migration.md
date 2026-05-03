---
title: hapax-livestream-tap conf-file → systemd pactl-load migration (H3 phase 1)
date: 2026-05-03
audience: operator + alpha + beta
status: shipped (DRAFT — empirical drift observed, see § Empirical baseline)
related:
  - docs/research/2026-05-03-audio-config-hardening-unthought-of-solutions.md
  - docs/runbooks/audio-incidents.md
  - docs/runbooks/audio-topology.md
  - config/pipewire/hapax-livestream-tap.conf
  - config/pipewire/hapax-livestream-tap.conf.replaced-by-systemd-2026-05-03
  - scripts/hapax-livestream-tap-load
  - systemd/units/hapax-livestream-tap-loopback.service
---

# `hapax-livestream-tap` conf-file → systemd pactl-load migration

## What changed

The `module-loopback` that forwards `hapax-livestream-tap` (null-sink) output to
`hapax-livestream` (filter-chain) has been moved out of
`~/.config/pipewire/pipewire.conf.d/hapax-livestream-tap.conf` into a systemd
one-shot pactl-load. The null-audio-sink declaration stays in the conf — only
the loopback migrated.

**Files involved:**

| Path | Role |
|------|------|
| `config/pipewire/hapax-livestream-tap.conf` | null-audio-sink only (post-migration) |
| `config/pipewire/hapax-livestream-tap.conf.replaced-by-systemd-2026-05-03` | full pre-migration conf, archived for reference / rollback |
| `scripts/hapax-livestream-tap-load` | loader script (deployed via `~/.local/bin/`) |
| `systemd/units/hapax-livestream-tap-loopback.service` | systemd one-shot |

## Why

Per `docs/research/2026-05-03-audio-config-hardening-unthought-of-solutions.md`
§6 ("One immediate-ship recommendation") — the H3 hardening phase 1.

Three of six audio incidents on 2026-05-03 involved `hapax-livestream-tap`
directly or transitively. PipeWire upstream issue #2791 confirms a
load-bearing fact about PipeWire startup ordering vs WirePlumber: conf-loaded
`module-loopback` instances can link capture+playback ports correctly but
silently fail to flow signal. `pactl load-module` from a systemd one-shot
ordered `After=pipewire.service pipewire-pulse.service wireplumber.service`
runs after the session manager is fully up, with a clean state to negotiate
against, and avoids the failure mode entirely.

The iLoud loader (`~/.local/bin/hapax-obs-monitor-load` /
`hapax-obs-monitor-loopback.service`) has been the only stable loopback this
week and is the empirical template for this migration.

## Empirical baseline (2026-05-03 13:30Z – 13:46Z)

The migration was applied LIVE on the operator's system to capture pre/post
RMS + crest measurements at all 4 broadcast stages. Results show the migration
introduces a measurable signal drift that exceeds the operator's ±2 dB tolerance:

### BEFORE (conf-loaded, post-restart, quiet state)

| Stage | rms_dbfs | crest | classification |
|---|---|---|---|
| hapax-livestream-tap.monitor | -79.74 | 3.85 | silent |
| hapax-broadcast-master | -79.35 | 3.68 | silent |
| hapax-broadcast-normalized | -66.10 | 3.51 | noise |
| hapax-obs-broadcast-remap | -65.65 | 3.74 | noise |

### AFTER (pactl-loaded, post-restart, quiet state)

| Stage | rms_dbfs | crest | classification | Δ vs BEFORE |
|---|---|---|---|---|
| hapax-livestream-tap.monitor | -75.74 | 5.23 | silent | +4.0 dB |
| hapax-broadcast-master | -70.24 | 10.82 | **audio** | **+9.1 dB & flip silent→audio** |
| hapax-broadcast-normalized | -61.60 | 4.66 | noise | +4.5 dB |
| hapax-obs-broadcast-remap | -61.36 | 5.00 | noise | +4.3 dB |

### Interpretation

The migration introduces a +4 to +9 dB gain across the chain AND a
classification flip at `hapax-broadcast-master` (silent → audio). This
exceeds the ±2 dB rollback threshold and triggered automatic rollback.

**Hypothesis** for the drift (deferred for follow-up):

* Conf-loaded loopback uses `stream.capture.sink=true target.object=hapax-livestream-tap`,
  a PipeWire-native shorthand that subscribes the loopback's capture side to
  the sink-input mix BEFORE the monitor port adapter.
* Pactl-loaded loopback uses `source=hapax-livestream-tap.monitor`, the
  PulseAudio-API view, which flows through the auto-port-config monitor
  adapter (`mode=dsp position=preserve`).
* These two paths produce nominally equivalent signals but with different
  gain semantics — likely the monitor-port path applies a +4-9 dB makeup
  (or skips a passive-link attenuation) that the in-line `stream.capture.sink`
  mode does not.

**Status**: PR shipped with the empirical drift documented; **NOT
auto-merged**. Rollback executed live; runtime restored to conf-loaded
behavior. Follow-up work (§ Follow-up) needed before this can ship enabled.

## Scope of H3 phase 1

This PR migrates ONLY `hapax-livestream-tap`. Subsequent phases of H3 will
migrate the other module-loopback confs in
`~/.config/pipewire/pipewire.conf.d/hapax-*.conf` per the table in research
§1.H3.C1:

| Conf shape | Reliable as conf? | Migrate? |
|---|---|---|
| `module-loopback` (pure forwarding, no filter) | NO (issue #2791 + 3 council incidents) | YES |
| `module-filter-chain` (LADSPA / builtin DSP) | YES | NO |
| `module-null-audio-sink` (virtual sink) | YES | NO |
| WirePlumber rules / device profiles | YES | NO |

## Deployment

`scripts/hapax-post-merge-deploy` matches `systemd/units/*.service` and
`config/pipewire/*.conf` and handles deployment automatically on merge:

1. `cp config/pipewire/hapax-livestream-tap.conf ~/.config/pipewire/pipewire.conf.d/`
   (the post-migration null-sink-only conf overwrites the prior conf-with-loopback)
2. `cp systemd/units/hapax-livestream-tap-loopback.service ~/.config/systemd/user/`
3. `systemctl --user daemon-reload`
4. `systemctl --user restart pipewire pipewire-pulse wireplumber`
   (the post-merge-deploy script handles this automatically when `config/pipewire/`
   files change)
5. `systemctl --user enable --now hapax-livestream-tap-loopback.service`

The script `scripts/hapax-livestream-tap-load` itself is symlinked into
`~/.local/bin/` by `hapax-post-merge-deploy` per the `scripts/hapax-*` rule.

## Verification

After deployment, confirm signal flow at all 4 broadcast stages with
`scripts/audio-measure.sh`:

```bash
# Each stage should show LUFS-I within ±2 dB of pre-migration baseline,
# same classification (audio / silent / noise).
audio-measure.sh 30 hapax-livestream-tap
audio-measure.sh 30 hapax-broadcast-master
audio-measure.sh 30 hapax-broadcast-normalized
audio-measure.sh 30 hapax-obs-broadcast-remap
```

And confirm the loopback module is loaded by pactl, not by conf:

```bash
pactl list modules | grep -B1 -A4 'hapax-livestream-tap.monitor.*hapax-livestream'
# Expect a `Module #N` block with Argument referencing source=hapax-livestream-tap.monitor
# sink=hapax-livestream, and source_dont_move=true sink_dont_move=true.
```

The loopback should NOT be created by the conf file:

```bash
grep -c module-loopback ~/.config/pipewire/pipewire.conf.d/hapax-livestream-tap.conf
# Expect: 0
```

## Rollback

If the migration regresses (LUFS-I drift > ±2 dB at any broadcast stage, or
classification flip silent↔audio↔noise):

1. Disable + stop the systemd unit:
   ```bash
   systemctl --user disable --now hapax-livestream-tap-loopback.service
   pactl unload-module $(pactl list modules | awk '/^Module #/{idx=substr($2,2)} /^\tName: module-loopback/{is_lb=1; next} /^\tName:/{is_lb=0} is_lb && /hapax-livestream-tap/ && /hapax-livestream/ {print idx; is_lb=0}')
   ```
2. Restore the pre-migration conf:
   ```bash
   cp config/pipewire/hapax-livestream-tap.conf.replaced-by-systemd-2026-05-03 \
      ~/.config/pipewire/pipewire.conf.d/hapax-livestream-tap.conf
   systemctl --user restart pipewire pipewire-pulse
   ```
3. Verify the loopback re-loaded from the conf:
   ```bash
   pactl list modules | grep -B1 -A4 'hapax-livestream-tap.*hapax-livestream'
   ```

The pre-migration conf is preserved in the repo so this rollback is a single
copy.

## Failure modes the loader handles explicitly

* **Source or target sink not present at unit startup.** The loader waits
  up to 60s for both `hapax-livestream-tap` and `hapax-livestream` sinks to
  exist. If they don't, it tears down any orphan loopback and exits 0
  (success) so systemd doesn't loop on Restart=on-failure. The unit can be
  manually restarted after the operator fixes the underlying conf-load
  issue.
* **Idempotency.** Re-running the loader detects an existing loopback with
  matching source+target and exits 0 without reloading. Safe to invoke
  repeatedly.
* **`automove` re-routing.** `source_dont_move=true sink_dont_move=true`
  prevents PulseAudio's automove from silently re-targeting the loopback
  if either sink drops out at runtime. The loopback fails loudly (no
  signal) rather than re-routing silently.
* **Post-load verification.** After `pactl load-module`, the loader reads
  back the module's `Argument:` and confirms both sink names are present.
  If not, it unloads immediately and exits 1.

## Audio leak guard

The existing `scripts/audio-leak-guard.sh` continues to pin
`hapax-livestream-tap` as a forbidden private target — the migration does
not change the leak guard's invariants. The guard regex matches the sink
name regardless of how the loopback module is loaded.

## Follow-up

Before this migration can be enabled in production, the +4 to +9 dB drift
must be reconciled:

1. **Match capture-side semantics.** Determine whether `stream.capture.sink=true`
   can be passed via `source_output_properties=stream.capture.sink=true` in the
   pactl invocation, or whether a different load shape (e.g. the `pw-loopback`
   CLI or a module-loopback variant with explicit `capture.props` JSON) gives
   byte-identical behavior to the conf form.
2. **Calibrate the gain.** If the path semantics are inherently different,
   apply a -4 to -9 dB makeup at the loopback's output side so the chain
   reads identical at all 4 stages.
3. **Re-run pre/post probes** with active broadcast traffic (the 2026-05-03
   probe was during a quiet broadcast window). Need 30s captures at each
   stage during representative producer activity.
4. **Track this work** as an immediate follow-up to the H3 phase 1 PR; do not
   enable the systemd unit globally until acceptance criteria are met.
