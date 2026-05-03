# Private→Broadcast Leak Guard (3-layer defense)

## Constitutional invariant

The L-12 broadcast bus only carries broadcast-bound audio. Private monitor
streams (`hapax-private*`, `hapax-notification-private*`) MUST route to a
non-broadcast monitor destination and MUST NEVER reach broadcast.

Memory: `feedback_l12_equals_livestream_invariant`.

## Option C amendment (2026-05-02)

Per `docs/superpowers/specs/2026-05-02-hapax-private-monitor-track-fenced-via-s4.md`,
the private-monitor target was **retargeted from the Yeti monitor sink to the
S-4 USB IN Track 1 input** to satisfy the NO-DRY-HAPAX anti-anthropomorphism
mandate while preserving the privacy invariant. The S-4 internal scene
`HAPAX-PRIVATE-MONITOR` routes Track 1 input → analog OUT 1/2 (operator's
non-broadcast monitor patch), so the privacy invariant is enforced at
TRACK-OUTPUT level, not device level.

The 3-layer defense shape is unchanged — only the Layer B target moved
from Yeti to S-4 USB IN. The prior Yeti pin is preserved on disk as
`56-hapax-private-pin-yeti.conf.disabled-2026-05-02-option-c` for revert
capability. See `docs/governance/option-c-private-track-fenced-routing.md`
for the operator runbook.

## Why the three layers

On 2026-05-02 the topology audit kept showing
`hapax-private-playback -> alsa_output.usb-ZOOM_Corporation_L-12...
analog-surround-40` as an unclassified edge. Wireplumber's stream-restore had
re-applied a stale per-device target rule from a pre-TB-dock-topology-change
boot snapshot, so the private playback loopback was being re-targeted at the
L-12 broadcast sink on every restart. Manual `pw-link -d` cleared it but it
re-emerged after each PipeWire/WirePlumber restart.

A single layer is not enough — each protects against a different failure mode
and they compose:

| Layer | File | Failure mode it prevents |
|-------|------|--------------------------|
| A | `config/wireplumber/55-hapax-private-no-restore.conf` | Stream-restore re-applies a stale `target.object` from `~/.local/state/wireplumber/restore-stream` |
| B | `config/wireplumber/56-hapax-private-pin-s4-track-1.conf` | Linker default-sink elevation when no explicit target — pins S-4 USB IN, fail-closed if S-4 absent (Option C, was 56-hapax-private-pin-yeti.conf pre-2026-05-02) |
| C | `scripts/hapax-private-broadcast-leak-guard` | Anything else: a forbidden link survives layers A+B, the runtime guard breaks it within 30s |

Together they protect the constitutional invariant against (a) stale state,
(b) linker policy, (c) any unanticipated wiring path.

## Layer A — restore-stream rule

`config/wireplumber/55-hapax-private-no-restore.conf` tells WirePlumber's
restore-stream policy to ignore any saved target/props for nodes whose
`node.name` matches `hapax-private*` or `hapax-notification-private*`. The
stream comes up with config-defined target only — no inherited state from
prior boots.

This is the right primitive for the failure mode that fired today. WirePlumber
0.5.x supports `restore-stream.rules` as a top-level `wireplumber.settings`
key, with `update-props { state.restore-target = false }` inside the action.

## Layer B — hard-pin to S-4 USB IN (Option C, 2026-05-02)

`config/wireplumber/56-hapax-private-pin-s4-track-1.conf` forces the private
loopbacks to `target.object = alsa_output.usb-Torso_Electronics_S-4_*.multichannel-output`
with these fail-closed properties:

| Property | Effect |
|----------|--------|
| `node.dont-fallback = true` | If S-4 absent, stream stays unrouted instead of falling back to L-12 |
| `node.dont-reconnect = true` | Released link is not re-established to a different target on the next policy sweep |
| `node.dont-move = true` | Refuses session-policy retarget after creation |
| `node.linger = true` | Loopback stays alive across hardware changes (waits for S-4 to reappear) |
| `priority.session = -1` | Deprioritised for any default-sink-elevation policy |

The S-4 USB sink node name is hard-coded; if the S-4 firmware / USB
enumeration name ever changes, edit the `target.object` literal. The runtime
guard (Layer C) does NOT need editing — it identifies broadcast targets by a
forbidden-list, not by the allowed S-4 USB IN target.

**S-4 internal scene programming required.** The Layer B WirePlumber pin
only governs the host-side software route. The S-4 internal scene
`HAPAX-PRIVATE-MONITOR` (operator-side firmware action, not in this layer)
must wire `Track 1: input = USB IN <pair>, output = analog OUT 1/2,
slots = <wet character>` for the path to actually produce wet audio on the
operator's monitor amp. See `docs/governance/option-c-private-track-fenced-routing.md`
§ "Program the S-4 internal scene".

## Layer C — runtime backstop

`scripts/hapax-private-broadcast-leak-guard` is a Python guard that runs every
30 seconds via `systemd/units/hapax-private-broadcast-leak-guard.timer`. On
each tick it:

