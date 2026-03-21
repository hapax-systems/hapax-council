import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

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
}

const GroundStudioContext = createContext<GroundStudioState | null>(null);

export function GroundStudioProvider({ children }: { children: ReactNode }) {
  const [heroRole, setHeroRole] = useState("brio-operator");
  const [effectSourceId, setEffectSourceId] = useState("camera");
  const [smoothMode, setSmoothMode] = useState(false);
  const [compositeMode, setCompositeMode] = useState(false);
  const [presetIdx, setPresetIdx] = useState(0);

  return (
    <GroundStudioContext.Provider
      value={{
        heroRole, setHeroRole,
        effectSourceId, setEffectSourceId,
        smoothMode, setSmoothMode,
        compositeMode, setCompositeMode,
        presetIdx, setPresetIdx,
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
