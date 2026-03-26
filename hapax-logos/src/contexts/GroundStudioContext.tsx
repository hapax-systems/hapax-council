import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

const STORAGE_KEY = "hapax-studio-state";

interface StoredState {
  heroRole?: string;
  effectSourceId?: string;
  smoothMode?: boolean;
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
}

const GroundStudioContext = createContext<GroundStudioState | null>(null);

export function GroundStudioProvider({ children }: { children: ReactNode }) {
  const stored = loadState();
  const [heroRole, setHeroRole] = useState(stored.heroRole ?? "brio-operator");
  const [effectSourceId, setEffectSourceId] = useState(stored.effectSourceId ?? "camera");
  const [smoothMode, setSmoothMode] = useState(stored.smoothMode ?? false);

  // Persist on change
  useEffect(() => {
    saveState({ heroRole, effectSourceId, smoothMode });
  }, [heroRole, effectSourceId, smoothMode]);

  // Wrap setters in useCallback to avoid unnecessary re-renders
  const setHeroRoleCb = useCallback((v: string) => setHeroRole(v), []);
  const setEffectSourceIdCb = useCallback((v: string) => setEffectSourceId(v), []);
  const setSmoothModeCb = useCallback((v: boolean) => setSmoothMode(v), []);

  return (
    <GroundStudioContext.Provider
      value={{
        heroRole, setHeroRole: setHeroRoleCb,
        effectSourceId, setEffectSourceId: setEffectSourceIdCb,
        smoothMode, setSmoothMode: setSmoothModeCb,
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
