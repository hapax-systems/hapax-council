import type { CommandRegistry } from "./commandRegistry";

/**
 * Connects the frontend to the Logos API WebSocket relay.
 * Receives commands from external clients (MCP, voice) and
 * executes them via the local registry.
 */
export function connectCommandRelay(
  registry: CommandRegistry,
  url = `ws://${window.location.hostname}:8051/ws/commands?role=frontend`,
): () => void {
  let ws: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let disposed = false;
  let consecutiveFailures = 0;

  function connect() {
    if (disposed) return;

    try {
      ws = new WebSocket(url);
    } catch {
      // WebSocket constructor can throw if URL is invalid
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      consecutiveFailures = 0;
      console.log("[logos relay] connected to backend");
    };

    ws.onmessage = async (event) => {
      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(event.data as string);
      } catch {
        return;
      }

      const type = msg.type as string;
      const id = msg.id as string | undefined;

      if (type === "execute") {
        const result = await registry.execute(
          msg.path as string,
          (msg.args as Record<string, unknown>) ?? {},
          "ws",
        );
        if (id && ws?.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "result", id, data: result }));
        }
      } else if (type === "query") {
        const value = registry.query(msg.path as string);
        if (id && ws?.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "result", id, data: { ok: true, state: value } }));
        }
      } else if (type === "list") {
        const commands = registry.list(msg.domain as string | undefined);
        const serializable = commands.map((c) => ({
          path: c.path,
          description: c.description,
          args: c.args,
        }));
        if (id && ws?.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "result", id, data: { ok: true, state: serializable } }));
        }
      }
    };

    ws.onclose = () => {
      if (!disposed) {
        scheduleReconnect();
      }
    };

    ws.onerror = () => {
      // onclose will fire after onerror — let it handle reconnect
      ws?.close();
    };
  }

  function scheduleReconnect() {
    consecutiveFailures++;
    // Exponential backoff: 1s, 2s, 4s, 8s, max 30s
    const delay = Math.min(1000 * Math.pow(2, consecutiveFailures - 1), 30000);
    // Only log on first failure and then every 5th to avoid console spam
    if (consecutiveFailures === 1 || consecutiveFailures % 5 === 0) {
      console.log(
        `[logos relay] disconnected, reconnecting in ${(delay / 1000).toFixed(0)}s` +
          (consecutiveFailures > 1 ? ` (attempt ${consecutiveFailures})` : ""),
      );
    }
    reconnectTimer = setTimeout(connect, delay);
  }

  // Forward all events to backend for external subscribers
  const unsub = registry.subscribe(/./, (event) => {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(
        JSON.stringify({
          type: "event",
          path: event.path,
          args: event.args,
          result: event.result,
          timestamp: event.timestamp,
        }),
      );
    }
  });

  connect();

  return () => {
    disposed = true;
    unsub();
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (ws) {
      // Clean close — no reconnect attempt
      ws.onclose = null;
      ws.onerror = null;
      ws.close();
    }
  };
}
