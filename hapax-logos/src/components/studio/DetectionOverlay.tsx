import { useCallback, useEffect, useRef, useState } from "react";
import type { ClassificationDetection } from "../../api/types";

// ── Gruvbox class colors ─────────────────────────────────────────────────
const CATEGORY_HEX: Record<string, string> = {
  person: "#8ec07c",
  furniture: "#bdae93",
  electronics: "#83a598",
  instrument: "#fabd2f",
  container: "#d3869b",
};

const LABEL_CATEGORY: Record<string, string> = {
  person: "person",
  chair: "furniture",
  couch: "furniture",
  bed: "furniture",
  desk: "furniture",
  "dining table": "furniture",
  monitor: "electronics",
  laptop: "electronics",
  keyboard: "electronics",
  mouse: "electronics",
  "cell phone": "electronics",
  tv: "electronics",
  remote: "electronics",
  guitar: "instrument",
  piano: "instrument",
  microphone: "instrument",
  cup: "container",
  bottle: "container",
  bowl: "container",
  vase: "container",
  book: "container",
  backpack: "container",
};

function classColor(label: string): string {
  const cat = LABEL_CATEGORY[label] ?? "electronics";
  return CATEGORY_HEX[cat] ?? "#83a598";
}

// ── Novelty → breathing period ──────────────────────────────────────────
// Matches SignalPip severity tiers: static→8s, low→4s, mod→1.5s, high→0.6s
function breathingPeriod(novelty: number): number {
  if (novelty < 0.1) return 0; // static — no breathing
  if (novelty < 0.3) return 8000;
  if (novelty < 0.6) return 4000;
  if (novelty < 0.8) return 1500;
  return 600;
}

// ── EMA smoothing for temporal stability ──────────────────────────────
interface SmoothedBox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

const EMA_ALPHA = 0.6; // higher = snappier tracking (was 0.3)

function lerpBox(prev: SmoothedBox, next: SmoothedBox): SmoothedBox {
  return {
    x1: prev.x1 + EMA_ALPHA * (next.x1 - prev.x1),
    y1: prev.y1 + EMA_ALPHA * (next.y1 - prev.y1),
    x2: prev.x2 + EMA_ALPHA * (next.x2 - prev.x2),
    y2: prev.y2 + EMA_ALPHA * (next.y2 - prev.y2),
  };
}

// ── Tier definitions ──────────────────────────────────────────────────
export type DetectionTier = 1 | 2 | 3;

// ── Directive event types ─────────────────────────────────────────────
interface HighlightDirective {
  entity_id: string;
  annotation?: string;
  duration_s?: number;
}

interface LayerDirective {
  visible: boolean;
  tier?: DetectionTier;
}

// ── Props ─────────────────────────────────────────────────────────────
export interface DetectionOverlayProps {
  containerRef: React.RefObject<HTMLElement | null>;
  cameraRole?: string;
  classificationDetections?: ClassificationDetection[];
  tier?: DetectionTier;
  visible?: boolean;
  objectFit?: "contain" | "cover";
}

