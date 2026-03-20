/**
 * HapaxPage — Hapax Corpora. The agent's visual body.
 *
 * Full-screen flexible injection canvas. No chrome. Hapax decides
 * what goes here based on system state, operator context, and mood.
 *
 * Philosophy: the display IS the agent, not a window into the agent.
 * When nothing needs attention, Hapax plays — generative, surprising,
 * alive. When signals arise, they layer on top of the visual richness.
 *
 * The operator doesn't read this display. They feel it.
 *
 * Keys: f=fullscreen, c=cameras, v=video-bg, s=signals
 */

import { useEffect, useState, useCallback, useRef } from "react";
import { AmbientShader } from "../components/hapax/AmbientShader";

const API = "/api";
const POLL_FAST_MS = 2000;
const SNAPSHOT_MS = 200; // camera composite refresh
const FRAGMENT_CYCLE_MS = 12000; // rotate floating text fragments

// ── Types ────────────────────────────────────────────────────────────────

interface SignalEntry {
  category: string;
  severity: number;
  title: string;
  detail: string;
  source_id: string;
}

interface AmbientParams {
  speed: number;
  turbulence: number;
  color_warmth: number;
  brightness: number;
}

interface VoiceSession {
  active: boolean;
  state: string;
  turn_count: number;
  last_utterance: string;
  last_response: string;
  active_tool: string | null;
  barge_in: boolean;
  routing_tier: string;
  routing_reason: string;
  routing_activation: number;
  // Experiment monitoring
  context_anchor_success: number;
  frustration_score: number;
  frustration_rolling_avg: number;
  acceptance_type: string;
  spoken_words: number;
  word_limit: number;
}

interface SupplementaryContent {
  content_type: string;
  title: string;
  body: string;
  image_path: string;
  timestamp: number;
}

interface InjectedFeed {
  role: string;
  x: number;
  y: number;
  w: number;
  h: number;
  opacity: number;
  css_filter: string;
  duration_s: number;
  injected_at: number;
}

interface VisualLayerState {
  available?: boolean;
  display_state: string;
  zone_opacities: Record<string, number>;
  signals: Record<string, SignalEntry[]>;
  ambient_params: AmbientParams;
  voice_session: VoiceSession;
  voice_content: SupplementaryContent[];
  injected_feeds: InjectedFeed[];
  ambient_text: string;
  activity_label: string;
  activity_detail: string;
  timestamp: number;
}

// ── Fallback ambient fragments (used when no dynamic content available) ──

const FALLBACK_FRAGMENTS = [
  "externalized executive function",
  "consent must thread invariantly",
  "what layer does this touch?",
  "let the angular behaviors glimmer",
  "subsumption: lower layers work independently",
  "the periphery informs without overburdening",
  "data is dreamed, not displayed",
  "if a machine can learn, can it also dream?",
  "confusion is a pedagogical tool",
  "LLMs are perspective machines",
  "proportionate to who they are",
  "23 minutes to recover from interruption",
  "the right amount is the minimum needed",
  "voice is the most expensive channel",
  "fractal complexity D=1.3 to 1.5",
];

// ── Color helpers ────────────────────────────────────────────────────────

const ZONE_COLORS: Record<string, string> = {
  context_time: "rgba(102, 153, 217, VAR)",
  governance: "rgba(77, 179, 179, VAR)",
  work_tasks: "rgba(217, 166, 77, VAR)",
  health_infra: "rgba(77, 204, 77, VAR)",
  profile_state: "rgba(230, 230, 230, VAR)",
  ambient_sensor: "rgba(153, 153, 179, VAR)",
  voice_session: "rgba(77, 217, 153, VAR)",
};

const SEVERITY_COLORS: Record<string, string> = {
  critical: "rgba(218, 54, 51, VAR)",
  high: "rgba(212, 123, 60, VAR)",
  medium: "rgba(210, 160, 68, VAR)",
  low: "rgba(102, 153, 217, VAR)",
};

const VOICE_STATE_COLORS: Record<string, string> = {
  listening: "#4ddb99",   // green
  transcribing: "#4ddb99",
  thinking: "#dbb84d",    // amber
  speaking: "#4d99db",    // blue
};

function sevLabel(sev: number): string {
  if (sev >= 0.85) return "critical";
  if (sev >= 0.7) return "high";
  if (sev >= 0.4) return "medium";
  return "low";
}

function zoneColor(cat: string, a: number): string {
  return (ZONE_COLORS[cat] ?? "rgba(128,128,128,VAR)").replace("VAR", String(a));
}

