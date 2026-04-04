import { memo, useCallback, useEffect, useRef, useState } from "react";
import { PresetChip } from "./PresetChip";
import { PRESET_CATEGORIES } from "./presetData";
import { useStudioGraph } from "../../stores/studioGraphStore";
import { activatePresets } from "./SequenceBar";
import { fetchPresetGraph } from "./presetLoader";
import { countSlots, MAX_SLOTS } from "./presetMerger";

const allPresetNames = PRESET_CATEGORIES.flatMap((cat) => cat.presets);

function ChainBuilderInner() {
  const sequence = useStudioGraph((s) => s.sequence);
  const updateChainPresets = useStudioGraph((s) => s.updateChainPresets);
  const chainSlotCount = useStudioGraph((s) => s.chainSlotCount);
  const setChainSlotCount = useStudioGraph((s) => s.setChainSlotCount);

  const [activating, setActivating] = useState(false);
  const dropRef = useRef<HTMLDivElement>(null);

  // Cache preset slot counts so we can show them in the palette
  const [presetSlotCounts, setPresetSlotCounts] = useState<Record<string, number>>({});

  useEffect(() => {
    let cancelled = false;
    async function loadSlotCounts() {
      const counts: Record<string, number> = {};
      // Load in batches to avoid overwhelming the API
      for (const name of allPresetNames) {
        if (cancelled) return;
        const graph = await fetchPresetGraph(name);
        if (graph) {
          counts[name] = countSlots([graph]);
        }
      }
      if (!cancelled) setPresetSlotCounts(counts);
    }
    loadSlotCounts();
    return () => { cancelled = true; };
  }, []);

  const activeIdx = sequence.activeChainIndex;
  const hasActiveChain = activeIdx >= 0 && activeIdx < sequence.chains.length;
  const chainPresets = hasActiveChain ? (sequence.chains[activeIdx]?.presets ?? []) : [];

  // Compute current chain's slot count from cached preset counts
  const currentChainSlots = chainPresets.reduce((sum, p) => sum + (presetSlotCounts[p] ?? 0), 0);

  const activate = useCallback(
    async (presets: string[]) => {
      setActivating(true);
      try {
        await activatePresets(presets, setChainSlotCount);
      } finally {
        setActivating(false);
      }
    },
    [setChainSlotCount],
  );

  const applyPresets = useCallback(
    (next: string[]) => {
      if (!hasActiveChain) return;
      updateChainPresets(activeIdx, next);
      activate(next);
    },
    [activeIdx, hasActiveChain, updateChainPresets, activate],
  );

  const addPreset = useCallback(
    (name: string) => {
      applyPresets([...chainPresets, name]);
    },
    [chainPresets, applyPresets],
  );

  const removePreset = useCallback(
    (index: number) => {
      applyPresets(chainPresets.filter((_, i) => i !== index));
    },
    [chainPresets, applyPresets],
  );

  const handleChainDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const reorderIdx = e.dataTransfer.getData("chain-reorder");
      const presetName = e.dataTransfer.getData("preset-name");

      if (presetName) {
        addPreset(presetName);
        return;
      }

      if (reorderIdx) {
        const fromIdx = parseInt(reorderIdx, 10);
        const rect = dropRef.current?.getBoundingClientRect();
        if (!rect) return;
        const chipWidth = rect.width / Math.max(chainPresets.length, 1);
        const toIdx = Math.min(
          Math.floor((e.clientX - rect.left) / chipWidth),
          chainPresets.length - 1,
        );
        if (fromIdx === toIdx) return;
        const next = [...chainPresets];
        const [moved] = next.splice(fromIdx, 1);
        next.splice(toIdx, 0, moved);
        applyPresets(next);
      }
    },
    [chainPresets, addPreset, applyPresets],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);

  const handleClickPreset = useCallback(
    (name: string) => {
      applyPresets([name]);
    },
    [applyPresets],
  );

  const slotsOver = chainSlotCount > MAX_SLOTS;

  // If no chains exist at all, show a hint
  if (sequence.chains.length === 0) {
    return (
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "rgba(29,32,33,0.92)",
          borderTop: "1px solid #3c3836",
          padding: "12px 16px",
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 10,
          color: "#504945",
          textAlign: "center",
        }}
      >
        add a chain to start
      </div>
    );
  }

  return (
    <div
      onClick={(e) => e.stopPropagation()}
      style={{
        background: "rgba(29,32,33,0.92)",
        borderTop: "1px solid #3c3836",
        padding: "8px 16px",
        fontFamily: "JetBrains Mono, monospace",
      }}
    >
      {/* Chain strip */}
      <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 8 }}>
        <span style={{ fontSize: 9, color: "#928374", marginRight: 4, flexShrink: 0 }}>
          {hasActiveChain ? `Editing Chain ${activeIdx + 1}:` : "Select a chain"}
        </span>
        {hasActiveChain && (
          <>
            <div
              ref={dropRef}
              onDrop={handleChainDrop}
              onDragOver={handleDragOver}
              style={{
                flex: 1,
                display: "flex",
                alignItems: "center",
                gap: 4,
                minHeight: 24,
                padding: "2px 4px",
                border: "1px dashed #504945",
                borderRadius: 2,
              }}
            >
              {chainPresets.length === 0 && (
                <span style={{ fontSize: 9, color: "#504945" }}>drag presets here</span>
              )}
              {chainPresets.map((name, i) => (
                <span key={`${name}-${i}`} style={{ display: "flex", alignItems: "center", gap: 2 }}>
                  {i > 0 && <span style={{ color: "#665c54", fontSize: 10 }}>&rarr;</span>}
                  <PresetChip name={name} inChain chainIndex={i} onRemove={removePreset} />
                </span>
              ))}
            </div>
            {chainSlotCount > 0 && (
              <span style={{ fontSize: 9, color: slotsOver ? "#fb4934" : "#665c54", flexShrink: 0 }}>
                {chainSlotCount}/{MAX_SLOTS}
              </span>
            )}
            {activating && <span style={{ fontSize: 9, color: "#fabd2f" }}>...</span>}
          </>
        )}
      </div>

      {/* Preset palette */}
      {hasActiveChain && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, maxHeight: 120, overflowY: "auto" }}>
          {allPresetNames.map((name) => {
            const presetSlots = presetSlotCounts[name] ?? 0;
            const wouldExceed = currentChainSlots + presetSlots > MAX_SLOTS;
            return (
              <PresetChip
                key={name}
                name={name}
                onClick={handleClickPreset}
                disabled={wouldExceed}
                slotCount={presetSlots > 0 ? presetSlots : undefined}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

export const ChainBuilder = memo(ChainBuilderInner);
