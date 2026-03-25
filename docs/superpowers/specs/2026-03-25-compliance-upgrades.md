# Compliance Upgrades — Staleness Enforcement and Source Separation

**Status:** Implemented
**Date:** 2026-03-25
**Builds on:** Background Data Architecture (Phase 4), Cross-System Cascades (Phase 3)

---

## 1. Problem Statement

Three cognitive consumers — briefing, nudges, and content scheduler — accept data from upstream sources without checking whether that data is still fresh. The result: stale profile facts can appear on the ground surface hours after they were fetched, briefing sections can reference health snapshots from a prior session, and nudges can fire from scout reports that are weeks old without indicating their age.

The background data architecture specifies three fixes for Phase 4:

1. **briefing.py** — Per-source staleness tracking.
2. **nudges.py** — Fast/slow source separation.
3. **content_scheduler.py** — Absolute staleness veto.

This specification defines mechanical changes to each file. No new shared library components are introduced. No architectural refactoring. Each change is independently testable.

## 2. Three Fixes

### Fix 1: Briefing Per-Source Staleness Tracking

**Current behavior.** `generate_briefing()` calls 4 collection functions (`_collect_intention_practice_gaps`, `_collect_profile_health`, `_collect_deliberation_health`, `_collect_axiom_status`) and feeds their output to the briefing agent without recording when each source was read or how old the underlying data is. The briefing's `generated_at` timestamp reflects when synthesis completed, not when constituent data was fetched.

**Fix.** Add a `SourceFreshness` model and populate it during collection. Each collector returns its data age alongside its content. The briefing agent receives a freshness summary in its context, and the briefing output includes a `source_freshness` field so consumers can see which sections are backed by stale data.

```python
class SourceFreshness(BaseModel):
    source: str
    age_s: float | None = None  # seconds since source data was produced
    stale: bool = False  # True if age exceeds source-specific threshold

SOURCE_STALENESS_THRESHOLDS: dict[str, float] = {
    "profile_digest": 3600.0,      # 1h — digest updates on profiler run
    "health_snapshot": 300.0,       # 5min — health runs every 5min
    "deliberation_metrics": 1800.0, # 30min — metrics from recent queries
    "axiom_status": 3600.0,         # 1h — axiom state changes rarely
    "scout_report": 691200.0,       # 8d — scout runs weekly
    "drift_report": 691200.0,       # 8d — drift runs weekly
    "goals": 600.0,                 # 10min — goals change on operator action
}
```

**Integration.** In `generate_briefing()`, after each collector runs, record a `SourceFreshness` entry. Pass the list to the agent as a context section ("Source Freshness") so the LLM can note stale inputs. Add `source_freshness: list[SourceFreshness]` to the `Briefing` output model.

**No behavioral change.** The briefing still generates even with stale sources — this is observability, not a gate. The operator sees which sections relied on stale data and can act accordingly.

### Fix 2: Nudges Fast/Slow Source Separation

**Current behavior.** `collect_nudges()` calls 14 collectors sequentially. Some are fast (health, goals — read local files, < 10ms) and some are slow (scout, drift, knowledge sufficiency — read Qdrant or compute reports, 50-500ms). All run on every evaluation regardless of how recently their underlying data changed.

**Fix.** Split collectors into two tiers with different evaluation cadences. Fast collectors run every evaluation. Slow collectors cache their results and only re-evaluate when their source data's mtime changes.

```python
_FAST_COLLECTORS = [
    _collect_health_nudges,
    _collect_action_item_nudges,
    _collect_goal_nudges,
    _collect_readiness_nudges,
]

_SLOW_COLLECTORS = [
    _collect_briefing_nudges,
    _collect_scout_nudges,
    _collect_drift_nudges,
    _collect_profile_nudges,
    _collect_sufficiency_nudges,
    _collect_knowledge_sufficiency_nudges,
    _collect_precedent_nudges,
    _collect_rag_quality_nudges,
    _collect_emergence_nudges,
    _collect_contradiction_nudges,
]
```

