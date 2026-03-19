import { useEffect, useRef, useState } from "react";

/**
 * Polls a snapshot URL and tracks staleness.
 * Returns an img ref to attach and an isStale flag.
 */
export function useSnapshotPoll(
  url: string,
  intervalMs: number,
  enabled = true,
): { imgRef: React.RefObject<HTMLImageElement | null>; isStale: boolean } {
  const imgRef = useRef<HTMLImageElement | null>(null);
  const lastSuccess = useRef(0);
  const [isStale, setIsStale] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    let running = true;
    let pending = false;
    let currentLoader: HTMLImageElement | null = null;
    lastSuccess.current = Date.now();

    const pull = () => {
      if (!running || pending) return;
      pending = true;
      const loader = new Image();
      currentLoader = loader;
      loader.onload = () => {
        if (running && imgRef.current) imgRef.current.src = loader.src;
        lastSuccess.current = Date.now();
        setIsStale(false);
        pending = false;
        currentLoader = null;
      };
      loader.onerror = () => {
        pending = false;
        currentLoader = null;
      };
      loader.src = `${url}${url.includes("?") ? "&" : "?"}_t=${Date.now()}`;
    };

    pull();
    const pollTimer = setInterval(pull, intervalMs);

    // Staleness check every 2s
    const staleTimer = setInterval(() => {
      if (Date.now() - lastSuccess.current > 10_000) {
        setIsStale(true);
      }
    }, 2_000);

    return () => {
      running = false;
      clearInterval(pollTimer);
      clearInterval(staleTimer);
      // Abort any in-flight image load
      if (currentLoader) {
        currentLoader.onload = null;
        currentLoader.onerror = null;
        currentLoader.src = "";
        currentLoader = null;
      }
    };
  }, [url, intervalMs, enabled]);

  return { imgRef, isStale };
}
