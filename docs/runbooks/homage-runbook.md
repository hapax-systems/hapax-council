# HOMAGE runbook

Operational notes for the HOMAGE framework (spec
`docs/superpowers/specs/2026-04-18-homage-framework-design.md`).

## Changelog

- **2026-04-18 — Phase 12 (task #120) — go-live.**
  - `HAPAX_HOMAGE_ACTIVE` default flipped from OFF to ON. Unset env
    resolves to active. Rollback requires an explicit falsy value.
  - Consent-safe variant registered: `bitchx_consent_safe`. Engaged by
    the choreographer when `/dev/shm/hapax-compositor/consent-safe-active.json`
    is present. Palette collapses to pure grey; signature artefact
    corpus stripped.
  - Signature artefact emission wired through the choreographer: one
    random artefact from the package corpus per rotation cycle, weighted
    by `SignatureArtefact.weight`. Published to
    `/dev/shm/hapax-compositor/homage-active-artefact.json`; counter
    `hapax_homage_signature_artefact_emitted_total` incremented.

## Rollback

Emergency: flip the flag back to off and restart the compositor.

```fish
export HAPAX_HOMAGE_ACTIVE=0
systemctl --user restart studio-compositor.service
```

Verify: no homage coupling payload should appear in
`/dev/shm/hapax-imagination/uniforms.json` under the
`signal.homage_custom_*` keys, and
`hapax_homage_package_active{package="bitchx"}` should read 0 on
Prometheus.

## Consent-safe engagement

The consent-live-egress guard writes the flag file when a non-operator
face is detected with no active consent contract. The choreographer
reads the file every reconcile tick; flipping happens within one tick
(~100 ms at the default cadence).

Manual engage (testing only):

```fish
mkdir -p /dev/shm/hapax-compositor
echo '{"consent_safe": true}' > /dev/shm/hapax-compositor/consent-safe-active.json
```

Manual disengage:

```fish
rm -f /dev/shm/hapax-compositor/consent-safe-active.json
```

## Observability

- Prometheus:
  - `hapax_homage_package_active{package}` — 1 when the named package
    is the one reconciled this tick.
  - `hapax_homage_transition_total{package,transition_name}` — transitions
    applied.
  - `hapax_homage_choreographer_rejection_total{reason}` — pending
    transitions the choreographer declined.
  - `hapax_homage_signature_artefact_emitted_total{package,form}` —
    signature artefacts rotated.
  - `hapax_homage_violation_total{package,kind}` — render-time paste /
    anti-pattern violations.
- Grafana panel: `Homage — Transitions & Violations` under the
  existing director dashboard.

## HARDM dot-matrix publisher (task #121 follow-up)

The HARDM ward (`agents/studio_compositor/hardm_source.py`) renders a
16×16 dot-matrix readout of 16 primary signals. It reads from
`/dev/shm/hapax-compositor/hardm-cell-signals.json`. If that file is
absent or stale the ward falls back to an all-idle skeleton.

The file is written by the `hapax-hardm-publisher.service` oneshot,
driven by `hapax-hardm-publisher.timer` every 2 seconds. Spec:
`docs/superpowers/specs/2026-04-18-hardm-dot-matrix-design.md`.

### Start / stop

```fish
# Start (and enable across reboots)
systemctl --user enable --now hapax-hardm-publisher.timer

# Pause publishing (ward falls back to idle within 1 s)
systemctl --user stop hapax-hardm-publisher.timer

# Fire one publish tick manually
systemctl --user start hapax-hardm-publisher.service
```

The timer is installed via `systemd/scripts/install-units.sh` but left
disabled-by-default; the operator must explicitly enable it as above.

### Verify signals flowing

```fish
# Payload + age
jq . /dev/shm/hapax-compositor/hardm-cell-signals.json
stat -c '%Y' /dev/shm/hapax-compositor/hardm-cell-signals.json

# Per-signal watch
watch -n1 'jq ".signals" /dev/shm/hapax-compositor/hardm-cell-signals.json'

# Service + timer liveness
systemctl --user status hapax-hardm-publisher.timer
journalctl --user -u hapax-hardm-publisher.service -n 20
```

All 16 keys must appear (`midi_active`, `vad_speech`, `watch_hr`,
`bt_phone`, `kde_connect`, `screen_focus`, `room_occupancy`,
`ir_person_detected`, `ambient_sound`, `director_stance`,
`stimmung_energy`, `shader_energy`, `reverie_pass`, `consent_gate`,
`degraded_stream`, `homage_package`).

### Troubleshooting

- **All cells idle in the ward.** Either the timer is not running
  (`systemctl --user is-active hapax-hardm-publisher.timer`) or the
  publisher is crashing — check `journalctl --user -u
  hapax-hardm-publisher.service`. Missing canonical state files
  (`perception-state.json`, `narrative-state.json`,
  `stimmung-state.json`, `uniforms.json`, `homage-active.json`) are
  non-fatal; they map to `False` / `None` defaults.
- **Signals stuck / stale.** Check file mtime; if older than 3 s the
  ward's staleness cutoff (`STALENESS_CUTOFF_S` in
  ``agents/studio_compositor/hardm_source.py``) drops the payload and
  every cell reverts to idle. Restart the timer:
  `systemctl --user restart hapax-hardm-publisher.timer`.
- **`consent_gate` always `null`.** The publisher imports
  `shared.consent.ConsentRegistry` best-effort; if the import fails
  the cell shows idle instead of stress. This is intentional
  (publisher must never crash on optional probes) but worth
  investigating if consent state never surfaces.
- **Publisher crashes.** Malformed canonical state is handled
  defensively (tests in `tests/scripts/test_hardm_publish_signals.py`
  pin the defaults-on-malformed contract). A genuine crash is a
  regression — attach stderr from the failing tick.
