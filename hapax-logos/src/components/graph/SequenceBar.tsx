import { memo, useCallback, useEffect, useRef, useState } from "react";
import { useStudioGraph } from "../../stores/studioGraphStore";
import { fetchPresetGraph, type EffectGraphJson } from "./presetLoader";
import { mergePresetGraphs, countSlots, MAX_SLOTS } from "./presetMerger";
import { api } from "../../api/client";

/** Activate a chain of presets on the compositor. */
export async function activatePresets(
  presets: string[],
  onSlotCount?: (n: number) => void,
): Promise<void> {
  if (presets.length === 0) {
    api.post("/studio/effect/select", { preset: "clean" }).catch(() => {});
    onSlotCount?.(0);
    return;
  }
  if (presets.length === 1) {
    api.post("/studio/effect/select", { preset: presets[0] }).catch(() => {});
    onSlotCount?.(0);
    return;
  }
  const graphs: EffectGraphJson[] = [];
  for (const name of presets) {
    const g = await fetchPresetGraph(name);
    if (g) graphs.push(g);
  }
  if (graphs.length === 0) return;
  const slots = countSlots(graphs);
  onSlotCount?.(slots);
  if (slots > MAX_SLOTS) return;
  const merged = mergePresetGraphs("chain", graphs);
  await api.put("/studio/effect/graph", merged);
}

const BLOCK_HEIGHT = 52;
const MIN_BLOCK_WIDTH = 120;

/** Summarize preset list to fit in a small block */
function summarizePresets(presets: string[]): string {
  if (presets.length === 0) return "empty";
  if (presets.length === 1) return presets[0];
  if (presets.length === 2) return `${presets[0]} → ${presets[1]}`;
  return `${presets.length} presets`;
}

