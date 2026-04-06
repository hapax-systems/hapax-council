import { memo, useCallback, useEffect, useRef, useState } from "react";
import { useStudioGraph, type PresetChain } from "../../stores/studioGraphStore";
import { fetchPresetGraph, type EffectGraphJson } from "./presetLoader";
import { mergePresetGraphs, countSlots, MAX_SLOTS } from "./presetMerger";
import { api } from "../../api/client";
import { PRESET_CATEGORIES } from "./presetData";

/** Activate a chain of presets on the compositor. Retries once on failure. */
export async function activatePresets(
  presets: string[],
  onSlotCount?: (n: number) => void,
  source = "@live",
  cameraSource = "live",
): Promise<void> {
  if (presets.length === 0) {
    api.post("/studio/effect/select", { preset: "clean" }).catch(() => {});
    onSlotCount?.(0);
    return;
  }
  if (presets.length === 1) {
    api.post("/studio/effect/select", { preset: presets[0], fx_source: cameraSource }).catch(() => {});
    onSlotCount?.(0);
    return;
  }

  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const graphs: EffectGraphJson[] = [];
      for (const name of presets) {
        const g = await fetchPresetGraph(name);
        if (g) graphs.push(g);
        else console.warn(`[activatePresets] fetchPresetGraph("${name}") returned null`);
      }
      if (graphs.length === 0) {
        console.warn("[activatePresets] no valid graphs fetched, aborting");
        return;
      }
      const slots = countSlots(graphs);
      onSlotCount?.(slots);
      if (slots > MAX_SLOTS) {
        console.warn(`[activatePresets] ${slots} slots exceeds MAX_SLOTS ${MAX_SLOTS}`);
        return;
      }
      const merged = mergePresetGraphs("chain", graphs, source);
      const payload = { ...merged, fx_source: cameraSource };
      try {
        await api.put("/studio/effect/graph", payload);
      } catch (putErr) {
        // PUT failed — fall back to writing mutation file via POST select
        // for the first preset as a degraded activation
        if (presets.length > 0) {
          await api.post("/studio/effect/select", { preset: presets[0] });
        }
        throw putErr;
      }
      return;
    } catch (err) {
      console.error(`[activatePresets] attempt ${attempt} failed:`, err);
      if (attempt === 0) await new Promise((r) => setTimeout(r, 500));
    }
  }
}

// Presets that genuinely destroy source recognizability.
// Every chain MUST include at least one of these.
// Excluded: mirror_rorschach, feedback, ghost, trails, diff, fisheye_pulse,
// screwed, voronoi — these transform but don't obscure identity.
const OBSCURING = new Set([
  "datamosh", "datamosh_heavy", "glitch_blocks_preset", "trap",
  "vhs_preset", "kaleidodream", "tunnelvision", "slitscan_preset",
  "thermal_preset",
  "ascii_preset", "halftone_preset", "dither_retro", "silhouette",
  "sculpture", "neon", "pixsort_preset",
]);

