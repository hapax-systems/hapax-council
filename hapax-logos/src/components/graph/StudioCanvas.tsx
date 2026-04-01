import { useCallback, useEffect } from "react";
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
};

export function StudioCanvas() {
  const nodes = useStudioGraph((s) => s.nodes);
  const edges = useStudioGraph((s) => s.edges);
  const setNodes = useStudioGraph((s) => s.setNodes);
  const setEdges = useStudioGraph((s) => s.setEdges);
  const markDirty = useStudioGraph((s) => s.markDirty);
  const selectNode = useStudioGraph((s) => s.selectNode);

  useGraphSync();

  // Seed default graph on first load
  useEffect(() => {
    if (nodes.length > 0) return;

    setNodes([
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
    ]);

    setEdges([
      { id: "e-cam-color", source: "camera-1", target: "colorgrade-1", type: "signal" },
      { id: "e-color-out", source: "colorgrade-1", target: "output-1", type: "signal" },
    ]);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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
