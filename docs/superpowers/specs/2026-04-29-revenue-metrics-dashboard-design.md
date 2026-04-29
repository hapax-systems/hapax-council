# Revenue Metrics Dashboard Design

## Purpose

`RevenueMetricsDashboard` is the canonical machine-readable revenue actuals view for the autonomous grounding value-stream train. It tracks cumulative gross, run-rate, stream actuals, net estimates, cost leakage, readiness, source metrics, and train correction status against the corrected content-programming forecast.

This is an internal operator/private train surface. It is not a public supporter, customer, payer, or audience surface.

## Forecast Source

The active forecast is the corrected content-programming grounding train, not the superseded narrow revenue forecast.

| Horizon | Baseline | Doubled target |
|---|---:|---:|
| `1_month` | $800 | $1,600 |
| `6_months` | $64,000 | $128,000 |
| `1_year` | $220,000 | $440,000 |
| `2_years` | $715,000 | $1,430,000 |

Stream baseline targets:

| Stream | 1 month | 6 months | 1 year | 2 years |
|---|---:|---:|---:|---:|
| `platform_native` | $0 | $8,000 | $45,000 | $190,000 |
| `support_rails` | $200 | $10,000 | $30,000 | $95,000 |
| `grants_fellowships` | $0 | $25,000 | $70,000 | $160,000 |
| `research_artifacts_licensing` | $400 | $10,000 | $35,000 | $110,000 |
| `product_tool_ip` | $150 | $5,000 | $20,000 | $70,000 |
| `consulting_by_artifact` | $0 | $0 | $0 | $0 |
| `aesthetic_editions` | $50 | $4,000 | $15,000 | $65,000 |
| `studio_adjacent` | $0 | $2,000 | $5,000 | $25,000 |

`consulting_by_artifact` remains a required dimension even though the corrected content-programming forecast does not assign it base target dollars. Actuals must still land there if a receive-only artifact consultation path is built later.

## Dashboard Payload

The payload is defined by `schemas/revenue-metrics-dashboard.schema.json` and the typed model in `shared/revenue_metrics_dashboard.py`.

Required top-level fields:

- `horizon_progress`: baseline, doubled target, actual, deltas, and confidence for each horizon.
- `monthly_run_rate`: actual run-rate plus baseline and doubled run-rate targets.
- `total_actuals`: cumulative gross, costs, platform fees, taxes/withholding placeholder, processor leakage, and net estimate.
- `streams`: one row for every canonical stream.
- `formats`: one row for every canonical content-programming format.
- `readiness`: one row for every public/revenue readiness dimension.
- `source_metrics`: source-specific counters and amounts.
- `separation_policy`: machine-readable guarantee that revenue and engagement never stand in for grounding quality.
- `train_status`: train-readable next-correction view.

## Stream Dimensions

The required streams are:

- `platform_native`
- `support_rails`
- `grants_fellowships`
- `research_artifacts_licensing`
- `product_tool_ip`
- `consulting_by_artifact`
- `aesthetic_editions`
- `studio_adjacent`

Each stream row tracks:

- cumulative gross
- monthly run-rate
- net estimate
- direct costs
- platform fees
- taxes/withholding placeholder
- processor leakage
- horizon progress against baseline and doubled targets
- confidence

## Format Dimensions

The required content-programming formats are:

- `tier_list`
- `bracket`
- `review`
- `comparison`
- `what_is_this`
- `react_commentary`
- `watch_along`
- `explainer_rundown`
- `debate`
- `refusal_breakdown`
- `claim_audit`
- `failure_autopsy`

Format rows may include engagement observations and revenue/artifact conversion counters, but these observations are only selection and revenue signals. They are never scientific warrant.

## Readiness Dimensions

The required readiness dimensions are:

- `safe_to_broadcast`
- `safe_to_archive`
- `safe_to_promote`
- `safe_to_monetize`
- `safe_to_publish_offer`
- `safe_to_publish_artifact`
- `safe_to_accept_payment`

Unknown readiness fails closed for public, offer, artifact, monetization, and payment actions. The dashboard may show unknown internally so the train can see what to build next.

