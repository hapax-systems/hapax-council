import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

interface GroundStudioState {
  heroRole: string;
  setHeroRole: (role: string) => void;
  fxMode: boolean;
  setFxMode: (on: boolean) => void;
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
}

const GroundStudioContext = createContext<GroundStudioState | null>(null);

export function GroundStudioProvider({ children }: { children: ReactNode }) {
  const [heroRole, setHeroRole] = useState("brio-operator");
  const [fxMode, setFxModeRaw] = useState(false);
  const [smoothMode, setSmoothModeRaw] = useState(false);
  const [compositeMode, setCompositeModeRaw] = useState(false);
  const [presetIdx, setPresetIdx] = useState(0);
  const [liveFilterIdx, setLiveFilterIdx] = useState(0);
  const [smoothFilterIdx, setSmoothFilterIdx] = useState(0);

  const setFxMode = useCallback((on: boolean) => {
    setFxModeRaw(on);
    if (on) { setSmoothModeRaw(false); setCompositeModeRaw(false); }
  }, []);

  const setSmoothMode = useCallback((on: boolean) => {
    setSmoothModeRaw(on);
    if (on) { setFxModeRaw(false); setCompositeModeRaw(false); }
  }, []);

  const setCompositeMode = useCallback((on: boolean) => {
    setCompositeModeRaw(on);
    if (on) { setFxModeRaw(false); setSmoothModeRaw(false); }
  }, []);

  return (
    <GroundStudioContext.Provider
      value={{
        heroRole, setHeroRole,
        fxMode, setFxMode,
        smoothMode, setSmoothMode,
        compositeMode, setCompositeMode,
        presetIdx, setPresetIdx,
        liveFilterIdx, setLiveFilterIdx,
        smoothFilterIdx, setSmoothFilterIdx,
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
