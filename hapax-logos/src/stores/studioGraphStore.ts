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

      setNodes: (nodes: Node[]) => set({ nodes }),
      setEdges: (edges: Edge[]) => set({ edges }),
      updateNodes: (updater: (nodes: Node[]) => Node[]) =>
        set((s: StudioGraphState) => ({ nodes: updater(s.nodes) })),
      updateEdges: (updater: (edges: Edge[]) => Edge[]) =>
        set((s: StudioGraphState) => ({ edges: updater(s.edges) })),
      setGraphName: (graphName: string) => set({ graphName }),
      markDirty: () => set({ graphDirty: true }),
      markClean: () => set({ graphDirty: false }),
      setCameraStatuses: (cameraStatuses: Record<string, "active" | "offline" | "starting">) =>
        set({ cameraStatuses }),
      selectNode: (selectedNodeId: string | null) => set({ selectedNodeId }),
      toggleHapaxLock: () =>
        set((s: StudioGraphState) => ({ hapaxLocked: !s.hapaxLocked })),
      toggleLeftDrawer: () =>
        set((s: StudioGraphState) => ({ leftDrawerOpen: !s.leftDrawerOpen })),
      toggleRightDrawer: () =>
        set((s: StudioGraphState) => ({ rightDrawerOpen: !s.rightDrawerOpen })),

      loadPreset: (name: string, nodes: Node[], edges: Edge[]) =>
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
      partialize: (state: StudioGraphState) => ({
        graphName: state.graphName,
        hapaxLocked: state.hapaxLocked,
        leftDrawerOpen: state.leftDrawerOpen,
        rightDrawerOpen: state.rightDrawerOpen,
      }),
    },
  ),
);