**Cache mechanism.** Module-level `_slow_cache: list[Nudge]` and `_slow_cache_time: float`. Slow collectors re-evaluate when `time.monotonic() - _slow_cache_time > SLOW_CACHE_TTL` (300s = 5min). Fast collectors always run fresh.

**Staleness threshold centralization.** Move `STALE_BRIEFING_H`, `STALE_SCOUT_H`, `STALE_DRIFT_H` from module-level constants into a `STALENESS_THRESHOLDS` dict alongside the comment that they mirror sidebar.py values. No actual change to the values — just grouping for clarity.

### Fix 3: Content Scheduler Absolute Staleness Veto

**Current behavior.** `ContentPools` carries `list[str]` for facts, moments, nudge_titles. No timestamps. The scheduler's `_available_sources()` checks `if pools.facts` (non-empty) but cannot distinguish 1-second-old facts from 1-hour-old facts. `_score_source()` applies a soft `perception_age_s` penalty but never vetoes.

**Fix.** Add `pool_age_s: float = 0.0` to `ContentPools`. The aggregator sets this to `time.monotonic() - last_pool_refresh_time` when building pools. The scheduler's `_available_sources()` rejects pool-backed sources when `pools.pool_age_s > MAX_POOL_AGE_S`.

```python
class ContentPools(BaseModel):
    facts: list[str] = Field(default_factory=list)
    moments: list[str] = Field(default_factory=list)
    nudge_titles: list[str] = Field(default_factory=list)
    camera_roles: list[str] = Field(default_factory=list)
    camera_filters: list[str] = Field(default_factory=list)
    pool_age_s: float = 0.0  # seconds since pools were last refreshed

MAX_POOL_AGE_S = 120.0  # 2 minutes — refuse stale content pools
```

**Veto logic in `_available_sources()`:**

```python
# Absolute staleness veto: refuse content from stale pools
pool_stale = pools.pool_age_s > MAX_POOL_AGE_S
if pools.facts and not pool_stale:
    available.append(ContentSource.PROFILE_FACT)
if pools.camera_roles and not pool_stale:
    available.append(ContentSource.CAMERA_FEED)
# ... etc for pool-backed sources

# Non-pool sources (shader, time_of_day, activity_label, biometric) always available
```

**Aggregator integration.** In `visual_layer_aggregator.py`, track `_pool_refresh_time` and set `pools.pool_age_s = time.monotonic() - self._pool_refresh_time` when constructing `ContentPools`.

## 3. Files Changed

**Fix 1 (briefing staleness):**
- `agents/briefing.py` — Add `SourceFreshness` model, populate during collection, add to `Briefing` output, inject into agent context

**Fix 2 (nudges fast/slow):**
- `logos/data/nudges.py` — Split collectors into `_FAST_COLLECTORS` / `_SLOW_COLLECTORS`, add slow-tier cache with 5min TTL, group staleness thresholds

**Fix 3 (scheduler staleness veto):**
- `agents/content_scheduler.py` — Add `pool_age_s` to `ContentPools`, add `MAX_POOL_AGE_S`, veto stale sources in `_available_sources()`
- `agents/visual_layer_aggregator.py` — Track pool refresh time, set `pool_age_s` on `ContentPools`

**Tests:**
- `tests/test_compliance_upgrades.py` — Tests for all three fixes

## 4. Scope Exclusions

This specification does not:

- Extract shared library components (`ContextManager`, `PhenomenalContextRenderer`, `DataSource` protocol). These are longer-term architectural targets, not Phase 4 scope.
- Add dual-band context to briefing. The briefing runs on-demand, not continuously — dual-band is a poor fit for its invocation pattern.
- Change phenomenal context rendering. Progressive fidelity layers are a voice daemon concern.
- Modify any collector's actual logic. Staleness tracking is observational; the collectors still produce the same data.
- Add hard gates to briefing. Briefing sections with stale data are annotated, not suppressed.
