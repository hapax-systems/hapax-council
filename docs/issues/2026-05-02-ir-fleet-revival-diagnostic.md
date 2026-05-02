# IR fleet revival diagnostic — 2026-05-02

cc-task: `ir-fleet-revival-diagnostic` (P1, gamma)

## Symptom

Operator reports: "IR fleet DEAD (3 Pis report persons=0,timestamp=0)".

## Diagnostic Findings

The fleet is **not dead**. Two independent failure modes coexist:

### 1. Heartbeat URL stale — `hapax-state/edge/hapax-pi{1,2,6}.json` 12 days old

`pi-edge/hapax-heartbeat.service` shipped to the Pis Apr 20 had
`Environment=WORKSTATION_URL=http://192.168.68.80:8051`. Since the deploy
the workstation's DHCP-assigned IP changed (currently `192.168.68.85`).

The repo's tracked unit file was also wrong — it pointed at
`http://hapax-podium-2.local:8051`, an mDNS name that does not resolve
on this LAN (only `hapax-podium.local` does). So fresh deploys would
have been broken too.

**Visible on the Pi**: the heartbeat service runs every 60s and exits
`status=0/SUCCESS`, because the underlying script silently swallows
network errors:

```
hapax-heartbeat.service: Deactivated successfully.
```

**Visible on council**: `~/hapax-state/edge/hapax-pi{1,2,6}.json`
mtime is Apr 20; `last_seen_epoch` is Apr 20 epoch; `check_pi_fleet`
correctly reports stale heartbeats — but only for `pi4`/`pi5` since
`pi1`/`pi2`/`pi6` are not in `health_monitor.constants.PI_FLEET`.
So the staleness was invisible to the health surface.

### 2. Person-detection true negatives confused for "broken"

Hand-zone NIR thresholding pipeline produces consistent
`hands=4` signal across all 3 Pis even when no operator is in any
camera's frame. The hand bboxes are at `y=1500-1900` of 1920-tall
portrait frames — **near the top edge of physical space (cameras are
mounted with sensor in portrait orientation)**, where stationary
LED/indicator lights on synthesizers, mixer faders, and MPC pads
register as "hand-shaped IR-bright blobs" that pass the motion-delta
gate even when motion is sub-perceptual (`motion_delta ≈ 0.013-0.015`,
i.e. NIR sensor noise floor).

Person detection (YOLOv8n single-class fine-tune, `best.onnx` 12MB)
is **functioning correctly**. Empirical verification:

- Captured greyscale debug frames from pi1/pi2 via SIGUSR1 (operator
  not in frame at capture time).
- Off-Pi inference on the same frame using the same `best.onnx`
  weights and identical preprocessing returned 0 person detections.
- Maximum confidence across all 2100 anchor boxes was `0.0224` —
  well below the `0.25` threshold and consistent with no person
  present.
- Output shape `(1, 5, 2100)` confirms single-class fine-tune
  (4 bbox + 1 person score), not 80-class COCO.

So `persons=0` is the **correct** answer for the captured frames.
The operator's audit caught a true-negative window when nobody was
in any camera's view.

## Coupled symptoms

- `timestamp=0` claim (per operator audit): unverified in council
  state files but consistent with consumer of stale `last_seen_epoch`
  treating it as a zero / null value when comparing to `now`.
- Pi-6 `192.168.68.74` is ICMP-unreachable from this workstation
  (`100% packet loss`), but its IR data still flows fresh because
  `hapax_ir_edge.py` resolves the council via mDNS
  (`hapax-podium.local`). Pi-6's inbound SSH path is the broken edge —
  outbound mDNS-resolved POSTs continue to land. **Operator action:**
  power-cycle Pi-6 or reach it via local console; not in scope for
  this diagnostic.

## Remediation Shipped

1. **`pi-edge/hapax-heartbeat.service`** — corrected `WORKSTATION_URL`
   to `http://hapax-podium.local:8051` (the mDNS name that actually
   resolves and that `hapax_ir_edge.py` already uses successfully).

2. **`scripts/ir-fleet-audit.sh`** — per-Pi audit covering ICMP, SSH,
   daemon liveness, heartbeat-timer install state, ONNX model
   presence, IR-state freshness, IR signal sanity, and heartbeat
   freshness. Distinguishes "timer active but heartbeat stale" from
   "timer not installed" — useful for telling URL-misconfig from
   timer-not-deployed.

3. **`scripts/ir-fleet-restart.sh`** — restart procedure that
   rsyncs latest unit files from the repo to each Pi, stops the
   ir-edge daemon, installs and enables the heartbeat timer (with
   role-substituted env), restarts the daemon as a direct background
   process (matches the stable production pattern — pid=875 on Pi-1
   ran as direct process for 10 days+), and verifies post-restart
   state freshness on the council side.

## Follow-up tasks (not shipped here)

- **`ir-hand-detection-static-noise-suppression`** — the NIR
  hand-zone thresholding is firing on stationary LED/backlight blobs
  even when no hand is moving. `motion_delta` cross-correlation
  per-zone (rather than global) would suppress this. Tracked as a
  separate cc-task.
- **`pi6-ssh-reachability`** — Pi-6 inbound SSH is dead. Operator
  needs to power-cycle or local-console. Outbound mDNS-resolved
  posting still works, so the Pi is alive enough that IR data
  flows; only the maintenance path is broken.
- **`bayesian-presence-engine-false-positive-audit`** — the
  `ir_hand_active` Bayesian signal (LR=8.5x positive-only) is
  currently driving false PRESENT inferences when operator is
  absent because of (1). Audit downstream consumers and add a
  signal-quality gate: require motion_delta > floor AND hand
  bbox y-coord in the operator-zone band, not just any zone.

## Refs

- `docs/superpowers/specs/2026-03-31-ir-perception-remediation-design.md`
- `pi-edge/hapax_ir_edge.py`, `pi-edge/ir_inference.py`
- `agents/health_monitor/constants.py` `PI_FLEET`
- `agents/health_monitor/checks/edge.py` `check_pi_fleet()`
- CLAUDE.md `## IR Perception (Pi NoIR Edge Fleet)`
- CLAUDE.md `## Bayesian Presence Detection`
