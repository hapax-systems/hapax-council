/**
 * Hapax governance ambient visualization.
 *
 * Three layers:
 * 1. Param pulse — animated dot next to modulated param labels (in NodeDetailSheet)
 * 2. Edge intensity — brighter/thicker edges when governance drives them (via edge styles)
 * 3. Preset transition — toast when atmospheric selector switches presets
 *
 * This component handles layer 3 (toast). Layers 1 and 2 are CSS-driven
 * via node/edge data attributes set by useGovernanceSync.
 */
import { useEffect, useRef, useState } from "react";
import { useStudioGraph, type StudioGraphState } from "../../stores/studioGraphStore";

type S = StudioGraphState;

interface PresetSuggestion {
  preset: string;
  reason: string;
  timestamp: number;
}

export function HapaxOverlay() {
  const hapaxLocked = useStudioGraph((s: S) => s.hapaxLocked);
  const [suggestion, setSuggestion] = useState<PresetSuggestion | null>(null);
  const dismissTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Listen for governance preset suggestions via custom events
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<PresetSuggestion>).detail;
      setSuggestion(detail);

      // Auto-dismiss after 8s
      if (dismissTimer.current) clearTimeout(dismissTimer.current);
      dismissTimer.current = setTimeout(() => setSuggestion(null), 8000);
    };

    window.addEventListener("hapax:preset-suggestion", handler);
    return () => {
      window.removeEventListener("hapax:preset-suggestion", handler);
      if (dismissTimer.current) clearTimeout(dismissTimer.current);
    };
  }, []);

  if (!suggestion) return null;

  return (
    <div
      style={{
        position: "absolute",
        top: 44,
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 25,
        background: "var(--color-bg1)",
        border: `1px solid ${hapaxLocked ? "var(--color-yellow)" : "var(--color-green)"}`,
        borderRadius: 6,
        padding: "6px 12px",
        fontSize: 12,
        display: "flex",
        alignItems: "center",
        gap: 8,
        boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
      }}
    >
      <span style={{ color: "var(--color-yellow)", fontWeight: 600 }}>Hapax</span>
      <span style={{ color: "var(--color-fg3)" }}>→</span>
      <span style={{ color: "var(--color-fg1)" }}>{suggestion.preset}</span>
      <span style={{ color: "var(--color-fg4)", fontSize: 10 }}>{suggestion.reason}</span>

      {hapaxLocked && (
        <span style={{ color: "var(--color-fg4)", fontSize: 10, fontStyle: "italic" }}>
          (suppressed)
        </span>
      )}

      <button
        onClick={() => setSuggestion(null)}
        style={{
          background: "none",
          border: "none",
          color: "var(--color-fg4)",
          cursor: "pointer",
          fontSize: 14,
          padding: "0 2px",
        }}
      >
        ×
      </button>
    </div>
  );
}
