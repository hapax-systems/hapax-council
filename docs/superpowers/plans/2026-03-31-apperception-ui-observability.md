# Apperception UI + Observability Surface — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface apperception pipeline internals (dimensions, observations, reflections, pending actions, coherence floor, liveness) in the FlowPage detail panel and SystemStatus dashboard. Expand the flow API and Rust mirror to deliver text content alongside counts.

**Architecture:** Data flows from `/dev/shm/hapax-apperception/self-band.json` through two parallel paths: Python `flow.py` (FastAPI, primary) and Rust `system_flow.rs` (Tauri fallback). Both feed the same React components. FlowPage detail panel gets a dedicated `apperception` case (replacing the JSON fallback). SystemStatus gets dimension count and staleness. All nodes get a staleness header in the detail panel.

**Tech Stack:** Python 3.12 (FastAPI), Rust (Tauri 2, serde_json), React 18 + TypeScript, inline styles following design language palette.

**Spec:** `docs/superpowers/specs/2026-03-31-apperception-ui-observability-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `logos/api/routes/flow.py` | Modify | Add text content + liveness fields to apperception metrics |
| `hapax-logos/src-tauri/src/commands/system_flow.rs` | Modify | Mirror API expansion in Rust |
| `hapax-logos/src/pages/FlowPage.tsx` | Modify | Add apperception detail panel case; add staleness header to all nodes |
| `hapax-logos/src/components/dashboard/SystemStatus.tsx` | Modify | Add dimension count row, staleness row |

---

### Task 1: Expand Flow API — Apperception Metrics

**Files:**
- Modify: `logos/api/routes/flow.py:317-344` (legacy apperception node)

- [ ] **Step 1: Add text content and liveness fields to apperception metrics**

In `logos/api/routes/flow.py`, replace the apperception node construction (lines 328-344) to add `recent_observations`, `recent_reflections`, `pending_actions`, `tick_seq`, and `events_this_tick`:

```python
    nodes.append(
        {
            "id": "apperception",
            "label": "Apperception",
            "status": _status(apper_age),
            "age_s": round(apper_age, 1),
            "metrics": {
                "coherence": model.get("coherence", 0.0),
                "dimensions": apper_dims,
                "observation_count": len(model.get("recent_observations", [])),
                "reflection_count": len(model.get("recent_reflections", [])),
                "pending_action_count": len((apperception or {}).get("pending_actions", [])),
                # Text content (bounded for frontend rendering)
                "recent_observations": model.get("recent_observations", [])[-5:],
                "recent_reflections": model.get("recent_reflections", [])[-3:],
                "pending_actions": (apperception or {}).get("pending_actions", [])[:3],
                # Liveness fields (from sub-project 1)
                "tick_seq": (apperception or {}).get("tick_seq", 0),
                "events_this_tick": (apperception or {}).get("events_this_tick", 0),
            }
            if apperception
            else {},
        }
    )
```

- [ ] **Step 2: Verify API response**

```fish
cd hapax-council
uv run python -c "
import json, urllib.request
r = urllib.request.urlopen('http://localhost:8051/api/flow/state')
data = json.loads(r.read())
apper = next((n for n in data['nodes'] if n['id'] == 'apperception'), None)
if apper:
    m = apper['metrics']
    print('coherence:', m.get('coherence'))
    print('observations:', len(m.get('recent_observations', [])))
    print('reflections:', len(m.get('recent_reflections', [])))
    print('pending_actions:', len(m.get('pending_actions', [])))
    print('tick_seq:', m.get('tick_seq'))
    print('events_this_tick:', m.get('events_this_tick'))
    print('dimensions:', list(m.get('dimensions', {}).keys()))
else:
    print('apperception node not found')
"
```

- [ ] **Step 3: Commit**

```fish
cd hapax-council
git add logos/api/routes/flow.py
git commit -m "feat(flow): add text content and liveness fields to apperception metrics

