/**
 * ClassificationInspector — dedicated per-camera classification viewer.
 *
 * Toggled with `C` key. z-40 overlay (same layer as investigation).
 * Shows live camera feed with theme-aware colored detection boxes per channel.
 * Right panel: 12 toggleable classification channels + confidence threshold.
 *
 * Exempt from Logos design language signal density rules — this is a
 * diagnostic tool for the operator, not a perception interface.
 */

import { useCallback, useMemo, useRef, useState, useEffect } from "react";
import { useTerrain } from "../../../contexts/TerrainContext";
import { usePerception, useVisualLayer } from "../../../api/hooks";
import { useTheme } from "../../../theme/ThemeProvider";
import { CHANNELS, InspectorChannelPanel } from "./InspectorChannelPanel";
import type { ClassificationDetection } from "../../../api/types";

// Camera roles as they appear in VL classification_detections and snapshot API.
// The VL aggregator prefixes with camera model; the snapshot API uses short names.
const CAMERAS = [
  { role: "brio-operator", streamRole: "operator", label: "Operator (Brio)" },
  { role: "brio-room", streamRole: "room-brio", label: "Room (Brio)" },
  { role: "brio-synths", streamRole: "synths-brio", label: "Synths (Brio)" },
  { role: "c920-desk", streamRole: "desk", label: "Desk (C920)" },
  { role: "c920-room", streamRole: "room", label: "Room (C920)" },
  { role: "c920-overhead", streamRole: "overhead", label: "Overhead (C920)" },
];

