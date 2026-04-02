import { useEffect, useRef } from "react";
import { usePageVisible } from "../../hooks/usePageVisible";
import { FRAME_SERVER_URL } from "../../config";

const FRAME_URL = `${FRAME_SERVER_URL}/frame`;
const FRAME_INTERVAL_MS = 333; // ~3fps

/**
 * Displays the wgpu visual surface as a fullscreen background image.
 * Uses Image() preloader → swap pattern to avoid flash-of-blank.
 * Adaptive setTimeout chain — no frame overlap, no stacking.
 */
export function VisualSurface() {
  const imgRef = useRef<HTMLImageElement>(null);
  const visible = usePageVisible();

  useEffect(() => {
    if (!visible) return;
    const img = imgRef.current;
    if (!img) return;

    let running = true;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = () => {
      if (!running) return;
      const loader = new Image();
      loader.onload = () => {
        if (running && img) img.src = loader.src;
        if (running) timer = setTimeout(poll, FRAME_INTERVAL_MS);
      };
      loader.onerror = () => {
        if (running) timer = setTimeout(poll, FRAME_INTERVAL_MS * 2);
      };
      loader.src = `${FRAME_URL}?_t=${Date.now()}`;
    };
    poll();

    return () => {
      running = false;
      if (timer) clearTimeout(timer);
    };
  }, [visible]);

  return (
    <img
      ref={imgRef}
      className="visual-surface"
      alt=""
      style={{
        position: "fixed",
        inset: 0,
        width: "100%",
        height: "100%",
        objectFit: "cover",
        zIndex: -1,
        pointerEvents: "none",
      }}
    />
  );
}
