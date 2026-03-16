/**
 * HapaxPage — Hapax Corpora. Full-screen flexible visual canvas.
 *
 * A dedicated view where Hapax can inject any visual content:
 * camera feeds, generative visuals, signal zones, text, images.
 * No chrome, no sidebar, no navbar. Just the canvas.
 *
 * Designed to be left full-screen on a monitor as Hapax's
 * persistent visual presence in the studio.
 */

import { useEffect, useState, useCallback } from "react";

const API = "/api";
const POLL_FAST_MS = 2000;
const POLL_SLOW_MS = 15000;

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

interface VisualLayerState {
  available?: boolean;
  display_state: string;
  zone_opacities: Record<string, number>;
  signals: Record<string, SignalEntry[]>;
  ambient_params: AmbientParams;
  timestamp: number;
}

interface StreamInfo {
  composite_available: boolean;
  fx_available: boolean;
  cameras: string[];
}

// ── Color palette (neurodivergent-safe, muted) ──────────────────────────

const ZONE_COLORS: Record<string, string> = {
  context_time: "rgba(102, 153, 217, VAR)",    // soft blue
  governance: "rgba(77, 179, 179, VAR)",        // teal
  work_tasks: "rgba(217, 166, 77, VAR)",        // amber
  health_infra: "rgba(77, 204, 77, VAR)",       // green (shifts at high severity)
  profile_state: "rgba(230, 230, 230, VAR)",    // neutral
  ambient_sensor: "rgba(153, 153, 179, VAR)",   // lavender
};

const SEVERITY_COLORS: Record<string, string> = {
  critical: "rgba(218, 54, 51, VAR)",
  high: "rgba(212, 123, 60, VAR)",
  medium: "rgba(210, 160, 68, VAR)",
  low: "rgba(102, 153, 217, VAR)",
};

function severityLabel(sev: number): string {
  if (sev >= 0.85) return "critical";
  if (sev >= 0.7) return "high";
  if (sev >= 0.4) return "medium";
  return "low";
}

function zoneColor(category: string, opacity: number): string {
  const base = ZONE_COLORS[category] ?? "rgba(128, 128, 128, VAR)";
  return base.replace("VAR", String(Math.min(opacity, 1)));
}

function sevColor(sev: number, opacity: number): string {
  const base = SEVERITY_COLORS[severityLabel(sev)] ?? SEVERITY_COLORS.low;
  return base.replace("VAR", String(Math.min(opacity, 1)));
}

// ── Ambient background ──────────────────────────────────────────────────

function ambientGradient(params: AmbientParams): string {
  const warmth = params.color_warmth;
  const brightness = params.brightness;
  // Interpolate between cool teal and warm red
  const r = Math.round(13 + warmth * 50);
  const g = Math.round(39 - warmth * 25);
  const b = Math.round(48 - warmth * 35);
  const r2 = Math.round(r * 0.7);
  const g2 = Math.round(g * 0.7);
  const b2 = Math.round(b * 0.7);
  const alpha = Math.min(brightness * 1.5, 1);
  return `radial-gradient(ellipse at 30% 40%, rgba(${r},${g},${b},${alpha}) 0%, rgba(${r2},${g2},${b2},${alpha * 0.6}) 60%, rgba(5,5,8,1) 100%)`;
}

// ── Component ───────────────────────────────────────────────────────────

