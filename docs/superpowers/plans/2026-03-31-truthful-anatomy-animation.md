# Truthful Anatomy Animation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all age-driven animations in the system anatomy with stimmung-stance-driven breathing and discrete node status colors, so every visual change represents a real system signal.

**Architecture:** Single-file refactor of `FlowPage.tsx`. Remove 5 age-driven animation functions, replace with stimmung-stance-aware breathing and binary node opacity. Edge particles removed entirely, edge colors simplified to source-node-status-based. Stimmung stance threaded from flow state into each node via React Flow data prop.

**Tech Stack:** React, @xyflow/react, TypeScript, CSS keyframes

**Spec:** `docs/superpowers/specs/2026-03-31-truthful-anatomy-animation-design.md`

---

### Task 1: Thread stimmung stance into node data

**Files:**
- Modify: `hapax-logos/src/pages/FlowPage.tsx:353-376` (the `useEffect` that builds React Flow nodes/edges from flow state)

Currently each node gets `data: n` (the raw `FlowNode`). The stimmung stance is only extracted at line 399 for the status bar. We need it available to every `SystemNode` so it can drive breathing.

- [ ] **Step 1: Extract stance when building nodes**

In the `useEffect` at line 353, add stance extraction before the node mapping:

```typescript
useEffect(() => { if (!flowState) return;
  const am: Record<string, number> = {}; for (const n of flowState.nodes) am[n.id] = n.age_s;
  const stimmungNode = flowState.nodes.find(n => n.id === "stimmung");
  const stance = (stimmungNode?.metrics?.stance as string) || "unknown";
  const rawNodes: Node[] = flowState.nodes.map(n => ({
    id: n.id, type: "system",
    position: prevPos.current[n.id] || FALLBACK_POSITIONS[n.id] || { x: 0, y: 0 },
    data: { ...n, _stance: stance }, draggable: true,
  }));
```

- [ ] **Step 2: Update FlowNode type to include stance**

At line 26, add the optional `_stance` field:

```typescript
interface FlowNode { id: string; label: string; status: string; age_s: number; metrics: NodeMetrics; _stance?: string; [key: string]: unknown; }
```

- [ ] **Step 3: Verify the app still builds**

Run: `cd hapax-council/hapax-logos && pnpm tauri dev`

Expected: App compiles, flow page renders. No visual change yet — stance is threaded but not consumed.

- [ ] **Step 4: Commit**

```bash
git add hapax-logos/src/pages/FlowPage.tsx
git commit -m "refactor(flow): thread stimmung stance into node data"
```

---

### Task 2: Replace node color and opacity functions

**Files:**
- Modify: `hapax-logos/src/pages/FlowPage.tsx:64-82` (color helpers)

- [ ] **Step 1: Update `flowColors` — stale uses yellow-400 instead of orange-400**

Replace lines 64-70:

```typescript
function flowColors(p: ThemePalette) {
  return {
    active: { bg: `color-mix(in srgb, ${p["green-400"]} 10%, transparent)`, border: p["green-400"] },
    stale: { bg: `color-mix(in srgb, ${p["yellow-400"]} 10%, transparent)`, border: p["yellow-400"] },
    offline: { bg: `color-mix(in srgb, ${p["zinc-600"]} 6%, transparent)`, border: p["zinc-600"] },
  };
}
```

Note: `glow` key removed — glow is now computed per-node from stance, not stored in the color map.

- [ ] **Step 2: Replace `breathDur` and `nodeOp` with `stimmungBreath`**

Replace lines 81-82:

```typescript
function stimmungBreath(stance: string, status: string): { dur: string; glow: string; scale: number } {
  if (status === "offline") return { dur: "0s", glow: "none", scale: 1 };
  switch (stance) {
    case "critical": return { dur: "2s", glow: "inset 0 0 12px", scale: 1.15 };
    case "degraded": return { dur: "6s", glow: "inset 0 0 8px", scale: 1 };
    default: return { dur: "0s", glow: "none", scale: 1 };
  }
}
```

- [ ] **Step 3: Replace `edgeColor` with status-based version**

Replace lines 72-74:

```typescript
function statusEdgeColor(sourceStatus: string, active: boolean, p: ThemePalette): string {
  if (!active) return p["zinc-700"];
  if (sourceStatus === "active") return p["green-400"];
  if (sourceStatus === "stale") return p["yellow-400"];
  return p["zinc-700"];
}
```

