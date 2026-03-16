import { useEffect, useRef, useState } from "react";
import { PRESETS, type CompositePreset } from "./compositePresets";
import { SOURCE_FILTERS } from "./compositeFilters";
import VisualLayerPanel from "./VisualLayerPanel";
import {
  useStudio,
  useStudioStreamInfo,
  useCompositorLive,
  useStudioDisk,
  useRecordingToggle,
} from "../../api/hooks";
import {
  Layers,
  Circle,
  Radio,
  Camera,
  Mic,
  Eye,
  Clock,
  PanelRightClose,
  PanelRightOpen,
  LayoutGrid,
  Sparkles,
  Video,
  Square,
} from "lucide-react";

const EFFECT_TOGGLES: { key: keyof CompositePreset["effects"]; label: string }[] = [
  { key: "scanlines", label: "Scanlines" },
  { key: "bandDisplacement", label: "Glitch Bands" },
  { key: "vignette", label: "Vignette" },
  { key: "syrupGradient", label: "Syrup" },
];

interface Props {
  viewMode: "grid" | "composite" | "smooth";
  onViewModeChange: (m: "grid" | "composite" | "smooth") => void;
  presetIdx: number;
  onPresetChange: (i: number) => void;
  liveFilterIdx: number;
  onLiveFilterChange: (i: number) => void;
  trailFilterIdx: number;
  onTrailFilterChange: (i: number) => void;
  effectOverrides: Partial<CompositePreset["effects"]> | null;
  baseEffects: CompositePreset["effects"];
  onEffectToggle: (key: keyof CompositePreset["effects"]) => void;
  onEffectReset: () => void;
  heroRole: string | null;
  onHeroChange: (role: string) => void;
  onOrderReset: () => void;
  cameraRoles: string[];
}

