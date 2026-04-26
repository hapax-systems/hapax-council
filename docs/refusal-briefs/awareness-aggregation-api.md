# Refusal Brief: Aggregation API for Awareness State / Refusal Log

**Slug:** `awareness-refused-aggregation-api`
**Axiom tag:** `feedback_full_automation_or_no_engagement`, `single_user`
**Refusal classification:** Anti-pattern (drop 6 §3) — aggregation obscures refusal-as-data
**Status:** REFUSED — no aggregation endpoints, no summary queries, no count-only parameters.
**Date:** 2026-04-26
**Related cc-task:** `awareness-refused-aggregation-api`
**Sibling briefs:**
  - `awareness-acknowledge-affordances.md` (acknowledge / mark-read / triage refusals)
  - `awareness-additional-affordances.md` (tile-tap, scheduled-summary, calendar-reminder, operator-curated-filters)

## What was refused

- `/api/awareness/aggregate` endpoint
- `/api/refusals/summary` endpoint
- `?summary=1` query parameter on `/api/refusals`
- `?group_by=axiom` / `?group_by=surface` / similar grouping parameters
- `?count_only=1` parameter
- Any database materialized view or scheduled job producing
  pre-aggregated refusal counts
- Grafana panel that pulls aggregated counts from awareness/refusal
  endpoints (raw-event time-series only)

## Why this is refused

### Refusal-as-data principle

Each refusal is a **discrete first-class data point**. Aggregation
collapses the data shape into counts; the lost individuality is the
lost data. Operators (and downstream research consumers) reading
aggregated counts are systematically blinded to refusal *content*.

The Refusal Brief's constitutional commitment is "refusal is itself a
measurement" — a measurement implies a specific event, a specific
axiom invoked, a specific surface refused, a specific timestamp. None
of that survives `count(refusals) GROUP BY axiom`.

### Surveillance-shaped surface

Per `feedback_full_automation_or_no_engagement` (operator
constitutional directive 2026-04-25T16:55Z): aggregation creates a
**surveillance-shaped surface** — the operator monitoring a chart,
watching the count tick up or down. That's exactly the
attention-economy pattern the constitutional posture forecloses.

A discrete refusal-event-stream is ambient infrastructure (consumers
poll, render row-by-row). An aggregation chart is a queue / dashboard
demanding attention.

### Anti-anthropomorphization

Counts imply emotional weight: "we refused 30 things today" carries
narrative valence. Raw rows ("at 14:32:01 the publication-bus refused
target X with rationale Y") are scientific register without
anthropomorphic framing.

### Single-operator axiom

Aggregation is the multi-tenant pattern: "which tenant generated what
counts." Refusals are operator-scoped raw events; aggregation
implicitly imposes a tenant-distribution shape that doesn't exist.

## Daemon-tractable boundary

The authorized awareness/refusal consumption pattern is:

1. **`/api/refusals`** returns raw refusal-event entries (per
   `awareness-api-rest-endpoint`); consumers read the tail
2. **Each consumer renders entries individually** — waybar shows the
   most-recent entry, weblog shows the per-entry list, etc.
3. **No consumer aggregates client-side either** — the constitutional
   principle is preserved at the rendering layer too

For genuinely-needed metrics (e.g., "is the refusal log writer
healthy?"), the existing Prometheus metrics from the V5 publication-
bus Counter (`hapax_publication_bus_publishes_total{result}`) provide
operational health signals separate from refusal-event content.

## Refused implementation

- NO `/api/awareness/aggregate` route on `logos-api`
- NO `/api/refusals/summary` route
- NO query parameters for count-only / group-by / pre-aggregation on
  existing routes
- NO server-side cache of aggregate counts
- NO Grafana panel pulling aggregates from awareness/refusal
  endpoints (raw event time-series only, if at all)
- NO `awareness/aggregator.py` module

## Lift conditions

This is a constitutional refusal grounded in refusal-as-data +
full-automation envelope + anti-anthropomorphization. Lift requires
either:

- Constitutional retirement of `feedback_full_automation_or_no_engagement`
- Explicit operator re-evaluation of the refusal-as-data principle
  per drop-6 §3 anti-pattern catalog (probe path: drop-6 spec doc)

The `refused-lifecycle-constitutional-watcher` daemon (when shipped)
will check both probes per its cadence policy.

## Cross-references

- cc-task vault note: `awareness-refused-aggregation-api.md`
- Sibling refusal-briefs: `awareness-acknowledge-affordances.md`,
  `awareness-additional-affordances.md`
- Authorized raw-event endpoint:
  `awareness-api-rest-endpoint.md` (offered, depends on
  awareness-state-stream-canonical)
- Constitutional reference: drop-6 §3 (anti-pattern catalog)
- Source research: drop-6 awareness epic
