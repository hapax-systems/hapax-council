# Quota/Resource Observability Model and Freshness Gate Design

**Authority:** CASE-CAPACITY-ROUTING-001
**Date:** 2026-05-20
**Status:** Design specification
**Cross-ref:** `docs/architecture/dispatcher-quality-preservation.md`

## 1. Quota/Resource State Model

Each observable quota state record carries:

| Field | Type | Description |
|-------|------|-------------|
| platform | string | claude, codex, gemini, vibe, antigravity |
| profile | string | Route profile (e.g., claude.headless.opus) |
| quota_class | enum | token_budget, request_rate, concurrent_slots, spend_budget |
| last_observed_value | decimal | Current value (remaining tokens, requests/min, etc.) |
| observation_timestamp | ISO 8601 | When the value was last read |
| ttl_seconds | int | Maximum age before the observation is stale |
| confidence | enum | confirmed, estimated, degraded, unknown |
| source | string | API probe, billing dashboard, inference from error codes |

### State Sources

| Platform | Source | Signal | Refresh Cadence |
|----------|--------|--------|-----------------|
| Claude | API response headers | `anthropic-ratelimit-*` | Per-request |
| Claude | Billing API | Monthly spend vs. limit | 1h |
| Codex | CLI exit code + stderr | Rate limit / quota errors | Per-dispatch |
| Gemini | API response headers | `x-ratelimit-*` | Per-request |
| Vibe | Process exit code | Mistral rate limit signals | Per-dispatch |
| TabbyAPI | Local `/v1/model` probe | Model loaded, VRAM available | 30s |

## 2. Freshness Gate

Every dispatch decision consults the freshness gate before proceeding.

### Three Gate Outcomes

| Outcome | Condition | Action |
|---------|-----------|--------|
| **Proceed** | All required quota states are within TTL and above floor | Dispatch normally |
| **Hold-and-refresh** | At least one quota state is stale (age > TTL) but not blocked | Trigger a probe, queue the task, retry after probe returns (max 30s) |
| **Block-with-reason** | Quota exhausted, platform degraded, or probe failed after retry | Record blocked reason, surface to operator, do not dispatch |

### TTL Defaults

| Quota Class | TTL | Rationale |
|-------------|-----|-----------|
| token_budget | 300s | API headers refresh per-request; 5min staleness is safe |
| request_rate | 60s | Rate limits can change rapidly |
| concurrent_slots | 30s | Slot count changes with every task start/finish |
| spend_budget | 3600s | Billing data is inherently delayed |

## 3. Degraded-Mode Policy

When the highest-quality eligible route is temporarily unavailable:

### Option Priority (in order)

1. **Queue and wait** (default for `quality_floor: frontier_review_required`) — task holds until the preferred route recovers. Maximum hold time: 30 minutes.
2. **Fallback with review containment** (for `quality_floor: deterministic_ok`) — route to the next eligible lane, but mark the route decision as `degraded` and require post-completion review before merge.
3. **Surface to operator** (after hold timeout or when all eligible routes are blocked) — emit ntfy alert with task ID, blocked reasons, and estimated recovery time.

### Explicit prohibition

A `quality_floor: frontier_review_required` task MUST NEVER silently downgrade to a non-frontier lane. The dispatcher records every degraded-mode decision in the route receipt with `degradation_type`, `original_route`, `fallback_route`, and `review_obligation`.

## 4. Rate-Limit Headroom Estimation

Headroom is estimated from observable signals:

```
headroom_pct = (remaining / limit) * 100
```

Where `remaining` and `limit` come from:
- **Claude:** `anthropic-ratelimit-tokens-remaining` / `anthropic-ratelimit-tokens-limit`
- **Gemini:** `x-ratelimit-remaining` / `x-ratelimit-limit`
- **Codex/Vibe:** Estimated from recent error rate (3 consecutive rate limits = 0% headroom)

### Headroom Thresholds

| Headroom | Spend Posture | Behavior |
|----------|---------------|----------|
| >50% | normal | All eligible tasks dispatch |
| 20-50% | cautious | Prefer lower-cost routes; hold WSJF < 3 tasks |
| <20% | exhausted | Hold all non-P0 tasks; surface to operator |

## 5. Budget Authority Check

Before dispatching a task that incurs paid API spend:

1. Read current `spend_budget` quota state for the target platform
2. Estimate task cost from historical per-token cost and expected token count
3. If `estimated_cost > remaining_budget * 0.1` (>10% of remaining budget in one task): require explicit operator approval via ntfy prompt
4. Record the budget check result in the route receipt

## 6. Consumer Integration

### Existing Scripts

| Script | Integration Point |
|--------|-------------------|
| `hapax-methodology-dispatch` | Reads freshness gate before selecting lane |
| `hapax-cross-runtime-dispatch` | Reads freshness gate + headroom before cross-platform routing |
| `shared/dispatcher_policy.py` | `evaluate()` calls freshness gate as pre-check |

### Consumption Pattern

```python
from shared.quota_observability import FreshnessGate, QuotaStateStore

store = QuotaStateStore()
gate = FreshnessGate(store)

result = gate.check(platform="claude", profile="claude.headless.opus")
if result.outcome == "proceed":
    dispatch(task, route)
elif result.outcome == "hold_and_refresh":
    store.refresh(platform="claude")
    # retry after refresh
elif result.outcome == "block_with_reason":
    hold_task(task, reason=result.blocked_reason)
```