- [ ] **Step 4: Verify build**

Run: `cd hapax-council/hapax-logos && pnpm tauri dev`

Expected: Build may have errors since `SystemNode` and `FlowingEdge` still reference old functions. That's fine — we fix consumers in the next tasks.

- [ ] **Step 5: Commit**

```bash
git add hapax-logos/src/pages/FlowPage.tsx
git commit -m "refactor(flow): replace age-driven color/animation helpers with stance-driven"
```

---

### Task 3: Update SystemNode to use new functions

**Files:**
- Modify: `hapax-logos/src/pages/FlowPage.tsx:247-281` (SystemNode component)

- [ ] **Step 1: Rewrite SystemNode render logic**

Replace lines 247-281:

```typescript
function SystemNode({ data }: { data: FlowNode }) {
  const { palette: p } = useTheme();
  const fc = flowColors(p), colors = fc[data.status as keyof typeof fc] || fc.offline;
  const m = data.metrics || {};
  const stance = data._stance || "unknown";
  const breath = stimmungBreath(stance, data.status);
  const op = data.status === "offline" ? 0.5 : 1.0;
  const sk = SP_METRIC[data.id]; if (sk && m[sk] !== undefined) pushSp(data.id, m[sk] as number);

  // Stimmung node gets stance-specific border opacity per design language §3.4
  const borderOpacity = data.id === "stimmung"
    ? stance === "critical" ? 0.35 : stance === "degraded" ? 0.25 : stance === "cautious" ? 0.15 : 1
    : 1;

  const glowColor = `color-mix(in srgb, ${colors.border} ${stance === "critical" ? "8%" : "6%"}, transparent)`;
  const boxShadow = breath.glow !== "none" ? `${breath.glow} ${glowColor}` : "none";

  const body = () => { switch (data.id) {
    case "perception": return <PerceptionBody m={m} p={p} />;
    case "stimmung": return <StimmungBody m={m} p={p} />;
    case "temporal": return <TemporalBody m={m} p={p} />;
    case "apperception": return <ApperceptionBody m={m} p={p} />;
    case "compositor": return <CompositorBody m={m} p={p} />;
    case "engine": return <EngineBody m={m} p={p} />;
    case "consent": return <ConsentBody m={m} p={p} bc={colors.border} />;
    case "voice": return <VoiceBody m={m} p={p} />;
    case "phenomenal": return <PhenomenalBody m={m} p={p} />;
    default: return null;
  }};

  const glowMin = breath.glow !== "none" ? `${breath.glow} ${glowColor}` : "none";
  const glowMax = breath.glow !== "none" ? `${breath.glow} color-mix(in srgb, ${colors.border} ${stance === "critical" ? "16%" : "12%"}, transparent)` : "none";

  return (
    <div style={{
      background: colors.bg,
      border: `1.5px solid ${colors.border}`,
      borderRadius: 12,
      padding: "10px 14px",
      minWidth: 150,
      maxWidth: 220,
      opacity: op * borderOpacity,
      transition: "opacity 1s ease, transform 0.3s ease",
      fontFamily: "'JetBrains Mono', monospace",
      animation: breath.dur !== "0s" ? `breathe ${breath.dur} ease-in-out infinite` : "none",
      transform: breath.scale !== 1 ? `scale(${breath.scale})` : undefined,
      '--breathe-glow-min': glowMin,
      '--breathe-glow-max': glowMax,
    } as React.CSSProperties}>
      <Handle type="target" position={Position.Top} style={{ background: colors.border, width: 6, height: 6 }} />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 5 }}>
        <span style={{ color: p["text-emphasis"], fontSize: 12, fontWeight: 600, letterSpacing: "0.02em" }}>{data.label}</span>
        <span style={{ width: 6, height: 6, borderRadius: "50%", background: colors.border, boxShadow: data.status === "active" ? `0 0 6px ${colors.border}` : "none" }} />
      </div>
      <div style={{ fontSize: 10, lineHeight: "1.6" }}>
        {body()}
        {SP_METRIC[data.id] && <Sparkline nodeId={data.id} color={colors.border} />}
        {data.status !== "offline" && <div style={{ color: p["border-muted"], marginTop: 3, fontSize: 9, textAlign: "right" }}>{data.age_s < 1 ? "now" : `${data.age_s.toFixed(0)}s`}</div>}
      </div>
      <Handle type="source" position={Position.Bottom} style={{ background: colors.border, width: 6, height: 6 }} />
    </div>
  );
}
```

