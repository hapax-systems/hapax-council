# Studio Graph Canvas — Foundation Plan (Plan A of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current studio frontend with a React Flow graph canvas that renders live camera feeds through shader node chains.

**Architecture:** A single React Flow canvas fills the Ground region. Custom node components for Source (camera thumbnails), Shader (collapsed param view), and Output (live video preview) nodes. Zustand store manages graph state, camera status, and UI. Existing snapshot polling reused for video. Old studio components deleted.

**Tech Stack:** @xyflow/react 12.x, zustand 4.x, @dagrejs/dagre 3.x, React 19, Tauri 2, TypeScript

**Spec:** `docs/superpowers/specs/2026-04-01-studio-graph-canvas-design.md` (sections 2, 3, 8)

**Depends on:** Nothing — this is the foundation.
**Enables:** Plan B (Editing & Library), Plan C (Governance & Polish)

---

### File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `hapax-logos/src/stores/studioGraphStore.ts` | Zustand store: graph nodes/edges, camera status, UI state |
| Create | `hapax-logos/src/components/graph/StudioCanvas.tsx` | React Flow canvas shell with nodeTypes/edgeTypes registration |
| Create | `hapax-logos/src/components/graph/nodes/SourceNode.tsx` | Camera/Reverie/IR source node with live thumbnail |
| Create | `hapax-logos/src/components/graph/nodes/ShaderNode.tsx` | Collapsed shader node showing type + key param |
| Create | `hapax-logos/src/components/graph/nodes/OutputNode.tsx` | Live video preview node, resizable |
| Create | `hapax-logos/src/components/graph/edges/SignalEdge.tsx` | Animated dot-flow edge |
| Create | `hapax-logos/src/components/graph/GraphToolbar.tsx` | Top bar: graph name, zoom, fit, undo placeholder |
| Create | `hapax-logos/src/components/graph/useGraphSync.ts` | Hook: serialize graph → EffectGraph JSON, activate via API |
| Modify | `hapax-logos/src/components/terrain/regions/GroundRegion.tsx` | Replace depth-based rendering with StudioCanvas |
| Modify | `hapax-logos/src/api/client.ts` | Add governance state + node snapshot + preset save endpoints |
| Delete | `hapax-logos/src/components/studio/effectSources.ts` | Replaced by direct preset JSON |
| Delete | `hapax-logos/src/components/terrain/ground/CameraHero.tsx` | Replaced by Output nodes |
| Delete | `hapax-logos/src/components/terrain/ground/CameraGrid.tsx` | Replaced by Source nodes |
| Delete | `hapax-logos/src/components/terrain/ground/CameraPip.tsx` | Replaced by Source node thumbnails |
| Delete | `hapax-logos/src/components/terrain/ground/StudioDetailPane.tsx` | Replaced by node detail (Plan B) |
| Delete | `hapax-logos/src/components/studio/StudioStatusGrid.tsx` | Replaced by utility nodes (Plan C) |
| Delete | `hapax-logos/src/components/studio/CameraSoloView.tsx` | Replaced by output node fullscreen |
| Delete | `hapax-logos/src/components/studio/VisualLayerPanel.tsx` | Replaced by modulation routing (Plan B) |
| Delete | `hapax-logos/src/components/studio/SceneBadges.tsx` | Absorbed into governance viz (Plan C) |
| Delete | `hapax-logos/src/contexts/GroundStudioContext.tsx` | Replaced by Zustand store |
| Delete | `hapax-logos/src/hooks/useSnapshotPoll.ts` | No longer needed (output nodes use batch poll) |

---

### Task 1: Add Zustand dependency

**Files:**
- Modify: `hapax-logos/package.json`

- [ ] **Step 1: Install zustand**

```bash
cd hapax-logos && pnpm add zustand
```

- [ ] **Step 2: Verify installation**

```bash
pnpm ls zustand
# Expected: zustand 4.x.x or 5.x.x
```

- [ ] **Step 3: Commit**

```bash
git add hapax-logos/package.json hapax-logos/pnpm-lock.yaml
git commit -m "chore: add zustand as direct dependency"
```

