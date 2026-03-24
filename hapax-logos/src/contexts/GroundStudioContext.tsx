import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import type { CompositePreset } from "../components/studio/compositePresets";

const STORAGE_KEY = "hapax-studio-state";

interface StoredState {
  heroRole?: string;
  effectSourceId?: string;
  smoothMode?: boolean;
  compositeMode?: boolean;
  presetIdx?: number;
  liveFilterIdx?: number;
  smoothFilterIdx?: number;
  effectOverrides?: Partial<CompositePreset["effects"]> | null;
}

function loadState(): StoredState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw) as StoredState;
  } catch { /* ignore */ }
  return {};
}

function saveState(s: StoredState) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
  } catch { /* ignore */ }
}

interface GroundStudioState {
  heroRole: string;
  setHeroRole: (role: string) => void;
  effectSourceId: string;
  setEffectSourceId: (id: string) => void;
  smoothMode: boolean;
  setSmoothMode: (on: boolean) => void;
  compositeMode: boolean;
  setCompositeMode: (on: boolean) => void;
  presetIdx: number;
  setPresetIdx: (idx: number) => void;
  liveFilterIdx: number;
  setLiveFilterIdx: (idx: number) => void;
  smoothFilterIdx: number;
  setSmoothFilterIdx: (idx: number) => void;
  effectOverrides: Partial<CompositePreset["effects"]> | null;
  setEffectOverrides: (v: Partial<CompositePreset["effects"]> | null) => void;
}

const GroundStudioContext = createContext<GroundStudioState | null>(null);

export function GroundStudioProvider({ children }: { children: ReactNode }) {
  const stored = loadState();
  const [heroRole, setHeroRole] = useState(stored.heroRole ?? "brio-operator");
  const [effectSourceId, setEffectSourceId] = useState(stored.effectSourceId ?? "camera");
  const [smoothMode, setSmoothMode] = useState(stored.smoothMode ?? false);
  const [compositeMode, setCompositeMode] = useState(stored.compositeMode ?? false);
  const [presetIdx, setPresetIdx] = useState(stored.presetIdx ?? 0);
  const [liveFilterIdx, setLiveFilterIdx] = useState(stored.liveFilterIdx ?? 0);
  const [smoothFilterIdx, setSmoothFilterIdx] = useState(stored.smoothFilterIdx ?? 0);
  const [effectOverrides, setEffectOverrides] = useState<Partial<CompositePreset["effects"]> | null>(
    stored.effectOverrides ?? null,
  );

  // Persist on change
  useEffect(() => {
    saveState({
      heroRole, effectSourceId, smoothMode, compositeMode,
      presetIdx, liveFilterIdx, smoothFilterIdx, effectOverrides,
    });
  }, [heroRole, effectSourceId, smoothMode, compositeMode, presetIdx, liveFilterIdx, smoothFilterIdx, effectOverrides]);

  // Wrap setters in useCallback to avoid unnecessary re-renders
  const setHeroRoleCb = useCallback((v: string) => setHeroRole(v), []);
  const setEffectSourceIdCb = useCallback((v: string) => setEffectSourceId(v), []);
  const setSmoothModeCb = useCallback((v: boolean) => setSmoothMode(v), []);
  const setCompositeModeCb = useCallback((v: boolean) => setCompositeMode(v), []);
  const setPresetIdxCb = useCallback((v: number) => setPresetIdx(v), []);
  const setLiveFilterIdxCb = useCallback((v: number) => setLiveFilterIdx(v), []);
  const setSmoothFilterIdxCb = useCallback((v: number) => setSmoothFilterIdx(v), []);
  const setEffectOverridesCb = useCallback((v: Partial<CompositePreset["effects"]> | null) => setEffectOverrides(v), []);

  return (
    <GroundStudioContext.Provider
      value={{
        heroRole, setHeroRole: setHeroRoleCb,
        effectSourceId, setEffectSourceId: setEffectSourceIdCb,
        smoothMode, setSmoothMode: setSmoothModeCb,
        compositeMode, setCompositeMode: setCompositeModeCb,
        presetIdx, setPresetIdx: setPresetIdxCb,
        liveFilterIdx, setLiveFilterIdx: setLiveFilterIdxCb,
        smoothFilterIdx, setSmoothFilterIdx: setSmoothFilterIdxCb,
        effectOverrides, setEffectOverrides: setEffectOverridesCb,
      }}
    >
      {children}
    </GroundStudioContext.Provider>
  );
}

export function useGroundStudio(): GroundStudioState {
  const ctx = useContext(GroundStudioContext);
  if (!ctx) throw new Error("useGroundStudio must be inside GroundStudioProvider");
  return ctx;
}