// Chain compatibility tags — every preset can chain, but certain combos conflict.
// Tags: "pattern" (converts to dots/chars/dither), "sparse" (edge detect, mostly
// black output), "temporal" (trail/feedback accumulation), "mono" (desaturates/B&W).
const TAGS: Record<string, Set<string>> = {
  ascii_preset: new Set(["pattern", "mono"]),
  halftone_preset: new Set(["pattern", "mono", "scanline"]),
  dither_retro: new Set(["pattern", "mono"]),
  silhouette: new Set(["sparse", "mono"]),
  sculpture: new Set(["sparse", "temporal", "mono"]),
  neon: new Set(["sparse"]),
  pixsort_preset: new Set(["pattern", "sparse"]),
  slitscan_preset: new Set(["temporal"]),
  nightvision: new Set(["mono"]),
  voronoi_crystal: new Set(["sparse"]),
  vhs_preset: new Set(["scanline"]),
  diff_preset: new Set(["mono", "sparse"]),
  ambient: new Set(["mono", "dim"]),
  heartbeat: new Set(["dim"]),
  thermal_preset: new Set(["sparse"]),
  trap: new Set(["glitch"]),
  datamosh: new Set(["glitch"]),
  datamosh_heavy: new Set(["glitch"]),
  glitch_blocks_preset: new Set(["glitch"]),
  screwed: new Set(["glitch"]),
  feedback_preset: new Set(["temporal"]),
  ghost: new Set(["temporal"]),
  trails: new Set(["temporal"]),
};
// Rule: a chain cannot contain two presets that share the same tag.
// Also: "sparse" + "temporal" is forbidden (accumulates black).
function canAdd(chain: string[], candidate: string): boolean {
  const candidateTags = TAGS[candidate] ?? new Set();
  for (const existing of chain) {
    const existingTags = TAGS[existing] ?? new Set();
    // No two of the same tag
    for (const t of candidateTags) {
      if (existingTags.has(t)) return false;
    }
    // sparse + temporal forbidden (accumulates black)
    // glitch + temporal forbidden (glitch fragments accumulate dark)
    if (
      (candidateTags.has("glitch") && existingTags.has("temporal")) ||
      (candidateTags.has("temporal") && existingTags.has("glitch")) ||
      (candidateTags.has("glitch") && existingTags.has("sparse")) ||
      (candidateTags.has("sparse") && existingTags.has("glitch")) ||
      (candidateTags.has("pattern") && existingTags.has("temporal")) ||
      (candidateTags.has("temporal") && existingTags.has("pattern")) ||
      (candidateTags.has("sparse") && existingTags.has("temporal")) ||
      (candidateTags.has("temporal") && existingTags.has("sparse"))
    ) return false;
  }
  return true;
}

// Available FX input sources: tiled composite + individual cameras
// Base source is always an individual camera — never "live" (tiled composite).
// The live view flashes as an overlay at 60% opacity on a random schedule.
// Only BRIOs — C920s have persistent USB errors after hot-plug cycles.
const FX_SOURCES = [
  "brio-operator", "brio-room", "brio-synths",
];

