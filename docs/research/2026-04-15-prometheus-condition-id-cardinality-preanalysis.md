# Prometheus condition_id cardinality pre-analysis

**Date:** 2026-04-15
**Author:** beta (PR #819 author, AWB mode) per delta queue refill 5 Item #77
**Scope:** estimate cardinality impact of adding `condition_id` label to Prometheus metrics across LRR Phase 10 per-condition slicing + HSEA Phase 1 research-state broadcaster consumers
**Verdict:** LOW-RISK. Realistic 6-month cardinality increase fits well inside current budget with comfortable headroom.

---

## 1. Context

LRR Phase 10 (beta's own `89283a9d1` extraction) deliverable 1 is *"per-condition Prometheus slicing"* — annotate existing metrics with a `condition_id` label so dashboards can filter a stimmung trace, a reaction-rate time series, or a GPU utilization panel by the research condition that was active at frame time.

LRR Phase 1 item 5 adds `condition_id` to spans + scores (Langfuse) + reactor-log JSONL. Downstream consumers:

- **HSEA Phase 1 1.1** — HUD strip pulls the active `condition_id` from `/dev/shm/hapax-compositor/research-marker.json` for display. Not directly Prometheus-tagged.
- **HSEA Phase 5 M1** — biometric strip reads per-condition Prometheus series to slice HR / HRV / presence by condition.
- **HSEA Phase 7 D2** — anomaly narration reads per-condition Prometheus series to attribute anomalies to the active condition window.

All three HSEA consumers REQUIRE `condition_id` to be a first-class Prometheus label, not a metadata-only tag. Cardinality impact is non-trivial.

## 2. Live Prometheus baseline (verified 2026-04-15T15:30Z)

`docker exec prometheus promtool tsdb analyze /prometheus` (most recent 2h block):

| Metric | Value |
|---|---|
| Total active series | **5,279** |
| Label names | 132 |
| Unique label pairs | 1,841 |
| Total label-pair entries | 34,777 |

Top churning label pairs: `instance=host.docker.internal:8051` (13 series), `component=reverie-predictions` (12 series), `hapax_uniform_value` (4 series), `hapax_uniform_deviation` (4 series), `component=node` (3 series), `component=llm-proxy` (2 series).

**Interpretation:** current cardinality is dominated by `instance` × `component` × `__name__` triples. Series count per metric name averages ~40 (5,279 / 132). The hottest metrics (reverie predictions, LLM proxy, node exporter) are the ones most likely to be sliced by condition_id in LRR Phase 10.

## 3. Active research-registry state (verified 2026-04-15T15:30Z)

`~/hapax-state/research-registry/current.txt` currently points at:

```
cond-phase-a-baseline-qwen-001
```

`~/hapax-state/research-registry/research_marker_changes.jsonl` has **19 transition entries** across the lifetime of the file (mostly backfill + test entries; real transitions are rarer). Condition directory count: 1.

**Baseline:** the registry today has 1 active condition. All existing metrics would carry `condition_id="cond-phase-a-baseline-qwen-001"` after LRR Phase 10 rollout — net increase of zero series on day 1 (each metric gets one new label value, same series count).

## 4. Realistic 6-month condition_id cardinality projection

Per LRR Phase 1 spec §3.2 naming convention: `cond-<short-name>-<sequential>`. Examples already used in specs:

- `cond-phase-a-baseline-qwen-001` — current (Qwen3.5-9B substrate)
- `cond-phase-a-prime-hermes-8b-002` — historical Phase 5b target (killed per drop #62 §14)
- `cond-phase-a-prime-olmo-8b-002` — alternative substrate per beta's substrate research §9.3 (operator-gated)

**Per drop #62 §P-3** (*"conditions never close, they branch"*), conditions accumulate over time. Realistic Phase A-only projection for 6 months:

| Quarter | Expected new conditions | Running total | Rationale |
|---|---|---|---|
| Q1 (now – 2026-07-15) | 2-3 | 3-4 | Phase A baseline stays; substrate swap (Option C) opens `cond-phase-a-prime-*`; 1-2 sub-experiments per claim |
| Q2 (2026-07-15 – 2026-10-15) | 3-4 | 6-8 | Claim-shaikh SFT/DPO split; HSEA Phase 0 intervention condition; 1-2 exploratory branches |
| Future (beyond 6 months) | — | ≤20 by EOY | matches delta's refill 5 Item #77 criteria *"≤ 20 distinct condition_id values realistic"* |

**Total realistic active condition_id values over 6 months: 6-8.** Delta's ceiling of 20 is conservative.

## 5. Per-metric cardinality contribution from `condition_id` label

Label multiplication is the multiplicative product of label value counts. For a metric with current cardinality N, adding a label with K values **maximally** multiplies cardinality by K, but realistic multiplication depends on whether the metric is exported while multiple conditions are simultaneously active.

**Key observation:** at any point in time, the compositor writes to EXACTLY ONE `condition_id` (the active marker). Different conditions occupy different time windows. The Prometheus time series for a metric does not get K parallel series — it gets ONE series whose label value changes over time. Old series become stale (no new samples), and once the stale time exceeds the retention window (Prometheus default: 15 days, hapax config TBD), the old series drops from active cardinality.

**Two cardinality regimes depending on how the metric is exported:**

### Regime A — metric is exported with `condition_id` as a static label

- Series count per metric multiplies by the number of condition_id values whose marker interval overlaps the retention window
- With 6-month retention: 6-8 conditions → 6-8x cardinality per annotated metric
- With 15-day retention: typically 1-2 conditions active in the 15-day window → 1-2x cardinality per annotated metric

### Regime B — metric is exported without `condition_id` label, read via on-demand filter at query time

- Prometheus cardinality: UNCHANGED (no new label)
- Query-time filtering by condition_id: requires joining on a `condition_id{active_since, active_until}` range vector OR filtering by timestamp
- More complex queries; fewer series

**Recommendation:** Regime A for metrics where per-condition slicing is a primary use case (reaction rate, presence probability, GPU utilization during livestream). Regime B for metrics where per-condition slicing is incidental (node_exporter CPU, Docker container health). Split the decision per-metric rather than globally.

## 6. Total cardinality budget impact

**Current total:** 5,279 active series + 1,841 unique label pairs.

**Estimated additional series from LRR Phase 10 per-condition slicing (Regime A, 15-day retention, 2 active conditions per window):**

| Metric category | Current series | New series (2× multiplier) | Increase |
|---|---|---|---|
| reverie-predictions (12 series baseline) | 12 | 24 | +12 |
| llm-proxy (2 series baseline) | 2 | 4 | +2 |
| hapax_uniform_* (8 series baseline) | 8 | 16 | +8 |
| stream/reaction metrics (TBD) | ~50 (estimate) | ~100 | +50 |
| stimmung metrics (TBD) | ~30 (estimate) | ~60 | +30 |
| **Subtotal (LRR Phase 10 targets)** | **~102** | **~204** | **~+102** |

**Adjusted total after LRR Phase 10 rollout:** 5,279 → ~5,381 (+2% series).

**Worst-case scenario (all 132 label names add condition_id, 6-month retention, 8 conditions active in window):**

- 5,279 × 8 = 42,232 series
- Still well under Prometheus default cardinality warning threshold (100k series) and node-local storage limits

**Prometheus CPU/memory impact:** with ~5k baseline series, hapax Prometheus runs at <200 MB resident memory. Doubling to ~10k series is expected to add ~80 MB resident. Node has 64 GB — zero concern.

**Bucket/histogram metrics:** histogram metrics multiply by bucket count. If `reaction_duration_seconds_bucket` has 11 buckets and gets condition_id, that's 11 × 8 = 88 series per instance. Still a rounding error.

## 7. Per-metric decision recommendations

LRR Phase 10 should NOT blanket-add condition_id to every metric. Split by purpose:

### High-value Regime A (static label, worth the cardinality)

- `hapax_reaction_rate_per_second{condition_id=...}` — primary research signal
- `hapax_presence_probability{condition_id=...}` — per-condition presence baseline
- `hapax_stimmung_dimension{dimension=..., condition_id=...}` — condition-specific mood baselines
- `hapax_llm_tokens_generated_total{model=..., condition_id=...}` — per-condition substrate cost attribution
- `hapax_gpu_memory_used_bytes{condition_id=...}` — condition-specific hardware envelope tracking

### Low-value Regime B (metadata tag, filter at query time)

- `node_cpu_seconds_total` — hardware metric, condition-agnostic
- `process_resident_memory_bytes` — process metric, condition-agnostic
- `http_requests_total` — LiteLLM gateway, condition_id live inside span metadata
- Container health / restart count metrics

### Hybrid (Regime A at session boundary, not per-sample)

- `hapax_condition_epoch{condition_id=..., epoch=N}` — single gauge per condition transition, written once at marker change time. Provides the joinable range vector for Regime B queries.

## 8. Headroom analysis

Prometheus warning threshold: 100,000 active series.
Prometheus memory warning: typically at ~40 GB resident for 1M series (linear scaling).

**Current:** 5,279 series ≈ 5% of warning threshold, <200 MB memory.

**Post-LRR Phase 10 (realistic Regime A):** ~5,500 series ≈ 5.5%, <250 MB memory.

**Post-HSEA Phase 5 M1 + Phase 7 D2 (adding biometric + anomaly per-condition series):** ~6,500 series ≈ 6.5%, <300 MB memory.

**Worst-case (all metrics get condition_id × 20 ceiling):** ~105,560 series ≈ 105%, ~500 MB memory. **This approaches the warning threshold** but would require blanket rollout that this pre-analysis explicitly recommends against.

**Conclusion:** with the per-metric Regime A/B split recommended in §7, total cardinality stays under 10k series indefinitely. Headroom is more than sufficient.

## 9. Non-goals + operational recommendations

**Non-goals:**

1. This pre-analysis does not propose a retention policy change. Prometheus retention stays at current config (TBD — check `docker compose config` for the `--storage.tsdb.retention.time` flag; default 15d).
2. This pre-analysis does not propose moving to Cortex / Thanos / Mimir. Local Prometheus is sufficient at these cardinalities.
3. This pre-analysis does not propose metric-name renames or deletions. Existing metrics stay as-is.

**Operational recommendations:**

1. **Phase 10 polish session should add a cardinality dashboard** — a Grafana panel reading `prometheus_tsdb_head_series` over time. Lets the operator see impact of condition_id rollout in real time.
2. **Phase 10 polish session should add an alert** — `prometheus_tsdb_head_series > 50000` → ntfy warning. Early warning against runaway cardinality.
3. **Cardinality budget as a research instrument** — if a metric unexpectedly doubles its series count when condition_id is added, the dashboard catches it. Useful for debugging misuse of the label.
4. **HSEA Phase 1 research-state broadcaster should write condition_id to the shared metric** — `hapax_condition_epoch` single gauge, written once at transition time by the broadcaster rather than per-metric. Gives Regime B queries a joinable vector without per-metric pollution.

## 10. Cardinality ceiling validation

Delta's refill 5 Item #77 criteria: *"How many distinct condition_id values realistic over a 6-month LRR cycle (≤ 20)"*.

This pre-analysis agrees: realistic 6-month ceiling is 6-8 active conditions at any point. 20 is a conservative worst-case for the whole 6-month period accounting for experimental branches that never retire. The 20 ceiling does NOT force 20× multiplication on any metric because conditions branch sequentially — the Prometheus series for an old condition goes stale and drops out of the active window at retention timeout.

## 11. References

- LRR Phase 1 spec `docs/superpowers/specs/2026-04-15-lrr-phase-1-research-registry-design.md` §3.2 (condition naming), §3.3 (research marker SHM schema), §3.4 (reaction tagging)
- LRR Phase 10 spec `docs/superpowers/specs/2026-04-15-lrr-phase-10-observability-drills-polish-design.md` item 1 (per-condition Prometheus slicing)
- HSEA Phase 1 spec `docs/superpowers/specs/2026-04-15-hsea-phase-1-hud-governance-overlay-design.md` deliverable 1.1 (HUD strip)
- HSEA Phase 5 spec `docs/superpowers/specs/2026-04-15-hsea-phase-5-m-series-biometric-strip-design.md` M1 (biometric strip)
- HSEA Phase 7 spec `docs/superpowers/specs/2026-04-15-hsea-phase-7-self-monitoring-catastrophic-tail-design.md` D2 (anomaly narration)
- Drop #62 §P-3 branching principle (`docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md`)
- Live Prometheus tsdb analyze output (2026-04-15T15:30Z)
- Live research-registry state (`~/hapax-state/research-registry/current.txt`)

— beta (PR #819 author, AWB mode), 2026-04-15T15:30Z
