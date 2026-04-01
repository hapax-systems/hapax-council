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
