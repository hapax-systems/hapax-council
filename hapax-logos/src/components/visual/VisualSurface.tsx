import { useEffect, useRef } from "react";
import { usePageVisible } from "../../hooks/usePageVisible";

const FRAME_URL = "http://127.0.0.1:8053/frame";
const MIN_FRAME_MS = 33; // ~30fps

/**
 * Displays the wgpu visual surface as a fullscreen background image.
 * Sets img.src directly to the frame server URL (cache-busted with timestamp).
 * Uses img-src CSP — no fetch/connect-src needed.
 */
export function VisualSurface() {
  const imgRef = useRef<HTMLImageElement>(null);
  const visible = usePageVisible();

  useEffect(() => {
    if (!visible) return;

    let active = true;
    let lastFrame = 0;
    let loading = false;

    const tick = (now: number) => {
      if (!active) return;

      if (now - lastFrame >= MIN_FRAME_MS && !loading && imgRef.current) {
        lastFrame = now;
        loading = true;
        imgRef.current.src = `${FRAME_URL}?_t=${Date.now()}`;
      }

      if (active) {
        requestAnimationFrame(tick);
      }
    };

    // Reset loading flag when image loads or errors
    const img = imgRef.current;
    if (img) {
      const onLoad = () => { loading = false; };
      const onError = () => { loading = false; };
      img.addEventListener("load", onLoad);
      img.addEventListener("error", onError);

      requestAnimationFrame(tick);

      return () => {
        active = false;
        img.removeEventListener("load", onLoad);
        img.removeEventListener("error", onError);
      };
    }

    return () => { active = false; };
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
