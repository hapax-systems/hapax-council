# Programme dwell-overshoot — recommended Grafana panel + alert

**Metric:** `hapax_programme_dwell_overshoot_ratio` (Gauge, labelled
`programme_id` + `role`)

**Semantics:** `elapsed_s / planned_duration_s` for the currently active
programme. `1.0` = on-time; values above `1.0` mean the programme is
overshooting its planned duration. Sustained values above `1.5` signal
the system is stuck on a programme and not advancing through the
planned arc — a quality-bar failure signal.

Set to `0` (on a sentinel `__none__` label) when no programme is
active. Left untouched (no emission) when the programme has a zero or
missing planned duration, or hasn't started yet.

Emitted by `ProgrammeManager.tick()` at the existing 1 Hz cadence.
Cheap: one Gauge.set per tick, no I/O.

## Recommended Grafana panel

Time-series panel, one series per active programme:

```promql
hapax_programme_dwell_overshoot_ratio{programme_id!="__none__"}
```

Horizontal reference lines at `1.0` (planned duration boundary) and
`1.5` (sustained-overshoot alert threshold).

## Recommended alert rule

```yaml
groups:
  - name: hapax-programme-layer
    rules:
      - alert: ProgrammeDwellOvershoot
        expr: |
          max by (programme_id, role) (
            hapax_programme_dwell_overshoot_ratio{programme_id!="__none__"}
          ) > 1.5
        for: 5m
        labels:
          severity: warning
          surface: programme-layer
        annotations:
          summary: "Programme {{ $labels.programme_id }} ({{ $labels.role }}) overshooting >1.5× planned for 5 min"
          description: |
            `hapax_programme_dwell_overshoot_ratio` sustained >1.5 indicates
            the system is stuck on a programme — content feels stagnant.
            Either the completion predicates never fire, or the planned
            duration was under-estimated. Check `hapax_programme_active`
            and the ProgrammeManager tick logs.
```

Firing at ratio `>1.5 for 5m` trips only on sustained overshoot — a
brief tick past the planned boundary (waiting for completion predicate)
is normal and should not alert. Five minutes of >50% overshoot is not.

## Cross-reference

- `hapax_programme_active` — is the programme still active?
- `hapax_programme_duration_planned_seconds` — what was the plan?
- `hapax_programme_soft_prior_overridden_total` — is the programme
  still shaping behaviour? (zero rate under overshoot = harder
  diagnosis — the programme is both overshooting AND ignored.)

## Spec

`~/Documents/Personal/20-projects/hapax-cc-tasks/active/ytb-QM3-programme-dwell-metric.md`