---

### Task 2: Create Zustand store

**Files:**
- Create: `hapax-logos/src/stores/studioGraphStore.ts`

- [ ] **Step 1: Create the store**

```typescript
// hapax-logos/src/stores/studioGraphStore.ts
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Node, Edge } from "@xyflow/react";

export interface StudioGraphState {
  // Graph
  nodes: Node[];
  edges: Edge[];
  graphName: string;
  graphDirty: boolean;

  // Cameras
  cameraStatuses: Record<string, "active" | "offline" | "starting">;

  // UI
  selectedNodeId: string | null;
  hapaxLocked: boolean;
  leftDrawerOpen: boolean;
  rightDrawerOpen: boolean;

  // Actions
  setNodes: (nodes: Node[]) => void;
  setEdges: (edges: Edge[]) => void;
  updateNodes: (updater: (nodes: Node[]) => Node[]) => void;
  updateEdges: (updater: (edges: Edge[]) => Edge[]) => void;
  setGraphName: (name: string) => void;
  markDirty: () => void;
  markClean: () => void;
  setCameraStatuses: (statuses: Record<string, "active" | "offline" | "starting">) => void;
  selectNode: (id: string | null) => void;
  toggleHapaxLock: () => void;
  toggleLeftDrawer: () => void;
  toggleRightDrawer: () => void;

  // Graph operations
  loadPreset: (name: string, nodes: Node[], edges: Edge[]) => void;
}

export const useStudioGraph = create<StudioGraphState>()(
  persist(
    (set) => ({
      nodes: [],
      edges: [],
      graphName: "Untitled",
      graphDirty: false,
      cameraStatuses: {},
      selectedNodeId: null,
      hapaxLocked: false,
      leftDrawerOpen: false,
      rightDrawerOpen: false,

      setNodes: (nodes) => set({ nodes }),
      setEdges: (edges) => set({ edges }),
      updateNodes: (updater) => set((s) => ({ nodes: updater(s.nodes) })),
      updateEdges: (updater) => set((s) => ({ edges: updater(s.edges) })),
      setGraphName: (graphName) => set({ graphName }),
      markDirty: () => set({ graphDirty: true }),
      markClean: () => set({ graphDirty: false }),
      setCameraStatuses: (cameraStatuses) => set({ cameraStatuses }),
      selectNode: (selectedNodeId) => set({ selectedNodeId }),
      toggleHapaxLock: () => set((s) => ({ hapaxLocked: !s.hapaxLocked })),
      toggleLeftDrawer: () => set((s) => ({ leftDrawerOpen: !s.leftDrawerOpen })),
      toggleRightDrawer: () => set((s) => ({ rightDrawerOpen: !s.rightDrawerOpen })),

      loadPreset: (name, nodes, edges) =>
        set({
          graphName: name,
          nodes,
          edges,
          graphDirty: false,
          selectedNodeId: null,
        }),
    }),
    {
      name: "hapax-studio-graph",
      partialize: (state) => ({
        graphName: state.graphName,
        hapaxLocked: state.hapaxLocked,
        leftDrawerOpen: state.leftDrawerOpen,
        rightDrawerOpen: state.rightDrawerOpen,
      }),
    },
  ),
);
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd hapax-logos && pnpm exec tsc --noEmit src/stores/studioGraphStore.ts 2>&1 | head -20
```

If tsc can't resolve paths standalone, verify via full build in a later step.

- [ ] **Step 3: Commit**

```bash
git add hapax-logos/src/stores/studioGraphStore.ts
git commit -m "feat: add Zustand store for studio graph canvas state"
```

---

### Task 3: Create SignalEdge component

**Files:**
- Create: `hapax-logos/src/components/graph/edges/SignalEdge.tsx`

- [ ] **Step 1: Create animated edge**