export function HapaxPage() {
  const [vlState, setVlState] = useState<VisualLayerState | null>(null);
  const [streamInfo, setStreamInfo] = useState<StreamInfo | null>(null);
  const [showCameras, setShowCameras] = useState(false);
  const [time, setTime] = useState(new Date());

  // Poll visual layer state
  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const res = await fetch(`${API}/studio/visual-layer`);
        if (res.ok && active) setVlState(await res.json());
      } catch { /* aggregator offline */ }
    };
    poll();
    const id = setInterval(poll, POLL_FAST_MS);
    return () => { active = false; clearInterval(id); };
  }, []);

  // Poll stream info (slower)
  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const res = await fetch(`${API}/studio/stream/info`);
        if (res.ok && active) setStreamInfo(await res.json());
      } catch { /* compositor offline */ }
    };
    poll();
    const id = setInterval(poll, POLL_SLOW_MS);
    return () => { active = false; clearInterval(id); };
  }, []);

  // Clock
  useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  // Keyboard: 'c' toggles cameras, 'f' fullscreen, Esc exits
  const handleKey = useCallback((e: KeyboardEvent) => {
    if (e.key === "c") setShowCameras(prev => !prev);
    if (e.key === "f") {
      if (document.fullscreenElement) document.exitFullscreen();
      else document.documentElement.requestFullscreen();
    }
  }, []);

  useEffect(() => {
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [handleKey]);

  const state = vlState?.display_state ?? "ambient";
  const signals = vlState?.signals ?? {};
  const opacities = vlState?.zone_opacities ?? {};
  const ambient = vlState?.ambient_params ?? { speed: 0.08, turbulence: 0.1, color_warmth: 0, brightness: 0.25 };
  const allSignals = Object.values(signals).flat();
  const hasSignals = allSignals.length > 0;

  const bg = ambientGradient(ambient);

  return (
    <div
      className="h-screen w-screen overflow-hidden select-none cursor-default"
      style={{
        background: bg,
        fontFamily: "'JetBrains Mono', monospace",
        transition: "background 2s ease",
      }}
    >
      {/* Camera feeds (toggled with 'c') */}
      {showCameras && streamInfo?.cameras && (
        <div className="absolute top-4 right-4 flex flex-col gap-2 z-10">
          {streamInfo.cameras.map(cam => (
            <div key={cam} className="relative">
              <img
                src={`${API}/studio/stream/camera/${cam}?t=${Date.now()}`}
                alt={cam}
                className="w-64 rounded-lg opacity-70 border border-white/10"
                style={{ transition: "opacity 0.5s" }}
              />
              <span className="absolute bottom-1 left-2 text-[10px] text-white/50">{cam}</span>
            </div>
          ))}
        </div>
      )}

      {/* Time — top right corner, subtle */}
      <div className="absolute top-6 right-6 text-right z-20">
        <div className="text-white/20 text-5xl font-light tracking-wider">
          {time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </div>
        <div className="text-white/10 text-sm mt-1">
          {time.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" })}
        </div>
      </div>

      {/* State indicator — top left, tiny */}
      <div className="absolute top-6 left-6 z-20">
        <div className={`text-xs tracking-widest uppercase ${
          state === "alert" ? "text-red-400/60" :
          state === "performative" ? "text-purple-400/60" :
          state === "informational" ? "text-amber-400/40" :
          "text-white/15"
        }`}>
          {state}
        </div>
      </div>

      {/* Signal zones — center area */}
      {hasSignals && (
        <div className="absolute inset-0 flex items-center justify-center z-10">
          <div className="max-w-2xl w-full px-8">
            {Object.entries(signals).map(([category, entries]) => {
              const opacity = opacities[category] ?? 0;
              if (opacity < 0.05 || !entries.length) return null;

              return (
                <div
                  key={category}
                  className="mb-6"
                  style={{
                    opacity: Math.min(opacity * 1.2, 1),
                    transition: "opacity 0.8s ease",
                  }}
                >
                  {/* Category label */}
                  <div
                    className="text-[10px] uppercase tracking-[0.3em] mb-2"
                    style={{ color: zoneColor(category, 0.4) }}
                  >
                    {category.replace("_", " ")}
                  </div>

                  {/* Signals */}
                  {entries.map((sig, i) => (
                    <div key={sig.source_id || i} className="mb-3">
                      <div
                        className="text-sm leading-relaxed"
                        style={{ color: sevColor(sig.severity, 0.85) }}
                      >
                        {sig.title}
                      </div>
                      {sig.detail && (
                        <div className="text-xs text-white/30 mt-0.5 leading-relaxed">
                          {sig.detail}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Ambient state — show nothing, just the gradient */}
      {!hasSignals && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="text-white/5 text-lg tracking-[0.5em] uppercase">
            hapax
          </div>
        </div>
      )}

      {/* Keyboard hints — bottom center, very subtle */}
      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-white/8 text-[10px] tracking-wider z-20">
        f fullscreen · c cameras
      </div>
    </div>
  );
}
