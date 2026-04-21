# Master-Bus Feedback Cycle — Post-Deploy Finding

**Date:** 2026-04-21
**Author:** delta
**Status:** post-incident — master-bus conf removed from repo; redesign pending
**References:**

- Merged-then-reverted: PR #1144 `config/pipewire/hapax-broadcast-master.conf`
- Prior fix attempt: commit `07de5c6c5` removed `media.class = Audio/Source`
  on playback.props based on the verified pattern from
  `hapax-obs-broadcast-remap.conf`.

## 1. What happened

PR #1144 shipped `hapax-broadcast-master.conf` with a loopback-pattern fix
that removed `media.class = Audio/Source` from the loopback's playback
props. Local reasoning held the fix eliminated the auto-link cycle
(`hapax-bm-capture:input ← hapax-broadcast-master-monitor:output`). On
merge, `hapax-post-merge-deploy` copied the conf to the user pipewire
directory and restarted the pipewire stack. `pw-link -l` then showed a
NEW cycle, same destination class but different waypoint:

```
hapax-livestream-tap-src:input_FL
  |<- hapax-livestream-tap:monitor_FL   ← intended
  |-> hapax-livestream-tap:playback_FL  ← intended (this loopback forwards tap → livestream)
  |-> hapax-livestream-tap:playback_FR
  |<- hapax-broadcast-master-monitor:output_FL   ← UNINTENDED auto-link
  |<- hapax-broadcast-master-monitor:output_FR   ← UNINTENDED auto-link
```

The filter-chain's monitor port (`hapax-broadcast-master-monitor`) was
auto-linked as an additional source into the EXISTING
`hapax-livestream-tap-src` capture node belonging to the livestream-tap
forwarding loopback. The sink was IDLE at observation time so no audio
was flowing through the cycle, but it would have activated the moment
the compositor wrote to `hapax-livestream-tap`.

Remediation: renamed user-dir conf to `.disabled`, restarted pipewire,
confirmed the cycle cleared. No live-stream audio impact because the
incident was caught before active signal flowed through the loop.

## 2. Root cause hypothesis

WirePlumber's default linking policy treats nodes with `media.class =
Audio/Source` (which a filter-chain's monitor port becomes by default
via the `node.monitor=true` path) as candidates to auto-link into any
compatible capture node. The existing livestream-tap loopback's
capture-side node (`hapax-livestream-tap-src`) is declared with
`stream.capture.sink = true` + `target.object = hapax-livestream-tap`,
which expresses "I want the monitor of livestream-tap," but does not
declare "and only that source." The default policy saw the
broadcast-master-monitor as a matching source and added it to the
capture's inputs, creating the cycle.

Removing `media.class = Audio/Source` from the broadcast-master
LOOPBACK (as the prior fix attempted) stopped the loopback's own
output from being a source, but did not prevent the
broadcast-master FILTER-CHAIN's monitor (a different node) from
being auto-linked.

## 3. Why per-source-loudnorms suffice without master-bus

The broadcast-master goal was to catch peak-stacking when multiple
sources coincide (voice + vinyl + YT + Evil Pet loop). With the
per-source loudnorms already deployed (`voice-fx-loudnorm.conf`,
`yt-loudnorm.conf`, `pc-loudnorm.conf`), each source is capped at
-14 LUFS / -1.0 dBTP individually. Summation can theoretically exceed
-1.0 dBTP briefly on simultaneous peaks, but:

- Each ingress loudnorm's hard_limiter caps at -1.0 dBTP, so the
  signal into `hapax-livestream` never exceeds that individual ceiling.
- YouTube ingest applies its own normalization to the final broadcast
  at the platform side.
- Operator-perceived dynamic range remains acceptable without the
  master-bus layer per live-stream observation today.

The master-bus is a belt-and-suspenders safety net, not a required
component for broadcast-legal output.

## 4. Path forward — when revisiting

A working master-bus requires preventing WirePlumber from auto-linking
the filter-chain's monitor port into any other capture node. Candidates:

- **WirePlumber policy rule**: a
  `config/wireplumber/50-broadcast-master-isolation.conf` script that
  explicitly blocks default-policy auto-linking for sources matching
  `node.name = hapax-broadcast-master-monitor`. Highest certainty,
  most invasive.
- **Node-property escape-hatch**: add
  `stream.restore.target = null` and `node.autoconnect = false` on the
  filter-chain's playback.props. Less certain WirePlumber honors these
  for filter-chain-emitted monitors, but worth testing.
- **Re-architect the capture**: instead of the filter-chain sink
  exposing a monitor that other nodes can auto-link, wrap the
  monitor in a `module-remap-source` (identical to the pattern
  `hapax-obs-broadcast-remap.conf` uses for `hapax-livestream`).
  The remap-source declares `device.class = filter`, `node.virtual = true`,
  a fixed `device.description` — these properties discourage auto-link
  in WirePlumber's default policy and give OBS a stable picker target.

The last option aligns with the verified-good pattern already in
production for `hapax-livestream`-to-OBS routing. When master-bus is
revisited, it should reuse that pattern.

## 5. Deliverable of this research

`config/pipewire/hapax-broadcast-master.conf` is removed from the
repository. The user-dir copy has been disabled (`.disabled` suffix).
No further action is in-flight. A future spec+plan for the revisit
should reference this document as prior-art.

## 6. Memory

Added to session memory: "master-bus filter-chain monitor auto-links
— removing media.class from the loopback is insufficient; the
filter-chain's own monitor port is the auto-link target. Fix requires
either a WirePlumber policy rule or a remap-source wrapper (same
pattern as hapax-obs-broadcast-remap)."