```typescript
// hapax-logos/src/components/graph/edges/SignalEdge.tsx
import { BaseEdge, getSmoothStepPath, type EdgeProps } from "@xyflow/react";

export function SignalEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style,
}: EdgeProps) {
  const [edgePath] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    borderRadius: 12,
  });

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          stroke: "var(--color-bg4)",
          strokeWidth: 2,
          ...style,
        }}
      />
      {/* Animated dot flowing along the edge */}
      <circle r="3" fill="var(--color-yellow)">
        <animateMotion dur="1.5s" repeatCount="indefinite" path={edgePath} />
      </circle>
    </>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add hapax-logos/src/components/graph/edges/SignalEdge.tsx
git commit -m "feat: add animated SignalEdge for graph canvas"
```

---

### Task 4: Create SourceNode component

**Files:**
- Create: `hapax-logos/src/components/graph/nodes/SourceNode.tsx`

- [ ] **Step 1: Create source node with live thumbnail**

```typescript
// hapax-logos/src/components/graph/nodes/SourceNode.tsx
import { memo, useEffect, useRef } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { LOGOS_API_URL } from "../../../config";
import { useStudioGraph } from "../../../stores/studioGraphStore";

export interface SourceNodeData {
  sourceType: "camera" | "reverie" | "ir" | "generator";
  role: string; // camera role or generator type
  label: string;
}

function SourceNodeInner({ id, data }: NodeProps) {
  const { sourceType, role, label } = data as SourceNodeData;
  const imgRef = useRef<HTMLImageElement>(null);
  const cameraStatuses = useStudioGraph((s) => s.cameraStatuses);
  const status = cameraStatuses[role] ?? "offline";

  // Poll thumbnail at ~4fps
  useEffect(() => {
    if (sourceType !== "camera") return;
    let running = true;
    const poll = () => {
      if (!running || !imgRef.current) return;
      const url = `${LOGOS_API_URL}/studio/stream/cameras/batch?roles=${role}&_t=${Date.now()}`;
      const loader = new Image();
      loader.onload = () => {
        if (running && imgRef.current) imgRef.current.src = loader.src;
      };
      loader.src = url;
    };
    poll();
    const timer = setInterval(poll, 250);
    return () => {
      running = false;
      clearInterval(timer);
    };
  }, [sourceType, role]);

  const statusColor =
    status === "active"
      ? "var(--color-green)"
      : status === "starting"
        ? "var(--color-yellow)"
        : "var(--color-red)";

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{
        width: 140,
        background: "var(--color-bg1)",
        border: "2px solid var(--color-yellow)",
      }}
    >
      {/* Thumbnail */}
      <div style={{ width: 140, height: 80, background: "var(--color-bg0)", position: "relative" }}>
        {sourceType === "camera" && (
          <img
            ref={imgRef}
            alt={label}
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
          />
        )}
        {sourceType === "reverie" && (
          <div
            style={{
              width: "100%",
              height: "100%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "var(--color-fg4)",
              fontSize: 11,
            }}
          >
            Reverie
          </div>
        )}
        {/* Status dot */}
        {sourceType === "camera" && (
          <div
            style={{
              position: "absolute",
              top: 4,
              right: 4,
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: statusColor,
            }}
          />
        )}
      </div>

      {/* Label */}
      <div
        style={{
          padding: "4px 8px",
          fontSize: 11,
          color: "var(--color-fg2)",
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {label}
      </div>

      {/* Output handle */}
      <Handle
        type="source"
        position={Position.Right}
        style={{ background: "var(--color-yellow)", width: 10, height: 10 }}
      />
    </div>
  );
}

export const SourceNode = memo(SourceNodeInner);
```

- [ ] **Step 2: Commit**

```bash
git add hapax-logos/src/components/graph/nodes/SourceNode.tsx
git commit -m "feat: add SourceNode with live camera thumbnail polling"
```

---

### Task 5: Create ShaderNode component

**Files:**
- Create: `hapax-logos/src/components/graph/nodes/ShaderNode.tsx`

- [ ] **Step 1: Create collapsed shader node**

