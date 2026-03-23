/**
 * In-app demo runner — timeline scheduler with Web Audio API.
 *
 * Audio is the master clock. AudioContext.currentTime is a hardware monotonic
 * clock with sub-millisecond precision. Actions fire at exact timestamps
 * via requestAnimationFrame polling (~60fps, <16ms worst-case latency).
 *
 * Mount inside TerrainProvider. Activate via ?demo={name}.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useDemoBridge, type DemoBridge } from "./useDemoBridge";
import { loadDemo, type DemoManifest, type DemoScene } from "./scripts";

type Phase = "loading" | "ready" | "playing" | "done";

// Breathing room between scenes — lets the audience absorb
const SCENE_GAP_S = 2.5;

interface Props {
  demoName: string;
}

export function DemoRunner({ demoName }: Props) {
  const bridge = useDemoBridge();
  const [phase, setPhase] = useState<Phase>("loading");
  const [currentScene, setCurrentScene] = useState(0);
  const [loadProgress, setLoadProgress] = useState(0);
  const [manifest, setManifest] = useState<DemoManifest | null>(null);

  const audioCtxRef = useRef<AudioContext | null>(null);
  const buffersRef = useRef<AudioBuffer[]>([]);
  const startTimeRef = useRef(0);
  const sceneStartTimesRef = useRef<number[]>([]);
  const nextActionRef = useRef(0);
  const rafRef = useRef(0);
  const bridgeRef = useRef<DemoBridge>(bridge);

  useEffect(() => {
    bridgeRef.current = bridge;
  }, [bridge]);

  // ── Load manifest + audio buffers ──────────────────────────────────
  useEffect(() => {
    let cancelled = false;

    async function load() {
      // Load script manifest
      let m: DemoManifest;
      try {
        m = await loadDemo(demoName);
      } catch (err) {
        console.error("Failed to load demo manifest:", err);
        setPhase("done"); // show error state
        return;
      }
      if (cancelled) return;
      setManifest(m);

      // Load audio
      const ctx = new AudioContext();
      audioCtxRef.current = ctx;

      const buffers: AudioBuffer[] = [];
      for (let i = 0; i < m.scenes.length; i++) {
        const scene = m.scenes[i];
        try {
          const resp = await fetch(`${m.audioDir}/${scene.audioFile}`);
          if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${scene.audioFile}`);
          const arrayBuf = await resp.arrayBuffer();
          const audioBuf = await ctx.decodeAudioData(arrayBuf);
          buffers.push(audioBuf);
        } catch (err) {
          console.error(`Failed to load ${scene.audioFile}:`, err);
          const fallback = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
          buffers.push(fallback);
        }
        if (cancelled) return;
        setLoadProgress(Math.round(((i + 1) / m.scenes.length) * 100));
      }

      buffersRef.current = buffers;

      const starts: number[] = [];
      let cursor = 0;
      for (let i = 0; i < buffers.length; i++) {
        starts.push(cursor);
        cursor += buffers[i].duration + (i < buffers.length - 1 ? SCENE_GAP_S : 0);
      }
      sceneStartTimesRef.current = starts;

      if (!cancelled) setPhase("ready");
    }

    load();
    return () => { cancelled = true; };
  }, [demoName]);

  // ── Build flat action timeline ─────────────────────────────────────
  const buildTimeline = useCallback(() => {
    if (!manifest) return [];
    const starts = sceneStartTimesRef.current;
    const timeline: { at: number; action: (ctx: DemoBridge) => void; sceneIdx: number; label?: string }[] = [];

    for (let i = 0; i < manifest.scenes.length; i++) {
      const scene = manifest.scenes[i];
      const sceneStart = starts[i];
      for (const act of scene.actions) {
        timeline.push({
          at: sceneStart + act.at,
          action: act.action,
          sceneIdx: i,
          label: act.label,
        });
      }
    }

    timeline.sort((a, b) => a.at - b.at);
    return timeline;
  }, [manifest]);

  // ── Start playback ────────────────────────────────────────────────
  const start = useCallback(() => {
    const ctx = audioCtxRef.current;
    if (!ctx || phase !== "ready") return;

    if (ctx.state === "suspended") ctx.resume();

    const timeline = buildTimeline();
    nextActionRef.current = 0;
    setPhase("playing");
    setCurrentScene(0);

    const starts = sceneStartTimesRef.current;
    const playbackStart = ctx.currentTime + 0.1;
    startTimeRef.current = playbackStart;

    for (let i = 0; i < buffersRef.current.length; i++) {
      const source = ctx.createBufferSource();
      source.buffer = buffersRef.current[i];
      source.connect(ctx.destination);
      source.start(playbackStart + starts[i]);

      const sceneIdx = i;
      source.onended = () => {
        if (sceneIdx === buffersRef.current.length - 1) {
          setPhase("done");
          cancelAnimationFrame(rafRef.current);
        }
      };
    }

    function tick() {
      const elapsed = ctx!.currentTime - startTimeRef.current;

      const starts = sceneStartTimesRef.current;
      for (let i = starts.length - 1; i >= 0; i--) {
        if (elapsed >= starts[i]) {
          setCurrentScene(i);
          break;
        }
      }

      while (nextActionRef.current < timeline.length) {
        const next = timeline[nextActionRef.current];
        if (elapsed >= next.at) {
          try {
            next.action(bridgeRef.current);
          } catch (err) {
            console.warn(`Demo action failed [${next.label}]:`, err);
          }
          nextActionRef.current++;
        } else {
          break;
        }
      }

      rafRef.current = requestAnimationFrame(tick);
    }

    rafRef.current = requestAnimationFrame(tick);
  }, [phase, buildTimeline]);

  // ── Keyboard handler ───────────────────────────────────────────────
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.code === "Space" && phase === "ready") {
        e.preventDefault();
        start();
      }
      if (e.code === "Escape" && phase === "playing") {
        audioCtxRef.current?.close();
        cancelAnimationFrame(rafRef.current);
        setPhase("done");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase, start]);

  // ── Cleanup ────────────────────────────────────────────────────────
  useEffect(() => {
    return () => {
      cancelAnimationFrame(rafRef.current);
      audioCtxRef.current?.close();
    };
  }, []);

  // ── Render ─────────────────────────────────────────────────────────
  const scenes: DemoScene[] = manifest?.scenes ?? [];
  const scene = scenes[currentScene];
  const totalScenes = scenes.length;

  if (phase === "loading") {
    return (
      <div className="fixed inset-0 z-[100] flex items-center justify-center bg-[#1d2021]/90">
        <div className="text-center">
          <div className="text-zinc-400 text-sm mb-4">Loading demo audio...</div>
          <div className="w-64 h-1 bg-zinc-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-[#fabd2f] transition-all duration-300"
              style={{ width: `${loadProgress}%` }}
            />
          </div>
          <div className="text-zinc-600 text-xs mt-2">{loadProgress}%</div>
        </div>
      </div>
    );
  }

  if (phase === "ready") {
    return (
      <div className="fixed inset-0 z-[100] flex items-center justify-center bg-[#1d2021]/80 backdrop-blur-sm">
        <div className="text-center">
          <div className="text-[#ebdbb2] text-lg mb-2">Hapax</div>
          <div className="text-zinc-500 text-xs mb-6">{totalScenes} scenes</div>
          <div className="text-[#fabd2f] text-sm animate-pulse">Press Space to start</div>
          <div className="text-zinc-600 text-[10px] mt-4">Escape to stop at any time</div>
        </div>
      </div>
    );
  }

  if (phase === "done") {
    return (
      <div className="fixed inset-0 z-[100] flex items-center justify-center bg-[#1d2021]/80 backdrop-blur-sm">
        <div className="text-center">
          <div className="text-[#ebdbb2] text-lg">Demo complete</div>
          <div className="text-zinc-500 text-xs mt-2">
            Reload page to exit demo mode
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed bottom-0 left-0 right-0 z-[100] pointer-events-none">
      <div className="flex items-center justify-between px-4 py-2 bg-[#1d2021]/60 backdrop-blur-sm">
        <div className="text-zinc-400 text-[10px] uppercase tracking-widest">
          {scene?.title}
        </div>
        <div className="text-zinc-600 text-[10px]">
          {currentScene + 1}/{totalScenes}
        </div>
      </div>
      <div className="h-px bg-zinc-800">
        <div
          className="h-full bg-[#fabd2f]/40 transition-all duration-1000"
          style={{ width: `${((currentScene + 1) / totalScenes) * 100}%` }}
        />
      </div>
    </div>
  );
}
