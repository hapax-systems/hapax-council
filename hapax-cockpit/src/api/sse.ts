/**
 * SSE stream consumer using fetch + ReadableStream.
 * Works with EventSourceResponse from sse-starlette.
 */

export interface SSEEvent {
  event: string;
  data: string;
}

export type SSECallback = (event: SSEEvent) => void;

/**
 * Connect to an SSE endpoint via POST and stream events.
 * Returns an AbortController for cancellation.
 */
export function connectSSE(
  url: string,
  options: {
    method?: string;
    body?: unknown;
    onEvent: SSECallback;
    onDone?: () => void;
    onError?: (error: Error) => void;
  },
): AbortController {
  const controller = new AbortController();

  (async () => {
    try {
      const res = await fetch(url, {
        method: options.method ?? "POST",
        headers: options.body ? { "Content-Type": "application/json" } : {},
        body: options.body ? JSON.stringify(options.body) : undefined,
        signal: controller.signal,
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(`SSE ${res.status}: ${text}`);
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        let currentEvent = "message";
        for (const line of lines) {
          if (line.startsWith("event: ")) {
            currentEvent = line.slice(7).trim();
          } else if (line.startsWith("data: ")) {
            const data = line.slice(6);
            options.onEvent({ event: currentEvent, data });
            currentEvent = "message";
          }
        }
      }

      options.onDone?.();
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        options.onDone?.();
        return;
      }
      options.onError?.(err instanceof Error ? err : new Error(String(err)));
    }
  })();

  return controller;
}
