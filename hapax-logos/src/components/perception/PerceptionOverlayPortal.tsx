import { ZoneOverlay } from "./ZoneOverlay";
import { DisplayStateBadge } from "./DisplayStateBadge";
import {
  SIGNAL_CATEGORIES,
  useSignals,
  useOverlayControl,
} from "../../contexts/ClassificationOverlayContext";
import type { SignalEntry } from "../../api/types";

/**
 * Portable overlay — visual classification focus.
 * Three densities: off, minimal (HUD badges), full (zone overlays).
 */
export function PerceptionOverlayPortal() {
  const { visualLayer, filteredSignals, perception } = useSignals();
  const { overlayMode, zoneOpacityOverrides } = useOverlayControl();

  if (overlayMode === "off" || !visualLayer) return null;

  const displayState = visualLayer.display_state ?? "ambient";
  const zoneOpacities = visualLayer.zone_opacities ?? {};

  if (overlayMode === "minimal") {
    // Collect alerts
    const alerts: SignalEntry[] = [];
    for (const cat of SIGNAL_CATEGORIES) {
      for (const s of filteredSignals[cat] ?? []) {
        if (s.severity >= 0.4) alerts.push(s);
      }
    }

    return (
      <div className="pointer-events-none absolute inset-0 z-10">
        {/* Top-right: state badge */}
        <div className="absolute right-2 top-2">
          <DisplayStateBadge state={displayState} />
        </div>

        {/* Top-left: visual classification readout */}
        {perception && (
          <div className="absolute left-2 top-2 flex flex-col gap-1">
            <span className="rounded bg-black/70 px-2 py-0.5 text-[10px] font-bold text-emerald-300 backdrop-blur-sm">
              {perception.person_count ?? perception.face_count} person{(perception.person_count ?? perception.face_count) !== 1 ? "s" : ""}
              {perception.gaze_direction && perception.gaze_direction !== "unknown" && (
                <span className="ml-2 text-zinc-400">gaze: {perception.gaze_direction}</span>
              )}
            </span>
            {perception.top_emotion && perception.top_emotion !== "neutral" && (
              <span className="rounded bg-black/70 px-2 py-0.5 text-[10px] font-bold text-rose-300 backdrop-blur-sm">
                {perception.top_emotion}
              </span>
            )}
            {perception.posture && perception.posture !== "unknown" && (
              <span className={`rounded bg-black/70 px-2 py-0.5 text-[10px] font-bold backdrop-blur-sm ${
                perception.posture === "slouching" ? "text-amber-300" : "text-zinc-300"
              }`}>
                {perception.posture}
              </span>
            )}
            {perception.detected_action && perception.detected_action !== "unknown" && (
              <span className="rounded bg-black/70 px-2 py-0.5 text-[10px] font-bold text-teal-300 backdrop-blur-sm">
                {perception.detected_action}
              </span>
            )}
            {perception.scene_type && perception.scene_type !== "unknown" && (
              <span className="rounded bg-black/70 px-2 py-0.5 text-[10px] text-teal-400 backdrop-blur-sm">
                {perception.scene_type.replace(/_/g, " ")}
              </span>
            )}
          </div>
        )}

        {/* Bottom-left: alerts */}
        {alerts.length > 0 && (
          <div className="absolute bottom-2 left-2 flex flex-col gap-1">
            {alerts.slice(0, 4).map((s, i) => (
              <div
                key={`${s.source_id}-${i}`}
                className={`rounded border-l-2 px-2.5 py-1 backdrop-blur-sm ${
                  s.severity >= 0.85
                    ? "animate-pulse border-l-red-400 bg-red-950/70"
                    : "border-l-amber-400 bg-amber-950/50"
                }`}
              >
                <span className={`text-[10px] font-medium ${s.severity >= 0.85 ? "text-red-200" : "text-amber-200"}`}>
                  {s.title}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Bottom-right: gesture + hand */}
        {perception && (
          <div className="absolute bottom-2 right-2 flex items-center gap-1.5">
            {perception.hand_gesture && perception.hand_gesture !== "none" && (
              <span className="rounded bg-black/70 px-2 py-0.5 text-[10px] font-bold text-violet-300 backdrop-blur-sm">
                {perception.hand_gesture}
              </span>
            )}
            {perception.scene_objects && (
              <span className="max-w-[200px] truncate rounded bg-black/70 px-2 py-0.5 text-[9px] text-teal-400 backdrop-blur-sm">
                {perception.scene_objects}
              </span>
            )}
          </div>
        )}
      </div>
    );
  }

  // Full mode: all 6 zones
  return (
    <div className="pointer-events-none absolute inset-0 z-10">
      {SIGNAL_CATEGORIES.map((cat) => {
        const signals: SignalEntry[] = filteredSignals[cat] ?? [];
        const baseOpacity = zoneOpacities[cat] ?? 0;
        const override = zoneOpacityOverrides[cat];
        const opacity = override !== undefined ? override : baseOpacity;

        return (
          <ZoneOverlay
            key={cat}
            category={cat}
            signals={signals}
            opacity={Math.min(opacity, 0.85)}
          />
        );
      })}
    </div>
  );
}
