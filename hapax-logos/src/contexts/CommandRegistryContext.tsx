import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { CommandRegistry } from "../lib/commandRegistry";
import { evaluateKeyMap, LOGOS_KEY_MAP } from "../lib/keyboardAdapter";
import { registerTerrainCommands, type TerrainState } from "../lib/commands/terrain";
import { registerOverlayCommands, type OverlayState } from "../lib/commands/overlay";
import { registerNavCommands } from "../lib/commands/nav";
import { registerSplitCommands, type SplitState } from "../lib/commands/split";
import { registerDataCommands } from "../lib/commands/data";
import { registerBuiltinSequences } from "../lib/commands/sequences";
import { connectCommandRelay } from "../lib/commandRelay";
import { useTerrainDisplay, useTerrainActions, type RegionName, type Depth, type InvestigationTab } from "./TerrainContext";

const CommandRegistryCtx = createContext<CommandRegistry | null>(null);

export function useCommandRegistry(): CommandRegistry {
  const ctx = useContext(CommandRegistryCtx);
  if (!ctx) throw new Error("useCommandRegistry must be inside CommandRegistryProvider");
  return ctx;
}

interface Props {
  children: ReactNode;
  onManualToggle: () => void;
  onPaletteToggle: () => void;
}

/**
 * Synchronous state mirror that updates immediately when actions fire,
 * before React re-renders. This ensures query() returns post-execution
 * state without waiting for a render cycle.
 */
function createStateMirror<T extends Record<string, unknown>>(initial: T) {
  let state = { ...initial };
  return {
    get: () => state,
    set: (patch: Partial<T>) => { state = { ...state, ...patch }; },
    sync: (fresh: T) => { state = { ...fresh }; },
  };
}

export function CommandRegistryProvider({
  children,
  onManualToggle,
  onPaletteToggle,
}: Props) {
  const registry = useMemo(() => new CommandRegistry(), []);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const terrainDisplay = useTerrainDisplay();
  const terrainActions = useTerrainActions();

  // Synchronous mirrors — updated eagerly on action, synced on React render
  const terrainMirror = useRef(createStateMirror<TerrainState>({
    focusedRegion: terrainDisplay.focusedRegion,
    depths: terrainDisplay.regionDepths,
  })).current;

  const overlayMirror = useRef(createStateMirror<OverlayState>({
    active: terrainDisplay.activeOverlay,
  })).current;

  const splitMirror = useRef(createStateMirror<SplitState>({
    region: terrainDisplay.splitRegion,
    fullscreen: terrainDisplay.splitFullscreen,
  })).current;

  // Sync mirrors from React state on every render
  terrainMirror.sync({
    focusedRegion: terrainDisplay.focusedRegion,
    depths: terrainDisplay.regionDepths,
  });
  overlayMirror.sync({ active: terrainDisplay.activeOverlay });
  splitMirror.sync({
    region: terrainDisplay.splitRegion,
    fullscreen: terrainDisplay.splitFullscreen,
  });

  const onManualRef = useRef(onManualToggle);
  onManualRef.current = onManualToggle;
  const onPaletteRef = useRef(onPaletteToggle);
  onPaletteRef.current = onPaletteToggle;

  // Register core domains once
  useEffect(() => {
    registerTerrainCommands(
      registry,
      () => terrainMirror.get(),
      {
        setFocusedRegion: (region: RegionName | null) => {
          terrainMirror.set({ focusedRegion: region });
          terrainActions.focusRegion(region);
        },
        setDepth: (region: string, depth: string) => {
          const depths = { ...terrainMirror.get().depths, [region]: depth };
          terrainMirror.set({ depths });
          terrainActions.setRegionDepth(region as RegionName, depth as Depth);
        },
      },
    );

    registerOverlayCommands(
      registry,
      () => overlayMirror.get(),
      {
        setActive: (name: string | null) => {
          overlayMirror.set({ active: name });
          terrainActions.setOverlay(name as Parameters<typeof terrainActions.setOverlay>[0]);
        },
      },
    );

    registerSplitCommands(
      registry,
      () => splitMirror.get(),
      {
        setRegion: (region: string | null) => {
          splitMirror.set({ region });
          terrainActions.setSplitRegion(region as RegionName | null);
        },
        setFullscreen: (v: boolean) => {
          splitMirror.set({ fullscreen: v });
          terrainActions.setSplitFullscreen(v);
        },
      },
    );

    registerNavCommands(
      registry,
      () => ({
        currentPath: window.location.pathname,
        manualOpen: false,
        paletteOpen: false,
      }),
      {
        setCurrentPath: navigate,
        setManualOpen: () => onManualRef.current(),
        setPaletteOpen: () => onPaletteRef.current(),
        openInvestigationTab: (tab: string) => {
          overlayMirror.set({ active: "investigation" });
          terrainActions.setOverlay("investigation");
          terrainActions.setInvestigationTab(tab as InvestigationTab);
        },
      },
    );

    registerDataCommands(registry, {
      invalidate: (key?: string) => {
        if (key) {
          queryClient.invalidateQueries({ queryKey: [key] });
        } else {
          queryClient.invalidateQueries();
        }
      },
    });

    registerBuiltinSequences(registry);

    // Expose on window for Playwright and debug access
    const api = {
      execute: registry.execute.bind(registry),
      query: registry.query.bind(registry),
      list: registry.list.bind(registry),
      subscribe: registry.subscribe.bind(registry),
      getState: registry.getState.bind(registry),
      get debug() {
        return registry.debug;
      },
      set debug(v: boolean) {
        registry.debug = v;
      },
    };
    (window as unknown as Record<string, unknown>).__logos = api;

    // Connect to backend WS relay for external consumers (MCP, voice)
    const disconnectRelay = connectCommandRelay(registry);

    return () => {
      disconnectRelay();
      delete (window as unknown as Record<string, unknown>).__logos;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable refs, register once
  }, [registry]);

  // Global keyboard handler
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      const isInput =
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.isContentEditable;

      // Ctrl+P — palette toggle (works even in inputs)
      if ((e.ctrlKey || e.metaKey) && e.key === "p") {
        e.preventDefault();
        onPaletteRef.current();
        return;
      }

      // Skip other shortcuts when in input fields
      if (isInput && e.key !== "Escape") return;

      const match = evaluateKeyMap(
        LOGOS_KEY_MAP,
        e.key,
        { ctrl: e.ctrlKey, shift: e.shiftKey, alt: e.altKey, meta: e.metaKey },
        registry,
      );

      if (match) {
        e.preventDefault();
        registry.execute(match.command, match.args ?? {}, "keyboard");
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [registry]);

  return (
    <CommandRegistryCtx.Provider value={registry}>
      {children}
    </CommandRegistryCtx.Provider>
  );
}
