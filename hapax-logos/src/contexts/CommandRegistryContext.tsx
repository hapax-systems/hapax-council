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
import { registerTerrainCommands } from "../lib/commands/terrain";
import { registerOverlayCommands } from "../lib/commands/overlay";
import { registerNavCommands } from "../lib/commands/nav";
import { registerSplitCommands } from "../lib/commands/split";
import { registerDataCommands } from "../lib/commands/data";
import { registerBuiltinSequences } from "../lib/commands/sequences";
import { connectCommandRelay } from "../lib/commandRelay";
import { useTerrainDisplay, useTerrainActions } from "./TerrainContext";

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

  // Refs for frequently-changing values so registration closures stay current
  const terrainRef = useRef(terrainDisplay);
  terrainRef.current = terrainDisplay;

  const onManualRef = useRef(onManualToggle);
  onManualRef.current = onManualToggle;

  const onPaletteRef = useRef(onPaletteToggle);
  onPaletteRef.current = onPaletteToggle;

  // Register core domains once (terrain, overlay, split, nav, data, sequences)
  useEffect(() => {
    registerTerrainCommands(
      registry,
      () => ({
        focusedRegion: terrainRef.current.focusedRegion,
        regionDepths: terrainRef.current.regionDepths as Record<string, string>,
      }),
      {
        focusRegion: terrainActions.focusRegion,
        setRegionDepth: terrainActions.setRegionDepth,
        cycleDepth: terrainActions.cycleDepth,
      },
    );

    registerOverlayCommands(
      registry,
      () => ({ activeOverlay: terrainRef.current.activeOverlay }),
      { setOverlay: terrainActions.setOverlay },
    );

    registerSplitCommands(
      registry,
      () => ({
        splitRegion: terrainRef.current.splitRegion,
        splitFullscreen: terrainRef.current.splitFullscreen,
        focusedRegion: terrainRef.current.focusedRegion,
      }),
      {
        setSplitRegion: terrainActions.setSplitRegion,
        setSplitFullscreen: terrainActions.setSplitFullscreen,
      },
    );

    registerNavCommands(
      registry,
      () => ({ currentPath: window.location.pathname }),
      {
        navigate,
        toggleManual: () => onManualRef.current(),
        togglePalette: () => onPaletteRef.current(),
      },
    );

    registerDataCommands(registry, {
      invalidateQueries: (key?: string) => {
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