export function DetectionOverlay({
  containerRef,
  cameraRole,
  classificationDetections = [],
  tier = 1,
  visible = true,
  objectFit = "contain",
}: DetectionOverlayProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const smoothedRef = useRef<Map<string, SmoothedBox>>(new Map());
  const hoveredIdRef = useRef<string | null>(null);
  const [highlights, setHighlights] = useState<Map<string, { annotation?: string; expires: number }>>(new Map());
  const [layerOverride, setLayerOverride] = useState<{ visible: boolean; tier?: DetectionTier } | null>(null);

  // Filter detections for this camera
  const detections = cameraRole
    ? classificationDetections.filter((d) => d.camera === cameraRole)
    : classificationDetections;

  // Listen for Hapax directive events
  useEffect(() => {
    const onHighlight = (e: Event) => {
      const detail = (e as CustomEvent<HighlightDirective>).detail;
      setHighlights((prev) => {
        const next = new Map(prev);
        next.set(detail.entity_id, {
          annotation: detail.annotation,
          expires: Date.now() + (detail.duration_s ?? 5) * 1000,
        });
        return next;
      });
    };

    const onAnnotate = (e: Event) => {
      const detail = (e as CustomEvent<HighlightDirective>).detail;
      setHighlights((prev) => {
        const next = new Map(prev);
        next.set(detail.entity_id, {
          annotation: detail.annotation,
          expires: Date.now() + (detail.duration_s ?? 10) * 1000,
        });
        return next;
      });
    };

    const onLayer = (e: Event) => {
      const detail = (e as CustomEvent<LayerDirective>).detail;
      setLayerOverride(detail);
    };

    window.addEventListener("hapax:detection-highlight", onHighlight);
    window.addEventListener("hapax:detection-annotate", onAnnotate);
    window.addEventListener("hapax:detection-layer", onLayer);
    return () => {
      window.removeEventListener("hapax:detection-highlight", onHighlight);
      window.removeEventListener("hapax:detection-annotate", onAnnotate);
      window.removeEventListener("hapax:detection-layer", onLayer);
    };
  }, []);

  // Expire old highlights
  useEffect(() => {
    if (highlights.size === 0) return;
    const timer = setInterval(() => {
      const now = Date.now();
      setHighlights((prev) => {
        const next = new Map(prev);
        for (const [id, h] of next) {
          if (h.expires < now) next.delete(id);
        }
        return next.size !== prev.size ? next : prev;
      });
    }, 500);
    return () => clearInterval(timer);
  }, [highlights.size]);

  // Pointer tracking for tier 2 hover
  const handlePointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (tier < 2 && !layerOverride) return;
      const canvas = canvasRef.current;
      const container = containerRef.current;
      if (!canvas || !container) return;
      const rect = container.getBoundingClientRect();
      // Account for object-fit letterboxing/cropping
      const imgAspect = 16 / 9;
      const cAspect = rect.width / rect.height;
      let iX = 0, iY = 0, iW = rect.width, iH = rect.height;
      if (objectFit === "cover") {
        if (cAspect > imgAspect) { iH = rect.width / imgAspect; iY = (rect.height - iH) / 2; }
        else { iW = rect.height * imgAspect; iX = (rect.width - iW) / 2; }
      } else {
        if (cAspect > imgAspect) { iW = rect.height * imgAspect; iX = (rect.width - iW) / 2; }
        else { iH = rect.width / imgAspect; iY = (rect.height - iH) / 2; }
      }
      const px = (e.clientX - rect.left - iX) / iW;
      const py = (e.clientY - rect.top - iY) / iH;

      let found: string | null = null;
      for (const det of detections) {
        const [x1, y1, x2, y2] = det.box;
        if (px >= x1 && px <= x2 && py >= y1 && py <= y2) {
          found = det.entity_id;
          break;
        }
      }
      hoveredIdRef.current = found;
    },
    [tier, layerOverride, detections, containerRef, objectFit],
  );

  const handlePointerLeave = useCallback(() => { hoveredIdRef.current = null; }, []);

  // Resolve effective visibility and tier
  const effectiveVisible = layerOverride ? layerOverride.visible : visible;
  const effectiveTier = layerOverride?.tier ?? tier;

  // Render loop
  useEffect(() => {
    if (!effectiveVisible) return;

    let running = true;
    let lastRender = 0;
    const MIN_FRAME_MS = 33; // cap at ~30fps (max 3Hz state change, smooth animation)

    const render = (timestamp: number) => {
      if (!running) return;
      if (timestamp - lastRender < MIN_FRAME_MS) {
        requestAnimationFrame(render);
        return;
      }
      lastRender = timestamp;

      const canvas = canvasRef.current;
      const container = containerRef.current;
      if (!canvas || !container) {
        requestAnimationFrame(render);
        return;
      }

      // Skip rendering when container is off-screen (hidden region)
      if (!container.offsetParent) {
        requestAnimationFrame(render);
        return;
      }

      const rect = container.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      const targetW = Math.round(rect.width * dpr);
      const targetH = Math.round(rect.height * dpr);
      const resized = canvas.width !== targetW || canvas.height !== targetH;
      if (resized) {
        canvas.width = targetW;
        canvas.height = targetH;
        canvas.style.width = `${rect.width}px`;
        canvas.style.height = `${rect.height}px`;
      }

      const ctx = canvas.getContext("2d");
      if (!ctx) {
        requestAnimationFrame(render);
        return;
      }
      if (resized) ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, rect.width, rect.height);

      if (detections.length === 0) {
        requestAnimationFrame(render);
        return;
      }

      // Compute image content rect within container
      // Camera aspect ratios: BRIO=16:9, C920=16:9 — all 16:9
      const imgAspect = 16 / 9;
      const containerAspect = rect.width / rect.height;
      let imgX = 0, imgY = 0, imgW = rect.width, imgH = rect.height;
      if (objectFit === "cover") {
        // object-cover: image fills container, overflow clipped, centered
        if (containerAspect > imgAspect) {
          // Container wider — image scaled to width, top/bottom cropped
          imgH = rect.width / imgAspect;
          imgY = (rect.height - imgH) / 2;
        } else {
          // Container taller — image scaled to height, sides cropped
          imgW = rect.height * imgAspect;
          imgX = (rect.width - imgW) / 2;
        }
      } else {
        // object-contain: image fits inside, letterboxed
        if (containerAspect > imgAspect) {
          imgW = rect.height * imgAspect;
          imgX = (rect.width - imgW) / 2;
        } else {
          imgH = rect.width / imgAspect;
          imgY = (rect.height - imgH) / 2;
        }
      }

      const now = Date.now();
      const currentHovered = hoveredIdRef.current;

      // Gradient cache — reuse gradients for similar positions
      const gradientCache = new Map<string, CanvasGradient>();

      for (const det of detections) {
        const color = classColor(det.label);
        const isHovered = currentHovered === det.entity_id;
        const highlight = highlights.get(det.entity_id);
        const isHighlighted = !!highlight;

        // Smooth box positions with EMA
        const rawBox: SmoothedBox = {
          x1: det.box[0],
          y1: det.box[1],
          x2: det.box[2],
          y2: det.box[3],
        };
        const prev = smoothedRef.current.get(det.entity_id);
        const smoothed = prev ? lerpBox(prev, rawBox) : rawBox;
        smoothedRef.current.set(det.entity_id, smoothed);

        // Map normalized coords to image content area (not full container)
        const dx1 = imgX + smoothed.x1 * imgW;
        const dy1 = imgY + smoothed.y1 * imgH;
        const dx2 = imgX + smoothed.x2 * imgW;
        const dy2 = imgY + smoothed.y2 * imgH;
        const cx = (dx1 + dx2) / 2;
        const cy = (dy1 + dy2) / 2;
        const dw = dx2 - dx1;
        const dh = dy2 - dy1;
        // Depth modulates halo radius: close=larger, far=smaller
        const depthScale = det.depth === "close" ? 1.1 : det.depth === "far" ? 0.7 : 1.0;
        // Use geometric mean of dimensions, capped to prevent frame-filling blobs
        const rawRadius = Math.sqrt(dw * dh) * 0.5 * depthScale;
        const maxRadius = Math.min(imgW, imgH) * 0.25; // never exceed 25% of frame
        const radius = Math.min(rawRadius, maxRadius);

        // Breathing animation
        const period = breathingPeriod(det.novelty);
        let breathe = 1.0;
        if (period > 0) {
          breathe = 0.7 + 0.3 * Math.sin((now / period) * Math.PI * 2);
        }

        // Highlight pulse
        if (isHighlighted) {
          breathe = 0.5 + 0.5 * Math.sin((now / 300) * Math.PI * 2);
        }

        const baseOpacity = det.confidence * breathe;

        // ── Tier 1: Ambient halos ────────────────────────────────
        // Quantize gradient params for cache reuse
        const qcx = cx >> 1;
        const qcy = cy >> 1;
        const qr = radius >> 1;
        const qo = Math.round(baseOpacity * 10);
        const gradKey = `${qcx}:${qcy}:${qr}:${qo}:${color}`;
        let grad = gradientCache.get(gradKey);
        if (!grad) {
          grad = ctx.createRadialGradient(cx, cy, radius * 0.1, cx, cy, radius);
          grad.addColorStop(0, color + Math.round(baseOpacity * 0.8 * 255).toString(16).padStart(2, "0"));
          grad.addColorStop(0.5, color + Math.round(baseOpacity * 0.4 * 255).toString(16).padStart(2, "0"));
          grad.addColorStop(1, color + "00");
          gradientCache.set(gradKey, grad);
        }

        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.ellipse(cx, cy, radius, radius * 0.8, 0, 0, Math.PI * 2);
        ctx.fill();

        // ── Tier 2+: Corner brackets + label (on hover or deep) ──
        const showBrackets = effectiveTier >= 3 || (effectiveTier >= 2 && isHovered) || isHighlighted;

        if (showBrackets) {
          const cornerLen = Math.min(dw, dh) * 0.2;
          ctx.strokeStyle = color;
          ctx.lineWidth = 1.5;
          ctx.globalAlpha = Math.min(1, baseOpacity + 0.3);

          // Top-left
          ctx.beginPath();
          ctx.moveTo(dx1, dy1 + cornerLen);
          ctx.lineTo(dx1, dy1);
          ctx.lineTo(dx1 + cornerLen, dy1);
          ctx.stroke();
          // Top-right
          ctx.beginPath();
          ctx.moveTo(dx2 - cornerLen, dy1);
          ctx.lineTo(dx2, dy1);
          ctx.lineTo(dx2, dy1 + cornerLen);
          ctx.stroke();
          // Bottom-left
          ctx.beginPath();
          ctx.moveTo(dx1, dy2 - cornerLen);
          ctx.lineTo(dx1, dy2);
          ctx.lineTo(dx1 + cornerLen, dy2);
          ctx.stroke();
          // Bottom-right
          ctx.beginPath();
          ctx.moveTo(dx2 - cornerLen, dy2);
          ctx.lineTo(dx2, dy2);
          ctx.lineTo(dx2, dy2 - cornerLen);
          ctx.stroke();

          ctx.globalAlpha = 1;

          // Label pill
          const label = det.consent_suppressed ? det.label : `${det.label} ${(det.confidence * 100).toFixed(0)}%`;
          ctx.font = "bold 9px 'JetBrains Mono', monospace";
          const tm = ctx.measureText(label);
          const lw = tm.width + 8;
          const lh = 14;
          const lx = dx1;
          const ly = dy1 - lh - 2;

          ctx.fillStyle = color + "cc";
          ctx.beginPath();
          ctx.roundRect(lx, ly, lw, lh, 3);
          ctx.fill();

          ctx.fillStyle = "#1d2021";
          ctx.fillText(label, lx + 4, ly + 10);

          // Person enrichment pips (tier 2+, not consent-suppressed)
          if (det.label === "person" && !det.consent_suppressed && effectiveTier >= 2) {
            const pips: { color: string; label: string }[] = [];

            // Real enrichment data from perception pipeline
            if (det.gaze_direction) pips.push({ color: "#83a598", label: det.gaze_direction });
            if (det.emotion && det.emotion !== "neutral") pips.push({ color: "#d3869b", label: det.emotion });
            if (det.posture && det.posture !== "upright") pips.push({ color: "#fabd2f", label: det.posture });
            if (det.action) pips.push({ color: "#fe8019", label: det.action });
            if (det.gesture && det.gesture !== "none") pips.push({ color: "#b8bb26", label: det.gesture });

            // Fallback to mobility/novelty when no enrichments
            if (pips.length === 0) {
              if (det.mobility === "dynamic") pips.push({ color: "#fabd2f", label: "moving" });
              if (det.novelty > 0.5) pips.push({ color: "#fb4934", label: "new" });
            }

            let pipX = dx1 + 2;
            for (const pip of pips) {
              ctx.fillStyle = pip.color;
              ctx.beginPath();
              ctx.arc(pipX + 4, dy2 + 8, 3, 0, Math.PI * 2);
              ctx.fill();

              if (effectiveTier >= 3 || isHovered) {
                ctx.fillStyle = pip.color;
                ctx.font = "8px 'JetBrains Mono', monospace";
                ctx.fillText(pip.label, pipX + 10, dy2 + 11);
                pipX += ctx.measureText(pip.label).width + 16;
              } else {
                pipX += 12;
              }
            }
          }
        }

        // ── Tier 3: Trajectory trail from sightings history ──────
        if (effectiveTier >= 3 && det.sightings && det.sightings.length >= 2) {
          ctx.strokeStyle = color + "50";
          ctx.lineWidth = 1;
          ctx.setLineDash([3, 3]);
          ctx.beginPath();

          // Draw connected centroids from sightings history
          for (let i = 0; i < det.sightings.length; i++) {
            const s = det.sightings[i];
            const sx = imgX + ((s[0] + s[2]) / 2) * imgW;
            const sy = imgY + ((s[1] + s[3]) / 2) * imgH;
            if (i === 0) ctx.moveTo(sx, sy);
            else ctx.lineTo(sx, sy);
          }
          // Connect to current position
          ctx.lineTo(cx, cy);
          ctx.stroke();
          ctx.setLineDash([]);

          // Fading dots at each sighting position
          for (let i = 0; i < det.sightings.length; i++) {
            const s = det.sightings[i];
            const sx = imgX + ((s[0] + s[2]) / 2) * imgW;
            const sy = imgY + ((s[1] + s[3]) / 2) * imgH;
            const age = i / det.sightings.length; // 0=oldest, ~1=newest
            ctx.fillStyle = color + Math.round(age * 0.6 * 255).toString(16).padStart(2, "0");
            ctx.beginPath();
            ctx.arc(sx, sy, 2, 0, Math.PI * 2);
            ctx.fill();
          }
        } else if (effectiveTier >= 3 && det.mobility === "dynamic") {
          // Fallback: direction indicator when no sightings data
          ctx.strokeStyle = color + "40";
          ctx.lineWidth = 1;
          ctx.setLineDash([3, 3]);
          ctx.beginPath();
          ctx.moveTo(cx, cy);
          ctx.lineTo(cx + dw * 0.15, cy);
          ctx.stroke();
          ctx.setLineDash([]);
        }

        // ── Tier 3: Directional arrow from temporal delta ─────────
        if (effectiveTier >= 3 && det.velocity != null && det.velocity > 0.005 && det.direction_deg != null) {
          const arrowLen = Math.min(Math.max(dw, dh) * 0.4, det.velocity * 500);
          const rad = (det.direction_deg * Math.PI) / 180;
          const ax = cx + Math.cos(rad) * arrowLen;
          const ay = cy + Math.sin(rad) * arrowLen;

          ctx.strokeStyle = color + "80";
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.moveTo(cx, cy);
          ctx.lineTo(ax, ay);
          ctx.stroke();

          // Arrowhead
          const headLen = 6;
          ctx.beginPath();
          ctx.moveTo(ax, ay);
          ctx.lineTo(ax - Math.cos(rad - 0.4) * headLen, ay - Math.sin(rad - 0.4) * headLen);
          ctx.moveTo(ax, ay);
          ctx.lineTo(ax - Math.cos(rad + 0.4) * headLen, ay - Math.sin(rad + 0.4) * headLen);
          ctx.stroke();
        }

        // ── Entry/exit animations ────────────────────────────────
        if (det.is_entering) {
          // Radial expand pulse on entry (500ms cycle)
          const entryPhase = ((now % 500) / 500);
          const entryRadius = radius * (1.0 + entryPhase * 0.3);
          ctx.strokeStyle = color + "30";
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.ellipse(cx, cy, entryRadius, entryRadius * 0.8, 0, 0, Math.PI * 2);
          ctx.stroke();
        }

        if (det.is_exiting && det.direction_deg != null) {
          // Fade + drift indicator for exiting entities
          ctx.globalAlpha = 0.3;
          const driftRad = (det.direction_deg * Math.PI) / 180;
          const driftX = cx + Math.cos(driftRad) * radius * 0.3;
          const driftY = cy + Math.sin(driftRad) * radius * 0.3;
          ctx.strokeStyle = color + "20";
          ctx.lineWidth = 1;
          ctx.setLineDash([2, 4]);
          ctx.beginPath();
          ctx.ellipse(driftX, driftY, radius * 0.8, radius * 0.6, 0, 0, Math.PI * 2);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.globalAlpha = 1;
        }

        // ── Dwell indicator: slow breathing when stationary > 30s ─
        if (det.dwell_s != null && det.dwell_s > 30) {
          // Render a subtle settling ring
          const settleOpacity = Math.min(0.2, (det.dwell_s - 30) / 300);
          ctx.strokeStyle = color + Math.round(settleOpacity * 255).toString(16).padStart(2, "0");
          ctx.lineWidth = 0.5;
          ctx.beginPath();
          ctx.ellipse(cx, cy, radius * 1.2, radius * 0.96, 0, 0, Math.PI * 2);
          ctx.stroke();
        }

        // ── Confidence instability: jitter on bracket corners ─────
        if (det.confidence_stability != null && det.confidence_stability > 0.1 && showBrackets) {
          const jitter = det.confidence_stability * 3;
          const jx = (Math.sin(now / 100 + cx) * jitter);
          const jy = (Math.cos(now / 130 + cy) * jitter);
          ctx.strokeStyle = color + "30";
          ctx.lineWidth = 0.5;
          const cLen = Math.min(dw, dh) * 0.15;
          // Jittered top-left corner
          ctx.beginPath();
          ctx.moveTo(dx1 + jx, dy1 + cLen + jy);
          ctx.lineTo(dx1 + jx, dy1 + jy);
          ctx.lineTo(dx1 + cLen + jx, dy1 + jy);
          ctx.stroke();
        }

        // ── Annotation (from Hapax directive) ─────────────────────
        if (highlight?.annotation) {
          const text = highlight.annotation;
          ctx.font = "bold 10px 'JetBrains Mono', monospace";
          const tw = ctx.measureText(text).width + 12;
          const tx = cx - tw / 2;
          const ty = dy2 + 16;

          ctx.fillStyle = "#1d2021dd";
          ctx.beginPath();
          ctx.roundRect(tx, ty, tw, 18, 4);
          ctx.fill();

          ctx.fillStyle = color;
          ctx.fillText(text, tx + 6, ty + 13);
        }

        // ── Cross-camera indicator (tier 3) ───────────────────────
        // Not rendered here — would need cross-camera data not available per-cell
      }

      // Clean up smoothed boxes for entities no longer present
      const activeIds = new Set(detections.map((d) => d.entity_id));
      for (const id of smoothedRef.current.keys()) {
        if (!activeIds.has(id)) smoothedRef.current.delete(id);
      }
      // Safety valve: cap Map size to prevent unbounded growth over long sessions
      if (smoothedRef.current.size > 200) {
        smoothedRef.current.clear();
      }

      requestAnimationFrame(render);
    };

    requestAnimationFrame(render);
    return () => {
      running = false;
    };
  }, [detections, effectiveVisible, effectiveTier, highlights, objectFit]);

  if (!effectiveVisible) return null;

  return (
    <canvas
      ref={canvasRef}
      onPointerMove={handlePointerMove}
      onPointerLeave={handlePointerLeave}
      className="absolute inset-0 z-10"
      style={{
        pointerEvents: effectiveTier >= 2 ? "auto" : "none",
        willChange: "transform",
      }}
    />
  );
}