export function StudioSidebar({
  viewMode,
  onViewModeChange,
  presetIdx,
  onPresetChange,
  liveFilterIdx,
  onLiveFilterChange,
  trailFilterIdx,
  onTrailFilterChange,
  effectOverrides,
  baseEffects,
  onEffectToggle,
  onEffectReset,
  heroRole,
  onHeroChange,
  onOrderReset,
  cameraRoles,
}: Props) {
  const { data: studio } = useStudio();
  const { data: streamInfo } = useStudioStreamInfo();
  const { data: liveStatus } = useCompositorLive();
  const { data: diskInfo } = useStudioDisk();
  const recordingToggle = useRecordingToggle();
  const compositor = studio?.compositor;
  const capture = studio?.capture;
  const isRecording = compositor?.recording_enabled ?? false;
  const [collapsed, setCollapsed] = useState(false);

  // Recording timer
  const [recElapsed, setRecElapsed] = useState("");
  const recStartRef = useRef<number | null>(null);

  useEffect(() => {
    if (!isRecording) {
      recStartRef.current = null;
      setRecElapsed("");
      return;
    }
    if (!recStartRef.current) recStartRef.current = Date.now();
    const tick = () => {
      if (!recStartRef.current) return;
      const s = Math.floor((Date.now() - recStartRef.current) / 1000);
      const m = Math.floor(s / 60);
      setRecElapsed(`${m}:${String(s % 60).padStart(2, "0")}`);
    };
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [isRecording]);
  const [expandToSection, setExpandToSection] = useState<string | null>(null);
  const sectionRefs = {
    view: useRef<HTMLElement>(null),
    recording: useRef<HTMLElement>(null),
    stream: useRef<HTMLElement>(null),
    layout: useRef<HTMLElement>(null),
    visualLayer: useRef<HTMLElement>(null),
    audio: useRef<HTMLElement>(null),
  };

  useEffect(() => {
    if (!collapsed && expandToSection) {
      const ref = sectionRefs[expandToSection as keyof typeof sectionRefs];
      if (ref?.current) {
        ref.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
      setExpandToSection(null);
    }
  }, [collapsed, expandToSection]);

  const expandTo = (section: string) => {
    setExpandToSection(section);
    setCollapsed(false);
  };

  const isComposite = viewMode === "composite";
  const currentEffects = effectOverrides
    ? { ...baseEffects, ...effectOverrides }
    : baseEffects;
  const recordingCams = compositor?.recording_cameras ?? {};

  // --- Collapsed: icon strip ---
  if (collapsed) {
    return (
      <div className="flex w-10 shrink-0 flex-col items-center gap-3 border-l border-zinc-800 bg-zinc-900/50 py-3">
        <button
          onClick={() => setCollapsed(false)}
          className="text-zinc-500 hover:text-zinc-300"
          title="Expand sidebar"
        >
          <PanelRightClose className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={() => expandTo("view")}
          className="text-zinc-500 hover:text-zinc-300"
          title="View"
        >
          <Layers className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={() => expandTo("recording")}
          className="relative text-zinc-500 hover:text-zinc-300"
          title="Recording"
        >
          <Circle className="h-3.5 w-3.5" />
          {isRecording && (
            <span className="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 animate-pulse rounded-full bg-red-500" />
          )}
        </button>
        <button
          onClick={() => expandTo("stream")}
          className="relative text-zinc-500 hover:text-zinc-300"
          title="Stream"
        >
          <Radio className="h-3.5 w-3.5" />
          {streamInfo?.hls_enabled && (
            <span className="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full bg-green-500" />
          )}
        </button>
        <button
          onClick={() => expandTo("layout")}
          className="text-zinc-500 hover:text-zinc-300"
          title="Layout"
        >
          <Camera className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={() => expandTo("audio")}
          className="relative text-zinc-500 hover:text-zinc-300"
          title="Audio"
        >
          <Mic className="h-3.5 w-3.5" />
          {capture?.audio_recorder_active && (
            <span className="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full bg-green-500" />
          )}
        </button>
      </div>
    );
  }

  // --- Expanded ---
  return (
    <div className="flex w-60 shrink-0 flex-col border-l border-zinc-800 bg-zinc-900/50 text-xs">
      {/* Collapse button */}
      <div className="flex items-center justify-between border-b border-zinc-700/40 px-3 py-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
          Controls
        </span>
        <button
          onClick={() => setCollapsed(true)}
          className="text-zinc-500 hover:text-zinc-300"
          title="Collapse sidebar"
        >
          <PanelRightOpen className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto">
        {/* VIEW */}
        <section ref={sectionRefs.view} className="border-b border-zinc-700/40 px-3 py-2.5">
          <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
            View
          </h3>
          <div className="flex gap-1">
            {(
              [
                { mode: "grid" as const, label: "Grid", Icon: LayoutGrid },
                { mode: "composite" as const, label: "FX", Icon: Sparkles },
                { mode: "smooth" as const, label: "Smooth", Icon: Video },
              ] as const
            ).map(({ mode, label, Icon }) => (
              <button
                key={mode}
                onClick={() => onViewModeChange(mode)}
                className={`flex flex-1 items-center justify-center gap-1 rounded px-1.5 py-1 text-[10px] font-medium transition-colors ${
                  viewMode === mode
                    ? "bg-zinc-700 text-zinc-100"
                    : "bg-zinc-800/50 text-zinc-500 hover:text-zinc-300"
                }`}
              >
                <Icon className="h-3 w-3" />
                {label}
              </button>
            ))}
          </div>
          {compositor && compositor.state !== "unknown" && (
            <p className="mt-1.5 text-[10px] text-zinc-600">
              {compositor.resolution} · {compositor.active_cameras}/{compositor.total_cameras} cams
            </p>
          )}
        </section>

        {/* PRESET (composite only) */}
        {isComposite && (
          <section className="border-b border-zinc-700/40 px-3 py-2.5">
            <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
              Preset
            </h3>
            <div className="flex flex-col gap-0.5">
              {PRESETS.map((p, i) => (
                <button
                  key={p.name}
                  onClick={() => onPresetChange(i)}
                  className={`flex items-start gap-2 rounded px-2 py-1.5 text-left transition-colors ${
                    presetIdx === i
                      ? "bg-purple-950/30 text-zinc-200"
                      : "text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-300"
                  }`}
                >
                  <span
                    className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${
                      presetIdx === i ? "bg-purple-400" : "bg-zinc-700"
                    }`}
                  />
                  <div className="min-w-0">
                    <div className="text-[11px] font-medium">{p.name}</div>
                    <div className="text-[10px] text-zinc-600">{p.description}</div>
                  </div>
                </button>
              ))}
            </div>
          </section>
        )}

        {/* FILTERS (composite only) */}
        {isComposite && (
          <section className="border-b border-zinc-700/40 px-3 py-2.5">
            <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
              Filters
            </h3>
            <div className="flex flex-col gap-2">
              {/* Live filter */}
              <label className="flex items-center gap-1.5">
                <Eye className="h-3 w-3 shrink-0 text-amber-400" />
                <span className="shrink-0 text-[10px] text-amber-300">Live</span>
                <select
                  value={liveFilterIdx}
                  onChange={(e) => onLiveFilterChange(Number(e.target.value))}
                  className="ml-auto w-24 rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-300 outline-none focus:ring-1 focus:ring-zinc-600"
                >
                  {SOURCE_FILTERS.map((f, i) => (
                    <option key={f.name} value={i}>
                      {f.name}
                    </option>
                  ))}
                </select>
              </label>
              {/* Trail filter */}
              <label className="flex items-center gap-1.5">
                <Clock className="h-3 w-3 shrink-0 text-cyan-400" />
                <span className="shrink-0 text-[10px] text-cyan-300">Trail</span>
                <select
                  value={trailFilterIdx}
                  onChange={(e) => onTrailFilterChange(Number(e.target.value))}
                  className="ml-auto w-24 rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-300 outline-none focus:ring-1 focus:ring-zinc-600"
                >
                  {SOURCE_FILTERS.map((f, i) => (
                    <option key={f.name} value={i}>
                      {f.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </section>
        )}

        {/* EFFECTS (composite only) */}
        {isComposite && (
          <section className="border-b border-zinc-700/40 px-3 py-2.5">
            <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
              Effects
            </h3>
            <div className="flex flex-wrap gap-1">
              {EFFECT_TOGGLES.map(({ key, label }) => {
                const active = !!currentEffects[key];
                return (
                  <button
                    key={key}
                    onClick={() => onEffectToggle(key)}
                    className={`rounded px-2 py-0.5 text-[10px] font-medium transition-colors ${
                      active
                        ? "bg-purple-900/50 text-purple-300"
                        : "bg-zinc-800/50 text-zinc-500 hover:text-zinc-400"
                    }`}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
            {effectOverrides !== null && (
              <button
                onClick={onEffectReset}
                className="mt-1.5 text-[10px] text-purple-400 hover:text-purple-300"
              >
                Reset to preset
              </button>
            )}
          </section>
        )}

        {/* RECORDING */}
        <section ref={sectionRefs.recording} className="border-b border-zinc-700/40 px-3 py-2.5">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
              Recording
              {isRecording && (
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-red-500" />
              )}
              {recElapsed && (
                <span className="font-mono text-[10px] font-normal text-red-400">
                  {recElapsed}
                </span>
              )}
            </h3>
            <button
              onClick={() => recordingToggle.mutate(!isRecording)}
              disabled={recordingToggle.isPending}
              className={`flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-medium transition-colors ${
                isRecording
                  ? "bg-red-900/50 text-red-300 hover:bg-red-900/70"
                  : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-200"
              }`}
            >
              {isRecording ? (
                <>
                  <Square className="h-2.5 w-2.5" />
                  Stop
                </>
              ) : (
                <>
                  <Circle className="h-2.5 w-2.5 fill-current" />
                  Record
                </>
              )}
            </button>
          </div>
          {cameraRoles.length > 0 ? (
            <div className="flex flex-col gap-1">
              {cameraRoles.map((role) => {
                const recStatus = recordingCams[role];
                const recActive = recStatus === "active";
                return (
                  <div key={role} className="flex items-center justify-between">
                    <span className="truncate text-[10px] text-zinc-400">{role}</span>
                    {recActive && (
                      <span className="shrink-0 rounded bg-red-900/50 px-1 py-0.5 text-[9px] font-medium text-red-400">
                        REC
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-[10px] text-zinc-600">No cameras</p>
          )}
          {/* Disk space */}
          {diskInfo && (
            <div className="mt-2">
              <div className="mb-0.5 flex items-center justify-between text-[10px]">
                <span className="text-zinc-500">Disk</span>
                <span className={`${diskInfo.free_gb < diskInfo.total_gb * 0.1 ? "text-red-400" : "text-zinc-400"}`}>
                  {diskInfo.free_gb}GB free
                </span>
              </div>
              <div className="h-1 overflow-hidden rounded-full bg-zinc-800">
                <div
                  className={`h-full rounded-full transition-all ${
                    diskInfo.free_gb < diskInfo.total_gb * 0.1
                      ? "bg-red-500"
                      : "bg-zinc-600"
                  }`}
                  style={{ width: `${Math.min((diskInfo.used_gb / diskInfo.total_gb) * 100, 100)}%` }}
                />
              </div>
            </div>
          )}
          {/* Consent status */}
          <div className="mt-2 flex items-center gap-2">
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                compositor?.consent_phase === "consent_refused"
                  ? "bg-red-500"
                  : compositor?.consent_phase === "consent_pending"
                    ? "bg-orange-500 animate-pulse"
                    : compositor?.consent_phase === "guest_detected"
                      ? "bg-yellow-500 animate-pulse"
                      : compositor?.consent_recording_allowed !== false
                        ? "bg-green-500"
                        : "bg-orange-500 animate-pulse"
              }`}
            />
            <span className="text-[10px] text-zinc-400">
              {compositor?.consent_phase === "consent_refused"
                ? "Guest refused"
                : compositor?.consent_phase === "consent_pending"
                  ? "Consent pending"
                  : compositor?.consent_phase === "guest_detected"
                    ? "Guest detected"
                    : compositor?.consent_phase === "consent_granted"
                      ? "Guest consented"
                      : "Consent OK"}
            </span>
          </div>
        </section>

        {/* STREAM */}
        <section ref={sectionRefs.stream} className="border-b border-zinc-700/40 px-3 py-2.5">
          <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
            Stream
          </h3>
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-1.5">
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  streamInfo?.hls_enabled ? "bg-green-500" : "bg-red-500"
                }`}
              />
              <span className="text-[10px] text-zinc-400">HLS</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  streamInfo?.enabled ? "bg-green-500" : "bg-red-500"
                }`}
              />
              <span className="text-[10px] text-zinc-400">Snapshot</span>
            </div>
          </div>
        </section>

        {/* LAYOUT */}
        <section ref={sectionRefs.layout} className="border-b border-zinc-700/40 px-3 py-2.5">
          <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
            Layout
          </h3>
          <label className="flex items-center gap-1.5">
            <span className="shrink-0 text-[10px] text-zinc-400">Hero</span>
            <select
              value={heroRole ?? ""}
              onChange={(e) => onHeroChange(e.target.value)}
              className="flex-1 rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-300 outline-none focus:ring-1 focus:ring-zinc-600"
            >
              <option value="">None</option>
              {cameraRoles.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </label>
          <button
            onClick={onOrderReset}
            className="mt-1.5 text-[10px] text-zinc-500 hover:text-zinc-300"
          >
            Reset order
          </button>
        </section>

        {/* VISUAL LAYER */}
        <section ref={sectionRefs.visualLayer} className="border-b border-zinc-700/40 px-3 py-2.5">
          <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
            Visual Layer
          </h3>
          <VisualLayerPanel />
        </section>

        {/* AUDIO */}
        <section ref={sectionRefs.audio} className="px-3 py-2.5">
          <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
            Audio
          </h3>
          <div className="flex items-center gap-1.5">
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                capture?.audio_recorder_active ? "bg-green-500" : "bg-red-500"
              }`}
            />
            <span className="text-[10px] text-zinc-400">
              {capture?.audio_recorder_active ? "Active" : "Inactive"}
            </span>
          </div>
          {/* VU meter */}
          {(() => {
            const energy = liveStatus?.audio_energy_rms ?? 0;
            const level = Math.min(energy * 4, 1);
            const pct = level * 100;
            const color =
              pct > 80 ? "bg-red-500" : pct > 50 ? "bg-yellow-500" : "bg-green-500";
            return (
              <div className="mt-2">
                <div className="mb-0.5 text-[10px] text-zinc-500">Level</div>
                <div className="h-1.5 overflow-hidden rounded-full bg-zinc-800">
                  <div
                    className={`h-full rounded-full transition-all duration-150 ${color}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            );
          })()}
        </section>
      </div>
    </div>
  );
}
