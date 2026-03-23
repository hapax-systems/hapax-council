/**
 * VoiceOverlay — portal z-50 over Ground during voice sessions.
 * Extracted from HapaxPage voice session rendering.
 *
 * Experiment monitoring: shows live grounding scores, activation bar,
 * turn counter, word cutoff indicator, and frustration trend.
 */

import { memo } from "react";
import type { VisualLayerState } from "../../../api/types";

// Voice state → palette token (theme-aware per §3.6)
const VOICE_STATE_COLORS: Record<string, string> = {
  listening: "var(--color-green-400)",
  transcribing: "var(--color-green-400)",
  thinking: "var(--color-yellow-400)",
  speaking: "var(--color-blue-400)",
};

const DEFAULT_VOICE = {
  active: false,
  state: "idle",
  turn_count: 0,
  last_utterance: "",
  last_response: "",
  active_tool: null as string | null,
  barge_in: false,
  routing_tier: "",
  routing_reason: "",
  routing_activation: 0.0,
  context_anchor_success: 0.0,
  frustration_score: 0.0,
  frustration_rolling_avg: 0.0,
  acceptance_type: "",
  spoken_words: 0,
  word_limit: 35,
};

// Acceptance → severity ladder (§3.7)
const ACCEPTANCE_COLORS: Record<string, string> = {
  ACCEPT: "var(--color-green-400)",
  CLARIFY: "var(--color-yellow-400)",
  REJECT: "var(--color-red-400)",
  IGNORE: "var(--color-zinc-500)",
};

interface VoiceOverlayProps {
  vl: VisualLayerState | undefined;
}

