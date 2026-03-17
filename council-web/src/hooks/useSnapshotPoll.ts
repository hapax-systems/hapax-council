import { useEffect, useRef, useState } from "react";

/**
 * Polls a snapshot URL and tracks staleness.
 * Returns an img ref to attach and an isStale flag.
 */
export function useSnapshotPoll(
  url: string,
  intervalMs: number,
): { imgRef: React.RefObject<HTMLImageElement | null>; isStale: boolean } {
  const imgRef = useRef<HTMLImageElement | null>(null);
  const lastSuccess = useRef(0);
  const [isStale, setIsStale] = useState(false);

  useEffect(() => {
    let running = true;
    let pending = false;
    lastSuccess.current = Date.now();

    const pull = () => {
      if (!running || pending) return;
      pending = true;
      const loader = new Image();
      loader.onload = () => {
        if (running && imgRef.current) imgRef.current.src = loader.src;
        lastSuccess.current = Date.now();
        setIsStale(false);
        pending = false;
      };
      loader.onerror = () => {
        pending = false;
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
    };
  }, [url, intervalMs]);

  return { imgRef, isStale };
}
