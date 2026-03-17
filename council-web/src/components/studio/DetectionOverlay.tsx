import { useEffect, useRef } from "react";

interface Detection {
  label: string;
  confidence: number;
  box: [number, number, number, number]; // x1, y1, x2, y2
  track_id: number | null;
}

interface PerceptionData {
  detected_objects: string; // JSON array of Detection
  person_count: number;
  top_emotion: string;
  posture: string;
  gaze_direction: string;
  hand_gesture: string;
  scene_type: string;
}

// Muted, professional palette per class
const CLASS_COLORS: Record<string, string> = {
  person: "#66dd66",
  keyboard: "#ddcc55",
  chair: "#5588cc",
  book: "#cc77cc",
  monitor: "#77ccdd",
  laptop: "#66bbdd",
  mouse: "#bbbb66",
  "cell phone": "#dd8866",
  cup: "#88cc88",
  bottle: "#ccaa77",
};
const DEFAULT_COLOR = "#aaaaaa";

interface DetectionOverlayProps {
  containerRef: React.RefObject<HTMLElement | null>;
  cameraRole?: string;
  showBoxes?: boolean;
  showLabels?: boolean;
  showEnrichments?: boolean;
}

export function DetectionOverlay({
  containerRef,
  cameraRole,
  showBoxes = true,
  showLabels = true,
  showEnrichments = true,
}: DetectionOverlayProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const dataRef = useRef<PerceptionData | null>(null);

  // Poll perception data
  useEffect(() => {
    let running = true;
    const poll = async () => {
      try {
        const res = await fetch("/api/studio/perception");
        if (res.ok) {
          dataRef.current = await res.json();
        }
      } catch {
        // ignore
      }
      if (running) setTimeout(poll, 2000);
    };
    poll();
    return () => { running = false; };
  }, []);

  // Render loop
  useEffect(() => {
    let running = true;
    const render = () => {
      if (!running) return;
      const canvas = canvasRef.current;
      const container = containerRef.current;
      const data = dataRef.current;
      if (!canvas || !container) {
        requestAnimationFrame(render);
        return;
      }

      const rect = container.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;

      const ctx = canvas.getContext("2d");
      if (!ctx) { requestAnimationFrame(render); return; }
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, rect.width, rect.height);

      if (!data) { requestAnimationFrame(render); return; }

      // Parse detections
      let detections: Detection[] = [];
      try {
        const raw = data.detected_objects;
        if (typeof raw === "string" && raw.length > 2) {
          detections = JSON.parse(raw);
        }
      } catch {
        // ignore parse errors
      }

      // Filter by camera if specified
      if (cameraRole) {
        const roleMap: Record<string, string> = {
          "brio-operator": "operator",
          "c920-hardware": "hardware",
          "c920-room": "room",
          "c920-aux": "aux",
        };
        const filterRole = roleMap[cameraRole] || cameraRole;
        detections = detections.filter(
          (d: Detection & { camera?: string }) => !d.camera || d.camera === filterRole,
        );
      }

      if (detections.length === 0) {
        requestAnimationFrame(render);
        return;
      }

      // Detection coords are from the camera's native resolution
      // BRIO = 1920x1080, C920 = 1280x720
      const isBrio = !cameraRole || cameraRole.includes("brio");
      const srcW = isBrio ? 1920 : 1280;
      const srcH = isBrio ? 1080 : 720;
      const scaleX = rect.width / srcW;
      const scaleY = rect.height / srcH;

      for (const det of detections) {
        const [x1, y1, x2, y2] = det.box;
        const dx1 = x1 * scaleX;
        const dy1 = y1 * scaleY;
        const dx2 = x2 * scaleX;
        const dy2 = y2 * scaleY;
        const dw = dx2 - dx1;
        const dh = dy2 - dy1;
        const color = CLASS_COLORS[det.label] || DEFAULT_COLOR;

        if (showBoxes) {
          // Corner brackets (professional style)
          const cornerLen = Math.min(dw, dh) * 0.2;
          ctx.strokeStyle = color;
          ctx.lineWidth = 2;

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
        }

        if (showLabels) {
          // Label pill above the box
          const label = `${det.label} ${(det.confidence * 100).toFixed(0)}%`;
          ctx.font = "bold 11px 'JetBrains Mono', monospace";
          const tm = ctx.measureText(label);
          const lw = tm.width + 8;
          const lh = 16;
          const lx = dx1;
          const ly = dy1 - lh - 2;

          // Background pill
          ctx.fillStyle = color + "cc"; // semi-transparent
          ctx.beginPath();
          ctx.roundRect(lx, ly, lw, lh, 3);
          ctx.fill();

          // Text
          ctx.fillStyle = "#000000";
          ctx.fillText(label, lx + 4, ly + 12);
        }

        // Person enrichments
        if (showEnrichments && det.label === "person" && det.confidence > 0.4) {
          const badges: string[] = [];
          if (data.top_emotion && data.top_emotion !== "neutral") {
            badges.push(data.top_emotion);
          }
          if (data.posture && data.posture !== "unknown") {
            badges.push(data.posture);
          }
          if (data.gaze_direction && data.gaze_direction !== "unknown") {
            badges.push(`gaze: ${data.gaze_direction}`);
          }
          if (data.hand_gesture && data.hand_gesture !== "none") {
            badges.push(data.hand_gesture);
          }

          let by = dy2 - 4;
          ctx.font = "10px 'JetBrains Mono', monospace";
          for (let i = badges.length - 1; i >= 0; i--) {
            const badge = badges[i];
            const bw = ctx.measureText(badge).width + 6;
            ctx.fillStyle = "rgba(0,0,0,0.7)";
            ctx.beginPath();
            ctx.roundRect(dx1 + 2, by - 13, bw, 15, 2);
            ctx.fill();
            ctx.fillStyle = color;
            ctx.fillText(badge, dx1 + 5, by - 2);
            by -= 16;
          }
        }
      }

      requestAnimationFrame(render);
    };
    requestAnimationFrame(render);
    return () => { running = false; };
  }, [containerRef, cameraRole, showBoxes, showLabels, showEnrichments]);

  return (
    <canvas
      ref={canvasRef}
      className="pointer-events-none absolute inset-0 z-10"
    />
  );
}
