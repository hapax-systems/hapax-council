// useAwareness hook integration test.
//
// Mocks @tauri-apps/api/core (invoke) and @tauri-apps/api/event (listen)
// to drive end-to-end the documented event flow:
//   1. Hook invokes subscribe_awareness on mount.
//   2. Three listen() handlers register: state / stale / heartbeat.
//   3. Synthesized awareness:state event sets state + clears stale.
//   4. Synthesized awareness:stale event sets stale.
//   5. Cleanup unsubscribes all three handlers.

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

// Capture listen handlers per-event so the test can fire them.
type Handler = (e: { payload: string }) => void;
const handlers = new Map<string, Handler>();
const unlisten = vi.fn();

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(() => Promise.resolve()),
}));

vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn((event: string, h: Handler) => {
    handlers.set(event, h);
    return Promise.resolve(unlisten);
  }),
}));

import { useAwareness } from "../awareness";
import { invoke } from "@tauri-apps/api/core";

beforeEach(() => {
  handlers.clear();
  unlisten.mockClear();
  (invoke as unknown as ReturnType<typeof vi.fn>).mockClear();
});

describe("useAwareness", () => {
  it("invokes subscribe_awareness on mount", async () => {
    renderHook(() => useAwareness());
    // Allow the listen() promises to settle so handlers register.
    await act(async () => {
      await Promise.resolve();
    });
    expect(invoke).toHaveBeenCalledWith("subscribe_awareness");
  });

  it("registers three event handlers", async () => {
    renderHook(() => useAwareness());
    await act(async () => {
      await Promise.resolve();
    });
    expect(handlers.has("awareness:state")).toBe(true);
    expect(handlers.has("awareness:stale")).toBe(true);
    expect(handlers.has("awareness:heartbeat")).toBe(true);
  });

  it("updates state and clears stale on awareness:state event", async () => {
    const { result } = renderHook(() => useAwareness());
    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.state).toBeNull();
    expect(result.current.stale).toBe(false);

    const stateHandler = handlers.get("awareness:state")!;
    const staleHandler = handlers.get("awareness:stale")!;

    // Set stale first to verify state event clears it.
    act(() => staleHandler({ payload: "{}" }));
    expect(result.current.stale).toBe(true);

    act(() =>
      stateHandler({
        payload: JSON.stringify({
          schema_version: 1,
          timestamp: "2026-04-26T12:00:00Z",
          ttl_seconds: 90,
          marketing_outreach: {},
          research_dispatches: {},
          music_soundcloud: {},
          publishing_pipeline: {},
          v5_publications: {},
          health_system: {},
          daimonion_voice: {},
          stream: {},
          studio: {},
          cross_account: {},
          governance: {},
          mail: {},
          content_programmes: {},
          hardware_fleet: {},
          time_sprint: {},
          monetization: {},
        }),
      }),
    );

    expect(result.current.state?.timestamp).toBe("2026-04-26T12:00:00Z");
    expect(result.current.stale).toBe(false);
    expect(result.current.lastUpdatedMs).not.toBeNull();
  });

  it("sets stale on awareness:stale event", async () => {
    const { result } = renderHook(() => useAwareness());
    await act(async () => {
      await Promise.resolve();
    });

    const staleHandler = handlers.get("awareness:stale")!;
    act(() => staleHandler({ payload: '{"age_s": 150}' }));
    expect(result.current.stale).toBe(true);
  });

  it("unsubscribes all handlers on unmount", async () => {
    const { unmount } = renderHook(() => useAwareness());
    await act(async () => {
      await Promise.resolve();
    });
    unmount();
    // Three listen() calls → three unlisten invocations.
    expect(unlisten).toHaveBeenCalledTimes(3);
  });

  it("ignores malformed state payloads without crashing", async () => {
    const { result } = renderHook(() => useAwareness());
    await act(async () => {
      await Promise.resolve();
    });

    const stateHandler = handlers.get("awareness:state")!;
    act(() => stateHandler({ payload: "not-json" }));

    expect(result.current.state).toBeNull();
  });
});
