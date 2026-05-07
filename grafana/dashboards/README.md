# Grafana dashboards

Authoritative copies of Grafana dashboard JSON live in this directory. Grafana reads dashboards from `~/llm-stack/grafana/provisioning/dashboards/json/` (bind-mounted into the container at `/etc/grafana/provisioning/dashboards/json`); deployment is a symlink or copy from here to there.

## Dashboards

| File | UID | Purpose |
|---|---|---|
| `studio-cameras.json` | (per-file) | Phase 4 of the camera 24/7 resilience epic. Source: `agents/studio_compositor/metrics.py` on `127.0.0.1:9482`. |
| `lrr-per-condition.json` | `lrr-per-condition` | LRR Phase 10 §3.1 per-condition LLM call slicing. Every LLM call site publishes `hapax_llm_calls_total` / `hapax_llm_call_latency_seconds` / `hapax_llm_call_outcomes_total` tagged with the active research condition_id. |
| `lrr-stimmung.json` | `lrr-stimmung` | LRR Phase 10 affect + system-state dashboard. 11 stimmung dimensions + overall stance + freshness. Source: `/api/predictions/metrics` (logos, scraped at 30s). |
| `finding-x-grounding.json` | `finding-x-grounding` | FINDING-X grounding-provenance constitutional-invariant observability. Surfaces `hapax_director_ungrounded_total` (raw LLM empty rate, pre-synthesis) + `hapax_director_ungrounded_synth_total{intent_family}` (synth-fallback rate). Rising synth rate = LLM-compliance drift. Spec: `docs/superpowers/specs/2026-04-21-finding-x-grounding-synth-design.md` §5. |
| `compositor-surface-health.json` | `hapax-compositor-surface-health` | Antigrav delta gap #23 fill — covers metric clusters previously absent from any dashboard: HOMAGE package + cadence + emphasis + signature artefacts, face-obscure pipeline, follow-mode cuts, ward modulator tick health, layout switch dispatches, broadcast/degraded posture. Source: `agents/studio_compositor/metrics.py` on `127.0.0.1:9482`. |
| `affordance-pipeline.json` | `hapax-affordance-pipeline` | Affordance pipeline observability — recruitment events per 6-domain taxonomy, outcome split, dispatch rate, winner-similarity percentiles, candidate-pool size, JSONL write-failure stat. Source: `shared/affordance_pipeline.py` + telemetry. |
| `cpal-daimonion.json` | `hapax-cpal-daimonion` | CPAL cognitive tick health — tick rate, cold-start events, p50/p95/p99 wallclock duration, ticks-by-type distribution. Source: `agents/hapax_daimonion/cpal/runner.py`. |
| `reverie-pool.json` | `hapax-reverie-pool` | Reverie DynamicPipeline transient texture pool — reuse ratio, active textures, bucket count, acquires-vs-allocations, named-slot count, imagination loop fragments + shader rollbacks. Source: `agents/hapax_imagination` + Rust `pool_metrics()`. |
| `narration-triad.json` | `hapax-narration-triad` | Narration triad lifecycle — opened vs satisfied rate, status appends by terminal status, blocked / corrected / stale / orphan counts. Source: `shared/narration_triad.py`. |
| `programme-lifecycle.json` | `hapax-programme-lifecycle` | Programme manager lifecycle — active programme, dwell overshoot ratio, starts per role+show, soft-prior overrides (INVARIANT >0/stream), planned vs actual duration. Source: `shared/programme_observability.py`. |
| `compositor-health.json` | `hapax-compositor-health` | Studio compositor process & pipeline health — uptime, watchdog, cameras healthy/total, v4l2sink last-frame, pipeline-restart cadence, v4l2sink stalls/recoveries, RSS+VRAM, FD count, camera-rebuild cadence, per-source render p95, director intents + voice activity. Source: `agents/studio_compositor/metrics.py`. Complementary to `compositor-surface-health.json` (different metric scope). |
| `broadcast-publishing.json` | `hapax-broadcast-publishing` | Broadcast publishing & fanout surfaces — active broadcast elapsed, broadcast mode, master LUFS, cross-platform fanout (Mastodon/Bluesky/Discord/omg-weblog/Are.na), omg.lol family activity, publication-bus mints, rotation cadence + refusals, allowlist decisions. Source: `agents/publication_bus/` + `agents/broadcast/`. |
| `mood-engines.json` | `hapax-mood-engines` | Mood-engine observability — arousal, valence, and coherence posterior gauges plus contributed-signal counters per engine. Source: `agents/hapax_daimonion/mood_*_engine.py` + `shared/mood_engine_metrics.py`. |

## Install

One-time symlink (recommended — updates to the council repo propagate automatically):

```bash
mkdir -p ~/llm-stack/grafana/provisioning/dashboards/json
for f in ~/projects/hapax-council/grafana/dashboards/*.json; do
    ln -sf "$f" ~/llm-stack/grafana/provisioning/dashboards/json/$(basename "$f")
done
```

Then reload provisioning:

```bash
docker restart grafana
# or via the Grafana UI: Dashboards → Browse → Provisioning → Reload
```

## Dashboard-under-repo invariant

Dashboards committed to this directory are the authoritative copy. Never hand-edit the JSON under `~/llm-stack/` directly — that's the live bind-mount target. Edits should go through a council-repo PR so they survive rebuilds, migrations, and diff reviews.

## Cross-references

- `scripts/provision_dashboards.py` — programmatic dashboard generator for some of the older dashboards (reverie predictions, etc.). Newer dashboards are hand-authored JSON.
- `docs/research/2026-04-15-grafana-dashboards-catalog.md` — catalog of existing dashboards and their metric sources.
- `docs/superpowers/specs/2026-04-03-affordance-observability-design.md` — metric definitions for `hapax_stimmung_*` gauges.
- `agents/telemetry/condition_metrics.py` — Prometheus emitters for `hapax_llm_calls_total` / `hapax_llm_call_latency_seconds` / `hapax_llm_call_outcomes_total`.
- `agents/telemetry/llm_call_span.py` — canonical span helper that drives the per-condition emissions (call-site migration shipped in #961 director + #966 11-site per-agent sweep).
