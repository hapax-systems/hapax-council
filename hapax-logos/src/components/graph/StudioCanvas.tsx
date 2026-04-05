import { useCallback, useEffect, useRef } from "react";
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
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useStudioGraph, type StudioGraphState } from "../../stores/studioGraphStore";
import { SourceNode } from "./nodes/SourceNode";
import { ShaderNode } from "./nodes/ShaderNode";
import { OutputNode, FullscreenOverlay } from "./nodes/OutputNode";
import { SignalEdge } from "./edges/SignalEdge";
import { GraphToolbar } from "./GraphToolbar";
import { NodeDetailSheet } from "./NodeDetailSheet";
import { NodePalette } from "./NodePalette";
import { PresetLibrary } from "./PresetLibrary";
import { HapaxOverlay } from "./HapaxOverlay";
import { useGraphSync } from "./useGraphSync";

type S = StudioGraphState;

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
};

export function StudioCanvas() {
  const nodes = useStudioGraph((s: S) => s.nodes);
  const edges = useStudioGraph((s: S) => s.edges);
  const selectNode = useStudioGraph((s: S) => s.selectNode);

  const toggleLeftDrawer = useStudioGraph((s: S) => s.toggleLeftDrawer);
  const toggleRightDrawer = useStudioGraph((s: S) => s.toggleRightDrawer);
  const toggleHapaxLock = useStudioGraph((s: S) => s.toggleHapaxLock);
  const rfRef = useRef<{ fitView: (opts?: { padding?: number }) => void } | null>(null);

  useGraphSync();

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Don't capture when typing in inputs
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      if (e.key === "p" && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        toggleLeftDrawer();
      } else if (e.key === "l" && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        toggleRightDrawer();
      } else if (e.key === " " && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        toggleHapaxLock();
      } else if (e.key === "f" && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        rfRef.current?.fitView({ padding: 0.15 });
      } else if (e.key === "s" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        const state = useStudioGraph.getState();
        import("./presetLoader").then(({ savePreset }) => {
          savePreset(state.graphName, state.nodes, state.edges).then((ok) => {
            if (ok) state.markClean();
          });
        });
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [toggleLeftDrawer, toggleRightDrawer, toggleHapaxLock]);

  // Seed default graph on first load
  useEffect(() => {
    if (nodes.length > 0) return;

    useStudioGraph.getState().setNodes([
      {
        id: "camera-1",
        type: "source",
        position: { x: 60, y: 120 },
        data: {
          sourceType: "camera",
          role: "brio-operator",
          label: "BRIO Operator",
        },
      },
      {
        id: "colorgrade-1",
        type: "shader",
        position: { x: 320, y: 140 },
        data: {
          shaderType: "colorgrade",
          label: "Color Grade",
          params: { contrast: 1.05, saturation: 1.05, brightness: 1.02 },
        },
      },
      {
        id: "output-1",
        type: "output",
        position: { x: 580, y: 60 },
        data: { label: "Output" },
        style: { width: 420, height: 260 },
      },
    ]);

    useStudioGraph.getState().setEdges([
      { id: "e-cam-color", source: "camera-1", target: "colorgrade-1", type: "signal" },
      { id: "e-color-out", source: "colorgrade-1", target: "output-1", type: "signal" },
    ]);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // fitView once React Flow is initialized
  const onInit = useCallback((instance: ReactFlowInstance) => {
    rfRef.current = instance;
    setTimeout(() => instance.fitView({ padding: 0.15 }), 200);
  }, []);

  // fitView when a new preset is loaded (graphName changes)
  const graphName = useStudioGraph((s: S) => s.graphName);
  useEffect(() => {
    if (rfRef.current && nodes.length > 0) {
      setTimeout(() => rfRef.current?.fitView({ padding: 0.15 }), 100);
    }
  }, [graphName]); // eslint-disable-line react-hooks/exhaustive-deps

  const onNodesChange: OnNodesChange = useCallback(
    (changes) => {
      const current = useStudioGraph.getState();
      current.setNodes(applyNodeChanges(changes, current.nodes));
      current.markDirty();
    },
    [],
  );

  const onEdgesChange: OnEdgesChange = useCallback(
    (changes) => {
      const current = useStudioGraph.getState();
      current.setEdges(applyEdgeChanges(changes, current.edges));
      current.markDirty();
    },
    [],
  );

  const onConnect: OnConnect = useCallback(
    (params) => {
      const current = useStudioGraph.getState();
      current.setEdges(addEdge({ ...params, type: "signal" }, current.edges));
      current.markDirty();
    },
    [],
  );

  const onPaneClick = useCallback(() => {
    selectNode(null);
  }, [selectNode]);

  const isFullscreen = useStudioGraph((s: S) => s.outputFullscreen);
  const setFullscreen = useStudioGraph((s: S) => s.setOutputFullscreen);

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <GraphToolbar />
      <NodePalette />
      <PresetLibrary />
      <NodeDetailSheet />
      <HapaxOverlay />
      {isFullscreen && <FullscreenOverlay onClose={() => setFullscreen(false)} />}
      <div style={{ width: "100%", height: "100%", paddingTop: 32 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onPaneClick={onPaneClick}
          onInit={onInit}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          defaultEdgeOptions={defaultEdgeOptions}
          proOptions={{ hideAttribution: true }}
          style={{ background: "#1d2021" }}
        >
          <Background color="#3c3836" gap={32} size={1} />
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