1. Calls `pw-link -l` and parses the live PipeWire graph.
2. Detects any link whose source node matches `hapax-private*` /
   `hapax-notification-private*` AND whose target matches the FORBIDDEN-list:
   - L-12 (`*ZOOM_Corporation_L-12*`)
   - S-4 USB OUT pair (`alsa_input.usb-Torso_Electronics_S-4_*` — the
     broadcast-bound capture surface; Option C 2026-05-02 narrowing).
     The S-4 USB IN sink (`alsa_output.usb-Torso_Electronics_S-4_*`) is
     ALLOWED — it is the new wet private path through Track 1.
   - `hapax-s4-content`, `hapax-s4-tap` (S-4 broadcast loopback nodes)
   - `hapax-livestream*`, `hapax-broadcast*`
   - `hapax-music-duck`, `hapax-tts-duck`
   - `hapax-music-loudnorm`, `hapax-pc-loudnorm`
   - `hapax-voice-fx-capture`, `hapax-loudnorm-capture`,
     `hapax-obs-broadcast-remap`
3. For each forbidden link, runs `pw-link -d <src> <dst>` to break it.
4. Logs detection + repair to journald via syslog (`tag=hapax-private-broadcast-leak-guard`).
5. Increments Prometheus counters
   `hapax_private_broadcast_leak_detected_total{target=...}` and
   `hapax_private_broadcast_leak_repaired_total{target=...}` via the
   node_exporter textfile collector at
   `~/.local/share/node_exporter/textfile_collector/hapax-private-broadcast-leak-guard.prom`.
6. Writes JSON status to `/dev/shm/hapax-private-broadcast/status.json`.

Exit codes are distinct so monitors can route by failure mode:

- `0` — clean: no forbidden links observed.
- `1` — leak detected (the privacy invariant was breached on this tick,
  even if the link was successfully torn down — operator MUST review the
  witness JSON).
- `2` — guard cannot evaluate: `pw-link` exited non-zero, the binary is
  missing, or PipeWire is down. The witness JSON sets `unavailable: true`
  and `ok: false`. This is the fail-CLOSED branch — the guard refuses to
  classify "no output = no leaks" because that would be silent fail-OPEN.

## Install steps

The wireplumber confs ship under `config/wireplumber/`. They are not picked up
automatically — symlink or copy to the user wireplumber config dir:

```sh
mkdir -p ~/.config/wireplumber/wireplumber.conf.d
ln -sf $(pwd)/config/wireplumber/55-hapax-private-no-restore.conf \
       ~/.config/wireplumber/wireplumber.conf.d/55-hapax-private-no-restore.conf
ln -sf $(pwd)/config/wireplumber/56-hapax-private-pin-s4-track-1.conf \
       ~/.config/wireplumber/wireplumber.conf.d/56-hapax-private-pin-s4-track-1.conf
# If reverting from Option C, remove the S-4 pin and copy the disabled Yeti
# pin back: see docs/governance/option-c-private-track-fenced-routing.md
systemctl --user restart wireplumber
```

The leak guard script and systemd units are deployed by the standard
`scripts/hapax-post-merge-deploy` chain (which copies `systemd/units/*.{service,timer}`
into `~/.config/systemd/user/` and the script into `~/.local/bin/`):

```sh
systemctl --user daemon-reload
systemctl --user enable --now hapax-private-broadcast-leak-guard.timer
```

Verify operation:

```sh
systemctl --user status hapax-private-broadcast-leak-guard.timer
journalctl --user -t hapax-private-broadcast-leak-guard -n 50
cat /dev/shm/hapax-private-broadcast/status.json
```

## Manual verification after install

After enabling, confirm that the live graph contains no forbidden private→
broadcast links:

```sh
~/.local/bin/hapax-private-broadcast-leak-guard --no-repair
```

Should print `ok no_forbidden_links` and exit 0. If it does not, run with
repair enabled (the default) and check the JSON status for any entries where
`repaired=false`.

## Related work

- `scripts/hapax-private-voice-leak-probe` — operator-authorized live probe
  that exercises the broadcast/private split for one Daimonion utterance.
  Read-only (no mutations); useful for post-incident verification.
- `scripts/hapax-usb-topology-witness` — broader USB topology witness that
  surfaces unclassified edges (this is what flagged today's incident).
- `config/audio-topology.yaml` — declarative topology spec; the
  `private-monitor-output` and `notification-private-monitor-output` entries
  document the intended S-4 USB IN Track 1 input target (Option C, was
  Yeti pre-2026-05-02).
- `docs/governance/option-c-private-track-fenced-routing.md` — Option C
  operator runbook (S-4 scene programming, hardware patch verification,
  smoke test).
- Incident research: `/tmp/usb-hardening-research-2026-05-02.md` §4.

## Constitutional notes

This guard is constitutional infrastructure: it backstops the L-12 invariant
that broadcast audio cannot be co-mingled with private audio. The 3-layer
shape (config + config + runtime) is deliberate — under the operator's
"never stall, revert > stall" policy, any single layer's failure is
recoverable from the other two without operator action.
