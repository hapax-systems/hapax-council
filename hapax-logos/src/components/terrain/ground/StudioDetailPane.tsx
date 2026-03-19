import { useEffect, useRef, useState } from "react";
import { Circle, Square } from "lucide-react";
import { PRESETS } from "../../studio/compositePresets";
import VisualLayerPanel from "../../studio/VisualLayerPanel";
import {
  useStudio,
  useStudioStreamInfo,
  useCompositorLive,
  useStudioDisk,
  useRecordingToggle,
} from "../../../api/hooks";
import type { ClassificationDetection } from "../../../api/types";
import { api } from "../../../api/client";

interface StudioDetailPaneProps {
  heroRole: string;
  onHeroChange: (role: string) => void;
  classificationDetections: ClassificationDetection[];
  fxMode: boolean;
  onFxModeChange: (on: boolean) => void;
  smoothMode: boolean;
  onSmoothModeChange: (on: boolean) => void;
}

export function StudioDetailPane({
  heroRole,
  onHeroChange,
  classificationDetections,
  fxMode,
  onFxModeChange,
  smoothMode,
  onSmoothModeChange,
}: StudioDetailPaneProps) {
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
  const [presetIdx, setPresetIdx] = useState(0);

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

  return (
    <div className="flex h-full flex-col overflow-y-auto text-xs">
      {/* CAMERA SELECT */}
      <Section title="Camera">
        <label className="flex items-center gap-1.5">
          <span className="shrink-0 text-[10px] text-zinc-400">Hero</span>
          <select
            value={heroRole}
            onChange={(e) => onHeroChange(e.target.value)}
            className="flex-1 rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-300 outline-none focus:ring-1 focus:ring-zinc-600"
          >
            {cameraRoles.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        {/* Camera status dots */}
        <div className="mt-1.5 flex flex-wrap gap-2">
          {cameraRoles.map((role) => {
            const status = compositor?.cameras[role] ?? "offline";
            return (
              <div key={role} className="flex items-center gap-1">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    status === "active"
                      ? "bg-green-500"
                      : status === "starting"
                        ? "bg-yellow-500"
                        : "bg-red-500"
                  }`}
                />
                <span className="text-[10px] text-zinc-400">{role}</span>
              </div>
            );
          })}
        </div>
      </Section>

      {/* DETECTION ENTITIES */}
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
                      ? "#665c54"
                      : det.label === "person"
                        ? "#8ec07c"
                        : "#83a598",
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

      {/* RECORDING */}
      <Section title="Recording">
        <div className="mb-2 flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            {isRecording && (
              <>
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-red-500" />
                <span className="font-mono text-[10px] text-red-400">{recElapsed}</span>
              </>
            )}
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
        {/* Per-camera recording status */}
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
        {/* Disk */}
        {diskInfo && (
          <div className="mt-2">
            <div className="mb-0.5 flex items-center justify-between text-[10px]">
              <span className="text-zinc-500">Disk</span>
              <span
                className={diskInfo.free_gb < diskInfo.total_gb * 0.1 ? "text-red-400" : "text-zinc-400"}
              >
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
        {/* Consent */}
        <div className="mt-2 flex items-center gap-2">
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              compositor?.consent_phase === "consent_refused"
                ? "bg-red-500"
                : compositor?.consent_phase === "consent_pending"
                  ? "bg-orange-500 animate-pulse"
                  : compositor?.consent_phase === "guest_detected"
                    ? "bg-yellow-500 animate-pulse"
                    : "bg-green-500"
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
      </Section>

      {/* VISUAL LAYER */}
      <Section title="Visual Layer">
        <VisualLayerPanel />
      </Section>

      {/* FX MODE */}
      <Section title="FX Mode">
        <button
          onClick={() => {
            onFxModeChange(!fxMode);
            if (!fxMode) onSmoothModeChange(false);
          }}
          className={`mb-2 w-full rounded px-2 py-1 text-[10px] font-medium transition-colors ${
            fxMode
              ? "bg-purple-900/50 text-purple-300"
              : "bg-zinc-800 text-zinc-500 hover:text-zinc-300"
          }`}
        >
          {fxMode ? "FX Active" : "Enable FX"}
        </button>
        {fxMode && (
          <div className="flex flex-col gap-0.5">
            {PRESETS.map((p, i) => (
              <button
                key={p.name}
                onClick={() => {
                  setPresetIdx(i);
                  api.selectEffect(p.name.toLowerCase()).catch(() => {});
                }}
                className={`rounded px-2 py-1 text-left text-[10px] transition-colors ${
                  presetIdx === i
                    ? "bg-purple-950/30 text-zinc-200"
                    : "text-zinc-400 hover:bg-zinc-800/50"
                }`}
              >
                {p.name}
              </button>
            ))}
          </div>
        )}
      </Section>

      {/* STREAM */}
      <Section title="Stream">
        <button
          onClick={() => {
            onSmoothModeChange(!smoothMode);
            if (!smoothMode) onFxModeChange(false);
          }}
          className={`mb-2 w-full rounded px-2 py-1 text-[10px] font-medium transition-colors ${
            smoothMode
              ? "bg-green-900/50 text-green-300"
              : "bg-zinc-800 text-zinc-500 hover:text-zinc-300"
          }`}
        >
          {smoothMode ? "HLS Active" : "Enable HLS"}
        </button>
        <div className="flex items-center gap-1.5">
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              streamInfo?.hls_enabled ? "bg-green-500" : "bg-red-500"
            }`}
          />
          <span className="text-[10px] text-zinc-400">
            HLS {streamInfo?.hls_enabled ? "available" : "offline"}
          </span>
        </div>
      </Section>

      {/* AUDIO */}
      <Section title="Audio">
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