```typescript
// hapax-logos/src/components/graph/nodes/ShaderNode.tsx
import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { useStudioGraph } from "../../../stores/studioGraphStore";

export interface ShaderNodeData {
  shaderType: string; // e.g. "mirror", "colorgrade", "trail"
  label: string;
  params: Record<string, number | string | boolean>;
}

/** One-line summary of the most distinctive param for this shader type. */
function paramSummary(shaderType: string, params: Record<string, number | string | boolean>): string {
  const first = Object.entries(params)[0];
  if (!first) return shaderType;
  const [key, val] = first;
  if (typeof val === "number") return `${key}: ${val.toFixed(2)}`;
  return `${key}: ${val}`;
}

function ShaderNodeInner({ id, data }: NodeProps) {
  const { shaderType, label, params } = data as ShaderNodeData;
  const selectedNodeId = useStudioGraph((s) => s.selectedNodeId);
  const selectNode = useStudioGraph((s) => s.selectNode);
  const isSelected = selectedNodeId === id;

  return (
    <div
      onClick={() => selectNode(id)}
      className="rounded-lg cursor-pointer"
      style={{
        width: 140,
        background: "var(--color-bg1)",
        border: `2px solid ${isSelected ? "var(--color-blue)" : "var(--color-bg3)"}`,
        transition: "border-color 0.15s",
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "6px 8px 2px",
          fontSize: 12,
          fontWeight: 600,
          color: "var(--color-fg1)",
        }}
      >
        {label || shaderType}
      </div>

      {/* Param summary */}
      <div
        style={{
          padding: "0 8px 6px",
          fontSize: 10,
          color: "var(--color-fg4)",
          fontFamily: "monospace",
        }}
      >
        {paramSummary(shaderType, params)}
      </div>

      {/* Input handle */}
      <Handle
        type="target"
        position={Position.Left}
        style={{ background: "var(--color-fg4)", width: 8, height: 8 }}
      />

      {/* Output handle */}
      <Handle
        type="source"
        position={Position.Right}
        style={{ background: "var(--color-fg4)", width: 8, height: 8 }}
      />
    </div>
  );
}

export const ShaderNode = memo(ShaderNodeInner);
```

- [ ] **Step 2: Commit**

```bash
git add hapax-logos/src/components/graph/nodes/ShaderNode.tsx
git commit -m "feat: add collapsed ShaderNode with param summary"
```

---

### Task 6: Create OutputNode component

**Files:**
- Create: `hapax-logos/src/components/graph/nodes/OutputNode.tsx`

- [ ] **Step 1: Create output node with live video**

```typescript
// hapax-logos/src/components/graph/nodes/OutputNode.tsx
import { memo, useEffect, useRef, useState } from "react";
import { Handle, Position, type NodeProps, NodeResizer } from "@xyflow/react";
import { LOGOS_API_URL } from "../../../config";

export interface OutputNodeData {
  label: string;
}

function OutputNodeInner({ id, data, selected }: NodeProps) {
  const { label } = data as OutputNodeData;
  const imgRef = useRef<HTMLImageElement>(null);
  const [isStale, setIsStale] = useState(false);
  const lastSuccess = useRef(Date.now());

  // Poll fx-snapshot at ~12fps
  useEffect(() => {
    let running = true;
    const poll = () => {
      if (!running || !imgRef.current) return;
      const url = `${LOGOS_API_URL}/studio/stream/fx?_t=${Date.now()}`;
      const loader = new Image();
      loader.onload = () => {
        if (running && imgRef.current) imgRef.current.src = loader.src;
        lastSuccess.current = Date.now();
        setIsStale(false);
      };
      loader.onerror = () => {
        /* skip frame */
      };
      loader.src = url;
    };
    poll();
    const pollTimer = setInterval(poll, 83); // ~12fps
    const staleTimer = setInterval(() => {
      if (Date.now() - lastSuccess.current > 5000) setIsStale(true);
    }, 2000);
    return () => {
      running = false;
      clearInterval(pollTimer);
      clearInterval(staleTimer);
    };
  }, []);

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{
        minWidth: 200,
        minHeight: 130,
        width: "100%",
        height: "100%",
        background: "var(--color-bg0)",
        border: `2px solid var(--color-green)`,
        position: "relative",
      }}
    >
      <NodeResizer
        isVisible={!!selected}
        minWidth={200}
        minHeight={130}
        lineStyle={{ borderColor: "var(--color-green)" }}
        handleStyle={{ background: "var(--color-green)", width: 8, height: 8 }}
      />

      {/* Video preview */}
      <img
        ref={imgRef}
        alt={label}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          display: "block",
        }}
      />

      {/* Label overlay */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          padding: "4px 8px",
          fontSize: 11,
          color: "var(--color-fg3)",
          background: "linear-gradient(rgba(0,0,0,0.6), transparent)",
        }}
      >
        {label}
        {isStale && (
          <span style={{ marginLeft: 8, color: "var(--color-red)", fontSize: 10 }}>stale</span>
        )}
      </div>

      {/* Input handle */}
      <Handle
        type="target"
        position={Position.Left}
        style={{ background: "var(--color-green)", width: 10, height: 10 }}
      />
    </div>
  );
}

export const OutputNode = memo(OutputNodeInner);
```

