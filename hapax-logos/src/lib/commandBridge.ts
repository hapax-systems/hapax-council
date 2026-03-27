/**
 * Tauri event bridge for the command registry.
 *
 * Replaces the WebSocket-based commandRelay.ts. The Rust backend now owns
 * the external WebSocket server (relay.rs on :8052). This module bridges
 * Tauri events to/from the local CommandRegistry.
 */
import { emit, listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { CommandRegistry } from "./commandRegistry";

interface RelayMessage {
  type: string;
  id?: string;
  path?: string;
  args?: Record<string, unknown>;
  domain?: string;
}

export function connectCommandBridge(registry: CommandRegistry): () => void {
  const unlisten: UnlistenFn[] = [];
  let disposed = false;

  // Helper: emit a result back to the Rust relay
  function sendResult(id: string, data: unknown) {
    if (!disposed) {
      emit("command:result", { type: "result", id, data });
    }
  }

  // Handle execute commands from external clients (via Rust relay)
  listen<RelayMessage>("command:execute", async (event) => {
    const msg = event.payload;
    if (!msg.id || !msg.path) return;
    const result = await registry.execute(msg.path, msg.args ?? {}, "relay");
    sendResult(msg.id, result);
  }).then((u) => unlisten.push(u));

  // Handle query commands
  listen<RelayMessage>("command:query", async (event) => {
    const msg = event.payload;
    if (!msg.id || !msg.path) return;
    const value = registry.query(msg.path);
    sendResult(msg.id, { ok: true, state: value });
  }).then((u) => unlisten.push(u));

  // Handle list commands
  listen<RelayMessage>("command:list", async (event) => {
    const msg = event.payload;
    if (!msg.id) return;
    const commands = registry.list(msg.domain);
    const serializable = commands.map((c) => ({
      path: c.path,
      description: c.description,
      args: c.args,
    }));
    sendResult(msg.id, { ok: true, state: serializable });
  }).then((u) => unlisten.push(u));

  // Forward all registry events to the Rust relay for external subscribers
  const unsubEvents = registry.subscribe(/./, (event) => {
    if (!disposed) {
      emit("command:event", {
        type: "event",
        path: event.path,
        args: event.args,
        result: event.result,
        timestamp: event.timestamp,
      });
    }
  });

  console.log("[logos bridge] command bridge connected via Tauri events");

  return () => {
    disposed = true;
    unsubEvents();
    for (const u of unlisten) u();
  };
}