Expand apperception node in /api/flow/state to include recent_observations
(last 5), recent_reflections (last 3), pending_actions (first 3), tick_seq,
and events_this_tick. Frontend can now render full apperception internals
instead of falling through to raw JSON."
```

---

### Task 2: Mirror API Expansion in Rust

**Files:**
- Modify: `hapax-logos/src-tauri/src/commands/system_flow.rs:182-212` (apperception node)

- [ ] **Step 1: Add text content arrays and liveness fields**

In `system_flow.rs`, replace the apperception metrics block (lines 200-211). After the existing `apper_dims` construction, add extraction of text arrays and liveness fields, then include them in the metrics JSON:

```rust
    // ── Apperception ────────────────────────────────────────────
    let apperception = read_json("/dev/shm/hapax-apperception/self-band.json");
    let apper_age = apperception.as_ref().map(age_s).unwrap_or(999.0);
    let model = apperception.as_ref().and_then(|a| a.get("self_model")).cloned().unwrap_or(serde_json::json!({}));
    let raw_dims = model.get("dimensions").cloned().unwrap_or(serde_json::json!({}));
    let mut apper_dims = serde_json::Map::new();
    if let Some(obj) = raw_dims.as_object() {
        for (name, dim) in obj {
            if let Some(d) = dim.as_object() {
                apper_dims.insert(name.clone(), serde_json::json!({
                    "confidence": d.get("confidence").and_then(|v| v.as_f64()).unwrap_or(0.0),
                    "assessment": d.get("current_assessment").and_then(|v| v.as_str()).unwrap_or("").chars().take(60).collect::<String>(),
                    "affirming": d.get("affirming_count").and_then(|v| v.as_u64()).unwrap_or(0),
                    "problematizing": d.get("problematizing_count").and_then(|v| v.as_u64()).unwrap_or(0),
                }));
            }
        }
    }

    // Extract text content arrays (bounded)
    let recent_obs: Vec<serde_json::Value> = model.get("recent_observations")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().rev().take(5).rev().cloned().collect())
        .unwrap_or_default();
    let recent_refs: Vec<serde_json::Value> = model.get("recent_reflections")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().rev().take(3).rev().cloned().collect())
        .unwrap_or_default();
    let pending_actions: Vec<serde_json::Value> = apperception.as_ref()
        .and_then(|a| a.get("pending_actions"))
        .and_then(|v| v.as_array())
        .map(|a| a.iter().take(3).cloned().collect())
        .unwrap_or_default();
    let tick_seq = apperception.as_ref()
        .and_then(|a| a.get("tick_seq"))
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    let events_this_tick = apperception.as_ref()
        .and_then(|a| a.get("events_this_tick"))
        .and_then(|v| v.as_u64())
        .unwrap_or(0);

    nodes.push(NodeState {
        id: "apperception".into(),
        label: "Apperception".into(),
        status: status_str(apper_age, 10.0).into(),
        age_s: apper_age,
        metrics: if apperception.is_some() { serde_json::json!({
            "coherence": model.get("coherence").and_then(|v| v.as_f64()).unwrap_or(0.0),
            "dimensions": serde_json::Value::Object(apper_dims),
            "observation_count": recent_obs.len(),
            "reflection_count": recent_refs.len(),
            "pending_action_count": pending_actions.len(),
            "recent_observations": recent_obs,
            "recent_reflections": recent_refs,
            "pending_actions": pending_actions,
            "tick_seq": tick_seq,
            "events_this_tick": events_this_tick,
        }) } else { serde_json::json!({}) },
    });
```

- [ ] **Step 2: Verify Rust builds**

```fish
cd hapax-council/hapax-logos
pnpm tauri build --debug 2>&1 | tail -5
```

If only checking compilation without full build:

```fish
cd hapax-council/hapax-logos/src-tauri
cargo check 2>&1 | tail -10
```

- [ ] **Step 3: Commit**

```fish
cd hapax-council
git add hapax-logos/src-tauri/src/commands/system_flow.rs
git commit -m "feat(tauri): mirror apperception text content + liveness in Rust flow command