- [ ] **Step 2: Commit**

```bash
git add hapax-logos/src/components/graph/nodes/OutputNode.tsx
git commit -m "feat: add OutputNode with live video preview and resize"
```

---

### Task 7: Create GraphToolbar component

**Files:**
- Create: `hapax-logos/src/components/graph/GraphToolbar.tsx`

- [ ] **Step 1: Create toolbar**

```typescript
// hapax-logos/src/components/graph/GraphToolbar.tsx
import { useReactFlow } from "@xyflow/react";
import { useStudioGraph } from "../../stores/studioGraphStore";

export function GraphToolbar() {
  const { fitView, zoomIn, zoomOut } = useReactFlow();
  const graphName = useStudioGraph((s) => s.graphName);
  const graphDirty = useStudioGraph((s) => s.graphDirty);
  const hapaxLocked = useStudioGraph((s) => s.hapaxLocked);
  const toggleHapaxLock = useStudioGraph((s) => s.toggleHapaxLock);

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        height: 36,
        background: "var(--color-bg1)",
        borderBottom: "1px solid var(--color-bg3)",
        display: "flex",
        alignItems: "center",
        padding: "0 12px",
        gap: 12,
        zIndex: 10,
        fontSize: 13,
      }}
    >
      {/* Graph name */}
      <span style={{ color: "var(--color-fg1)", fontWeight: 600 }}>
        {graphName}
        {graphDirty && <span style={{ color: "var(--color-yellow)", marginLeft: 4 }}>*</span>}
      </span>

      <div style={{ flex: 1 }} />

      {/* Hapax lock */}
      <button
        onClick={toggleHapaxLock}
        title={hapaxLocked ? "Hapax suppressed — click to allow" : "Hapax active — click to suppress"}
        style={{
          background: "none",
          border: "1px solid var(--color-bg3)",
          borderRadius: 4,
          padding: "2px 8px",
          color: hapaxLocked ? "var(--color-red)" : "var(--color-green)",
          cursor: "pointer",
          fontSize: 12,
        }}
      >
        {hapaxLocked ? "Hapax locked" : "Hapax active"}
      </button>

      {/* Zoom controls */}
      <button
        onClick={() => zoomOut()}
        style={{ background: "none", border: "none", color: "var(--color-fg4)", cursor: "pointer" }}
      >
        −
      </button>
      <button
        onClick={() => zoomIn()}
        style={{ background: "none", border: "none", color: "var(--color-fg4)", cursor: "pointer" }}
      >
        +
      </button>
      <button
        onClick={() => fitView({ padding: 0.2 })}
        style={{
          background: "none",
          border: "1px solid var(--color-bg3)",
          borderRadius: 4,
          padding: "2px 8px",
          color: "var(--color-fg4)",
          cursor: "pointer",
          fontSize: 12,
        }}
      >
        Fit
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add hapax-logos/src/components/graph/GraphToolbar.tsx
git commit -m "feat: add GraphToolbar with zoom controls and Hapax lock"
```

---

### Task 8: Create useGraphSync hook

**Files:**
- Create: `hapax-logos/src/components/graph/useGraphSync.ts`

- [ ] **Step 1: Create graph sync hook**

