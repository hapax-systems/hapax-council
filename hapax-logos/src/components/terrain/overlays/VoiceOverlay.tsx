/**
 * VoiceOverlay — portal z-50 over Ground during voice sessions.
 * Extracted from HapaxPage voice session rendering.
 */

import type { useVisualLayerPoll } from "../../../hooks/useVisualLayer";

const VOICE_STATE_COLORS: Record<string, string> = {
  listening: "#4ddb99",
  transcribing: "#4ddb99",
  thinking: "#dbb84d",
  speaking: "#4d99db",
};

interface VoiceOverlayProps {
  vl: ReturnType<typeof useVisualLayerPoll>;
}

export function VoiceOverlay({ vl }: VoiceOverlayProps) {
  const { voiceSession, voiceContent } = vl;
  if (!voiceSession.active) return null;

  const tierIntensity: Record<string, number> = {
    LOCAL: 0.3,
    FAST: 0.5,
    STRONG: 0.75,
    CAPABLE: 1.0,
  };
  const voiceIntensity = tierIntensity[voiceSession.routing_tier] ?? 0.5;
  const stateColor = VOICE_STATE_COLORS[voiceSession.state] ?? "#999";

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
            background: "rgba(0,0,0,0.6)",
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
              color: `${VOICE_STATE_COLORS.speaking}80`,
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
                background: "rgba(0,0,0,0.6)",
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
}