export const VoiceOverlay = memo(function VoiceOverlay({ vl }: VoiceOverlayProps) {
  const voiceSession = vl?.voice_session ?? DEFAULT_VOICE;
  const voiceContent = vl?.voice_content ?? [];
  if (!voiceSession.active) return null;

  const tierIntensity: Record<string, number> = {
    LOCAL: 0.3,
    FAST: 0.5,
    STRONG: 0.75,
    CAPABLE: 1.0,
  };
  const voiceIntensity = tierIntensity[voiceSession.routing_tier] ?? 0.5;
  const stateColor = VOICE_STATE_COLORS[voiceSession.state] ?? "var(--color-zinc-500)";
  const activation = voiceSession.routing_activation ?? 0;
  const anchor = voiceSession.context_anchor_success ?? 0;
  const frustration = voiceSession.frustration_score ?? 0;
  const frustrationAvg = voiceSession.frustration_rolling_avg ?? 0;
  const acceptance = voiceSession.acceptance_type ?? "";
  const spokenWords = voiceSession.spoken_words ?? 0;
  const wordLimit = voiceSession.word_limit ?? 35;
  const wordRatio = wordLimit > 0 ? Math.min(1, spokenWords / wordLimit) : 0;

  return (
    <div
      className="absolute inset-0 pointer-events-none"
      style={{ zIndex: 50 }}
    >
      {/* Voice indicator — bottom center of Ground area */}
      <div
        className="absolute left-1/2 -translate-x-1/2 pointer-events-auto"
        style={{ bottom: "max(16px, 12vh)", animation: "voiceIn 1.5s ease-out forwards" }}
      >
        <div
          className="flex items-center gap-3 backdrop-blur-md rounded-full px-6 py-3"
          style={{
            background: "color-mix(in srgb, var(--color-zinc-950) 80%, transparent)",
            boxShadow:
              voiceIntensity > 0.5
                ? `0 0 ${20 + voiceIntensity * 30}px ${stateColor}20`
                : "none",
            transition: "box-shadow 0.5s ease",
          }}
        >
          {/* State dot */}
          <div
            style={{
              width: `${8 + voiceIntensity * 6}px`,
              height: `${8 + voiceIntensity * 6}px`,
              borderRadius: "50%",
              background: stateColor,
              boxShadow: `0 0 ${6 + voiceIntensity * 12}px ${stateColor}`,
              animation:
                voiceSession.state === "listening" ? "pulse 2s ease-in-out infinite" : undefined,
              transition: "width 0.3s ease, height 0.3s ease, box-shadow 0.5s ease",
            }}
          />
          <span
            className="text-xs uppercase tracking-[0.3em] font-medium"
            style={{ color: stateColor }}
          >
            {voiceSession.state}
          </span>
          {/* Turn counter */}
          <span className="text-[9px] text-white/30 tabular-nums">
            T{voiceSession.turn_count}
          </span>
          {voiceIntensity >= 0.75 && (
            <span
              className="text-[9px] uppercase tracking-[0.2em]"
              style={{ color: stateColor, opacity: 0.4 }}
            >
              {voiceSession.routing_tier}
            </span>
          )}
          {voiceSession.active_tool && (
            <span className="text-[10px] text-white/40 ml-2">{voiceSession.active_tool}</span>
          )}
          {voiceSession.barge_in && (
            <span className="text-[9px] text-amber-400/60 ml-1">&uarr;</span>
          )}
        </div>

        {/* Experiment monitoring bar */}
        <div
          className="flex items-center gap-2 mt-2 px-4"
          style={{ opacity: 0.5 }}
        >
          {/* Activation bar */}
          <div className="flex items-center gap-1" title={`activation: ${activation.toFixed(2)}`}>
            <span className="text-[8px] text-white/30 uppercase">act</span>
            <div
              style={{
                width: "40px",
                height: "3px",
                background: "rgba(255,255,255,0.1)",
                borderRadius: "1.5px",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${activation * 100}%`,
                  height: "100%",
                  background: stateColor,
                  transition: "width 0.3s ease",
                }}
              />
            </div>
          </div>

          {/* Context anchor score */}
          <div className="flex items-center gap-1" title={`anchor: ${anchor.toFixed(2)}`}>
            <span className="text-[8px] text-white/30 uppercase">ctx</span>
            <div
              style={{
                width: "40px",
                height: "3px",
                background: "rgba(255,255,255,0.1)",
                borderRadius: "1.5px",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${anchor * 100}%`,
                  height: "100%",
                  background: anchor > 0.5 ? "var(--color-green-400)" : "var(--color-yellow-400)",
                  transition: "width 0.3s ease",
                }}
              />
            </div>
          </div>

          {/* Frustration indicator */}
          <div
            className="flex items-center gap-1"
            title={`frustration: ${frustration.toFixed(2)} (avg: ${frustrationAvg.toFixed(2)})`}
          >
            <span
              className="text-[8px] uppercase"
              style={{ color: frustrationAvg > 0.5 ? "var(--color-red-400)" : "rgba(255,255,255,0.3)" }}
            >
              frs
            </span>
            <div
              style={{
                width: "40px",
                height: "3px",
                background: "rgba(255,255,255,0.1)",
                borderRadius: "1.5px",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${Math.min(1, frustrationAvg) * 100}%`,
                  height: "100%",
                  background: frustrationAvg > 0.5 ? "var(--color-red-400)" : frustrationAvg > 0.3 ? "var(--color-yellow-400)" : "var(--color-green-400)",
                  transition: "width 0.3s ease",
                }}
              />
            </div>
          </div>

          {/* Acceptance type */}
          {acceptance && (
            <span
              className="text-[8px] uppercase"
              style={{ color: ACCEPTANCE_COLORS[acceptance] ?? "var(--color-zinc-500)" }}
            >
              {acceptance}
            </span>
          )}

          {/* Word cutoff indicator */}
          {spokenWords > 0 && (
            <div
              className="flex items-center gap-1"
              title={`${spokenWords}/${wordLimit} words`}
            >
              <span
                className="text-[8px] tabular-nums"
                style={{
                  color: wordRatio > 0.8 ? "var(--color-red-400)" : "rgba(255,255,255,0.3)",
                }}
              >
                {spokenWords}/{wordLimit}w
              </span>
            </div>
          )}
        </div>

        {/* Last utterance */}
        {voiceSession.last_utterance && (
          <div
            className="text-center mt-2 text-xs max-w-md mx-auto"
            style={{
              color:
                voiceSession.state === "speaking"
                  ? "rgba(255,255,255,0.1)"
                  : "rgba(255,255,255,0.25)",
              transition: "color 0.5s ease",
            }}
          >
            {voiceSession.last_utterance}
          </div>
        )}

        {/* Last response */}
        {voiceSession.state === "speaking" && voiceSession.last_response && (
          <div
            className="text-center mt-1 text-xs max-w-md mx-auto"
            style={{
              color: "color-mix(in srgb, var(--color-blue-400) 50%, transparent)",
              animation: "fragmentIn 1s ease-out forwards",
            }}
          >
            {voiceSession.last_response.slice(0, 120)}
          </div>
        )}
      </div>

      {/* Supplementary content cards */}
      {voiceContent.length > 0 && (
        <div
          className="absolute top-[15%] right-[5%] flex flex-col gap-3 max-w-sm max-h-[50vh] overflow-y-auto pointer-events-auto"
        >
          {voiceContent.map((content, i) => (
            <div
              key={`${content.content_type}-${content.timestamp}`}
              className="backdrop-blur-md rounded-xl p-4"
              style={{
                background: "color-mix(in srgb, var(--color-zinc-950) 80%, transparent)",
                animation: `contentIn 2s ease-out ${i * 0.3}s both`,
              }}
            >
              <div className="text-[9px] uppercase tracking-[0.3em] text-white/30 mb-1">
                {content.content_type}
              </div>
              <div className="text-sm text-white/80 font-medium">{content.title}</div>
              {content.body && (
                <div className="text-xs text-white/50 mt-1 line-clamp-3">{content.body}</div>
              )}
            </div>
          ))}
        </div>
      )}

      <style>{`
        @keyframes voiceIn {
          from { opacity: 0; transform: translate(-50%, 20px); }
          to { opacity: 1; transform: translate(-50%, 0); }
        }
        @keyframes contentIn {
          from { opacity: 0; transform: translateX(20px); }
          to { opacity: 1; transform: translateX(0); }
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
        @keyframes fragmentIn {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 0.08; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
});