This hook syncs the React Flow graph state with the backend: activates presets via fx-request.txt and updates camera statuses from polling.

```typescript
// hapax-logos/src/components/graph/useGraphSync.ts
import { useEffect } from "react";
import { useStudioGraph } from "../../stores/studioGraphStore";
import { useCompositorLive } from "../../api/hooks";
import { api } from "../../api/client";

/**
 * Sync graph canvas state with backend:
 * - Poll camera statuses from compositor
 * - Activate preset on backend when graph changes
 */
export function useGraphSync() {
  const setCameraStatuses = useStudioGraph((s) => s.setCameraStatuses);
  const { data: compositor } = useCompositorLive();

  // Sync camera statuses from compositor polling
  useEffect(() => {
    if (!compositor?.cameras) return;
    const statuses: Record<string, "active" | "offline" | "starting"> = {};
    for (const [role, status] of Object.entries(compositor.cameras)) {
      statuses[role] = status as "active" | "offline" | "starting";
    }
    setCameraStatuses(statuses);
  }, [compositor?.cameras, setCameraStatuses]);
}

/** Activate a preset on the backend by writing to fx-request.txt. */
export async function activatePreset(presetName: string): Promise<void> {
  await api.post("/studio/effect/select", { preset: presetName });
}
```

- [ ] **Step 2: Commit**

```bash
git add hapax-logos/src/components/graph/useGraphSync.ts
git commit -m "feat: add useGraphSync hook for backend state sync"
```

---

### Task 9: Create StudioCanvas — the main component

**Files:**
- Create: `hapax-logos/src/components/graph/StudioCanvas.tsx`

- [ ] **Step 1: Create the canvas shell**

```typescript
// hapax-logos/src/components/graph/StudioCanvas.tsx
import { useCallback } from "react";
import {
  ReactFlow,
  Background,
  MiniMap,
  Controls,
  type OnNodesChange,
  type OnEdgesChange,
  type OnConnect,
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useStudioGraph } from "../../stores/studioGraphStore";
import { SourceNode } from "./nodes/SourceNode";
import { ShaderNode } from "./nodes/ShaderNode";
import { OutputNode } from "./nodes/OutputNode";
import { SignalEdge } from "./edges/SignalEdge";
import { GraphToolbar } from "./GraphToolbar";
import { useGraphSync } from "./useGraphSync";

const nodeTypes = {
  source: SourceNode,
  shader: ShaderNode,
  output: OutputNode,
};

const edgeTypes = {
  signal: SignalEdge,
};

const defaultEdgeOptions = {
  type: "signal",
  animated: false,
};

export function StudioCanvas() {
  const nodes = useStudioGraph((s) => s.nodes);
  const edges = useStudioGraph((s) => s.edges);
  const setNodes = useStudioGraph((s) => s.setNodes);
  const setEdges = useStudioGraph((s) => s.setEdges);
  const markDirty = useStudioGraph((s) => s.markDirty);
  const selectNode = useStudioGraph((s) => s.selectNode);

  useGraphSync();

  const onNodesChange: OnNodesChange = useCallback(
    (changes) => {
      setNodes(applyNodeChanges(changes, nodes));
      markDirty();
    },
    [nodes, setNodes, markDirty],
  );

  const onEdgesChange: OnEdgesChange = useCallback(
    (changes) => {
      setEdges(applyEdgeChanges(changes, edges));
      markDirty();
    },
    [edges, setEdges, markDirty],
  );

  const onConnect: OnConnect = useCallback(
    (params) => {
      setEdges(addEdge({ ...params, type: "signal" }, edges));
      markDirty();
    },
    [edges, setEdges, markDirty],
  );

  const onPaneClick = useCallback(() => {
    selectNode(null);
  }, [selectNode]);

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <GraphToolbar />
      <div style={{ width: "100%", height: "100%", paddingTop: 36 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onPaneClick={onPaneClick}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          defaultEdgeOptions={defaultEdgeOptions}
          fitView
          proOptions={{ hideAttribution: true }}
          style={{ background: "var(--color-bg0)" }}
        >
          <Background color="var(--color-bg2)" gap={24} size={1} />
          <MiniMap
            nodeColor={() => "var(--color-bg3)"}
            maskColor="rgba(0,0,0,0.5)"
            style={{ background: "var(--color-bg1)" }}
          />
          <Controls
            showInteractive={false}
            style={{ background: "var(--color-bg1)", border: "1px solid var(--color-bg3)" }}
          />
        </ReactFlow>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add hapax-logos/src/components/graph/StudioCanvas.tsx
git commit -m "feat: add StudioCanvas with React Flow, custom nodes/edges, toolbar"
```

