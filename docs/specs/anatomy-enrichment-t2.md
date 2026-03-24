# System Anatomy Enrichment — Tier 2

Dense instrument clusters, typed detail panels, expanded backend data.

**Status:** Design
**Branch:** `feat/anatomy-enrichment-t2`
**Depends on:** Tier 1 enrichments (PR #171, merged), design language (PR #282, merged)
**Touches:** `logos/api/routes/flow.py`, `hapax-logos/src-tauri/src/commands/system_flow.rs`, `hapax-logos/src/pages/FlowPage.tsx`

---

## 1. Problem

The system anatomy view (FlowPage) shows ~15% of available data. Nine nodes display 2-5 scalar key-value pairs each. The detail panel dumps raw JSON. The backend filters out rich structures (stimmung dimensions, temporal phases, apperception self-model, compositor zones, engine stats) before they reach the frontend.

The operator cannot distinguish a healthy system from a degraded one without opening external tools. The anatomy view should be the single surface where system state is fully legible at a glance.

## 2. Design Principles

From the design language (§1):

- **Functionalism** — every element carries information. No decorative chrome.
- **Color is meaning** — severity ladder (green-400 / yellow-400 / orange-400 / red-400), signal categories (8 colors per §3.3), stimmung stance colors (§3.4). All via CSS custom properties.
- **Density** — information rendered small and close. Position fixed, state encoded through color, pattern, motion.
- **Single typeface** — JetBrains Mono. Size varies, family never changes.
- **Proportional system** — 2px base unit for all spacing.

## 3. Architecture Decision: Dual-Path Data

Both the Python API (`/api/flow/state`) and the Tauri IPC command (`get_system_flow`) read the same shm files independently. Changes to the data model must be made in both places. The response shape is:

```typescript
interface SystemFlowState {
  nodes: FlowNode[];    // 9 nodes, each with typed metrics
  edges: FlowEdge[];    // 16 directed edges
  timestamp: number;
}
```

The `metrics` field is currently `Record<string, unknown>`. This design enriches what goes into `metrics` for each node and adds typed rendering on the frontend. The TypeScript types remain structural (no enum of node types) — node-specific rendering is dispatched by `node.id`.

## 4. Node Enrichments

### 4.1 Stimmung

**Current:** `stance`, `health` (scalar), `resource_pressure` (scalar).

**Enriched metrics:**
```typescript
{
  stance: "nominal" | "cautious" | "degraded" | "critical",
  health: number,                    // 0.0-1.0
  resource_pressure: number,         // 0.0-1.0
  dimensions: {                      // NEW: all 10 dimensions
    [name: string]: {
      value: number,                 // 0.0-1.0
      trend: "rising" | "falling" | "stable",
      freshness_s: number,
    }
  },
  non_nominal: string[],             // NEW: dimension names currently non-nominal
}
```

**Rendering:**
- Header: node label + stance-colored stripe (3px, full width, color from §3.4).
- **Dimension bar cluster:** 10 vertical bars, each 3px wide x 20px tall, spaced 2px apart. Bar fill height = dimension value. Bar color = severity ladder applied to value (>0.7 = red, >0.4 = orange, >0.2 = yellow, else green). Trend encoded as a 1px arrow glyph above each bar (up/down/dash). Stale dimensions (freshness_s > 60) rendered at 50% opacity.
- Sparkline: composite health trace (existing, keep).
- Age indicator: existing, keep.
- Remove: raw key-value pairs for stance/health/resource_pressure (encoded in stripe + bar cluster).

**Total width:** 10 bars x 5px (3px bar + 2px gap) = 50px. Fits within 150px min-width.

### 4.2 Temporal Bands

**Current:** `max_surprise` (scalar), `retention_count`, `protention_count`.

**Enriched metrics:**
```typescript
{
  max_surprise: number,
  retention_count: number,
  protention_count: number,
  surprise_count: number,            // already in Python, add to Rust
  flow_state: string,                // NEW: "idle" | "engaged" | "deep"
  impression: {                      // NEW: current moment
    flow_score: number,
    audio_energy: number,
    heart_rate: number | null,
    presence: boolean,
  },
}
```

**Rendering:**
- Header: node label + flow_state as colored word (idle=zinc-500, engaged=yellow-400, deep=green-400).
- **Three band indicators:** Retention / Impression / Protention as three horizontal bars (full node width, 4px tall each, 2px gap). Retention fills left-to-right proportional to retention_count (max 5). Impression always full (current moment). Protention fills proportional to protention_count (max 3). All colored blue-400 (temporal category per §3.3).
- **Surprise gauge:** max_surprise as a horizontal bar (0-1 scale), colored by severity ladder.
- Sparkline: max_surprise (existing, keep).
- Remove: raw count displays (encoded in band widths).

### 4.3 Apperception

**Current:** `coherence` (scalar), `dimensions` (count), `observations` (count).

**Enriched metrics:**
```typescript
{
  coherence: number,                 // 0.0-1.0
  dimensions: {                      // NEW: full self-model
    [name: string]: {
      confidence: number,            // 0.0-1.0
      assessment: string,            // current assessment text (truncated)
      affirming: number,
      problematizing: number,
    }
  },
  observation_count: number,
  reflection_count: number,          // NEW
  pending_action_count: number,      // NEW
}
```

**Rendering:**
- Header: node label + coherence as inline arc gauge (16px diameter SVG circle, arc fill = coherence, color = severity ladder on coherence value).
- **Dimension confidence bars:** 4 horizontal bars (one per dimension: system_awareness, temporal_prediction, continuity, accuracy). Each bar 100% node width, 3px tall. Fill = confidence. Color = green-400 if confidence > 0.6, yellow-400 if > 0.3, red-400 otherwise. Tiny label (8px) left-aligned: first 3 chars of dimension name (sys/tmp/con/acc).
- **Observation counter:** `obs: N` and `ref: N` in text-muted, right-aligned.
- Sparkline: coherence (existing, keep).
- Remove: raw dimension count and observation count.

### 4.4 Compositor

**Current:** `display_state` (string).

**Enriched metrics:**
```typescript
{
  display_state: string,
  zone_opacities: {                  // NEW: 8 zone attention weights
    [zone: string]: number,          // 0.0-1.0
  },
  signal_count: number,              // NEW: total active signals
  max_severity: number,              // NEW: highest signal severity
  ambient_speed: number,             // NEW
  ambient_turbulence: number,        // NEW
}
```

**Rendering:**
- Header: node label + display_state as colored word (alert=red-400, active=green-400, ambient=emerald-400, idle=zinc-500).
- **Zone attention heatstrip:** 8 cells in a row (one per zone), each 8px wide x 12px tall. Fill opacity = zone opacity value. Color = signal category color for that zone (per §3.3: context_time=blue, governance=fuchsia, work_tasks=orange, health_infra=red, profile_state=green, ambient_sensor=emerald, voice_session=yellow, system_state=zinc).
- **Signal severity pip:** single pip (6-10px per §5.2) colored by max_severity using severity ladder. Breathing animation per §5.2 tempo.
- Remove: raw display_state text (encoded in header color).

### 4.5 Reactive Engine

**Current:** empty metrics (cached file, often missing).

**Enriched metrics:**
```typescript
{
  events_processed: number,          // NEW: total lifetime
  actions_executed: number,          // NEW: total lifetime
  error_count: number,               // NEW
  rules_evaluated: number,           // NEW
  novelty_score: number,             // NEW: 0.0-1.0, novel pattern detection
  shift_score: number,               // NEW: 0.0-1.0, distribution change
  uptime_s: number,                  // NEW
}
```

**Data source change:** Instead of reading from the stale cached file, both backends should call the engine status endpoint or read from a live shm file. If the engine exposes `/api/engine/status`, the flow route should call it internally. For the Tauri path, read from a new `/dev/shm/hapax-engine/status.json` that the engine writes on each tick. **Loose end: verify engine can write to shm.**

**Rendering:**
- Header: node label + uptime indicator (green dot if uptime > 0, else red).
- **Throughput line:** `N evt / N act / N err` in compact format. Error count colored red-400 if > 0.
- **Novelty/shift pips:** Two pips side by side. Novelty pip: green-400 if < 0.3, yellow-400 if < 0.6, red-400 if >= 0.6. Shift pip: same ladder. Breathing per severity.
- No sparkline (no single metric to track meaningfully).

### 4.6 Consent

**Current:** `phase` (string) + 5-dot state machine.

**Enriched metrics:**
```typescript
{
  phase: string,
  active_contracts: number,          // NEW: count of active consent contracts
  coverage_pct: number,              // NEW: Qdrant label coverage percentage
  channel_sufficient: boolean,       // NEW: whether consent channels are sufficient
}
```

**Data source:** The flow route should call the consent coverage endpoint internally (cached, not per-poll). Coverage is slow-changing; refresh every 60s.

**Rendering:**
- Header: node label + phase-colored dot (fuchsia-400 for governance per §3.3).
- **State dots:** Keep existing 5-dot consent state machine (unchanged).
- **Coverage arc:** Small arc gauge (16px) showing coverage_pct. Color: green-400 if > 80%, yellow-400 if > 50%, red-400 otherwise.
- **Contract count:** `N contracts` in text-muted below arc.
- **Channel sufficiency:** green or red dot next to "channels" label.

### 4.7 Voice Pipeline

**Current:** `active`, `state`, `turn_count`, `last_utterance`, `last_response`, `routing_tier`, `routing_reason`, `routing_activation`, `barge_in`.

**Enriched metrics:** Keep all existing fields. Add:
```typescript
{
  // ... existing fields ...
  frustration_score: number,         // NEW: 0.0-1.0
  acceptance_type: string,           // NEW: ACCEPT/CLARIFY/REJECT/IGNORE
}
```

**Rendering:**
- Header: node label + state-colored word (per §3.6: listening=green, thinking=yellow, speaking=blue, idle=zinc).
- **Salience bar:** routing_activation as horizontal bar (0-1), colored by severity ladder. This is the single most important voice metric.
- **Tier badge:** routing_tier as a small colored badge (LOCAL=zinc, FAST=yellow, CAPABLE=green).
- **Turn counter:** `turn N` in text-muted.
- **Frustration indicator:** Only visible when frustration_score > 0.3. Small red-400 pip with breathing.
- Sparkline: activation (existing, keep).
- Remove: last_utterance and last_response from node face (move to detail panel — too long for compact display).

### 4.8 Perception

**Current:** `activity`, `flow_score`, `presence_probability`, `face_count`, `consent_phase`.

**Enriched metrics:** Add:
```typescript
{
  // ... existing fields ...
  aggregate_confidence: number,      // NEW: 0.0-1.0 backend availability
  heart_rate_bpm: number | null,     // NEW: from biometrics
  stress_elevated: boolean,          // NEW
  interruptibility_score: number,    // NEW: 0.0-1.0
}
```

**Rendering:**
- Header: node label + activity as colored word.
- **Flow score bar:** horizontal bar (0-1), colored by severity (inverted: high flow = green).
- **Presence indicator:** presence_probability as opacity of a small emerald-400 dot. face_count as tiny number next to it.
- **Confidence pip:** aggregate_confidence as colored pip (severity ladder).
- **Biometric line:** heart_rate_bpm (if non-null) as a small number + stress indicator (red pip if stress_elevated).
- Sparkline: flow_score (existing, keep).
- Remove: consent_phase (lives on Consent node). Remove raw key-value pairs.

### 4.9 Phenomenal Context

**Current:** empty metrics, status only.

**Enriched metrics:**
```typescript
{
  bound: boolean,                    // NEW: temporal + apperception both fresh (<30s)
  coherence: number | null,          // NEW: from apperception
  surprise: number | null,           // NEW: from temporal
  active_dimensions: number,         // NEW: count of apperception dimensions with recent shifts
}
```

**Rendering:**
- Header: node label + binding indicator (green-400 dot if bound, orange-400 if fragmented).
- **Coherence/surprise pair:** Two small values side by side: `coh: 0.49` and `sur: 0.35`, colored by severity.
- **Active dimensions:** `N dims` in text-muted.
- No sparkline (derived node, no single owned metric).

## 5. Detail Panel Enrichment

Replace the raw JSON dump with **typed detail views** dispatched by node ID.

### 5.1 Common structure

```
+----------------------------------+
| Node Label                    ×  |
| ● status — Ns ago               |
+----------------------------------+
| [node-specific content]          |
|                                  |
+----------------------------------+
```

Width: 320px. Background: `surface` token at 95% opacity. Border: node status color. Backdrop blur: 8px. Font: JetBrains Mono 10px.

### 5.2 Per-node detail content

**Stimmung:** Table of all 10 dimensions (6 infrastructure + 1 cognitive + 3 biometric) with columns: name, value (colored bar), trend (arrow), freshness. Non-nominal dimensions highlighted with yellow-400 background. Stale dimensions (freshness > 300s) grayed out.

**Temporal:** Three sections (Retention / Impression / Protention). Each shows its fields as key-value pairs. Surprises section lists individual surprise events with field, observed, expected, score.

**Apperception:** Per-dimension detail: name, confidence bar, current_assessment text (wrapped), affirming/problematizing counts. Recent observations list (last 5).

**Compositor:** Zone opacity table (8 rows, name + bar). Signal list grouped by category with severity + title. Ambient parameter values.

**Engine:** Event throughput counters. Novelty/shift scores with interpretation. Last 5 events from history (timestamp, event_type, rules_matched).

**Consent:** Contract list (id, scope, active since). Coverage breakdown. Channel list with friction scores.

**Voice:** Full conversation state: last_utterance, last_response (scrollable). Routing rationale. Frustration trace. Acceptance history.

**Perception:** Full sensor readout: biometrics section, environment section, device state section, detection summary.

**Phenomenal:** Integration status, contributing sources with freshness, active dimension list.

## 6. System Summary Bar Enrichment

The bottom bar currently shows: stance, flows, offline count.

**Enriched bar:**
```
stance: cautious    flows: 9/16    health: 95/103    gpu: 25%  38°C    cost: $2.41    offline: 2
```

Additional fields fetched from supplementary endpoints at lower cadence (every 30s):
- `GET /api/health` → pass/fail counts
- `GET /api/gpu` → usage_pct, temperature_c
- `GET /api/cost` → today_cost

These are fetched by a separate `useSystemSummary` hook, not by the flow state poll.

## 7. Edge Rendering Changes

Minimal changes to edges:
- Edge labels hidden by default, visible on hover (reduce visual noise).
- Consent gate edge uses fuchsia-400 (governance color per §3.3) instead of amber.
- No other edge changes in this tier.

## 8. Depth Integration

The FlowPage renders only at Watershed Core depth. Surface and Stratum depths are unaffected by this work. The FlowSummary component (Surface) already consumes stance + counts from `useSystemFlow` — no changes needed there.

## 9. Hardcoded Color Audit

The current FlowPage has several hardcoded hex values that violate the design language:

- `#e5e7eb` (node label color) → should be `text-emphasis` token
- `#9ca3af`, `#d1d5db`, `#4b5563`, `#374151` (metric text) → should be `text-secondary`, `text-primary`, `text-muted`, `border-muted` tokens
- `#6b7280` (edge label, controls) → should be `text-muted` token
- `#f59e0b` (consent gate barrier) → should be `fuchsia-400` token
- `#10b981` (title bar active count) → should be `green-400` token
- `#1a1f2e`, `#2a2f3a` (controls background) → should be `surface`, `elevated` tokens
- `#161b2e` (grid background) → should be `bg` token
- `rgba(10, 15, 26, 0.95)` (detail panel background) → should be `surface` at 95% opacity

All must be converted to palette tokens via `useTheme()`. This is a prerequisite for correct mode switching.

## 10. Resolved Questions

1. **Engine status source:** The engine does NOT write to any file. `engine-status.json` does not exist. The `ReactiveEngine` class has a `@property status` method (`logos/engine/__init__.py:246`) returning running, paused, uptime_s, events_processed, rules_evaluated, actions_executed, errors, unique_patterns, novelty_score, shift_score, window_events. The engine instance is available at `app.state.engine` in the FastAPI process. **Decision:** The flow route calls `engine.status` directly (in-process, zero I/O). The Tauri command calls `GET /api/engine/status` (HTTP, cached by the API).

2. **Consent coverage caching:** The consent coverage endpoint makes 3 Qdrant `count()` queries per call (total, labeled, provenance). No existing caching. **Decision:** Add a module-level TTL cache (60s) in flow.py for consent metrics. The flow route calls `collect_consent_coverage()` internally with the cache wrapper. The Tauri command fetches via HTTP with the same cache.

3. **Stimmung dimensions:** Canonical model (`shared/stimmung.py:SystemStimmung`) defines exactly **10 dimensions** in 3 categories: 6 infrastructure (health, resource_pressure, error_rate, processing_throughput, perception_confidence, llm_cost_pressure), 1 cognitive (grounding_quality), 3 biometric (operator_stress, operator_energy, physiological_coherence). `overall_stance` is a derived field, not a dimension. **Important:** The shm file only contains the 6 infrastructure dimensions (written by `stimmung_sync.py`). Biometric + cognitive dimensions live in the visual-layer-aggregator's in-memory model. **Decision:** The flow route reads the shm file for infra dimensions AND reads the compositor's visual-layer-state.json for biometric fields (heart_rate, stress, coherence are already there). Frontend renders dynamically — no hardcoded dimension count.

4. **Sparkline history persistence:** Keep current module-level approach. Depth cycling is infrequent; rebuilding 30 points takes 90s (30 polls). Not worth the complexity of lifting state.

5. **Stimmung detail panel dimension count:** The detail panel in §5.2 says "13 dimensions" — corrected to 10. The detail view should show all 10 when available, graying out any that are stale (freshness_s > 300).

## 11. Non-Goals

- Ambient WebGL/shader visualization (future tier, per visualization research doc).
- New nodes beyond the existing 9 (health, GPU, cost are in the summary bar, not the graph).
- Edge throughput encoding (deferred to tier 3).
- Historical replay / time-travel debugging.
- Mobile/responsive layout (Logos is desktop-only per single-workstation axiom).
