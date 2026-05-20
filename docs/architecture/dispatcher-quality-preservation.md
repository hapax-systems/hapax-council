# Dispatcher Architecture: Quality-Preserving Subscription Routing

**Authority:** CASE-CAPACITY-ROUTING-001
**Date:** 2026-05-20
**Status:** Design specification

## 1. Overview

The methodology-aware headless dispatcher routes tasks to platform lanes
(Claude, Codex, Gemini, Vibe, Antigravity) while preserving quality
guarantees. It reads fresh quota state, enforces quality floors, prevents
silent downgrades, and emits observable route decisions.

## 2. Enforcement Points

### 2.1 Pre-Dispatch Gate

Before any task reaches a lane:

1. **Quality floor check** — task's `quality_floor` compared against lane capability profile
2. **Authority level match** — `frontier_review_required` tasks cannot route to JR+ lanes
3. **Mutation surface gate** — governance/audio/live-egress surfaces blocked from non-frontier lanes
4. **Dependency check** — unmet `depends_on` blocks dispatch regardless of lane availability

### 2.2 Route Selection

The dispatcher evaluates candidates in priority order:

1. Read fresh supply vectors from `config/platform-capability-registry.json`
2. Filter lanes by eligibility (quality floor, authority level, platform suitability)
3. Score remaining candidates by: task WSJF, lane freshness, quota headroom, spend posture
4. Select highest-scoring eligible lane
5. If no eligible lane exists: hold task, emit `route_decision.held` event

### 2.3 Post-Dispatch Validation

After route selection, before task delivery:

1. **Quota freshness probe** — verify the selected lane's quota is not stale (>5min)
2. **Concurrent load check** — lane is not at capacity (active task count < max)
3. **Degraded mode check** — if platform reports degraded, downgrade ceiling to `dry_run_only`

## 3. Fresh Metadata Mechanisms

### 3.1 Platform Capability Registry

Source: `config/platform-capability-registry.json`

Provides per-route supply vectors (context window, tool access, model tier).
Read at dispatch time, not cached across decisions.

### 3.2 Quota Spend Ledger

Source: `shared/quota_spend_ledger.py`

Tracks cumulative spend per platform per billing period. The dispatcher reads
the ledger to compute remaining headroom before routing high-cost tasks.

### 3.3 Route Decision Receipts

Source: `shared/platform_capability_receipts.py`

Each dispatch writes an append-only receipt recording: task_id, selected_route,
rejected_routes (with reasons), quota_state_at_decision, timestamp.

## 4. Silent Downgrade Prevention

### 4.1 Rule: No Quality Floor Violation

A task with `quality_floor: frontier_review_required` MUST NOT route to a lane
whose capability profile is below frontier. Violation is a hard error, not a
degraded-mode fallback.

### 4.2 Rule: No Authority Bypass

Tasks with `authority_level: support_non_authoritative` require independent
review. The dispatcher records this obligation in the route receipt; downstream
merge gates enforce it.

### 4.3 Rule: Governance Surface Protection

Files in `axioms/`, `shared/governance/`, `agents/hapax_daimonion/`,
`config/pipewire/`, `CODEOWNERS`, and `CLAUDE.md` are off-limits for JR+ and
burst-mode lanes. The dispatcher reads `mutation_scope_refs` and rejects routes
that would violate these boundaries.

### 4.4 Rule: Explicit Degradation

When a preferred lane is unavailable, the dispatcher MUST:
- Emit a `route_decision.degraded` event with the original and fallback lanes
- Record the quality delta in the receipt
- Never silently substitute a lower-tier lane without an observable record

## 5. Observability Requirements

### 5.1 Route Decision Events

Every dispatch emits a structured event:

```yaml
event_type: route_decision
task_id: <task_id>
selected_route: <route_id>
selected_platform: <platform>
quality_floor: <task quality floor>
lane_capability: <lane profile tier>
quota_headroom_pct: <remaining %>
rejected_routes:
  - route_id: <route>
    reason: <quality_floor_violation|quota_exhausted|capacity_full|...>
spend_posture: <normal|cautious|exhausted>
decision_latency_ms: <ms>
```

### 5.2 Spend Posture Dashboard

The dispatcher exposes current spend posture per platform:
- **normal** — >50% quota remaining
- **cautious** — 20-50% remaining, prefer lower-cost routes
- **exhausted** — <20% remaining, hold non-urgent tasks

### 5.3 Alerting

- `route_decision.held` events with count >5 in 1h trigger ntfy alert
- `route_decision.degraded` events trigger ntfy alert per occurrence
- Quota exhaustion triggers ntfy alert when crossing 20% threshold

## 6. Implementation Status

| Component | Status | Location |
|-----------|--------|----------|
| Dispatcher policy evaluator | Implemented | `shared/dispatcher_policy.py` |
| Platform capability registry | Implemented | `config/platform-capability-registry.json` |
| Quota spend ledger | Implemented | `shared/quota_spend_ledger.py` |
| Route decision receipts | Implemented | `shared/platform_capability_receipts.py` |
| Quality floor enforcement | Implemented | `shared/dispatcher_policy.py` |
| Governance surface protection | Implemented | hooks + dispatcher policy |
| Observable route events | Partial | Receipts exist, structured events pending |
| Spend posture dashboard | Not started | Design in this document |
| ntfy alerting for held/degraded | Not started | Design in this document |