function sevColor(sev: number, a: number): string {
  return (SEVERITY_COLORS[sevLabel(sev)] ?? SEVERITY_COLORS.low).replace("VAR", String(a));
}

// ── Component ───────────────────────────────────────────────────────────

export function HapaxPage() {
  const [vlState, setVlState] = useState<VisualLayerState | null>(null);
  const [showCameras, setShowCameras] = useState(false);
  const [showVideo, setShowVideo] = useState(false);
  const [showSignals, setShowSignals] = useState(true);
  const [time, setTime] = useState(new Date());
  const [fragmentIdx, setFragmentIdx] = useState(0);
  const [showCorrection, setShowCorrection] = useState(false);
  const [correctionInput, setCorrectionInput] = useState("");
  const snapshotRef = useRef<HTMLImageElement>(null);

  // Poll visual layer state
  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const res = await fetch(`${API}/studio/visual-layer`);
        if (res.ok && active) setVlState(await res.json());
      } catch { /* offline */ }
    };
    poll();
    const id = setInterval(poll, POLL_FAST_MS);
    return () => { active = false; clearInterval(id); };
  }, []);

  // Snapshot refresh for video background
  useEffect(() => {
    if (!showVideo) return;
    const img = snapshotRef.current;
    if (!img) return;
    const refresh = () => {
      img.src = `${API}/studio/stream/snapshot?t=${Date.now()}`;
    };
    refresh();
    const id = setInterval(refresh, SNAPSHOT_MS);
    return () => clearInterval(id);
  }, [showVideo]);

  // Clock
  useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  // Rotating fallback fragments (only used when no dynamic ambient_text)
  useEffect(() => {
    const id = setInterval(() => {
      setFragmentIdx(prev => (prev + 1) % FALLBACK_FRAGMENTS.length);
    }, FRAGMENT_CYCLE_MS);
    return () => clearInterval(id);
  }, []);

  // Keyboard
  const handleKey = useCallback((e: KeyboardEvent) => {
    if (e.key === "c") setShowCameras(prev => !prev);
    if (e.key === "v") setShowVideo(prev => !prev);
    if (e.key === "s") setShowSignals(prev => !prev);
    if (e.key === "f") {
      if (document.fullscreenElement) document.exitFullscreen();
      else document.documentElement.requestFullscreen();
    }
  }, []);

  useEffect(() => {
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [handleKey]);

  const submitCorrection = useCallback(async () => {
    if (!correctionInput.trim()) return;
    try {
      await fetch(`${API}/studio/activity-correction`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label: correctionInput.trim() }),
      });
    } catch { /* ignore */ }
    setShowCorrection(false);
    setCorrectionInput("");
  }, [correctionInput]);

  const state = vlState?.display_state ?? "ambient";
  const signals = vlState?.signals ?? {};
  const opacities = vlState?.zone_opacities ?? {};
  const ambient = vlState?.ambient_params ?? { speed: 0.08, turbulence: 0.1, color_warmth: 0.3, brightness: 0.25 };
  const voiceSession = vlState?.voice_session ?? { active: false, state: "idle", turn_count: 0, last_utterance: "", last_response: "", active_tool: null, barge_in: false, routing_tier: "", routing_reason: "", routing_activation: 0.0, context_anchor_success: 0, frustration_score: 0, frustration_rolling_avg: 0, acceptance_type: "", spoken_words: 0, word_limit: 35 };

  // Routing tier modulates visual intensity — LOCAL is ambient, CAPABLE is intense
  const tierIntensity: Record<string, number> = { LOCAL: 0.3, FAST: 0.5, STRONG: 0.75, CAPABLE: 1.0 };
  const voiceIntensity = voiceSession.active ? (tierIntensity[voiceSession.routing_tier] ?? 0.5) : 0;
  const voiceContent = vlState?.voice_content ?? [];
  const injectedFeeds = vlState?.injected_feeds ?? [];
  const activityLabel = vlState?.activity_label ?? "present";
  const activityDetail = vlState?.activity_detail ?? "";
  const allSignals = Object.values(signals).flat();
  const hasSignals = allSignals.length > 0 && showSignals;
  const isAlert = state === "alert";
  const isPerformative = state === "performative";

  // Dynamic ambient text (from aggregator) or fallback
  const fragment = vlState?.ambient_text || FALLBACK_FRAGMENTS[fragmentIdx];

  return (
    <div
      className="h-screen w-screen overflow-hidden select-none cursor-none relative"
      style={{
        fontFamily: "'JetBrains Mono', monospace",
        background: "#060301",
      }}
    >
      {/* Layer 0: WebGL generative shader background
          Voice state modulates the visual field:
          - listening: slightly brighter, receptive
          - thinking: warmer, more turbulent (working)
          - speaking: cooler, calmer (delivering)
          Tier intensity scales the modulation magnitude */}
      <AmbientShader
        speed={voiceSession.state === "thinking"
          ? ambient.speed + 0.05 * voiceIntensity
          : ambient.speed}
        turbulence={voiceSession.state === "thinking"
          ? ambient.turbulence + 0.08 * voiceIntensity
          : ambient.turbulence}
        warmth={voiceSession.state === "thinking"
          ? ambient.color_warmth + 0.15 * voiceIntensity
          : voiceSession.state === "speaking"
            ? ambient.color_warmth - 0.05 * voiceIntensity
            : ambient.color_warmth}
        brightness={voiceSession.active
          ? ambient.brightness + 0.06 * voiceIntensity
          : ambient.brightness}
        displayState={state}
      />

      {/* Layer 0.5: Live compositor snapshot as background texture */}
      {showVideo && (
        <img
          ref={snapshotRef}
          alt=""
          className="absolute inset-0 w-full h-full object-cover"
          style={{
            opacity: isAlert ? 0.12 : isPerformative ? 0.5 : 0.2,
            filter: `saturate(${isPerformative ? 1.0 : 0.3}) contrast(${isPerformative ? 1.1 : 0.9}) brightness(${isPerformative ? 0.8 : 0.5}) sepia(0.4)`,
            transition: "opacity 2s ease, filter 2s ease",
            zIndex: 1,
          }}
        />
      )}

      {/* Layer 1: Organic floating shapes — generative CSS art */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none" style={{ zIndex: 2 }}>
        {/* Slowly drifting circles — visual richness, not emptiness */}
        <div
          className="absolute rounded-full"
          style={{
            width: "40vw", height: "40vw",
            left: "10%", top: "20%",
            background: "radial-gradient(circle, rgba(120,45,10,0.08) 0%, transparent 70%)",
            animation: `drift1 ${25 + ambient.speed * 30}s ease-in-out infinite alternate`,
          }}
        />
        <div
          className="absolute rounded-full"
          style={{
            width: "30vw", height: "30vw",
            right: "5%", bottom: "10%",
            background: "radial-gradient(circle, rgba(160,70,15,0.06) 0%, transparent 70%)",
            animation: `drift2 ${30 + ambient.speed * 25}s ease-in-out infinite alternate`,
          }}
        />
        <div
          className="absolute rounded-full"
          style={{
            width: "50vw", height: "50vw",
            left: "40%", top: "-10%",
            background: "radial-gradient(circle, rgba(90,25,8,0.07) 0%, transparent 70%)",
            animation: `drift3 ${35 + ambient.speed * 20}s ease-in-out infinite alternate`,
          }}
        />
      </div>

      {/* Layer 2: Floating text fragments — Hapax being playful */}
      <div className="absolute inset-0 flex items-end justify-start p-12 pointer-events-none" style={{ zIndex: 3 }}>
        <div className="relative h-16 overflow-hidden">
          <div
            key={fragment}
            className="text-white/8 text-2xl font-light tracking-wider leading-relaxed"
            style={{
              animation: "fragmentIn 3s ease-out forwards",
            }}
          >
            {fragment}
          </div>
        </div>
      </div>

      {/* Layer 3: Injected camera feeds (Batch F) */}
      {injectedFeeds.map((feed) => (
        <div
          key={`${feed.role}-${feed.injected_at}`}
          className="absolute overflow-hidden rounded-xl"
          style={{
            left: `${feed.x * 100}%`,
            top: `${feed.y * 100}%`,
            width: `${feed.w * 100}%`,
            height: `${feed.h * 100}%`,
            opacity: feed.opacity,
            filter: feed.css_filter,
            transition: "opacity 2s ease",
            animation: "feedIn 2s ease-out forwards",
            zIndex: 4,
          }}
        >
          <img
            src={`${API}/studio/stream/camera/${feed.role}?t=${time.getTime()}`}
            alt=""
            className="w-full h-full object-cover"
          />
        </div>
      ))}

      {/* Layer 3.5: Camera feeds (toggled with 'c') */}
      {showCameras && (
        <div className="absolute top-4 right-4 flex flex-col gap-2" style={{ zIndex: 5 }}>
          {["brio-operator", "c920-hardware", "c920-room", "c920-aux"].map(cam => (
            <div key={cam} className="relative">
              <img
                src={`${API}/studio/stream/camera/${cam}?t=${time.getTime()}`}
                alt={cam}
                className="w-56 rounded-lg border border-white/10"
                style={{
                  opacity: 0.7,
                  filter: "saturate(0.7)",
                  transition: "opacity 0.5s",
                }}
              />
              <span className="absolute bottom-1 left-2 text-[9px] text-white/40">{cam}</span>
            </div>
          ))}
        </div>
      )}

      {/* Layer 4: Signal zones — layered ON TOP of visual richness */}
      {hasSignals && (
        <div className="absolute inset-0" style={{ zIndex: 6 }}>
          {/* Signals rendered in positioned zones */}
          {Object.entries(signals).map(([category, entries]) => {
            const opacity = opacities[category] ?? 0;
            if (opacity < 0.05 || !entries.length) return null;

            const pos = ZONE_POSITIONS[category];
            if (!pos) return null;

            return (
              <div
                key={category}
                className="absolute"
                style={{
                  ...pos,
                  opacity: Math.min(opacity * 1.2, 1),
                  transition: "opacity 1.5s ease",
                }}
              >
                <div className="backdrop-blur-md rounded-xl p-5" style={{ background: "rgba(0,0,0,0.65)" }}>
                  <div
                    className="text-[9px] uppercase tracking-[0.3em] mb-2"
                    style={{ color: zoneColor(category, 0.5) }}
                  >
                    {category.replace(/_/g, " ")}
                  </div>
                  {entries.slice(0, 3).map((sig, i) => (
                    <div key={sig.source_id || i} className="mb-2">
                      <div
                        className="text-sm leading-relaxed font-medium"
                        style={{ color: sevColor(sig.severity, 1.0) }}
                      >
                        {sig.title.slice(0, 60)}
                      </div>
                      {sig.detail && (
                        <div className="text-xs text-white/50 mt-0.5">
                          {sig.detail.slice(0, 80)}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Layer 5: Voice session — the agent's conversational body */}
      {voiceSession.active && (
        <div
          className="absolute bottom-[8%] left-1/2 -translate-x-1/2"
          style={{
            zIndex: 7,
            animation: "voiceIn 1.5s ease-out forwards",
          }}
        >
          {/* Voice indicator — size and glow scale with routing tier */}
          <div className="flex items-center gap-3 backdrop-blur-md rounded-full px-6 py-3"
            style={{
              background: "rgba(0,0,0,0.6)",
              boxShadow: voiceIntensity > 0.5
                ? `0 0 ${20 + voiceIntensity * 30}px ${VOICE_STATE_COLORS[voiceSession.state] ?? "#999"}20`
                : "none",
              transition: "box-shadow 0.5s ease",
            }}
          >
            {/* State dot — size scales with tier intensity */}
            <div
              style={{
                width: `${8 + voiceIntensity * 6}px`,
                height: `${8 + voiceIntensity * 6}px`,
                borderRadius: "50%",
                background: VOICE_STATE_COLORS[voiceSession.state] ?? "#999",
                boxShadow: `0 0 ${6 + voiceIntensity * 12}px ${VOICE_STATE_COLORS[voiceSession.state] ?? "#999"}`,
                animation: voiceSession.state === "listening" ? "pulse 2s ease-in-out infinite" : undefined,
                transition: "width 0.3s ease, height 0.3s ease, box-shadow 0.5s ease",
              }}
            />
            {/* State label */}
            <span
              className="text-xs uppercase tracking-[0.3em] font-medium"
              style={{ color: VOICE_STATE_COLORS[voiceSession.state] ?? "#999" }}
            >
              {voiceSession.state}
            </span>
            {/* Tier indicator — subtle, only visible for STRONG/CAPABLE */}
            {voiceIntensity >= 0.75 && (
              <span
                className="text-[9px] uppercase tracking-[0.2em]"
                style={{
                  color: VOICE_STATE_COLORS[voiceSession.state] ?? "#999",
                  opacity: 0.4,
                }}
              >
                {voiceSession.routing_tier}
              </span>
            )}
            {/* Active tool */}
            {voiceSession.active_tool && (
              <span className="text-[10px] text-white/40 ml-2">
                {voiceSession.active_tool}
              </span>
            )}
            {/* Barge-in indicator */}
            {voiceSession.barge_in && (
              <span className="text-[9px] text-amber-400/60 ml-1">↑</span>
            )}
          </div>
          {/* Last utterance — fades based on state */}
          {voiceSession.last_utterance && (
            <div
              className="text-center mt-2 text-xs max-w-md mx-auto"
              style={{
                color: voiceSession.state === "speaking"
                  ? "rgba(255,255,255,0.1)"
                  : "rgba(255,255,255,0.25)",
                transition: "color 0.5s ease",
              }}
            >
              {voiceSession.last_utterance}
            </div>
          )}
          {/* Last response — only when speaking */}
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
      )}

      {/* Layer 6: Supplementary content cards (Batch B) */}
      {voiceContent.length > 0 && (
        <div className="absolute top-[15%] right-[5%] flex flex-col gap-3 max-w-sm" style={{ zIndex: 7 }}>
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
              <div className="text-sm text-white/80 font-medium">
                {content.title}
              </div>
              {content.body && (
                <div className="text-xs text-white/50 mt-1 line-clamp-3">
                  {content.body}
                </div>
              )}
              {content.image_path && (
                <img
                  src={`${API}/studio/stream/camera/${content.image_path}?t=${time.getTime()}`}
                  alt=""
                  className="w-full rounded-lg mt-2 opacity-80"
                />
              )}
            </div>
          ))}
        </div>
      )}

      {/* Time — top right, subtle but present */}
      <div className="absolute top-6 right-6 text-right" style={{ zIndex: 8 }}>
        <div className="text-white/15 text-5xl font-extralight tracking-wider">
          {time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </div>
        <div className="text-white/8 text-xs mt-1">
          {time.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" })}
        </div>
      </div>

      {/* State indicator — top left */}
      <div className="absolute top-6 left-6" style={{ zIndex: 8 }}>
        <div className={`text-[10px] tracking-[0.4em] uppercase ${
          isAlert ? "text-red-400/50" :
          isPerformative ? "text-purple-400/50" :
          state === "informational" ? "text-amber-400/30" :
          "text-white/10"
        }`}>
          {state === "ambient" ? "hapax" : state}
        </div>
      </div>

      {/* Activity label — what Hapax thinks operator is doing (always visible) */}
      <div className="absolute top-6 left-6 mt-6" style={{ zIndex: 8 }}>
        <div
          className="text-white/12 text-xs tracking-wider cursor-pointer select-text"
          onClick={() => setShowCorrection(prev => !prev)}
          style={{ marginTop: "1.2rem" }}
        >
          {activityLabel}
          {activityDetail && (
            <span className="text-white/6 ml-2">{activityDetail}</span>
          )}
        </div>
        {showCorrection && (
          <div className="mt-2">
            <input
              type="text"
              value={correctionInput}
              onChange={e => setCorrectionInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === "Enter") submitCorrection();
                if (e.key === "Escape") setShowCorrection(false);
                e.stopPropagation(); // prevent hotkey conflicts
              }}
              placeholder="what are you actually doing?"
              autoFocus
              className="bg-white/5 border border-white/10 rounded px-3 py-1.5 text-white/60 text-xs outline-none focus:border-white/20 w-64"
              style={{ fontFamily: "'JetBrains Mono', monospace" }}
            />
          </div>
        )}
      </div>

      {/* Keyboard hints — bottom right, barely visible */}
      <div className="absolute bottom-3 right-4 text-white/5 text-[9px] tracking-wider" style={{ zIndex: 8 }}>
        f · c · v · s
      </div>

      {/* CSS keyframes for animations */}
      <style>{`
        @keyframes drift1 {
          from { transform: translate(0, 0) scale(1); }
          to { transform: translate(5vw, 3vh) scale(1.1); }
        }
        @keyframes drift2 {
          from { transform: translate(0, 0) scale(1); }
          to { transform: translate(-4vw, -5vh) scale(0.9); }
        }
        @keyframes drift3 {
          from { transform: translate(0, 0) scale(1); }
          to { transform: translate(3vw, 4vh) scale(1.05); }
        }
        @keyframes fragmentIn {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 0.08; transform: translateY(0); }
        }
        @keyframes voiceIn {
          from { opacity: 0; transform: translate(-50%, 20px); }
          to { opacity: 1; transform: translate(-50%, 0); }
        }
        @keyframes contentIn {
          from { opacity: 0; transform: translateX(20px); }
          to { opacity: 1; transform: translateX(0); }
        }
        @keyframes feedIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </div>
  );
}

// ── Zone positions (CSS properties) ─────────────────────────────────────

const ZONE_POSITIONS: Record<string, React.CSSProperties> = {
  context_time: { top: "8%", left: "4%", maxWidth: "28%" },
  governance: { top: "8%", right: "4%", maxWidth: "28%" },
  work_tasks: { top: "30%", left: "4%", maxWidth: "22%" },
  health_infra: { bottom: "8%", right: "4%", maxWidth: "24%" },
  ambient_sensor: { bottom: "8%", left: "4%", maxWidth: "40%" },
  voice_session: { bottom: "15%", left: "25%", maxWidth: "50%" },
};
