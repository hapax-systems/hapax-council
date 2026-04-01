import { useEffect, useRef } from "react";
import { usePageVisible } from "../../hooks/usePageVisible";
import { FRAME_SERVER_URL } from "../../config";

const FRAME_URL = `${FRAME_SERVER_URL}/frame`;
const FRAME_INTERVAL_MS = 333; // ~3fps — background ambiance, imperceptible above 3fps

/**
 * Displays the wgpu visual surface as a fullscreen background image.
 * Uses setInterval (not rAF) to avoid 60fps tick overhead.
 */
export function VisualSurface() {
  const imgRef = useRef<HTMLImageElement>(null);
  const visible = usePageVisible();

  useEffect(() => {
    if (!visible) return;

    let loading = false;
    const img = imgRef.current;
    if (!img) return;

    const onLoad = () => { loading = false; };
    const onError = () => { loading = false; };
    img.addEventListener("load", onLoad);
    img.addEventListener("error", onError);

    const timer = setInterval(() => {
      if (!loading && img) {
        loading = true;
        img.src = `${FRAME_URL}?_t=${Date.now()}`;
      }
    }, FRAME_INTERVAL_MS);

    return () => {
      clearInterval(timer);
      img.removeEventListener("load", onLoad);
      img.removeEventListener("error", onError);
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
