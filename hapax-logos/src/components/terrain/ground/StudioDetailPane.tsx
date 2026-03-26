import { useEffect, useRef, useState } from "react";
import { Circle, Square, ChevronDown, ChevronRight } from "lucide-react";
import { EFFECT_SOURCES } from "../../studio/effectSources";
import VisualLayerPanel from "../../studio/VisualLayerPanel";
import {
  useStudio,
  useStudioStreamInfo,
  useCompositorLive,
  useStudioDisk,
  useRecordingToggle,
} from "../../../api/hooks";
import type { ClassificationDetection } from "../../../api/types";
import { useGroundStudio } from "../../../contexts/GroundStudioContext";
import { useTerrainActions, useTerrainDisplay } from "../../../contexts/TerrainContext";

/** Preset names fetched from backend effect graph. */
const BACKEND_PRESETS = [
  "Ghost", "Trails", "Screwed", "Datamosh", "VHS", "Neon", "Trap", "Diff",
  "NightVision", "Silhouette", "Thermal IR", "Pixsort", "Slit-scan", "Feedback",
  "Halftone", "Glitch Blocks", "ASCII", "Ambient", "Clean",
];

const EFFECT_TOGGLES = [
  { key: "scanlines", label: "Scanlines" },
  { key: "bandDisplacement", label: "Glitch Bands" },
  { key: "vignette", label: "Vignette" },
  { key: "syrupGradient", label: "Syrup" },
] as const;

interface StudioDetailPaneProps {
  classificationDetections: ClassificationDetection[];
}

