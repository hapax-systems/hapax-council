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

  function connect() {
    if (disposed) return;
    ws = new WebSocket(url);

    ws.onopen = () => {
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
        console.log("[logos relay] disconnected, reconnecting in 3s...");
        reconnectTimer = setTimeout(connect, 3000);
      }
    };

    ws.onerror = () => {
      ws?.close();
    };
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
    ws?.close();
  };
}
