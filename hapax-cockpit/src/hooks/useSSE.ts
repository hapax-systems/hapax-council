import { useState, useRef, useCallback } from "react";
import { connectSSE } from "../api/sse";

interface UseSSEReturn {
  lines: string[];
  isRunning: boolean;
  error: string | null;
  start: (url: string, body?: unknown) => void;
  cancel: () => void;
  clear: () => void;
}

export function useSSE(): UseSSEReturn {
  const [lines, setLines] = useState<string[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const start = useCallback((url: string, body?: unknown) => {
    // Cancel any existing stream
    controllerRef.current?.abort();
    setLines([]);
    setError(null);
    setIsRunning(true);

    controllerRef.current = connectSSE(url, {
      method: "POST",
      body,
      onEvent: (event) => {
        try {
          const data = JSON.parse(event.data);
          if (event.event === "output") {
            setLines((prev) => [...prev, data.line]);
          } else if (event.event === "done") {
            const msg = data.cancelled
              ? `--- cancelled (${data.duration}s) ---`
              : `--- done (exit ${data.exit_code}, ${data.duration}s) ---`;
            setLines((prev) => [...prev, msg]);
            setIsRunning(false);
          } else if (event.event === "error") {
            setError(data.message);
            setIsRunning(false);
          }
        } catch {
          // Non-JSON data, append raw
          setLines((prev) => [...prev, event.data]);
        }
      },
      onDone: () => setIsRunning(false),
      onError: (err) => {
        setError(err.message);
        setIsRunning(false);
      },
    });
  }, []);

  const cancel = useCallback(() => {
    controllerRef.current?.abort();
    // Also tell the server to cancel
    fetch("/api/agents/runs/current", { method: "DELETE" }).catch(() => {});
  }, []);

  const clear = useCallback(() => {
    setLines([]);
    setError(null);
  }, []);

  return { lines, isRunning, error, start, cancel, clear };
}
