/**
 * Right drawer: preset library with categorized presets and reference material.
 * Load presets onto canvas, save current graph as preset.
 */
import { useState } from "react";
import { useStudioGraph, type StudioGraphState } from "../../stores/studioGraphStore";
import { api } from "../../api/client";
import { PRESET_CATEGORIES, type PresetCategory } from "./presetData";

type S = StudioGraphState;

export function PresetLibrary() {
  const rightDrawerOpen = useStudioGraph((s: S) => s.rightDrawerOpen);
  const toggleRightDrawer = useStudioGraph((s: S) => s.toggleRightDrawer);
  const graphName = useStudioGraph((s: S) => s.graphName);
  const graphDirty = useStudioGraph((s: S) => s.graphDirty);

  const [expandedCategory, setExpandedCategory] = useState<string | null>(null);
  const [showReferences, setShowReferences] = useState<string | null>(null);

  if (!rightDrawerOpen) {
    return (
      <button
        onClick={toggleRightDrawer}
        title="Preset Library (L)"
        style={{
          position: "absolute",
          top: 44,
          right: 8,
          zIndex: 15,
          background: "var(--color-bg1)",
          border: "1px solid var(--color-bg3)",
          borderRadius: 4,
          padding: "4px 8px",
          color: "var(--color-fg4)",
          cursor: "pointer",
          fontSize: 11,
        }}
      >
        Presets
      </button>
    );
  }

  return (
    <div
      style={{
        position: "absolute",
        top: 36,
        right: 0,
        bottom: 0,
        width: 300,
        background: "var(--color-bg1)",
        borderLeft: "1px solid var(--color-bg3)",
        zIndex: 20,
        overflowY: "auto",
        fontSize: 12,
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "8px 12px",
          borderBottom: "1px solid var(--color-bg3)",
        }}
      >
        <span style={{ fontWeight: 600, color: "var(--color-fg1)" }}>Presets</span>
        <button
          onClick={toggleRightDrawer}
          style={{ background: "none", border: "none", color: "var(--color-fg4)", cursor: "pointer" }}
        >
          ×
        </button>
      </div>

      {/* Current graph */}
      <div style={{ padding: "8px 12px", borderBottom: "1px solid var(--color-bg2)" }}>
        <div style={{ fontSize: 10, color: "var(--color-fg4)", textTransform: "uppercase", marginBottom: 4 }}>
          Current
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ color: "var(--color-fg1)", fontWeight: 600 }}>
            {graphName}
            {graphDirty && <span style={{ color: "var(--color-yellow)", marginLeft: 4 }}>*</span>}
          </span>
        </div>
      </div>

      {/* Preset categories */}
      <div style={{ padding: "4px 0" }}>
        {PRESET_CATEGORIES.map((cat) => (
          <CategorySection
            key={cat.id}
            category={cat}
            expanded={expandedCategory === cat.id}
            onToggle={() => setExpandedCategory(expandedCategory === cat.id ? null : cat.id)}
            showReferences={showReferences === cat.id}
            onToggleReferences={() => setShowReferences(showReferences === cat.id ? null : cat.id)}
          />
        ))}
      </div>
    </div>
  );
}

interface CategorySectionProps {
  category: PresetCategory;
  expanded: boolean;
  onToggle: () => void;
  showReferences: boolean;
  onToggleReferences: () => void;
}

function CategorySection({
  category,
  expanded,
  onToggle,
  showReferences,
  onToggleReferences,
}: CategorySectionProps) {
  return (
    <div style={{ borderBottom: "1px solid var(--color-bg2)" }}>
      <button
        onClick={onToggle}
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          width: "100%",
          background: "none",
          border: "none",
          padding: "8px 12px",
          color: expanded ? "var(--color-fg1)" : "var(--color-fg3)",
          cursor: "pointer",
          fontSize: 12,
          textAlign: "left",
        }}
      >
        <span>{category.label}</span>
        <span style={{ fontSize: 10, color: "var(--color-fg4)" }}>
          {category.presets.length} · {expanded ? "▾" : "▸"}
        </span>
      </button>

      {expanded && (
        <div style={{ padding: "0 12px 8px" }}>
          {/* Presets */}
          {category.presets.map((preset) => (
            <PresetItem key={preset} name={preset} />
          ))}

          {/* Reference material toggle */}
          <button
            onClick={onToggleReferences}
            style={{
              display: "block",
              width: "100%",
              textAlign: "left",
              background: "none",
              border: "none",
              padding: "4px 0",
              color: "var(--color-fg4)",
              cursor: "pointer",
              fontSize: 10,
              marginTop: 4,
            }}
          >
            {showReferences ? "▾ Hide references" : "▸ Reference works"}
          </button>

          {showReferences && (
            <div style={{ paddingLeft: 4, marginTop: 4 }}>
              {category.references.map((ref, i) => (
                <div key={i} style={{ marginBottom: 6 }}>
                  <div style={{ color: "var(--color-fg2)", fontSize: 11 }}>
                    {ref.artist}, <em>{ref.title}</em> ({ref.year})
                  </div>
                  <div style={{ color: "var(--color-fg4)", fontSize: 10 }}>{ref.description}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function PresetItem({ name }: { name: string }) {
  const loadPreset = useStudioGraph((s: S) => s.loadPreset);

  const handleClick = async () => {
    // Activate on backend
    await api.post("/studio/effect/select", { preset: name }).catch(() => {});
    // Load minimal graph representation (full graph loading from JSON is Plan B+)
    loadPreset(name, [], []);
  };

  return (
    <button
      onClick={handleClick}
      style={{
        display: "block",
        width: "100%",
        textAlign: "left",
        background: "none",
        border: "none",
        padding: "3px 4px",
        color: "var(--color-fg2)",
        cursor: "pointer",
        fontSize: 11,
        borderRadius: 3,
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = "var(--color-bg2)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = "none";
      }}
    >
      {name}
    </button>
  );
}