---

### Task 10: Wire StudioCanvas into GroundRegion

**Files:**
- Modify: `hapax-logos/src/components/terrain/regions/GroundRegion.tsx`

- [ ] **Step 1: Read current GroundRegion**

Read `hapax-logos/src/components/terrain/regions/GroundRegion.tsx` to understand the current structure.

- [ ] **Step 2: Replace depth-based rendering with StudioCanvas**

Replace the entire body of GroundRegion to render StudioCanvas at all depths. The Region wrapper and fortress check stay, but instead of surface/stratum/core depth switching, it always renders the canvas:

```typescript
// Replace the GroundRegion render function body.
// Keep the Region wrapper and component imports, but replace the depth-based
// content with a single StudioCanvas that fills the region.

import { ReactFlowProvider } from "@xyflow/react";
import { StudioCanvas } from "../../graph/StudioCanvas";

// Inside the Region render callback, replace the depth-based switch with:
<ReactFlowProvider>
  <StudioCanvas />
</ReactFlowProvider>
```

The exact edit depends on the current file structure. Read the file, preserve the Region wrapper, replace the depth-based children.

- [ ] **Step 3: Verify dev server renders the canvas**

```bash
cd hapax-logos && pnpm tauri dev
```

Navigate to the Ground region. Should see an empty React Flow canvas with the toolbar, minimap, and controls. No nodes yet — that's expected.

- [ ] **Step 4: Commit**

```bash
git add hapax-logos/src/components/terrain/regions/GroundRegion.tsx
git commit -m "feat: wire StudioCanvas into GroundRegion, replacing depth-based rendering"
```

---

### Task 11: Seed a default graph

**Files:**
- Modify: `hapax-logos/src/components/graph/StudioCanvas.tsx`

- [ ] **Step 1: Add initial graph seeding**

Add a `useEffect` that seeds a default graph if the store has no nodes. This gives users something to see on first load:

```typescript
// Add inside StudioCanvas, before the return:

const graphName = useStudioGraph((s) => s.graphName);

// Seed default graph on first load
useEffect(() => {
  if (nodes.length > 0) return;

  const defaultNodes = [
    {
      id: "camera-1",
      type: "source",
      position: { x: 50, y: 100 },
      data: {
        sourceType: "camera",
        role: "brio-operator",
        label: "BRIO Operator",
      },
    },
    {
      id: "colorgrade-1",
      type: "shader",
      position: { x: 280, y: 100 },
      data: {
        shaderType: "colorgrade",
        label: "Color Grade",
        params: { contrast: 1.05, saturation: 1.05, brightness: 1.02 },
      },
    },
    {
      id: "output-1",
      type: "output",
      position: { x: 500, y: 60 },
      data: { label: "Output" },
      style: { width: 320, height: 200 },
    },
  ];

  const defaultEdges = [
    { id: "e-cam-color", source: "camera-1", target: "colorgrade-1", type: "signal" },
    { id: "e-color-out", source: "colorgrade-1", target: "output-1", type: "signal" },
  ];

  setNodes(defaultNodes);
  setEdges(defaultEdges);
}, []); // eslint-disable-line react-hooks/exhaustive-deps
```

- [ ] **Step 2: Verify in dev server**

Open the app. Ground region should show: Camera node (with live thumbnail) → Colorgrade node → Output node (with live video). Animated dots should flow along the edges.

- [ ] **Step 3: Commit**

```bash
git add hapax-logos/src/components/graph/StudioCanvas.tsx
git commit -m "feat: seed default graph with camera → colorgrade → output chain"
```

