/**
 * Tauri event-based stream consumer.
 * Replaces the fetch-based SSE module — all streaming now goes through
 * Rust IPC so the frontend never makes direct HTTP calls.
 */

import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export interface StreamEvent {
  event: string;
  data: string;
}

export type StreamCallback = (event: StreamEvent) => void;

export interface StreamHandle {
  streamId: number;
  cancel: () => Promise<void>;
}

interface StreamPayload {
  type: "event" | "done" | "error";
  event?: string;
  data?: string;
}

/**
 * Start a Tauri-bridged SSE stream.
 *
 * The Rust backend connects to the FastAPI SSE endpoint and re-emits events
 * to the frontend via Tauri events on channel `stream:{id}`.
 */
export async function startStream(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    onEvent: StreamCallback;
    onDone?: () => void;
    onError?: (error: Error) => void;
  },
): Promise<StreamHandle> {
  const streamId = await invoke<number>("start_stream", {
    path,
    method: options.method ?? null,
    body: options.body ?? null,
  });

  const eventName = `stream:${streamId}`;
  let unlisten: UnlistenFn | null = null;

  unlisten = await listen<StreamPayload>(eventName, (ev) => {
    const payload = ev.payload;
    switch (payload.type) {
      case "event":
        if (payload.event && payload.data !== undefined) {
          options.onEvent({ event: payload.event, data: payload.data });
        }
        break;
      case "done":
        unlisten?.();
        options.onDone?.();
        break;
      case "error":
        unlisten?.();
        options.onError?.(new Error(payload.data ?? "Stream error"));
        break;
    }
  });

  const cancel = async () => {
    unlisten?.();
    await invoke("cancel_stream", { streamId });
  };

  return { streamId, cancel };
}

/**
 * Start a cancellable stream that also tells the server to abort on cancel.
 * Used by useSSE and ChatProvider where cancellation should stop both the
 * local stream and the server-side agent run.
 */
export async function startCancellableStream(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    onEvent: StreamCallback;
    onDone?: () => void;
    onError?: (error: Error) => void;
  },
): Promise<StreamHandle> {
  const handle = await startStream(path, options);

  return {
    streamId: handle.streamId,
    cancel: async () => {
      // handle.cancel() unlistens the Tauri event + cancels the local stream
      // cancel_stream_and_server also cancels locally (idempotent) + tells server to abort
      await handle.cancel();
      await invoke("cancel_stream_and_server", { streamId: handle.streamId });
    },
  };
}
