# Phase 7 — Research Observability

**Spec:** §3.6, §5 Phase 7
**Goal:** Every directorial decision produces research-quality artifacts. JSONL append-only log, Langfuse span metadata, Prometheus gauges. Downstream RIFTS / MCMC BEST / palette-coverage dashboards consume without extra wiring.

## File manifest

- **Create:** `shared/director_observability.py` — `emit_director_intent(intent, condition_id)`, `emit_structural_intent(intent, condition_id)`, `emit_palette_coverage(families_recruited_in_window)`.
- **Modify:** `agents/studio_compositor/director_loop.py::_call_activity_llm` — extend Langfuse span metadata.
- **Modify:** `agents/studio_compositor/structural_director.py` — same span enrichment.
- **Create:** `config/prometheus/alerts/director-intent.yml` — optional alerts (no alerts fire by default; sanity rules only).
- **Create:** `config/grafana/director-palette-coverage.json` — dashboard definition.
- **Create:** `scripts/director-intent-replay.py` — reads JSONL, replays for analysis.
- **Create:** `tests/shared/test_director_observability.py`.

## Condition ID

All emitters read the active condition from `/dev/shm/hapax-compositor/research-marker.json` (the `condition_id` field) at emit-time. Missing/absent file ⇒ `condition_id="none"`. Reader is cached 5 s to avoid per-emission syscall. This matches the pattern already in `director_loop.py:_read_research_marker`.

## Metrics emitted (Prometheus)

All labels include `condition_id` per LRR Phase 10 per-condition slicing.

- `hapax_director_intent_total{condition_id, activity, stance}` — counter, incremented per narrative intent.
- `hapax_director_structural_intent_total{condition_id, scene_mode, preset_family_hint}` — counter.
- `hapax_director_twitch_move_total{condition_id, intent_family}` — counter.
- `hapax_director_grounding_signal_used_total{condition_id, signal_name}` — counter, one increment per entry in grounding_provenance.
- `hapax_director_palette_coverage_ratio{condition_id, window="10m"}` — gauge, updated per structural tick. Count distinct affordance families recruited in trailing 10 min / total possible families.
- `hapax_director_llm_latency_seconds_bucket{condition_id, director_tier="narrative|structural"}` — histogram.
- `hapax_director_intent_parse_failure_total{condition_id, director_tier}` — counter of LLM JSON malformed fallbacks.

## Tasks

- [ ] **7.1** — Implement `shared/director_observability.py`:
  - Use existing `prometheus_client` gauges/counters (follow pattern in `agents/telemetry/llm_call_span.py`).
  - Use existing `hapax_span` from `shared/telemetry.py` for Langfuse integration.
  - JSONL append via `shared/atomic_write.py` (batched per-tick).
- [ ] **7.2** — Write tests:
  - `test_emit_director_intent_appends_jsonl`: intent emitted → new line in file, parseable back.
  - `test_emit_director_intent_bumps_prometheus_counter`: metric value increments.
  - `test_grounding_signal_counter_per_provenance`: 3 provenance entries → counter incremented 3 times.
  - `test_palette_coverage_calculation`: given a history of recruited families, ratio is correct.
  - `test_parse_failure_recorded`: fallback path records failure counter.
- [ ] **7.3** — Run tests, verify fail, implement, verify pass.
- [ ] **7.4** — Commit: `feat(observability): director intent + grounding signal + palette coverage metrics`.
- [ ] **7.5** — Modify `director_loop._call_activity_llm` / `structural_director._call_structural_llm` to invoke `emit_director_intent` / `emit_structural_intent` after each successful emission.
- [ ] **7.6** — Extend existing Langfuse span metadata in `_call_activity_llm`:
  - `grounding_provenance_count: int`
  - `compositional_impingement_count: int`
  - `structural_active: bool` (true if a structural intent is currently in-flight)
  - `twitch_moves_in_prev_tick: int`
- [ ] **7.7** — Add Prometheus gauge update in `TwitchDirector` — bump `hapax_director_twitch_move_total` per emission.
- [ ] **7.8** — Create Grafana dashboard JSON: panels for grounding-signal distribution, palette-coverage time series, director latency histogram, parse-failure rate. Use existing Prometheus datasource config.
- [ ] **7.9** — Run tests + ruff + pyright.
- [ ] **7.10** — Commit: `feat(observability): Langfuse span metadata extensions + Grafana palette dashboard`.
- [ ] **7.11** — Restart compositor. Within 2 minutes, verify:
  - `~/hapax-state/stream-experiment/director-intent.jsonl` has entries.
  - Prometheus scrape endpoint returns new metrics.
  - Langfuse spans for `stream.reaction` contain new metadata keys.
  - Grafana dashboard renders palette-coverage panel (may show zero until recruitment runs).
- [ ] **7.12** — Mark Phase 7 ✓.

## Acceptance criteria

- Every narrative + structural intent logged to JSONL + Prometheus + Langfuse.
- Every twitch move counted in Prometheus.
- Palette-coverage ratio gauge updates per structural tick.
- Grafana dashboard renders at least one data point per metric.
- No measurable latency impact on director tick (&lt;50 ms overhead).

## Test strategy

- Unit: each emit function writes expected outputs.
- Integration: 30-s director run in a test harness produces expected Prometheus values.
- Grafana smoke: dashboard JSON imports without error.

## Rollback

`HAPAX_DIRECTOR_OBSERVABILITY=0` env disables emissions. No-op everywhere.

## Downstream integration

- `scripts/director-intent-replay.py` reads JSONL, can be invoked by RIFTS harness to replay a session offline.
- Bayesian-validation schedule `docs/research/bayesian-validation-schedule.md` Measure 5 (salience correlation) consumes `grounding_provenance`; no producer changes needed.
- Langfuse scores surfaced to MCMC BEST via existing tags: `stream-experiment`.