---

### Task 12: Delete old studio components

**Files:**
- Delete: `hapax-logos/src/components/studio/effectSources.ts`
- Delete: `hapax-logos/src/components/terrain/ground/CameraHero.tsx`
- Delete: `hapax-logos/src/components/terrain/ground/CameraGrid.tsx`
- Delete: `hapax-logos/src/components/terrain/ground/CameraPip.tsx`
- Delete: `hapax-logos/src/components/terrain/ground/StudioDetailPane.tsx`
- Delete: `hapax-logos/src/components/studio/StudioStatusGrid.tsx`
- Delete: `hapax-logos/src/components/studio/CameraSoloView.tsx`
- Delete: `hapax-logos/src/components/studio/VisualLayerPanel.tsx`
- Delete: `hapax-logos/src/components/studio/SceneBadges.tsx`
- Delete: `hapax-logos/src/contexts/GroundStudioContext.tsx`
- Delete: `hapax-logos/src/hooks/useSnapshotPoll.ts`

- [ ] **Step 1: Delete the files**

```bash
cd hapax-logos/src
rm components/studio/effectSources.ts
rm components/terrain/ground/CameraHero.tsx
rm components/terrain/ground/CameraGrid.tsx
rm components/terrain/ground/CameraPip.tsx
rm components/terrain/ground/StudioDetailPane.tsx
rm components/studio/StudioStatusGrid.tsx
rm components/studio/CameraSoloView.tsx
rm components/studio/VisualLayerPanel.tsx
rm components/studio/SceneBadges.tsx
rm contexts/GroundStudioContext.tsx
rm hooks/useSnapshotPoll.ts
```

- [ ] **Step 2: Fix broken imports**

Grep for imports of deleted files and remove them:

```bash
grep -rn "effectSources\|CameraHero\|CameraGrid\|CameraPip\|StudioDetailPane\|StudioStatusGrid\|CameraSoloView\|VisualLayerPanel\|SceneBadges\|GroundStudioContext\|GroundStudioProvider\|useGroundStudio\|useSnapshotPoll" src/ --include="*.tsx" --include="*.ts" | grep -v node_modules
```

For each file with a broken import: remove the import line and any code that references the deleted component. The main files that will need cleanup:
- `GroundRegion.tsx` — should already be replaced (Task 10)
- `TerrainLayout.tsx` — may import GroundStudioProvider
- Any command files that reference old studio state

- [ ] **Step 3: Verify build compiles**

```bash
cd hapax-logos && pnpm exec tsc --noEmit
```

Fix any remaining type errors from dangling references.

- [ ] **Step 4: Verify dev server still works**

```bash
pnpm tauri dev
```

Ground region should still show the React Flow canvas with the default graph.

- [ ] **Step 5: Commit**

```bash
git add -u
git commit -m "chore: delete old studio components replaced by graph canvas

Remove effectSources.ts, CameraHero, CameraGrid, CameraPip,
StudioDetailPane, StudioStatusGrid, CameraSoloView, VisualLayerPanel,
SceneBadges, GroundStudioContext, useSnapshotPoll."
```

---

### Task 13: Lint, build, verify

- [ ] **Step 1: Lint**

```bash
cd hapax-logos && pnpm exec eslint src/components/graph/ src/stores/ --fix
```

- [ ] **Step 2: Full TypeScript check**

```bash
pnpm exec tsc --noEmit
```

- [ ] **Step 3: Build**

```bash
pnpm build
```

- [ ] **Step 4: Visual verification**

Open the app via `pnpm tauri dev`. Verify:
1. Ground region shows React Flow canvas
2. Camera source node shows live thumbnail (brio-operator feed)
3. Output node shows live video (fx-snapshot)
4. Animated dots flow along edges
5. Toolbar shows graph name, zoom controls, Hapax lock
6. Minimap visible in corner
7. Can pan, zoom, select nodes, drag nodes
8. Can draw new connections between nodes

- [ ] **Step 5: Commit any final fixes**

```bash
git add -u
git commit -m "style: lint and build fixes for graph canvas foundation"
```
