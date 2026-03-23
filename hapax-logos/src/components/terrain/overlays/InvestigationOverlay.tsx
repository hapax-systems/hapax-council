/**
 * InvestigationOverlay — translucent panel z-40, covers middle 60%.
 * Toggled with `/` key. Contains Chat, Insight, and Demos tabs.
 */

import { useTerrain } from "../../../contexts/TerrainContext";
import { InvestigationTabs } from "./InvestigationTabs";

export function InvestigationOverlay() {
  const { activeOverlay, setOverlay } = useTerrain();
  if (activeOverlay !== "investigation") return null;

  return (
    <div
      className="absolute inset-0 flex items-center justify-center"
      style={{ zIndex: 40, animation: "overlayFadeIn 200ms ease-out" }}
      onClick={(e) => {
        if (e.target === e.currentTarget) setOverlay(null);
      }}
    >
      <div
        className="w-[60%] h-[90%] rounded-2xl overflow-hidden"
        style={{
          background: "color-mix(in srgb, var(--color-zinc-950) 88%, transparent)",
          backdropFilter: "blur(16px)",
          border: "1px solid color-mix(in srgb, var(--color-zinc-700) 30%, transparent)",
          boxShadow: "0 16px 64px rgba(0,0,0,0.5)",
          animation: "overlaySlideIn 250ms ease-out",
        }}
      >
        <InvestigationTabs />
      </div>

      <style>{`
        @keyframes overlayFadeIn {
          from { background: transparent; }
          to { background: rgba(0, 0, 0, 0.3); }
        }
        @keyframes overlaySlideIn {
          from { opacity: 0; transform: translateY(12px) scale(0.98); }
          to { opacity: 1; transform: translateY(0) scale(1); }
        }
      `}</style>
    </div>
  );
}