export function StudioDetailPane({
  classificationDetections,
}: StudioDetailPaneProps) {
  const {
    heroRole, setHeroRole,
    effectSourceId, setEffectSourceId,
    smoothMode, setSmoothMode,
  } = useGroundStudio();
  const { data: studio } = useStudio();
  const { data: streamInfo } = useStudioStreamInfo();
  const { data: liveStatus } = useCompositorLive();
  const { data: diskInfo } = useStudioDisk();
  const recordingToggle = useRecordingToggle();
  const compositor = studio?.compositor;
  const capture = studio?.capture;
  const isRecording = compositor?.recording_enabled ?? false;
  const cameraRoles = compositor ? Object.keys(compositor.cameras) : [];
  const recordingCams = compositor?.recording_cameras ?? {};
  const [sourceExpanded, setSourceExpanded] = useState(false);
  const [recExpanded, setRecExpanded] = useState(false);
  const { setRegionDepth } = useTerrainActions();
  const { regionDepths } = useTerrainDisplay();

  // Track active preset name (from backend)
  const [activePreset, setActivePreset] = useState<string | null>(null);
  // Track active effect states (from backend)
  const [effectStates, setEffectStates] = useState<Record<string, boolean>>({
    scanlines: false,
    bandDisplacement: false,
    vignette: false,
    syrupGradient: false,
  });

  const activateHls = () => {
    setSmoothMode(true);
    if (regionDepths.ground !== "core") setRegionDepth("ground", "core");
  };

  const activatePreset = async (name: string) => {
    try {
      await fetch(`/api/studio/presets/${encodeURIComponent(name)}/activate`, { method: "POST" });
      setActivePreset(name);
    } catch { /* ignore */ }
  };

  const toggleEffect = async (key: string) => {
    const enabled = !effectStates[key];
    try {
      await fetch("/api/studio/effect/graph", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node: key, enabled }),
      });
      setEffectStates((prev) => ({ ...prev, [key]: enabled }));
    } catch { /* ignore */ }
  };

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
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [isRecording]);

  // Consent summary
  const consentLabel =
    compositor?.consent_phase === "consent_refused" ? "Refused"
    : compositor?.consent_phase === "consent_pending" ? "Pending"
    : compositor?.consent_phase === "guest_detected" ? "Guest"
    : "OK";
  const consentColor =
    compositor?.consent_phase === "consent_refused" ? "bg-red-500"
    : compositor?.consent_phase === "consent_pending" ? "bg-orange-500 animate-pulse"
    : compositor?.consent_phase === "guest_detected" ? "bg-yellow-500 animate-pulse"
    : "bg-green-500";

  // Recording camera count
  const recCount = Object.values(recordingCams).filter(s => s === "active").length;

  return (
    <div className="flex h-full flex-col overflow-y-auto text-xs">
      {/* CAMERA */}
      <Section title="Camera">
        <label className="flex items-center gap-1.5">
          <span className="shrink-0 text-[10px] text-zinc-400">Hero</span>
          <select
            value={heroRole}
            onChange={(e) => setHeroRole(e.target.value)}
            className="flex-1 rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-300 outline-none focus:ring-1 focus:ring-zinc-600"
          >
            {cameraRoles.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </label>
        <div className="mt-1.5 flex flex-wrap gap-2">
          {cameraRoles.map((role) => {
            const status = compositor?.cameras[role] ?? "offline";
            return (
              <div key={role} className="flex items-center gap-1">
                <span className={`h-1.5 w-1.5 rounded-full ${
                  status === "active" ? "bg-green-500"
                  : status === "starting" ? "bg-yellow-500"
                  : "bg-red-500"
                }`} />
                <span className="text-[10px] text-zinc-400">{role}</span>
              </div>
            );
          })}
        </div>
      </Section>

      {/* MODE */}
      <Section title="Mode">
        <div className="flex gap-1">
          <button
            onClick={() => { if (smoothMode) { setSmoothMode(false); } else { activateHls(); } }}
            className={`flex-1 rounded px-2 py-1 text-[10px] font-medium transition-colors ${
              smoothMode
                ? "bg-green-900/50 text-green-300"
                : "bg-zinc-800/50 text-zinc-500 hover:text-zinc-300"
            }`}
          >
            HLS
          </button>
        </div>
        <div className="mt-1.5 flex items-center gap-1.5">
          <span className={`h-1.5 w-1.5 rounded-full ${streamInfo?.hls_enabled ? "bg-green-500" : "bg-red-500"}`} />
          <span className="text-[10px] text-zinc-400">
            HLS {streamInfo?.hls_enabled ? "available" : "offline"}
          </span>
        </div>
      </Section>

      {/* PRESET — backend-driven presets */}
      <Section title="Preset">
        <div className="grid grid-cols-6 gap-0.5">
          {BACKEND_PRESETS.map((name) => (
            <button
              key={name}
              onClick={() => activatePreset(name)}
              className={`rounded px-1 py-1 text-left text-[9px] transition-colors ${
                activePreset === name
                  ? "bg-zinc-800 text-zinc-200"
                  : "text-zinc-500 hover:bg-zinc-800/30"
              }`}
              style={{
                borderLeft: `2px solid ${
                  activePreset === name ? "var(--color-zinc-400)" : "transparent"
                }`,
              }}
            >
              {name.length > 6 ? name.slice(0, 6) : name}
            </button>
          ))}
        </div>
      </Section>

      {/* SOURCE — collapsible chip grid */}
      <Section title="Source">
        <button
          onClick={() => setSourceExpanded(!sourceExpanded)}
          className="flex w-full items-center gap-1.5 text-[10px] text-zinc-400 hover:text-zinc-300"
        >
          {sourceExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          <span>{EFFECT_SOURCES.find(s => s.id === effectSourceId)?.label ?? "Camera"}</span>
        </button>
        {sourceExpanded && (
          <div className="mt-1.5 grid grid-cols-4 gap-0.5">
            {EFFECT_SOURCES.map((src) => (
              <button
                key={src.id}
                onClick={() => { setEffectSourceId(src.id); setSourceExpanded(false); }}
                className={`rounded px-1.5 py-1 text-[9px] transition-colors ${
                  effectSourceId === src.id
                    ? "bg-zinc-800 text-zinc-200"
                    : "text-zinc-500 hover:bg-zinc-800/30"
                }`}
              >
                {src.label}
              </button>
            ))}
          </div>
        )}
      </Section>

      {/* EFFECTS — 2x2 toggle grid, backend-driven */}
      <Section title="Effects">
        <div className="grid grid-cols-2 gap-1">
          {EFFECT_TOGGLES.map(({ key, label }) => {
            const active = !!effectStates[key];
            return (
              <button
                key={key}
                onClick={() => toggleEffect(key)}
                className="flex items-center gap-2 rounded px-1.5 py-1 transition-colors hover:bg-zinc-800/50"
              >
                <span
                  className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{
                    backgroundColor: active ? "var(--color-fuchsia-400)" : "var(--color-zinc-600)",
                    opacity: active ? 1.0 : 0.2,
                  }}
                />
                <span className={`text-[10px] ${active ? "text-zinc-200" : "text-zinc-600"}`}>
                  {label}
                </span>
              </button>
            );
          })}
        </div>
      </Section>

      {/* ENTITIES */}
      <Section title={`Entities (${classificationDetections.length})`}>
        {classificationDetections.length === 0 ? (
          <p className="text-[10px] text-zinc-600">No detections</p>
        ) : (
          <div className="flex flex-col gap-1">
            {classificationDetections.map((det) => (
              <div
                key={det.entity_id}
                className="flex items-center gap-2 rounded border border-zinc-800 px-2 py-1"
              >
                <span
                  className="inline-block h-2 w-2 shrink-0 rounded-full"
                  style={{
                    background: det.consent_suppressed
                      ? "var(--color-zinc-600)"
                      : det.label === "person"
                        ? "var(--color-emerald-400)"
                        : "var(--color-blue-400)",
                  }}
                />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[10px] font-medium text-zinc-300">
                    {det.label}
                  </div>
                  <div className="text-[9px] text-zinc-600">
                    {det.camera} · {(det.confidence * 100).toFixed(0)}% · {det.mobility}
                  </div>
                </div>
                {det.consent_suppressed && (
                  <span className="shrink-0 text-[8px] text-orange-400">suppressed</span>
                )}
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* RECORDING — compact with collapsible detail */}
      <Section title="Recording">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            {isRecording && (
              <>
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-red-500" />
                <span className="font-mono text-[10px] text-red-400">{recElapsed}</span>
              </>
            )}
            <button
              onClick={() => setRecExpanded(!recExpanded)}
              className="text-[10px] text-zinc-600 hover:text-zinc-400"
            >
              {recCount}/{cameraRoles.length} cams · <span className={`inline-block h-1.5 w-1.5 rounded-full ${consentColor}`} /> {consentLabel}
            </button>
          </div>
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
              <><Square className="h-2.5 w-2.5" /> Stop</>
            ) : (
              <><Circle className="h-2.5 w-2.5 fill-current" /> Record</>
            )}
          </button>
        </div>
        {recExpanded && (
          <div className="mt-2">
            {cameraRoles.map((role) => {
              const recActive = recordingCams[role] === "active";
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
            {diskInfo && (
              <div className="mt-2">
                <div className="mb-0.5 flex items-center justify-between text-[10px]">
                  <span className="text-zinc-500">Disk</span>
                  <span className={diskInfo.free_gb < diskInfo.total_gb * 0.1 ? "text-red-400" : "text-zinc-400"}>
                    {diskInfo.free_gb}GB free
                  </span>
                </div>
                <div className="h-1 overflow-hidden rounded-full bg-zinc-800">
                  <div
                    className={`h-full rounded-full transition-all ${
                      diskInfo.free_gb < diskInfo.total_gb * 0.1 ? "bg-red-500" : "bg-zinc-600"
                    }`}
                    style={{ width: `${Math.min((diskInfo.used_gb / diskInfo.total_gb) * 100, 100)}%` }}
                  />
                </div>
              </div>
            )}
          </div>
        )}
      </Section>

      {/* VISUAL LAYER */}
      <Section title="Visual Layer">
        <VisualLayerPanel />
      </Section>

      {/* AUDIO */}
      <Section title="Audio">
        <div className="flex items-center gap-1.5">
          <span className={`h-1.5 w-1.5 rounded-full ${capture?.audio_recorder_active ? "bg-green-500" : "bg-red-500"}`} />
          <span className="text-[10px] text-zinc-400">
            {capture?.audio_recorder_active ? "Active" : "Inactive"}
          </span>
        </div>
        {(() => {
          const energy = liveStatus?.audio_energy_rms ?? 0;
          const level = Math.min(energy * 4, 1);
          const pct = level * 100;
          const color = pct > 80 ? "bg-red-500" : pct > 50 ? "bg-yellow-500" : "bg-green-500";
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
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-zinc-700/40 px-3 py-2.5">
      <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
        {title}
      </h3>
      {children}
    </section>
  );
}
