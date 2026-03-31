# Apperception UI + Observability Surface — Design Spec

**Date**: 2026-03-31
**Sub-project**: 3 of 3 (Core Hardening → Event Source Completion → UI + Observability)
**Depends on**: Sub-project 1 (assessment field removal, API changes)
**Scope**: FlowPage detail panel, SystemStatus enrichment, API expansion, staleness alerts.

## Context

The apperception pipeline produces rich self-observation data (dimensions, observations, reflections, pending actions, coherence) but the frontend surfaces only scalar summaries. The FlowPage detail panel falls through to a raw JSON dump when clicking the apperception node. SystemStatus shows only coherence. No staleness alerts exist.

## A. API Expansion

### Current State

`/api/flow/state` returns an apperception node with:
```json
{
  "id": "apperception",
  "metrics": {
    "coherence": 0.73,
    "dimensions": {"temporal_prediction": {"confidence": 0.6, "affirming": 5, "problematizing": 2}},
    "observation_count": 12,
    "reflection_count": 3,
    "pending_action_count": 1
  }
}
```

Counts only — no actual text content. Observations, reflections, and pending actions are hidden.

### Changes to `logos/api/routes/flow.py`

Add full text content to the apperception node metrics (token-bounded for frontend rendering):

```python
"metrics": {
    "coherence": model.get("coherence", 0.0),
    "dimensions": {
        name: {
            "confidence": dim.get("confidence", 0.0),
            "affirming": dim.get("affirming_count", 0),
            "problematizing": dim.get("problematizing_count", 0),
        }
        for name, dim in model.get("dimensions", {}).items()
        if isinstance(dim, dict)
    },
    "observation_count": len(model.get("recent_observations", [])),
    "reflection_count": len(model.get("recent_reflections", [])),
    "pending_action_count": len((apperception or {}).get("pending_actions", [])),
    # NEW: text content (bounded)
    "recent_observations": model.get("recent_observations", [])[-5:],
    "recent_reflections": model.get("recent_reflections", [])[-3:],
    "pending_actions": (apperception or {}).get("pending_actions", [])[:3],
    # NEW: liveness fields (from sub-project 1)
    "tick_seq": (apperception or {}).get("tick_seq", 0),
    "events_this_tick": (apperception or {}).get("events_this_tick", 0),
}
```

### Changes to `hapax-logos/src-tauri/src/commands/system_flow.rs`

Mirror the Python API — add `recent_observations`, `recent_reflections`, `pending_actions`, `tick_seq`, `events_this_tick` to the Rust apperception node construction. Extract arrays with serde_json, truncate to same bounds (5, 3, 3).

## B. FlowPage Detail Panel

### Current State

`FlowPage.tsx` detail panel (lines 286-311) has explicit cases for `stimmung`, `engine`, `voice`. Apperception falls through to `default: return <pre>{JSON.stringify(m, null, 2)}</pre>`.

### Design

Add an `apperception` case to the detail panel switch:

