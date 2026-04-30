// Awareness SSE bridge — React hook for subscribing to the Tauri-relayed
// /api/awareness/stream events.
//
// The Rust side (commands::streaming::subscribe_awareness) maintains a
// long-lived HTTP connection to FastAPI and re-emits each named SSE event
// as a Tauri event with the `awareness:` prefix. This hook listens for
// those events and exposes the latest state + stale flag.
//
// Read-only by design: there is no mutation path. Per the awareness
// substrate constitutional invariant, awareness state is Hapax-emitted,
// never operator-edited.

import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

// AwarenessState mirrors agents/operator_awareness/state.py::AwarenessState
// at the top-level shape. Block-level fields are kept loose (Record<string,
// unknown>) so additions to the Pydantic model don't require coordinated
// TS updates — consumers cast specific blocks they read.
export interface AwarenessState {
  schema_version: number;
  timestamp: string; // ISO-8601 UTC
  ttl_seconds: number;
  marketing_outreach: Record<string, unknown>;
  research_dispatches: Record<string, unknown>;
  music_soundcloud: Record<string, unknown>;
  publishing_pipeline: Record<string, unknown>;
  v5_publications: Record<string, unknown>;
  health_system: Record<string, unknown>;
  daimonion_voice: Record<string, unknown>;
  stream: Record<string, unknown>;
  studio: Record<string, unknown>;
  cross_account: Record<string, unknown>;
  governance: Record<string, unknown>;
  mail: Record<string, unknown>;
  content_programmes: Record<string, unknown>;
  hardware_fleet: Record<string, unknown>;
  time_sprint: Record<string, unknown>;
  monetization: Record<string, unknown>;
  // Forward-compatible: schema additions land here without breaking
  // existing consumers.
  [key: string]: unknown;
}

export interface UseAwarenessResult {
  state: AwarenessState | null;
  stale: boolean;
  // Wall-clock timestamp of the last `awareness:state` event. Useful for
  // last-known-good dimming when stale=true.
  lastUpdatedMs: number | null;
}

export function useAwareness(): UseAwarenessResult {
  const [state, setState] = useState<AwarenessState | null>(null);
  const [stale, setStale] = useState(false);
  const [lastUpdatedMs, setLastUpdatedMs] = useState<number | null>(null);

  useEffect(() => {
    let mounted = true;
    const unlistens: UnlistenFn[] = [];

    // Fire-and-forget: the Rust command is idempotent, so multiple
    // mounts of useAwareness across the app are safe.
    invoke("subscribe_awareness").catch((err) => {
      // Surface in console; don't throw — the hook degrades to empty
      // state rather than breaking the panel that uses it.
      console.warn("subscribe_awareness failed:", err);
    });

    listen<string>("awareness:state", (e) => {
      if (!mounted) return;
      try {
        const parsed = JSON.parse(e.payload) as AwarenessState;
        setState(parsed);
        setStale(false);
        setLastUpdatedMs(Date.now());
      } catch (err) {
        console.warn("awareness:state parse failed:", err);
      }
    }).then((u) => unlistens.push(u));

    listen("awareness:stale", () => {
      if (!mounted) return;
      setStale(true);
    }).then((u) => unlistens.push(u));

    // Heartbeat: no state change, but reset stale flag — the connection
    // is still alive even if nothing has changed.
    listen("awareness:heartbeat", () => {
      if (!mounted) return;
      // Heartbeat does NOT clear stale (the file may still be old).
      // Heartbeat only confirms the bridge is alive; stale resolves
      // when a new `state` event arrives.
    }).then((u) => unlistens.push(u));

    return () => {
      mounted = false;
      for (const u of unlistens) u();
    };
  }, []);

  return { state, stale, lastUpdatedMs };
}