Key changes from the original:
- `breathDur(data.age_s, data.status)` → `stimmungBreath(stance, data.status)`
- `nodeOp(data.age_s, data.status)` → binary `0.5` or `1.0`
- `boxShadow` computed from stance, not hardcoded glow color
- `transform: scale()` applied at critical stance (1.15x pulse)
- Stimmung node gets border opacity modulation per §3.4
- Age text color stays `border-muted` (no severity coding)

- [ ] **Step 2: Update the `@keyframes breathe` to use stance-driven glow**

Replace line 385. The keyframe needs to animate `box-shadow` intensity since CSS `box-shadow` on the element uses a CSS custom property set inline. We use a CSS custom property `--glow-intensity` to modulate the glow:

```css
@keyframes breathe {
  0%, 100% { box-shadow: var(--breathe-glow-min, none); opacity: 1; }
  50% { box-shadow: var(--breathe-glow-max, none); opacity: 0.92; }
}
```

Then in the `SystemNode` style, set these custom properties based on stance:

```typescript
// Add to the style object in SystemNode's outer div:
'--breathe-glow-min': breath.glow !== "none" ? `${breath.glow} ${glowColor}` : "none",
'--breathe-glow-max': breath.glow !== "none" ? `${breath.glow} color-mix(in srgb, ${colors.border} ${stance === "critical" ? "16%" : "12%"}, transparent)` : "none",
```

This way the keyframe oscillates the glow intensity between 6-12% (degraded) or 8-16% (critical), creating a visible breathing effect driven entirely by the stance custom properties. When stance is nominal/cautious, the custom properties are `none` and the keyframe is not applied (`animation: none`).

- [ ] **Step 3: Verify build and visual behavior**

Run: `cd hapax-council/hapax-logos && pnpm tauri dev`

Expected: Nodes render with correct status colors. No breathing at nominal/cautious stance. If stimmung is currently degraded/critical, all non-offline nodes breathe together.

- [ ] **Step 4: Commit**

```bash
git add hapax-logos/src/pages/FlowPage.tsx
git commit -m "feat(flow): wire SystemNode to stimmung-stance breathing

Nodes are still unless system enters degraded/critical stance.
Opacity is binary (1.0 or 0.5 offline). Glow and scale driven
by real stimmung data per design language §3.4."
```

---

### Task 4: Strip particles from FlowingEdge and simplify edge color

**Files:**
- Modify: `hapax-logos/src/pages/FlowPage.tsx:103-133` (FlowingEdge component)

- [ ] **Step 1: Rewrite FlowingEdge without particles**

We also need to pass source node status through edge data. First, update the edge data construction in the `useEffect` (line 361-365). Add `source_status`:

```typescript
const rawEdges: Edge[] = flowState.edges.map((e, i) => {
  const sourceNode = flowState.nodes.find(n => n.id === e.source);
  const sourceStatus = sourceNode?.status || "offline";
  return {
    id: `${e.source}-${e.target}-${i}`, source: e.source, target: e.target, type: "flowing",
    data: { active: e.active, source_status: sourceStatus, label: e.label, edge_type: e.edge_type || "confirmed" },
    markerEnd: { type: MarkerType.ArrowClosed, color: statusEdgeColor(sourceStatus, e.active, p), width: 12, height: 12 },
  };
});
```

Note: `age_s` removed from edge data — edges no longer need it.

- [ ] **Step 2: Rewrite the FlowingEdge component**

Replace lines 103-133:

