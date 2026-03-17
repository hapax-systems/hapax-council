import { describe, it, expect, vi, beforeEach } from "vitest";
import { connectSSE, type SSEEvent } from "../sse";

/**
 * Build a mock fetch response that streams the given SSE text chunks.
 * Each chunk is a string that will be encoded and returned sequentially.
 */
function mockStreamResponse(chunks: string[]) {
  const encoder = new TextEncoder();
  let chunkIndex = 0;

  const reader = {
    read: vi.fn(async () => {
      if (chunkIndex >= chunks.length) {
        return { done: true, value: undefined };
      }
      return {
        done: false,
        value: encoder.encode(chunks[chunkIndex++]),
      };
    }),
  };

  return {
    ok: true,
    status: 200,
    body: { getReader: () => reader },
  } as unknown as Response;
}

/**
 * Wait for the async internals of connectSSE to settle.
 * connectSSE fires an internal async IIFE; we flush the microtask queue.
 */
function flushPromises(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

describe("connectSSE", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("calls fetch with correct URL, method, and JSON body", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(mockStreamResponse([]));

    connectSSE("/api/query", {
      body: { question: "hello" },
      onEvent: vi.fn(),
    });

    await flushPromises();

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/query");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ question: "hello" }));
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe(
      "application/json",
    );
  });

  it("defaults to POST when no method is specified", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(mockStreamResponse([]));

    connectSSE("/api/query", { onEvent: vi.fn() });
    await flushPromises();

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
  });

  it("omits Content-Type header and body when no body option is provided", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(mockStreamResponse([]));

    connectSSE("/api/query", { onEvent: vi.fn() });
    await flushPromises();

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.body).toBeUndefined();
    expect((init.headers as Record<string, string>)?.["Content-Type"]).toBeUndefined();
  });

  it("parses a single SSE event with explicit event type", async () => {
    const chunk = "event: text_delta\ndata: hello world\n\n";
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      mockStreamResponse([chunk]),
    );

    const onEvent = vi.fn();
    connectSSE("/api/query", { onEvent });
    await flushPromises();

    expect(onEvent).toHaveBeenCalledOnce();
    expect(onEvent).toHaveBeenCalledWith<[SSEEvent]>({
      event: "text_delta",
      data: "hello world",
    });
  });

  it("defaults event type to 'message' when no event line precedes data", async () => {
    const chunk = "data: some payload\n\n";
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      mockStreamResponse([chunk]),
    );

    const onEvent = vi.fn();
    connectSSE("/api/query", { onEvent });
    await flushPromises();

    expect(onEvent).toHaveBeenCalledWith<[SSEEvent]>({
      event: "message",
      data: "some payload",
    });
  });

  it("parses multiple events from multiple chunks", async () => {
    const chunks = [
      "event: status\ndata: thinking\n\n",
      "event: text_delta\ndata: first\n\n",
      "event: done\ndata: \n\n",
    ];
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      mockStreamResponse(chunks),
    );

    const onEvent = vi.fn();
    connectSSE("/api/query", { onEvent });
    await flushPromises();

    expect(onEvent).toHaveBeenCalledTimes(3);
    expect(onEvent).toHaveBeenNthCalledWith(1, { event: "status", data: "thinking" });
    expect(onEvent).toHaveBeenNthCalledWith(2, { event: "text_delta", data: "first" });
    expect(onEvent).toHaveBeenNthCalledWith(3, { event: "done", data: "" });
  });

  it("parses a complete event contained within a single chunk", async () => {
    // When both the event: and data: lines are in the same chunk, event type is preserved.
    const chunk = "event: text_delta\ndata: complete\n\n";
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      mockStreamResponse([chunk]),
    );

    const onEvent = vi.fn();
    connectSSE("/api/query", { onEvent });
    await flushPromises();

    expect(onEvent).toHaveBeenCalledOnce();
    expect(onEvent).toHaveBeenCalledWith({ event: "text_delta", data: "complete" });
  });

  it("handles data-only chunks (no preceding event line) as 'message'", async () => {
    // Each chunk starts a fresh currentEvent = "message". If event: is in a prior
    // chunk and data: is in the next, the event type is lost — parser limitation.
    const chunks = ["event: text_delta\n", "data: orphaned\n\n"];
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      mockStreamResponse(chunks),
    );

    const onEvent = vi.fn();
    connectSSE("/api/query", { onEvent });
    await flushPromises();

    expect(onEvent).toHaveBeenCalledOnce();
    // event type reverts to "message" because currentEvent resets each chunk iteration
    expect(onEvent).toHaveBeenCalledWith({ event: "message", data: "orphaned" });
  });

  it("calls onDone when the stream ends normally", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(mockStreamResponse([]));

    const onDone = vi.fn();
    connectSSE("/api/query", { onEvent: vi.fn(), onDone });
    await flushPromises();

    expect(onDone).toHaveBeenCalledOnce();
  });

  it("calls onError with a descriptive Error on non-ok response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 422,
      text: async () => "Unprocessable Entity",
    } as unknown as Response);

    const onError = vi.fn();
    connectSSE("/api/query", { onEvent: vi.fn(), onError });
    await flushPromises();

    expect(onError).toHaveBeenCalledOnce();
    const err: Error = onError.mock.calls[0][0];
    expect(err).toBeInstanceOf(Error);
    expect(err.message).toContain("422");
    expect(err.message).toContain("Unprocessable Entity");
  });

  it("calls onDone (not onError) when the AbortController is used to cancel", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(
      Object.assign(new DOMException("Aborted", "AbortError")),
    );

    const onDone = vi.fn();
    const onError = vi.fn();
    const controller = connectSSE("/api/query", {
      onEvent: vi.fn(),
      onDone,
      onError,
    });
    controller.abort();
    await flushPromises();

    expect(onDone).toHaveBeenCalledOnce();
    expect(onError).not.toHaveBeenCalled();
  });

  it("returns an AbortController", () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(mockStreamResponse([]));

    const controller = connectSSE("/api/query", { onEvent: vi.fn() });
    expect(controller).toBeInstanceOf(AbortController);
  });

  it("calls onError when response body is null", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      body: null,
    } as unknown as Response);

    const onError = vi.fn();
    connectSSE("/api/query", { onEvent: vi.fn(), onError });
    await flushPromises();

    expect(onError).toHaveBeenCalledOnce();
    const err: Error = onError.mock.calls[0][0];
    expect(err.message).toContain("No response body");
  });
});