function generateRandomSequence(): PresetChain[] {
  const allPresets = PRESET_CATEGORIES.flatMap((c) => c.presets)
    .filter((p) => !["clean", "echo", "reverie_vocabulary", "ambient", "heartbeat", "nightvision"].includes(p));
  const numChains = 8 + Math.floor(Math.random() * 5); // 8-12 chains
  const chains: PresetChain[] = [];
  let lastUsed: string[] = [];
  let lastSource = "";

  for (let i = 0; i < numChains; i++) {
    const presets: string[] = [];
    const pool = [...allPresets]
      .filter((p) => !lastUsed.includes(p))
      .sort(() => Math.random() - 0.5);
    const fallback = [...allPresets].sort(() => Math.random() - 0.5);
    const available = pool.length >= 5 ? pool : fallback;

    // Pick 2-3 compatible presets
    const chainSize = Math.random() < 0.65 ? 3 : 2;
    for (const p of available) {
      if (presets.length >= chainSize) break;
      if (presets.includes(p)) continue;
      if (!canAdd(presets, p)) continue;
      presets.push(p);
    }

    if (presets.length === 0) continue;
    // Anonymity: ensure at least one obscuring preset in every chain
    if (!presets.some((p) => OBSCURING.has(p))) {
      const obscPool = available.filter(
        (p) => OBSCURING.has(p) && !presets.includes(p) && canAdd(presets, p),
      );
      if (obscPool.length > 0) presets.push(obscPool[0]);
    }
    lastUsed = [...presets];

    // Pick a random camera source, avoid repeating consecutively
    const srcPool = FX_SOURCES.filter((s) => s !== lastSource);
    const source = srcPool[Math.floor(Math.random() * srcPool.length)];
    lastSource = source;

    chains.push({
      id: crypto.randomUUID(),
      presets,
      durationSeconds: 15 + Math.floor(Math.random() * 10), // 15-25s, capped at 25
      source,
    });
  }
  return chains;
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
  const setSequenceChains = useStudioGraph((s) => s.setSequenceChains);
  const addChain = useStudioGraph((s) => s.addChain);
  const removeChain = useStudioGraph((s) => s.removeChain);
  const updateChainDuration = useStudioGraph((s) => s.updateChainDuration);
  const setChainSlotCount = useStudioGraph((s) => s.setChainSlotCount);
  const savedSequences = useStudioGraph((s) => s.savedSequences);
  const sequenceName = useStudioGraph((s) => s.sequenceName);
  const saveSequence = useStudioGraph((s) => s.saveSequence);
  const loadSequence = useStudioGraph((s) => s.loadSequence);
  const deleteSequence = useStudioGraph((s) => s.deleteSequence);
  const setSequenceName = useStudioGraph((s) => s.setSequenceName);

  const [editingDurationIdx, setEditingDurationIdx] = useState<number | null>(null);
  const [draftDuration, setDraftDuration] = useState("");
  const [elapsed, setElapsed] = useState(0); // seconds elapsed in current chain
  const [activating, setActivating] = useState(false);

  const elapsedRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const shuffleModeRef = useRef(false);

  const { chains, activeChainIndex, playing, looping } = sequence;
  const activeChain = activeChainIndex >= 0 ? chains[activeChainIndex] : undefined;

  // Activate a chain by index — reads from store directly to avoid stale closures
  const activateIndex = useCallback(
    async (idx: number) => {
      const current = useStudioGraph.getState().sequence.chains;
      const chain = current[idx];
      if (!chain) return;
      setActivating(true);
      try {
        await activatePresets(chain.presets, setChainSlotCount, "@live", chain.source ?? "live");
      } finally {
        setActivating(false);
      }
    },
    [setChainSlotCount],
  );

  // Select chain (click)
  const handleSelectChain = useCallback(
    (idx: number) => {
      console.log(`[chain-click] selecting chain ${idx}`);
      setActiveChainIndex(idx);
      activateIndex(idx).catch((err: unknown) => console.error("[chain-click] activation failed:", err));
      elapsedRef.current = 0;
      setElapsed(0);
    },
    [setActiveChainIndex, activateIndex],
  );

  // Advance to next chain — reads from store to avoid stale closures
  const advanceChain = useCallback(() => {
    const state = useStudioGraph.getState().sequence;
    const currentChains = state.chains;
    const currentIdx = state.activeChainIndex;
    if (currentChains.length === 0) return;
    const nextIdx = currentIdx + 1;
    if (nextIdx >= currentChains.length) {
      if (looping && shuffleModeRef.current) {
        // Re-randomize only in shuffle mode
        const newChains = generateRandomSequence();
        setSequenceChains(newChains);
        setActiveChainIndex(0);
        const firstChain = newChains[0];
        if (firstChain) {
          activatePresets(firstChain.presets, setChainSlotCount, "@live", firstChain.source ?? "live").catch(() => {});
        }
        elapsedRef.current = 0;
        setElapsed(0);
      } else if (looping) {
        // Normal loop: restart from beginning without re-randomizing
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
  }, [looping, setActiveChainIndex, activateIndex, setSequencePlaying, setSequenceChains, setChainSlotCount]);

  // Timer effect — reads from store to avoid stale closure
  useEffect(() => {
    if (!playing) {
      if (timerRef.current) clearInterval(timerRef.current);
      timerRef.current = null;
      return;
    }
    timerRef.current = setInterval(() => {
      elapsedRef.current += 0.5;
      setElapsed(elapsedRef.current);
      const state = useStudioGraph.getState().sequence;
      const duration = state.chains[state.activeChainIndex]?.durationSeconds ?? 30;
      if (elapsedRef.current >= duration) {
        elapsedRef.current = 0;
        setElapsed(0);
        advanceChain();
      }
    }, 500);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [playing, advanceChain]);

  // Reset elapsed when chain changes externally
  useEffect(() => {
    elapsedRef.current = 0;
    setElapsed(0);
  }, [activeChainIndex]);

  const handlePlayPause = useCallback(() => {
    const state = useStudioGraph.getState().sequence;
    if (state.chains.length === 0) return;
    if (!state.playing) {
      if (state.activeChainIndex >= 0) activateIndex(state.activeChainIndex);
      elapsedRef.current = 0;
      setElapsed(0);
    }
    setSequencePlaying(!state.playing);
  }, [activateIndex, setSequencePlaying]);

  const handleShuffle = useCallback(() => {
    shuffleModeRef.current = true;
    const newChains = generateRandomSequence();
    setSequenceChains(newChains);
    setActiveChainIndex(0);
    setSequenceLooping(true);
    setSequencePlaying(true);
    elapsedRef.current = 0;
    setElapsed(0);
    const firstChain = newChains[0];
    if (firstChain) {
      activatePresets(firstChain.presets, setChainSlotCount, "@live", firstChain.source ?? "live").catch(() => {});
    }
  }, [setSequenceChains, setActiveChainIndex, setSequenceLooping, setSequencePlaying, setChainSlotCount]);

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

        {/* Shuffle */}
        <button
          onClick={handleShuffle}
          title="Random sequence"
          style={{
            background: "none",
            border: "1px solid #504945",
            borderRadius: 2,
            padding: "2px 6px",
            fontSize: 9,
            fontFamily: "JetBrains Mono, monospace",
            color: "#928374",
            cursor: "pointer",
            flexShrink: 0,
          }}
        >
          shuffle
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

        {/* Sequence save/load controls */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 3,
            flexShrink: 0,
            borderLeft: "1px solid #3c3836",
            paddingLeft: 6,
          }}
        >
          {/* Name input */}
          <input
            value={sequenceName}
            onChange={(e) => setSequenceName(e.target.value)}
            placeholder="sequence name"
            style={{
              width: 88,
              fontSize: 9,
              fontFamily: "JetBrains Mono, monospace",
              background: "#3c3836",
              border: "1px solid #504945",
              borderRadius: 2,
              color: "#928374",
              padding: "1px 4px",
              outline: "none",
            }}
          />
          {/* Save button */}
          <button
            onClick={() => {
              if (sequenceName.trim()) saveSequence(sequenceName.trim());
            }}
            title="Save sequence"
            disabled={!sequenceName.trim()}
            style={{
              background: "none",
              border: "1px solid #504945",
              borderRadius: 2,
              padding: "1px 5px",
              fontSize: 9,
              fontFamily: "JetBrains Mono, monospace",
              color: sequenceName.trim() ? "#928374" : "#3c3836",
              cursor: sequenceName.trim() ? "pointer" : "not-allowed",
              flexShrink: 0,
            }}
          >
            💾
          </button>
          {/* Load dropdown */}
          {Object.keys(savedSequences).length > 0 && (
            <>
              <select
                value=""
                onChange={(e) => {
                  if (e.target.value) loadSequence(e.target.value);
                }}
                title="Load saved sequence"
                style={{
                  fontSize: 9,
                  fontFamily: "JetBrains Mono, monospace",
                  background: "#3c3836",
                  border: "1px solid #504945",
                  borderRadius: 2,
                  color: "#928374",
                  padding: "1px 2px",
                  cursor: "pointer",
                  maxWidth: 96,
                }}
              >
                <option value="" disabled>
                  load…
                </option>
                {Object.keys(savedSequences).map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
              {/* Delete button for currently loaded sequence */}
              {sequenceName && savedSequences[sequenceName] && (
                <button
                  onClick={() => deleteSequence(sequenceName)}
                  title={`Delete "${sequenceName}"`}
                  style={{
                    background: "none",
                    border: "1px solid #504945",
                    borderRadius: 2,
                    padding: "1px 4px",
                    fontSize: 9,
                    fontFamily: "JetBrains Mono, monospace",
                    color: "#665c54",
                    cursor: "pointer",
                    flexShrink: 0,
                  }}
                >
                  ×
                </button>
              )}
            </>
          )}
        </div>
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
