import { useEffect, useState, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { LayerControls } from "../components/visual/LayerControls";
import { StateReadout } from "../components/visual/StateReadout";
import { SurfacePreview } from "../components/visual/SurfacePreview";

const IS_TAURI = "__TAURI_INTERNALS__" in window;

interface VisualState {
  stance: string;
  speed: number;
  turbulence: number;
  color_warmth: number;
  brightness: number;
  layer_opacities: Record<string, number>;
  fps: number;
  frame_time_ms: number;
}

interface FrameStats {
  frame_time_ms: number;
  stance: string;
  warmth: number;
  feed_rate: number;
  fps: number;
}

export function VisualPage() {
  const [state, setState] = useState<VisualState>({
    stance: "nominal",
    speed: 0.08,
    turbulence: 0.1,
    color_warmth: 0.0,
    brightness: 0.25,
    layer_opacities: {},
    fps: 0,
    frame_time_ms: 0,
  });

  const refresh = useCallback(async () => {
    if (!IS_TAURI) return;
    try {
      const s = await invoke<VisualState>("get_visual_surface_state");
      setState(s);
    } catch {
      // Surface may not be running
    }
  }, []);

  // Poll state every 500ms
  useEffect(() => {
    if (!IS_TAURI) return;
    refresh();
    const interval = setInterval(refresh, 500);
    return () => clearInterval(interval);
  }, [refresh]);

  // Listen for frame stats events from the visual surface
  useEffect(() => {
    if (!IS_TAURI) return;
    const unlisten = listen<FrameStats>("visual:frame-stats", (event) => {
      setState((prev) => ({
        ...prev,
        fps: event.payload.fps,
        frame_time_ms: event.payload.frame_time_ms,
        stance: event.payload.stance.toLowerCase(),
        color_warmth: event.payload.warmth,
      }));
    });
    return () => {
      unlisten.then((fn) => fn());
    };
  }, []);

  if (!IS_TAURI) {
    return (
      <div className="flex items-center justify-center p-12 text-zinc-500">
        Visual surface controls require the Tauri desktop app.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-[1fr_320px] gap-6 p-6">
      <div className="space-y-6">
        <h2 className="text-lg font-medium text-zinc-200">Visual Surface</h2>
        <SurfacePreview />
      </div>
      <div className="space-y-6">
        <StateReadout
          stance={state.stance}
          speed={state.speed}
          turbulence={state.turbulence}
          colorWarmth={state.color_warmth}
          brightness={state.brightness}
          fps={state.fps}
          frameTimeMs={state.frame_time_ms}
        />
        <LayerControls opacities={state.layer_opacities} onUpdate={refresh} />
      </div>
    </div>
  );
}
