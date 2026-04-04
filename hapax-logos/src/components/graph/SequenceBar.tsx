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

const BAR_HEIGHT = 32;
const MIN_BLOCK_WIDTH = 60;

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
  const activeChain = chains[activeChainIndex];

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
    if (!playing) {
      // Activate current chain immediately when starting playback
      activateIndex(activeChainIndex);
      elapsedRef.current = 0;
      setElapsed(0);
    }
    setSequencePlaying(!playing);
  }, [playing, activeChainIndex, activateIndex, setSequencePlaying]);

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

  // Total duration for proportional widths
  const totalDuration = chains.reduce((sum, c) => sum + c.durationSeconds, 0) || 1;
  const currentDuration = activeChain?.durationSeconds ?? 30;
  const progressPct = Math.min((elapsed / currentDuration) * 100, 100);

  return (
    <div
      onClick={(e) => e.stopPropagation()}
      style={{
        position: "absolute",
        bottom: 0,
        left: 0,
        right: 0,
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
          gap: 4,
          padding: "4px 8px",
          height: BAR_HEIGHT + 8,
          borderBottom: "1px solid #3c3836",
        }}
      >
        {/* Play/pause */}
        <button
          onClick={handlePlayPause}
          title={playing ? "Pause sequence" : "Play sequence"}
          style={{
            background: "none",
            border: "1px solid #504945",
            borderRadius: 2,
            padding: "1px 6px",
            fontSize: 13,
            color: playing ? "#fabd2f" : "#928374",
            cursor: "pointer",
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
            gap: 2,
            overflow: "hidden",
          }}
        >
          {chains.map((chain, idx) => {
            const isActive = idx === activeChainIndex;
            const widthPct = (chain.durationSeconds / totalDuration) * 100;
            const minW = MIN_BLOCK_WIDTH;
            return (
              <div
                key={chain.id}
                onClick={() => handleSelectChain(idx)}
                title={`Chain ${idx + 1}: ${chain.presets.length} preset(s), ${chain.durationSeconds}s`}
                style={{
                  position: "relative",
                  flexShrink: 0,
                  width: `max(${minW}px, ${widthPct}%)`,
                  maxWidth: 200,
                  height: BAR_HEIGHT,
                  background: isActive ? "rgba(250,189,47,0.10)" : "rgba(60,56,54,0.5)",
                  border: isActive
                    ? "1px solid #fabd2f"
                    : "1px solid #504945",
                  borderRadius: 2,
                  cursor: "pointer",
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "center",
                  padding: "0 4px",
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
                      background: "rgba(250,189,47,0.15)",
                      pointerEvents: "none",
                      transition: "width 0.4s linear",
                    }}
                  />
                )}

                {/* Chain label */}
                <div
                  style={{
                    fontSize: 9,
                    color: isActive ? "#fabd2f" : "#928374",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    zIndex: 1,
                  }}
                >
                  {`C${idx + 1}`}
                  {chain.presets.length > 0 && (
                    <span style={{ color: "#665c54", marginLeft: 3 }}>
                      {chain.presets.length}p
                    </span>
                  )}
                </div>

                {/* Duration (click to edit) */}
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
                        width: 36,
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
                        color: "#665c54",
                        cursor: "text",
                        textDecoration: "underline dotted",
                      }}
                    >
                      {chain.durationSeconds}s
                    </span>
                  )}
                </div>

                {/* Remove button */}
                {chains.length > 1 && (
                  <button
                    onClick={(e) => handleRemoveChain(e, idx)}
                    title="Remove chain"
                    style={{
                      position: "absolute",
                      top: 1,
                      right: 2,
                      background: "none",
                      border: "none",
                      fontSize: 8,
                      color: "#665c54",
                      cursor: "pointer",
                      padding: 0,
                      lineHeight: 1,
                      zIndex: 2,
                    }}
                  >
                    ×
                  </button>
                )}
              </div>
            );
          })}
        </div>

        {/* Add chain */}
        <button
          onClick={addChain}
          title="Add chain"
          style={{
            background: "none",
            border: "1px solid #504945",
            borderRadius: 2,
            padding: "1px 6px",
            fontSize: 12,
            color: "#928374",
            cursor: "pointer",
            flexShrink: 0,
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
            padding: "1px 6px",
            fontSize: 9,
            color: looping ? "#b8bb26" : "#504945",
            cursor: "pointer",
            flexShrink: 0,
          }}
        >
          ↺
        </button>
      </div>
    </div>
  );
}

export const SequenceBar = memo(SequenceBarInner);