Add recent_observations (last 5), recent_reflections (last 3),
pending_actions (first 3), tick_seq, events_this_tick to the Rust
get_system_flow apperception node. Matches Python API expansion."
```

---

### Task 3: Add Apperception Detail Panel to FlowPage

**Files:**
- Modify: `hapax-logos/src/pages/FlowPage.tsx:290-303` (DetailPanel switch)

- [ ] **Step 1: Add `apperception` case to the detail panel switch**

In `FlowPage.tsx`, insert a new case before the `default` case in the `detail()` switch (line 302). The new case renders dimensions table, observations, reflections, actions, and coherence floor warning:

```tsx
    case "apperception": {
      const dims = (m.dimensions as Record<string, {
        confidence: number; affirming: number; problematizing: number;
      }>) || {};
      const obs = (m.recent_observations as string[]) || [];
      const refs = (m.recent_reflections as string[]) || [];
      const actions = (m.pending_actions as string[]) || [];
      const coh = (m.coherence as number) ?? 0;

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

The switch location: insert this case between the existing `case "voice":` block (ends at line 301) and `default:` (line 302). The exact edit target is:

```tsx
// BEFORE (line 302):
    default: return <pre style={{ background: ...

// AFTER:
    case "apperception": { /* ... full block above ... */ }
    default: return <pre style={{ background: ...
```

- [ ] **Step 2: Commit**

```fish
cd hapax-council
git add hapax-logos/src/pages/FlowPage.tsx
git commit -m "feat(flow-ui): add apperception detail panel with dimensions, observations, reflections

Replace raw JSON fallback for apperception node with structured panel
showing coherence gauge + floor guard, dimension confidence bars with
affirming/problematizing counts, recent observations, reflections
(yellow italic), and pending actions (orange)."
```

---

### Task 4: Add Staleness Header to Detail Panel (All Nodes)

**Files:**
- Modify: `hapax-logos/src/pages/FlowPage.tsx:305-311` (DetailPanel render)

- [ ] **Step 1: Add age/staleness display to detail panel header**

In `FlowPage.tsx`, modify the DetailPanel's header section (line 307-308). Replace the existing header div with one that includes a staleness indicator on the right side:

```tsx
// BEFORE (line 307):
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}><h3 style={{ color: p["text-emphasis"], margin: 0, fontSize: 14 }}>{node.label}</h3><button onClick={onClose} style={{ background: "none", border: "none", color: p["text-muted"], cursor: "pointer", fontSize: 16 }}>x</button></div>
      <div style={{ color: p["text-secondary"], fontSize: 11, marginBottom: 8 }}><span style={{ color: colors.border }}>*</span> {node.status} — {node.age_s.toFixed(1)}s ago</div>

// AFTER:
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
        <h3 style={{ color: p["text-emphasis"], margin: 0, fontSize: 14 }}>{node.label}</h3>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{
            color: node.status === "active" ? p["green-400"]
                 : node.status === "stale" ? p["yellow-400"]
                 : p["red-400"],
            fontSize: 10,
          }}>
            {node.age_s < 10 ? "live" : `${Math.round(node.age_s)}s ago`}
          </span>
          <button onClick={onClose} style={{ background: "none", border: "none", color: p["text-muted"], cursor: "pointer", fontSize: 16 }}>x</button>
        </div>
      </div>
      <div style={{ color: p["text-secondary"], fontSize: 11, marginBottom: 8 }}><span style={{ color: colors.border }}>*</span> {node.status}</div>
```

Key changes:
- Move the close button into a flex container with the staleness indicator
- Staleness text is color-coded: green for active, yellow for stale, red for offline
- Shows "live" for age <10s, otherwise shows seconds
- Remove age from the status line (now shown in header) — keep status text only

- [ ] **Step 2: Commit**

```fish
cd hapax-council
git add hapax-logos/src/pages/FlowPage.tsx
git commit -m "feat(flow-ui): add color-coded staleness indicator to detail panel header

All nodes now show live/Ns age in the detail panel header, color-coded
by status (green=active, yellow=stale, red=offline). Replaces the
inline age text in the status line."
```

---

### Task 5: Enrich SystemStatus Dashboard

**Files:**
- Modify: `hapax-logos/src/components/dashboard/SystemStatus.tsx:67-78` (metrics extraction), `124-147` (render)

- [ ] **Step 1: Extract dimension count and staleness from apperception node**

In `SystemStatus.tsx`, after the existing metric extraction block (around line 78, after `const voiceTier`), add:

```tsx
  const dimCount = Object.keys((apperception?.metrics?.dimensions as object) || {}).length;
  const ageS = apperception?.age_s ?? 999;
```

- [ ] **Step 2: Add dimension count and staleness rows to the metrics grid**

In `SystemStatus.tsx`, after the coherence row (line 139-140) and before the voice row (line 141), add:

```tsx
        <div className="flex justify-between">
          <span className="text-zinc-600">self-dims</span>
          <span className="text-zinc-400">{dimCount}</span>
        </div>
        {ageS > 30 && (
          <div className="flex justify-between col-span-2">
            <span className="text-zinc-600">apperception</span>
            <span className="text-amber-400">stale</span>
          </div>
        )}
```

The full metrics grid section after the edit should look like:

```tsx
      {/* Key metrics */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[10px]">
        <div className="flex justify-between">
          <span className="text-zinc-600">activity</span>
          <span className="text-zinc-400">{activity}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-600">flow</span>
          <span className="text-zinc-400">{(flowScore * 100).toFixed(0)}%</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-600">presence</span>
          <span className="text-zinc-400">{(presence * 100).toFixed(0)}%</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-600">coherence</span>
          <span className="text-zinc-400">{coherence.toFixed(2)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-600">self-dims</span>
          <span className="text-zinc-400">{dimCount}</span>
        </div>
        {ageS > 30 && (
          <div className="flex justify-between col-span-2">
            <span className="text-zinc-600">apperception</span>
            <span className="text-amber-400">stale</span>
          </div>
        )}
        {voiceActive && (
          <div className="flex justify-between col-span-2">
            <span className="text-zinc-600">voice</span>
            <span className="text-emerald-400">{voiceTier || "active"}</span>
          </div>
        )}
      </div>
```

- [ ] **Step 3: Commit**

```fish
cd hapax-council
git add hapax-logos/src/components/dashboard/SystemStatus.tsx
git commit -m "feat(dashboard): add self-dimension count and apperception staleness to SystemStatus

Show number of active self-dimensions in the metrics grid. When
apperception age exceeds 30s, show a col-span-2 'stale' warning row
in amber. Keeps the dashboard compact — staleness row only appears
when relevant."
```

---

### Task 6: Visual Verification + PR

- [ ] **Step 1: Start dev server**

```fish
cd hapax-council
pnpm tauri dev
```

- [ ] **Step 2: Verify FlowPage apperception detail panel**

Click the apperception node in the FlowPage. Verify:
1. Detail panel shows coherence gauge (not raw JSON)
2. Self-dimensions render with confidence HBars and +/- counts
3. Recent observations appear as plain text lines
4. Reflections appear in yellow italic
5. Pending actions appear in orange
6. If coherence is at floor (<=0.2), "floor guard active" label shows in red

- [ ] **Step 3: Verify staleness header (all nodes)**

Click any node in the FlowPage. Verify:
1. Header shows "live" (green) for active nodes with age <10s
2. Header shows "Ns ago" (yellow/red) for stale/offline nodes
3. Close button still works

- [ ] **Step 4: Verify SystemStatus enrichment**

Open the dashboard. Verify:
1. "self-dims" row shows dimension count (e.g., "3")
2. "coherence" row still shows the value
3. If apperception is stale (>30s), "apperception: stale" row appears in amber
4. If apperception is fresh, no staleness row (no noise)

- [ ] **Step 5: Lint and type-check**

```fish
cd hapax-council
uv run ruff check logos/api/routes/flow.py
cd hapax-logos
pnpm tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 6: Create PR**

```fish
cd hapax-council
git push -u origin HEAD
gh pr create \
  --title "feat: apperception UI observability surface" \
  --body "## Summary
- Expand flow API (Python + Rust) to include apperception text content (observations, reflections, actions) and liveness fields (tick_seq, events_this_tick)
- Add dedicated apperception detail panel to FlowPage with coherence gauge, dimension table, text content sections, and floor guard warning
- Add color-coded staleness header to all detail panel nodes
- Enrich SystemStatus with self-dimension count and conditional staleness alert

## Spec
docs/superpowers/specs/2026-03-31-apperception-ui-observability-design.md

## Test plan
- [ ] Click apperception node → structured panel (not JSON dump)
- [ ] Coherence floor (<=0.2) → red 'floor guard active' label
- [ ] Dimensions render with confidence bars and +/- counts
- [ ] Observations, reflections, actions appear when present
- [ ] Click any node → staleness header shows live/age
- [ ] SystemStatus shows self-dims count
- [ ] Stale apperception (>30s) → amber 'stale' row in dashboard
- [ ] Rust cargo check passes
- [ ] TypeScript type-check passes
- [ ] Ruff check passes"
```