function SequenceBarInner() {
  const sequence = useStudioGraph((s) => s.sequence);
  const setActiveChainIndex = useStudioGraph((s) => s.setActiveChainIndex);
  const setSequencePlaying = useStudioGraph((s) => s.setSequencePlaying);
  const setSequenceLooping = useStudioGraph((s) => s.setSequenceLooping);
  const addChain = useStudioGraph((s) => s.addChain);
  const removeChain = useStudioGraph((s) => s.removeChain);
  const updateChainDuration = useStudioGraph((s) => s.updateChainDuration);
  const setChainSlotCount = useStudioGraph((s) => s.setChainSlotCount);

  const [editingDurationIdx, setEditingDurationIdx] = useState<number | null>(null);
  const [draftDuration, setDraftDuration] = useState("");
  const [elapsed, setElapsed] = useState(0); // seconds elapsed in current chain
  const [activating, setActivating] = useState(false);

  const elapsedRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const { chains, activeChainIndex, playing, looping } = sequence;
  const activeChain = activeChainIndex >= 0 ? chains[activeChainIndex] : undefined;

  // Activate a chain by index
  const activateIndex = useCallback(
    async (idx: number) => {
      const chain = chains[idx];
      if (!chain) return;
      setActivating(true);
      try {
        await activatePresets(chain.presets, setChainSlotCount);
      } finally {
        setActivating(false);
      }
    },
    [chains, setChainSlotCount],
  );

  // Select chain (click)
  const handleSelectChain = useCallback(
    (idx: number) => {
      setActiveChainIndex(idx);
      activateIndex(idx);
      elapsedRef.current = 0;
      setElapsed(0);
    },
    [setActiveChainIndex, activateIndex],
  );

  // Advance to next chain
  const advanceChain = useCallback(() => {
    if (chains.length === 0) return;
    const nextIdx = activeChainIndex + 1;
    if (nextIdx >= chains.length) {
      if (looping) {
        setActiveChainIndex(0);
        activateIndex(0);
        elapsedRef.current = 0;
        setElapsed(0);
      } else {
        setSequencePlaying(false);
      }
    } else {
      setActiveChainIndex(nextIdx);
      activateIndex(nextIdx);
      elapsedRef.current = 0;
      setElapsed(0);
    }
  }, [activeChainIndex, chains.length, looping, setActiveChainIndex, activateIndex, setSequencePlaying]);

  // Timer effect
  useEffect(() => {
    if (!playing) {
      if (timerRef.current) clearInterval(timerRef.current);
      timerRef.current = null;
      return;
    }
    timerRef.current = setInterval(() => {
      elapsedRef.current += 0.5;
      setElapsed(elapsedRef.current);
      const duration = chains[activeChainIndex]?.durationSeconds ?? 30;
      if (elapsedRef.current >= duration) {
        elapsedRef.current = 0;
        setElapsed(0);
        advanceChain();
      }
    }, 500);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [playing, activeChainIndex, chains, advanceChain]);

  // Reset elapsed when chain changes externally
  useEffect(() => {
    elapsedRef.current = 0;
    setElapsed(0);
  }, [activeChainIndex]);

  const handlePlayPause = useCallback(() => {
    if (chains.length === 0) return;
    if (!playing) {
      if (activeChainIndex >= 0) activateIndex(activeChainIndex);
      elapsedRef.current = 0;
      setElapsed(0);
    }
    setSequencePlaying(!playing);
  }, [playing, activeChainIndex, chains.length, activateIndex, setSequencePlaying]);

  const handleDurationClick = useCallback(
    (e: React.MouseEvent, idx: number) => {
      e.stopPropagation();
      setEditingDurationIdx(idx);
      setDraftDuration(String(chains[idx]?.durationSeconds ?? 30));
    },
    [chains],
  );

  const commitDuration = useCallback(() => {
    if (editingDurationIdx === null) return;
    const val = parseFloat(draftDuration);
    if (!isNaN(val) && val > 0) {
      updateChainDuration(editingDurationIdx, val);
    }
    setEditingDurationIdx(null);
  }, [editingDurationIdx, draftDuration, updateChainDuration]);

  const handleDurationKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter") commitDuration();
      if (e.key === "Escape") setEditingDurationIdx(null);
    },
    [commitDuration],
  );

  const handleRemoveChain = useCallback(
    (e: React.MouseEvent, idx: number) => {
      e.stopPropagation();
      removeChain(idx);
    },
    [removeChain],
  );

  const handleAddChain = useCallback(() => {
    addChain();
  }, [addChain]);

  // Total duration for proportional widths
  const totalDuration = chains.reduce((sum, c) => sum + c.durationSeconds, 0) || 1;
  const currentDuration = activeChain?.durationSeconds ?? 30;
  const progressPct = Math.min((elapsed / currentDuration) * 100, 100);

  return (
    <div
      onClick={(e) => e.stopPropagation()}
      style={{
        background: "rgba(29,32,33,0.96)",
        borderTop: "1px solid #3c3836",
        fontFamily: "JetBrains Mono, monospace",
        userSelect: "none",
      }}
    >
      {/* Sequence bar row */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          padding: "6px 8px",
          borderBottom: "1px solid #3c3836",
        }}
      >
        {/* Play/pause */}
        <button
          onClick={handlePlayPause}
          title={playing ? "Pause sequence" : "Play sequence"}
          disabled={chains.length === 0}
          style={{
            background: "none",
            border: "1px solid #504945",
            borderRadius: 2,
            padding: "2px 8px",
            fontSize: 13,
            color: chains.length === 0 ? "#3c3836" : playing ? "#fabd2f" : "#928374",
            cursor: chains.length === 0 ? "not-allowed" : "pointer",
            flexShrink: 0,
            lineHeight: 1,
          }}
        >
          {playing ? "⏸" : "▶"}
        </button>

        {/* Chain blocks */}
        <div
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            gap: 4,
            overflowX: "auto",
            overflowY: "hidden",
          }}
        >
          {chains.length === 0 && (
            <span style={{ fontSize: 9, color: "#504945", paddingLeft: 4 }}>
              no chains — press [+] to add one
            </span>
          )}
          {chains.map((chain, idx) => {
            const isActive = idx === activeChainIndex;
            const widthPct = (chain.durationSeconds / totalDuration) * 100;
            const presetSummary = summarizePresets(chain.presets);
            return (
              <div
                key={chain.id}
                onClick={() => handleSelectChain(idx)}
                title={`Chain ${idx + 1}: ${chain.presets.join(" → ") || "empty"}, ${chain.durationSeconds}s`}
                style={{
                  position: "relative",
                  flexShrink: 0,
                  width: `max(${MIN_BLOCK_WIDTH}px, ${widthPct}%)`,
                  maxWidth: 240,
                  height: BLOCK_HEIGHT,
                  background: isActive ? "rgba(250,189,47,0.10)" : "rgba(60,56,54,0.5)",
                  border: isActive ? "1.5px solid #fabd2f" : "1px solid #504945",
                  borderRadius: 3,
                  cursor: "pointer",
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                  padding: "4px 6px",
                  overflow: "hidden",
                }}
              >
                {/* Progress fill for active+playing */}
                {isActive && playing && (
                  <div
                    style={{
                      position: "absolute",
                      top: 0,
                      left: 0,
                      height: "100%",
                      width: `${progressPct}%`,
                      background: "rgba(250,189,47,0.12)",
                      pointerEvents: "none",
                      transition: "width 0.4s linear",
                    }}
                  />
                )}

                {/* Top row: chain number + remove button */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    zIndex: 1,
                  }}
                >
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: "bold",
                      color: isActive ? "#fabd2f" : "#928374",
                    }}
                  >
                    C{idx + 1}
                  </span>
                  <button
                    onClick={(e) => handleRemoveChain(e, idx)}
                    title="Remove chain"
                    style={{
                      background: "none",
                      border: "none",
                      fontSize: 10,
                      color: "#504945",
                      cursor: "pointer",
                      padding: 0,
                      lineHeight: 1,
                      zIndex: 2,
                    }}
                  >
                    ×
                  </button>
                </div>

                {/* Preset names */}
                <div
                  style={{
                    fontSize: 9,
                    color: isActive ? "#ebdbb2" : "#665c54",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    zIndex: 1,
                  }}
                >
                  {presetSummary}
                </div>

                {/* Duration row */}
                <div style={{ zIndex: 1 }}>
                  {editingDurationIdx === idx ? (
                    <input
                      autoFocus
                      value={draftDuration}
                      onChange={(e) => setDraftDuration(e.target.value)}
                      onBlur={commitDuration}
                      onKeyDown={handleDurationKeyDown}
                      onClick={(e) => e.stopPropagation()}
                      style={{
                        width: 40,
                        fontSize: 9,
                        background: "#1d2021",
                        border: "1px solid #fabd2f",
                        borderRadius: 1,
                        color: "#fabd2f",
                        fontFamily: "JetBrains Mono, monospace",
                        padding: "0 2px",
                      }}
                    />
                  ) : (
                    <span
                      onClick={(e) => handleDurationClick(e, idx)}
                      style={{
                        fontSize: 9,
                        color: "#504945",
                        cursor: "text",
                        textDecoration: "underline dotted",
                      }}
                    >
                      {chain.durationSeconds}s
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Add chain — prominent dashed button */}
        <button
          onClick={handleAddChain}
          title="Add chain"
          style={{
            background: "none",
            border: "1.5px dashed #928374",
            borderRadius: 3,
            width: 40,
            height: BLOCK_HEIGHT,
            fontSize: 18,
            color: "#928374",
            cursor: "pointer",
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            lineHeight: 1,
          }}
        >
          +
        </button>

        {/* Status indicators */}
        {activating && (
          <span style={{ fontSize: 9, color: "#fabd2f", flexShrink: 0 }}>…</span>
        )}

        {/* Loop toggle */}
        <button
          onClick={() => setSequenceLooping(!looping)}
          title={looping ? "Looping on" : "Looping off"}
          style={{
            background: "none",
            border: "1px solid #504945",
            borderRadius: 2,
            padding: "2px 6px",
            fontSize: 10,
            color: looping ? "#b8bb26" : "#504945",
            cursor: "pointer",
            flexShrink: 0,
          }}
        >
          ↺
        </button>
      </div>

      {/* Visual connector: downward arrow from active chain to ChainBuilder */}
      {activeChainIndex >= 0 && (
        <div
          style={{
            height: 6,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#fabd2f",
            fontSize: 8,
            lineHeight: 1,
            background: "rgba(250,189,47,0.04)",
            borderBottom: "1px solid #3c3836",
          }}
        >
          ▼
        </div>
      )}
    </div>
  );
}

export const SequenceBar = memo(SequenceBarInner);