```tsx
case "apperception": {
  const dims = (m.dimensions as Record<string, {
    confidence: number; affirming: number; problematizing: number;
  }>) || {};
  const obs = (m.recent_observations as string[]) || [];
  const refs = (m.recent_reflections as string[]) || [];
  const actions = (m.pending_actions as string[]) || [];
  const coh = (m.coherence as number) ?? 0;
  const tickSeq = (m.tick_seq as number) ?? 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {/* Coherence header with floor warning */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <ArcGauge value={coh} color={sevColor(1 - coh, p)} size={32} />
        <span style={{ color: p.text, fontSize: 13 }}>
          Coherence {coh.toFixed(2)}
        </span>
        {coh <= 0.2 && (
          <span style={{ color: p["red-400"], fontSize: 11 }}>
            floor guard active
          </span>
        )}
      </div>

      {/* Dimensions table */}
      {Object.keys(dims).length > 0 && (
        <div>
          <div style={{ color: p["text-muted"], fontSize: 10, marginBottom: 4 }}>
            Self-dimensions
          </div>
          {Object.entries(dims).map(([name, d]) => (
            <div key={name} style={{
              display: "flex", alignItems: "center", gap: 6,
              marginBottom: 2, fontSize: 11,
            }}>
              <span style={{ color: p["text-muted"], width: 120 }}>{name}</span>
              <HBar value={d.confidence} color={sevColor(1 - d.confidence, p)}
                    width={60} height={4} />
              <span style={{ color: p["green-400"], fontSize: 10 }}>
                +{d.affirming}
              </span>
              <span style={{ color: p["red-400"], fontSize: 10 }}>
                -{d.problematizing}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Recent observations */}
      {obs.length > 0 && (
        <div>
          <div style={{ color: p["text-muted"], fontSize: 10, marginBottom: 2 }}>
            Recent observations
          </div>
          {obs.map((o, i) => (
            <div key={i} style={{ color: p.text, fontSize: 10, marginBottom: 1 }}>
              {o}
            </div>
          ))}
        </div>
      )}

      {/* Reflections */}
      {refs.length > 0 && (
        <div>
          <div style={{ color: p["text-muted"], fontSize: 10, marginBottom: 2 }}>
            Reflections
          </div>
          {refs.map((r, i) => (
            <div key={i} style={{ color: p["yellow-400"], fontSize: 10,
                                  fontStyle: "italic", marginBottom: 1 }}>
              {r}
            </div>
          ))}
        </div>
      )}

      {/* Pending actions */}
      {actions.length > 0 && (
        <div>
          <div style={{ color: p["text-muted"], fontSize: 10, marginBottom: 2 }}>
            Pending actions
          </div>
          {actions.map((a, i) => (
            <div key={i} style={{ color: p["orange-400"], fontSize: 10, marginBottom: 1 }}>
              {a}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

Color choices follow the design language severity ladder and semantic palette:
- Observations: default text color (neutral information)
- Reflections: yellow-400 + italic (meta-cognition, warning-adjacent)
- Pending actions: orange-400 (actionable, urgent-adjacent)
- Floor guard: red-400 (system protection active)

## C. SystemStatus Enrichment

### Current State

SystemStatus.tsx shows only `coherence.toFixed(2)` for apperception. No staleness, no dimension summary.

### Design

Add a minimal enrichment — keep SystemStatus compact (it's a dashboard summary, not a detail view):

```tsx
// Existing: coherence row
// Add: dimension count + observation count
const apperception = state.nodes.find(n => n.id === "apperception");
const coh = (apperception?.metrics?.coherence as number) ?? 0;
const dimCount = Object.keys((apperception?.metrics?.dimensions as object) || {}).length;
const obsCount = (apperception?.metrics?.observation_count as number) ?? 0;
const ageS = apperception?.age_s ?? 999;

// Render
<Row label="coherence" value={coh.toFixed(2)} warn={coh < 0.4} />
<Row label="self-dims" value={dimCount} />
{ageS > 30 && <Row label="apperception" value="stale" warn />}
```

The staleness row appears ONLY when age > 30s. Otherwise invisible — no noise in the dashboard.

## D. Staleness Alerts

### Node Status Color

The flow.py `_status()` function already maps age to `active`/`stale`/`offline`. The FlowPage already colors nodes by status using the severity ladder. No change needed for the node card.

### Detail Panel Staleness

Add age display to the detail panel header (all nodes, not just apperception):

```tsx
// In DetailPanel, before the switch
<div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
  <span style={{ color: p.text, fontSize: 13, fontWeight: 600 }}>
    {node.label}
  </span>
  <span style={{
    color: node.status === "active" ? p["green-400"]
         : node.status === "stale" ? p["yellow-400"]
         : p["red-400"],
    fontSize: 10,
  }}>
    {node.age_s < 10 ? "live" : `${Math.round(node.age_s)}s ago`}
  </span>
</div>
```

## File Change Summary

| File | Action |
|------|--------|
| `logos/api/routes/flow.py` | Add text content fields to apperception metrics |
| `hapax-logos/src-tauri/src/commands/system_flow.rs` | Mirror API expansion in Rust |
| `hapax-logos/src/pages/FlowPage.tsx` | Add apperception detail panel case; add staleness header |
| `hapax-logos/src/components/dashboard/SystemStatus.tsx` | Add dimension count, staleness row |

## Testing

Frontend changes are visual — verify via `pnpm tauri dev`:
1. Click apperception node → formatted detail panel (not JSON)
2. Coherence at floor → "floor guard active" label visible
3. Dimensions render with confidence bars and +/- counts
4. Observations and reflections appear when present
5. SystemStatus shows dimension count
6. Stale apperception (>30s) shows "stale" row in SystemStatus
7. Detail panel shows age for all nodes

## Out of Scope

- Historical coherence sparklines (would require timeseries storage)
- Rumination gate visibility (would require exposing cascade internal state)
- Dimension trend charts (would require historical data — could use Qdrant store from sub-project 1 in future)
