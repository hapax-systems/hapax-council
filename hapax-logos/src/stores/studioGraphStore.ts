import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Node, Edge } from "@xyflow/react";

export interface PresetChain {
  id: string;
  presets: string[];
  durationSeconds: number;
  source: "live" | "hls" | "smooth";
}

export interface SequenceState {
  chains: PresetChain[];
  activeChainIndex: number;
  playing: boolean;
  looping: boolean;
}

function defaultSequence(_initialPresets: string[]): SequenceState {
  return {
    chains: [],
    activeChainIndex: -1,
    playing: false,
    looping: true,
  };
}

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
  outputFullscreen: boolean;

  // Chain (legacy — kept for backward compat, mirrors active chain presets)
  chainPresets: string[];
  chainSlotCount: number;

  // Sequence
  sequence: SequenceState;

  // Saved sequences
  savedSequences: Record<string, { chains: PresetChain[]; looping: boolean }>;
  sequenceName: string;

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
  setOutputFullscreen: (value: boolean) => void;
  setChainPresets: (presets: string[]) => void;
  setChainSlotCount: (count: number) => void;
  loadPreset: (name: string, nodes: Node[], edges: Edge[]) => void;

  // Sequence name + save/load actions
  saveSequence: (name: string) => void;
  loadSequence: (name: string) => void;
  deleteSequence: (name: string) => void;
  setSequenceName: (name: string) => void;

  // Sequence actions
  setSequenceChains: (chains: PresetChain[]) => void;
  setActiveChainIndex: (index: number) => void;
  setSequencePlaying: (playing: boolean) => void;
  setSequenceLooping: (looping: boolean) => void;
  addChain: () => void;
  removeChain: (index: number) => void;
  updateChainPresets: (index: number, presets: string[]) => void;
  updateChainDuration: (index: number, durationSeconds: number) => void;
  updateChainSource: (index: number, source: string) => void;
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
      outputFullscreen: false,
      chainPresets: [],
      chainSlotCount: 0,
      sequence: defaultSequence([]),
      savedSequences: {},
      sequenceName: "",

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
      setOutputFullscreen: (value: boolean) => set({ outputFullscreen: value }),
      setChainPresets: (presets) => set({ chainPresets: presets }),
      setChainSlotCount: (count) => set({ chainSlotCount: count }),

      loadPreset: (name: string, nodes: Node[], edges: Edge[]) =>
        set({
          graphName: name,
          nodes,
          edges,
          graphDirty: false,
          selectedNodeId: null,
        }),

      // Sequence name + save/load actions
      saveSequence: (name) =>
        set((s) => ({
          savedSequences: {
            ...s.savedSequences,
            [name]: { chains: s.sequence.chains, looping: s.sequence.looping },
          },
          sequenceName: name,
        })),
      loadSequence: (name) =>
        set((s) => {
          const saved = s.savedSequences[name];
          if (!saved) return {};
          return {
            sequenceName: name,
            sequence: {
              ...s.sequence,
              chains: saved.chains,
              looping: saved.looping,
              activeChainIndex: saved.chains.length > 0 ? 0 : -1,
              playing: false,
            },
          };
        }),
      deleteSequence: (name) =>
        set((s) => {
          const { [name]: _removed, ...rest } = s.savedSequences;
          return {
            savedSequences: rest,
            sequenceName: s.sequenceName === name ? "" : s.sequenceName,
          };
        }),
      setSequenceName: (sequenceName) => set({ sequenceName }),

      // Sequence actions
      setSequenceChains: (chains) =>
        set((s) => ({ sequence: { ...s.sequence, chains } })),
      setActiveChainIndex: (index) =>
        set((s) => ({ sequence: { ...s.sequence, activeChainIndex: index } })),
      setSequencePlaying: (playing) =>
        set((s) => ({ sequence: { ...s.sequence, playing } })),
      setSequenceLooping: (looping) =>
        set((s) => ({ sequence: { ...s.sequence, looping } })),
      addChain: () =>
        set((s) => {
          const chains = [
            ...s.sequence.chains,
            { id: crypto.randomUUID(), presets: [], durationSeconds: 30, source: "live" as const },
          ];
          // If this is the first chain, select it automatically
          const activeChainIndex =
            s.sequence.activeChainIndex === -1 ? chains.length - 1 : s.sequence.activeChainIndex;
          return { sequence: { ...s.sequence, chains, activeChainIndex } };
        }),
      removeChain: (index) =>
        set((s) => {
          const chains = s.sequence.chains.filter((_, i) => i !== index);
          // If empty, go to -1 (no selection)
          const activeChainIndex =
            chains.length === 0
              ? -1
              : Math.min(s.sequence.activeChainIndex, chains.length - 1);
          return { sequence: { ...s.sequence, chains, activeChainIndex } };
        }),
      updateChainPresets: (index, presets) =>
        set((s) => {
          const chains = s.sequence.chains.map((c, i) =>
            i === index ? { ...c, presets } : c,
          );
          return { sequence: { ...s.sequence, chains }, chainPresets: presets };
        }),
      updateChainDuration: (index, durationSeconds) =>
        set((s) => {
          const chains = s.sequence.chains.map((c, i) =>
            i === index ? { ...c, durationSeconds } : c,
          );
          return { sequence: { ...s.sequence, chains } };
        }),
      updateChainSource: (index, source) =>
        set((s) => {
          const chains = s.sequence.chains.map((c, i) =>
            i === index ? { ...c, source: source as "live" | "hls" | "smooth" } : c,
          );
          return { sequence: { ...s.sequence, chains } };
        }),
    }),
    {
      name: "hapax-studio-graph",
      version: 6,
      migrate: (persisted: unknown, version: number) => {
        const state = persisted as Partial<StudioGraphState>;
        if (version < 3) {
          // Migrate: wrap existing chainPresets into a sequence
          const initialPresets = state.chainPresets ?? [];
          state.sequence = defaultSequence(initialPresets);
        }
        if (version < 4) {
          // Migrate: reset to blank sequence (no default chain)
          state.sequence = defaultSequence([]);
        }
        if (version < 5) {
          // Migrate: add source field to existing chains
          if (state.sequence) {
            state.sequence = {
              ...state.sequence,
              chains: state.sequence.chains.map((c) => ({
                ...c,
                source: (c as PresetChain).source ?? "live",
              })),
            };
          }
        }
        if (version < 6) {
          // Migrate: add savedSequences and sequenceName
          if (!state.savedSequences) state.savedSequences = {};
          if (!state.sequenceName) state.sequenceName = "";
        }
        return state as StudioGraphState;
      },
      partialize: (state: StudioGraphState) => ({
        graphName: state.graphName,
        hapaxLocked: state.hapaxLocked,
        leftDrawerOpen: state.leftDrawerOpen,
        rightDrawerOpen: state.rightDrawerOpen,
        chainPresets: state.chainPresets,
        sequence: state.sequence,
        savedSequences: state.savedSequences,
        sequenceName: state.sequenceName,
      }),
    },
  ),
);