export function ClassificationInspector() {
  const { activeOverlay, setOverlay } = useTerrain();
  const { data: perception } = usePerception();
  const { data: vl } = useVisualLayer();
  const { palette } = useTheme();

  const [selectedCamera, setSelectedCamera] = useState("brio-operator");
  const [channelState, setChannelState] = useState<{
    enabled: Record<string, boolean>;
    threshold: number;
  }>({ enabled: {}, threshold: 0.3 });

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);

  // Poll camera snapshot
  useEffect(() => {
    if (activeOverlay !== "classification") return;
    let cancelled = false;
    const poll = () => {
      if (cancelled) return;
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => {
        if (!cancelled) {
          imgRef.current = img;
          drawFrame();
        }
        if (!cancelled) setTimeout(poll, 200); // 5fps
      };
      img.onerror = () => {
        if (!cancelled) setTimeout(poll, 1000);
      };
      const streamRole = CAMERAS.find((c) => c.role === selectedCamera)?.streamRole ?? selectedCamera;
      img.src = `/api/studio/stream/camera/${streamRole}?_t=${Date.now()}`;
    };
    poll();
    return () => {
      cancelled = true;
    };
  }, [activeOverlay, selectedCamera]);

  // Get detections for selected camera
  const detections = useMemo(() => {
    if (!vl?.classification_detections) return [];
    return vl.classification_detections.filter(
      (d: ClassificationDetection) =>
        d.camera === selectedCamera && d.confidence >= channelState.threshold,
    );
  }, [vl, selectedCamera, channelState.threshold]);

  // Channel → color map from theme
  const channelColors = useMemo(() => {
    const map: Record<string, string> = {};
    for (const ch of CHANNELS) {
      map[ch.id] = palette[ch.colorToken] ?? palette["zinc-500"] ?? "#888";
    }
    return map;
  }, [palette]);

  // Theme-aware canvas background color (derive once, reuse in drawFrame)
  const canvasBg = useMemo(() => {
    const hex = palette["zinc-950"] ?? "#1d2021";
    return { solid: hex, pill75: hex + "bf", pill80: hex + "cc" };
  }, [palette]);

  // Draw camera frame + detection boxes
  const drawFrame = useCallback(() => {
    const canvas = canvasRef.current;
    const img = imgRef.current;
    if (!canvas || !img) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    canvas.width = w;
    canvas.height = h;

    // Draw camera frame
    ctx.drawImage(img, 0, 0, w, h);

    // Draw detection boxes per enabled channel
    for (const det of detections) {
      const [x1, y1, x2, y2] = det.box;
      const bx = x1 * w;
      const by = y1 * h;
      const bw = (x2 - x1) * w;
      const bh = (y2 - y1) * h;

      // Base detection box (always if detections channel enabled)
      if (channelState.enabled.detections !== false) {
        const color = channelColors.detections;
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.strokeRect(bx, by, bw, bh);

        // Label — clamp inside canvas
        ctx.font = "12px 'JetBrains Mono', monospace";
        const labelText = `${det.label} ${(det.confidence * 100).toFixed(0)}%`;
        const metrics = ctx.measureText(labelText);
        const labelH = 16;
        const labelY = by >= labelH + 2 ? by - labelH : by + 2; // above box, or inside top
        ctx.fillStyle = canvasBg.pill75;
        ctx.fillRect(bx, labelY, metrics.width + 8, labelH);
        ctx.fillStyle = color;
        ctx.fillText(labelText, bx + 4, labelY + 12);
      }

      // Enrichment overlays (only for person entities)
      if (det.label === "person") {
        const enrichments: Array<{ id: string; value: string | null | undefined }> = [
          { id: "gaze", value: det.gaze_direction },
          { id: "emotion", value: det.emotion },
          { id: "posture", value: det.posture },
          { id: "gesture", value: det.gesture },
          { id: "action", value: det.action },
          { id: "depth", value: det.depth },
        ];

        const activeEnrichments = enrichments.filter(
          ({ id, value }) => value && channelState.enabled[id] !== false,
        );
        const chipHeight = 16;
        const totalChipHeight = activeEnrichments.length * chipHeight;

        // Place chips inside box, anchored to top-left (below the label).
        // This guarantees visibility regardless of how far the box extends.
        const chipStartY = by + 20; // below the label area
        const chipX = bx + 4;

        let chipY = Math.min(chipStartY, h - totalChipHeight - 4); // clamp to canvas
        chipY = Math.max(4, chipY); // never above canvas

        for (const { id, value } of activeEnrichments) {
          const color = channelColors[id];
          ctx.font = "11px 'JetBrains Mono', monospace";
          const text = `${id}: ${value}`;
          const tw = ctx.measureText(text).width;
          ctx.fillStyle = canvasBg.pill80;
          ctx.fillRect(chipX, chipY, tw + 8, chipHeight - 1);
          ctx.fillStyle = color;
          ctx.fillText(text, chipX + 4, chipY + 12);
          chipY += chipHeight;
        }
      }

      // Trajectory arrow
      if (
        channelState.enabled.trajectory !== false &&
        det.velocity != null &&
        det.velocity > 0.01 &&
        det.direction_deg != null
      ) {
        const cx = (x1 + x2) / 2 * w;
        const cy = (y1 + y2) / 2 * h;
        const len = Math.min(40, det.velocity * 400);
        const rad = (det.direction_deg * Math.PI) / 180;
        const ex = cx + Math.cos(rad) * len;
        const ey = cy + Math.sin(rad) * len;
        ctx.strokeStyle = channelColors.trajectory;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(ex, ey);
        ctx.stroke();
      }

      // Novelty halo
      if (channelState.enabled.novelty !== false && det.novelty > 0.3) {
        ctx.strokeStyle = channelColors.novelty;
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.strokeRect(bx - 3, by - 3, bw + 6, bh + 6);
        ctx.setLineDash([]);
      }

      // Dwell indicator — render inside box, clamped to canvas
      if (channelState.enabled.dwell !== false && det.dwell_s != null && det.dwell_s > 30) {
        ctx.font = "11px 'JetBrains Mono', monospace";
        const dwellText = `${det.dwell_s >= 3600 ? `${(det.dwell_s / 3600).toFixed(1)}h` : det.dwell_s >= 60 ? `${(det.dwell_s / 60).toFixed(0)}m` : `${det.dwell_s.toFixed(0)}s`}`;
        const dtw = ctx.measureText(dwellText).width;
        const dwellX = Math.min(bx + bw - dtw - 8, w - dtw - 8);
        const dwellY = Math.min(by + bh - 6, h - 6);
        ctx.fillStyle = canvasBg.pill75;
        ctx.fillRect(dwellX - 2, dwellY - 12, dtw + 6, 15);
        ctx.fillStyle = channelColors.dwell;
        ctx.fillText(dwellText, dwellX + 1, dwellY);
      }
    }

    // Scene type overlay (top-left corner)
    if (channelState.enabled.scene !== false && perception) {
      const scenes = perception.per_camera_scenes as Record<string, string> | undefined;
      const sceneStreamRole = CAMERAS.find((c) => c.role === selectedCamera)?.streamRole ?? selectedCamera;
      const sceneType = scenes?.[sceneStreamRole] ?? scenes?.[selectedCamera] ?? perception.scene_type ?? "";
      if (sceneType) {
        ctx.font = "12px 'JetBrains Mono', monospace";
        const text = `scene: ${sceneType}`;
        const tw = ctx.measureText(text).width;
        ctx.fillStyle = canvasBg.pill80;
        ctx.fillRect(4, 4, tw + 10, 18);
        ctx.fillStyle = channelColors.scene;
        ctx.fillText(text, 8, 16);
      }
    }
  }, [detections, channelState, channelColors, perception, selectedCamera]);

  // Redraw on detection/state changes
  useEffect(() => {
    if (activeOverlay === "classification") drawFrame();
  }, [detections, channelState, drawFrame, activeOverlay]);

  if (activeOverlay !== "classification") return null;

  return (
    <div
      className="absolute inset-0 flex items-center justify-center"
      style={{ zIndex: 40, animation: "overlayFadeIn 200ms ease-out" }}
      onClick={(e) => {
        if (e.target === e.currentTarget) setOverlay(null);
      }}
    >
      <div
        className="w-[80%] h-[90%] rounded-2xl overflow-hidden flex"
        style={{
          background: "color-mix(in srgb, var(--color-zinc-950) 88%, transparent)",
          backdropFilter: "blur(16px)",
          border: "1px solid color-mix(in srgb, var(--color-zinc-700) 30%, transparent)",
          boxShadow: "0 16px 64px rgba(0,0,0,0.5)",
          animation: "overlaySlideIn 250ms ease-out",
        }}
      >
        {/* Left: Camera feed with detection overlay */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Header */}
          <div
            className="flex items-center gap-3 px-4 py-2 shrink-0"
            style={{ borderBottom: "1px solid var(--color-zinc-800)" }}
          >
            <span
              className="text-xs font-mono uppercase tracking-widest"
              style={{ color: "var(--color-zinc-400)" }}
            >
              Classification Inspector
            </span>
            <select
              value={selectedCamera}
              onChange={(e) => setSelectedCamera(e.target.value)}
              className="ml-auto text-xs font-mono bg-zinc-900 text-zinc-300 border border-zinc-700 rounded px-2 py-1"
            >
              {CAMERAS.map((c) => (
                <option key={c.role} value={c.role}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
          {/* Canvas */}
          <div className="flex-1 relative">
            <canvas
              ref={canvasRef}
              className="absolute inset-0 w-full h-full"
              style={{ objectFit: "contain" }}
            />
          </div>
        </div>

        {/* Right: Channel controls */}
        <div
          className="w-56 shrink-0 flex flex-col"
          style={{ borderLeft: "1px solid var(--color-zinc-800)" }}
        >
          <InspectorChannelPanel onStateChange={setChannelState} />
        </div>
      </div>

      <style>{`
        @keyframes overlayFadeIn {
          from { background: transparent; }
          to { background: rgba(0, 0, 0, 0.3); }
        }
        @keyframes overlaySlideIn {
          from { opacity: 0; transform: translateY(12px) scale(0.98); }
          to { opacity: 1; transform: translateY(0) scale(1); }
        }
      `}</style>
    </div>
  );
}