```typescript
function FlowingEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data }: EdgeProps) {
  const [path] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const d = data as Record<string, unknown>;
  const active = (d?.active as boolean) ?? false;
  const sourceStatus = (d?.source_status as string) ?? "offline";
  const lbl = (d?.label as string) ?? "";
  const edgeType = (d?.edge_type as string) ?? "confirmed";
  const { palette: ep } = useTheme();

  let strokeDash: string | undefined;
  let color: string;
  let opacity: number;
  let width: number;
  switch (edgeType) {
    case "emergent":
      strokeDash = "6 3"; color = ep["yellow-400"]; opacity = 0.8; width = 2; break;
    case "dormant":
      strokeDash = "2 4"; color = ep["zinc-600"]; opacity = 0.2; width = 1; break;
    default: // confirmed
      strokeDash = undefined; color = statusEdgeColor(sourceStatus, active, ep); opacity = active ? 0.7 : 0.15; width = active ? 1.5 : 0.8;
  }
  return (
    <g className="flow-edge-group">
      <BaseEdge id={id} path={path} style={{ stroke: color, strokeWidth: width, opacity, strokeDasharray: strokeDash, transition: "stroke 1s ease, opacity 1s ease" }} />
      {lbl && <text className="flow-edge-label"><textPath href={`#${id}`} startOffset="50%" textAnchor="middle" style={{ fontSize: "9px", fill: edgeType === "emergent" ? ep["yellow-400"] : active ? ep["text-muted"] : ep["border-muted"], fontFamily: "'JetBrains Mono', monospace" }}>{edgeType === "emergent" ? `⚡ ${lbl}` : lbl}</textPath></text>}
    </g>
  );
}
```

The entire particle rendering block (`showParticles`, `pc`, `Array.from({length: pc}).map(...)`) is gone.

- [ ] **Step 3: Verify build and visual behavior**

Run: `cd hapax-council/hapax-logos && pnpm tauri dev`

Expected: Edges render without particles. Confirmed active edges are green (active source) or yellow (stale source). Dormant edges are visible as faint dotted lines. Emergent edges still show dashed amber with ⚡.

- [ ] **Step 4: Commit**

```bash
git add hapax-logos/src/pages/FlowPage.tsx
git commit -m "feat(flow): remove edge particles, simplify to status-based color

Particles claimed throughput but measured file age. Edges now show
source node status color (green=active, yellow=stale, zinc=offline).
Three edge classes retained: confirmed, emergent, dormant."
```

---

### Task 5: Clean up dead code

**Files:**
- Modify: `hapax-logos/src/pages/FlowPage.tsx`

- [ ] **Step 1: Remove the old `breathDur` and `nodeOp` functions**

These were replaced in Task 2 but may still be present if the replacement was added alongside rather than replacing. Verify lines 81-82 no longer contain the old functions. If they do, delete them.

- [ ] **Step 2: Remove the old `edgeColor` function**

Replaced by `statusEdgeColor`. Delete the old `edgeColor` function (was at line 72-74).

- [ ] **Step 3: Verify no references to removed functions**

Run: `cd hapax-council/hapax-logos && grep -n 'breathDur\|nodeOp\|edgeColor' src/pages/FlowPage.tsx`

Expected: No matches. If `edgeColor` appears in the marker construction, it was already replaced in Task 4.

- [ ] **Step 4: Run lint**

Run: `cd hapax-council/hapax-logos && pnpm exec tsc --noEmit`

Expected: Clean — no type errors, no unused imports.

- [ ] **Step 5: Verify the full app works**

Run: `cd hapax-council/hapax-logos && pnpm tauri dev`

Expected: Flow page renders correctly. Nodes show discrete status. No breathing at nominal stance. Edges have no particles. Bottom status bar unchanged.

- [ ] **Step 6: Commit**

```bash
git add hapax-logos/src/pages/FlowPage.tsx
git commit -m "chore(flow): remove dead age-driven animation code"
```

---

### Task 6: Visual verification

**Files:** None — this is a manual verification task.

- [ ] **Step 1: Check nominal state**

With stimmung at nominal stance, verify:
- All active nodes: green border, solid, no animation, no glow, opacity 1.0
- All stale nodes: yellow border, solid, no animation, no glow, opacity 1.0
- All offline nodes: zinc border, opacity 0.5, no animation
- No particles on any edge
- Dormant edges visible as faint dotted lines
- Status bar shows stance, flow count, health, gpu, cost

- [ ] **Step 2: Check degraded state**

If stimmung can be temporarily set to degraded (or wait for natural degradation), verify:
- All non-offline nodes breathe at 6s cycle
- Inset glow appears at 6% opacity of each node's border color
- No scale change
- Edges remain static

- [ ] **Step 3: Check critical state**

If stimmung reaches critical, verify:
- All non-offline nodes breathe at 2s cycle
- Inset glow at 8% opacity
- 1.15x scale pulse
- Stimmung node border at 35% opacity

- [ ] **Step 4: Final commit — squash if desired**

All implementation is complete. If commits are clean, no squash needed.