## Source Metrics

The dashboard exposes source metrics for:

- public events
- support prompts
- aggregate support receipts
- artifacts
- license requests
- grants
- editions
- YouTube state
- costs

Support receipt data is aggregate-only. Public or train state may include counts, rail totals, and gross aggregate amounts. It must not include payer identity, names, handles, message text, or per-payer history.

## Grounding Separation Policy

Revenue and engagement are separate from grounding quality:

- `engagement_can_override_grounding` is always `false`.
- `revenue_can_override_grounding` is always `false`.
- `popularity_is_scientific_warrant` is always `false`.
- Format engagement observations carry `kept_separate: true` and `may_override_grounding: false`.
- Grounding quality references must point to evaluator or public-event evidence, not view counts, receipt counts, or platform revenue.

## Train-Readable Status

`train_status` identifies:

- which streams are under target
- which horizons are under target
- the stream with the earliest largest baseline gap
- the packet that should unblock the next correction
- the reason the train should pick that packet before running revenue experiments

Initial packet mapping:

| Under-target stream | Next correction packet |
|---|---|
| `platform_native` | `content-programming-grounding-runner` |
| `support_rails` | `public-offer-page-generator-no-perk` |
| `grants_fellowships` | `grant-opportunity-scout-attestation-queue` |
| `research_artifacts_licensing` | `artifact-catalog-release-workflow` |
| `product_tool_ip` | `artifact-catalog-release-workflow` |
| `consulting_by_artifact` | `license-request-price-class-router` |
| `aesthetic_editions` | `condition-edition-marketplace-publisher` |
| `studio_adjacent` | `replay-card-marketplace-publisher` |

## Example

```json
{
  "schema_version": 1,
  "forecast_source": "corrected_content_programming_grounding_train",
  "horizon_progress": {
    "1_month": {
      "baseline_usd": 800,
      "doubled_target_usd": 1600,
      "actual_usd": 0,
      "delta_from_baseline_usd": -800,
      "delta_from_doubled_target_usd": -1600,
      "confidence": "unknown"
    },
    "6_months": {
      "baseline_usd": 64000,
      "doubled_target_usd": 128000,
      "actual_usd": 0,
      "delta_from_baseline_usd": -64000,
      "delta_from_doubled_target_usd": -128000,
      "confidence": "unknown"
    },
    "1_year": {
      "baseline_usd": 220000,
      "doubled_target_usd": 440000,
      "actual_usd": 0,
      "delta_from_baseline_usd": -220000,
      "delta_from_doubled_target_usd": -440000,
      "confidence": "unknown"
    },
    "2_years": {
      "baseline_usd": 715000,
      "doubled_target_usd": 1430000,
      "actual_usd": 0,
      "delta_from_baseline_usd": -715000,
      "delta_from_doubled_target_usd": -1430000,
      "confidence": "unknown"
    }
  },
  "source_metrics": {
    "aggregate_support_receipts": {
      "receipt_count": 0,
      "gross_usd": 0,
      "rail_counts": {},
      "public_state_aggregate_only": true,
      "per_receipt_public_state_allowed": false
    }
  },
  "separation_policy": {
    "engagement_can_override_grounding": false,
    "revenue_can_override_grounding": false,
    "popularity_is_scientific_warrant": false
  },
  "train_status": {
    "status": "under_target",
    "under_target_streams": [
      "support_rails",
      "research_artifacts_licensing",
      "product_tool_ip",
      "aesthetic_editions"
    ],
    "under_target_horizons": ["1_month", "6_months", "1_year", "2_years"],
    "next_correction_stream": "research_artifacts_licensing",
    "next_correction_packet": "artifact-catalog-release-workflow"
  }
}
```

## Downstream Unblockers

This contract unblocks:

- `revenue-experiment-controller`, which can consume `train_status` and source metrics.
- `public-offer-page-generator-no-perk`, which needs support prompt and aggregate receipt metrics.
- `artifact-catalog-release-workflow`, which needs artifact and license conversion metrics.
- `grant-opportunity-scout-attestation-queue`, which needs generated/submitted/won/disbursed grant counters.
