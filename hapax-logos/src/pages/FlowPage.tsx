import { useCallback, useEffect, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  type EdgeProps,
  Position,
  MarkerType,
  Handle,
  useNodesState,
  useEdgesState,
  getBezierPath,
  BaseEdge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { invoke } from "@tauri-apps/api/core";
import { api } from "../api/client";
import { useTheme } from "../theme/ThemeProvider";
import type { ThemePalette } from "../theme/palettes";

// ── Types ───────────────────────────────────────────────────────────

interface NodeMetrics { [key: string]: unknown; }
interface FlowNode { id: string; label: string; status: string; age_s: number; metrics: NodeMetrics; [key: string]: unknown; }
interface FlowEdge { source: string; target: string; active: boolean; label: string; }
interface SystemFlowState { nodes: FlowNode[]; edges: FlowEdge[]; timestamp: number; }

// ── Layout ──────────────────────────────────────────────────────────

const POSITIONS: Record<string, { x: number; y: number }> = {
  perception: { x: 400, y: 50 }, stimmung: { x: 100, y: 230 }, temporal: { x: 400, y: 230 },
  consent: { x: 700, y: 230 }, apperception: { x: 200, y: 420 }, phenomenal: { x: 520, y: 420 },
  voice: { x: 400, y: 610 }, engine: { x: 60, y: 610 }, compositor: { x: 720, y: 610 },
};

// ── Color helpers ───────────────────────────────────────────────────

function flowColors(p: ThemePalette) {
  return {
    active: { bg: `color-mix(in srgb, ${p["green-400"]} 10%, transparent)`, border: p["green-400"], glow: `color-mix(in srgb, ${p["green-400"]} 25%, transparent)` },
    stale: { bg: `color-mix(in srgb, ${p["orange-400"]} 10%, transparent)`, border: p["orange-400"], glow: `color-mix(in srgb, ${p["orange-400"]} 15%, transparent)` },
    offline: { bg: `color-mix(in srgb, ${p["zinc-600"]} 6%, transparent)`, border: p["zinc-600"], glow: "transparent" },
  };
}

function edgeColor(age_s: number, active: boolean, p: ThemePalette): string {
  if (!active) return p["zinc-700"]; if (age_s < 5) return p["green-400"]; if (age_s < 15) return p["yellow-400"]; return p["orange-400"];
}
function sevColor(v: number, p: ThemePalette) { return v > 0.7 ? p["red-400"] : v > 0.4 ? p["orange-400"] : v > 0.2 ? p["yellow-400"] : p["green-400"]; }
function stColor(s: string, p: ThemePalette) { return s === "nominal" ? p["green-400"] : s === "cautious" ? p["yellow-400"] : s === "degraded" ? p["orange-400"] : s === "critical" ? p["red-400"] : p["zinc-500"]; }

const SIG_CAT: Record<string, string> = { context_time: "blue-400", governance: "fuchsia-400", work_tasks: "orange-400", health_infra: "red-400", profile_state: "green-400", ambient_sensor: "emerald-400", voice_session: "yellow-400", system_state: "zinc-600" };
const VOICE_COL: Record<string, string> = { listening: "green-400", transcribing: "green-400", thinking: "yellow-400", speaking: "blue-400" };

function breathDur(age: number, st: string) { if (st !== "active") return "0s"; if (age < 3) return "1.5s"; if (age < 10) return "2.5s"; if (age < 20) return "4s"; return "6s"; }
function nodeOp(age: number, st: string) { if (st === "offline") return 0.5; if (age < 5) return 1.0; if (age < 15) return 0.95; if (age < 30) return 0.85; return 0.7; }

// ── Micro-components ────────────────────────────────────────────────

function HBar({ value, color, width = 80, height = 3 }: { value: number; color: string; width?: number; height?: number }) {
  const f = Math.max(0, Math.min(1, value));
  return <div style={{ width, height, background: `color-mix(in srgb, ${color} 15%, transparent)`, borderRadius: 1 }}><div style={{ width: `${f * 100}%`, height: "100%", background: color, borderRadius: 1, transition: "width 1s ease" }} /></div>;
}

function VBar({ value, color, height = 20, opacity = 1 }: { value: number; color: string; height?: number; opacity?: number }) {
  const f = Math.max(0, Math.min(1, value));
  return <div style={{ width: 3, height, background: `color-mix(in srgb, ${color} 15%, transparent)`, borderRadius: 1, display: "flex", flexDirection: "column-reverse", opacity }}><div style={{ width: "100%", height: `${f * 100}%`, background: color, borderRadius: 1, transition: "height 1s ease" }} /></div>;
}

function ArcGauge({ value, color, size = 16 }: { value: number; color: string; size?: number }) {
  const r = (size - 2) / 2, circ = 2 * Math.PI * r, f = Math.max(0, Math.min(1, value));
  return <svg width={size} height={size} style={{ verticalAlign: "middle" }}><circle cx={size/2} cy={size/2} r={r} fill="none" stroke={`color-mix(in srgb, ${color} 15%, transparent)`} strokeWidth={1.5} /><circle cx={size/2} cy={size/2} r={r} fill="none" stroke={color} strokeWidth={1.5} strokeDasharray={`${f*circ} ${circ}`} strokeLinecap="round" transform={`rotate(-90 ${size/2} ${size/2})`} style={{ transition: "stroke-dasharray 1s ease" }} /></svg>;
}

// ── Flowing Edge ────────────────────────────────────────────────────

function FlowingEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data }: EdgeProps) {
  const [path] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const d = data as Record<string, unknown>;
  const active = (d?.active as boolean) ?? false, age = (d?.age_s as number) ?? 999;
  const isGated = (d?.gated as boolean) ?? false, lbl = (d?.label as string) ?? "";
  const { palette: ep } = useTheme();
  const color = edgeColor(age, active, ep);
  const pc = active ? (age < 5 ? 3 : age < 15 ? 2 : 1) : 0;
  return (
    <g className="flow-edge-group">
      <BaseEdge id={id} path={path} style={{ stroke: color, strokeWidth: active ? 1.5 : 0.8, opacity: active ? 0.7 : 0.15, transition: "stroke 1s ease, opacity 1s ease" }} />
      {isGated && <circle r="4" fill={ep["fuchsia-400"]} opacity="0.8"><animateMotion dur="0.01s" path={path} fill="freeze" keyPoints="0.5" keyTimes="0" /></circle>}
      {Array.from({ length: pc }).map((_, i) => <circle key={i} r="2" fill={color} opacity="0.8"><animateMotion dur={age < 5 ? "2s" : age < 15 ? "3.5s" : "5s"} path={path} repeatCount="indefinite" begin={`${i/pc}s`} /></circle>)}
      {lbl && <text className="flow-edge-label"><textPath href={`#${id}`} startOffset="50%" textAnchor="middle" style={{ fontSize: "9px", fill: active ? ep["text-muted"] : ep["border-muted"], fontFamily: "'JetBrains Mono', monospace" }}>{lbl}</textPath></text>}
    </g>
  );
}
const edgeTypes = { flowing: FlowingEdge };

// ── Sparkline ───────────────────────────────────────────────────────

const SP_METRIC: Record<string, string> = { perception: "flow_score", stimmung: "health", temporal: "max_surprise", apperception: "coherence", voice: "routing_activation", compositor: "", phenomenal: "", engine: "", consent: "" };
const spHist: Record<string, number[]> = {};
function pushSp(id: string, v: number | undefined | null) { if (v == null || typeof v !== "number") return; if (!spHist[id]) spHist[id] = []; spHist[id].push(v); if (spHist[id].length > 30) spHist[id].shift(); }
function Sparkline({ nodeId, color }: { nodeId: string; color: string }) {
  const vals = spHist[nodeId]; if (!vals || vals.length < 3) return null;
  const w = 120, h = 20, mn = Math.min(...vals), mx = Math.max(...vals), rng = mx - mn || 1;
  const pts = vals.map((v, i) => `${((i/(vals.length-1))*w).toFixed(1)},${(h-((v-mn)/rng)*h).toFixed(1)}`).join(" ");
  return <svg width={w} height={h} style={{ opacity: 0.5, marginTop: 4 }}><polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

// ── Per-node renderers ──────────────────────────────────────────────

function PerceptionBody({ m, p }: { m: NodeMetrics; p: ThemePalette }) {
  const flow = (m.flow_score as number) ?? 0, pres = (m.presence_probability as number) ?? 0, conf = (m.aggregate_confidence as number) ?? 0;
  const hr = m.heart_rate_bpm as number | null, stress = m.stress_elevated as boolean;
  return <>
    <div style={{ display: "flex", alignItems: "center", gap: 4 }}><span style={{ color: p["text-muted"], fontSize: 9 }}>flow</span><HBar value={flow} color={sevColor(1-flow, p)} width={60} /><span style={{ color: p["text-primary"], fontSize: 9 }}>{flow.toFixed(2)}</span></div>
    <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 2 }}><span style={{ width: 6, height: 6, borderRadius: "50%", background: p["emerald-400"], opacity: pres }} /><span style={{ color: p["text-muted"], fontSize: 9 }}>{(m.face_count as number) ?? 0}f</span>{conf > 0 && <span style={{ width: 5, height: 5, borderRadius: "50%", background: sevColor(1-conf, p) }} title={`conf ${conf.toFixed(2)}`} />}</div>
    {hr != null && <div style={{ color: p["text-muted"], fontSize: 9, marginTop: 2 }}>{hr}bpm{stress && <span style={{ color: p["red-400"], marginLeft: 4 }}>stress</span>}</div>}
  </>;
}

function StimmungBody({ m, p }: { m: NodeMetrics; p: ThemePalette }) {
  const dims = (m.dimensions as Record<string, { value: number; trend: string; freshness_s: number }>) || {};
  const stance = (m.stance as string) || "unknown";
  const tg = (t: string, c: string) => <span style={{ fontSize: 6, color: c, lineHeight: 1 }}>{t === "rising" ? "\u25B2" : t === "falling" ? "\u25BC" : "\u2014"}</span>;
  return <>
    <div style={{ height: 3, width: "100%", background: stColor(stance, p), borderRadius: 1, marginBottom: 4 }} />
    <div style={{ display: "flex", gap: 2, alignItems: "flex-end" }}>
      {Object.entries(dims).map(([n, d]) => { const stale = d.freshness_s > 60; return <div key={n} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 1 }} title={`${n}: ${d.value.toFixed(2)} (${d.trend})`}>{tg(d.trend, stale ? p["zinc-600"] : sevColor(d.value, p))}<VBar value={d.value} color={sevColor(d.value, p)} opacity={stale ? 0.4 : 1} /></div>; })}
    </div>
  </>;
}

function TemporalBody({ m, p }: { m: NodeMetrics; p: ThemePalette }) {
  const ret = (m.retention_count as number) ?? 0, pro = (m.protention_count as number) ?? 0, sur = (m.max_surprise as number) ?? 0;
  const fs = (m.flow_state as string) || "idle", fc = fs === "deep" ? p["green-400"] : fs === "engaged" ? p["yellow-400"] : p["zinc-500"];
  return <>
    <span style={{ color: fc, fontSize: 9, fontWeight: 600 }}>{fs}</span>
    <div style={{ display: "flex", flexDirection: "column", gap: 2, marginTop: 3 }}><HBar value={ret/5} color={p["blue-400"]} height={4} /><HBar value={1} color={p["blue-400"]} height={4} /><HBar value={pro/3} color={p["blue-400"]} height={4} /></div>
    <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 3 }}><span style={{ color: p["text-muted"], fontSize: 9 }}>sur</span><HBar value={sur} color={sevColor(sur, p)} width={60} /></div>
  </>;
}

function ApperceptionBody({ m, p }: { m: NodeMetrics; p: ThemePalette }) {
  const coh = (m.coherence as number) ?? 0;
  const dims = (m.dimensions as Record<string, { confidence: number; affirming: number; problematizing: number }>) || {};
  const ab: Record<string, string> = { system_awareness: "sys", temporal_prediction: "tmp", continuity: "con", accuracy: "acc" };
  return <>
    <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 3 }}><ArcGauge value={coh} color={sevColor(1-coh, p)} /><span style={{ color: p["text-muted"], fontSize: 9 }}>coh {coh.toFixed(2)}</span></div>
    {Object.entries(dims).map(([n, d]) => <div key={n} style={{ display: "flex", alignItems: "center", gap: 3, marginTop: 1 }}><span style={{ color: p["text-muted"], fontSize: 8, width: 18 }}>{ab[n] || n.slice(0,3)}</span><HBar value={d.confidence} color={d.confidence > 0.6 ? p["green-400"] : d.confidence > 0.3 ? p["yellow-400"] : p["red-400"]} width={50} height={3} /><span style={{ color: p["text-muted"], fontSize: 8 }}>{d.affirming > 0 ? `+${d.affirming}` : ""}{d.problematizing > 0 ? ` -${d.problematizing}` : ""}</span></div>)}
  </>;
}

function CompositorBody({ m, p }: { m: NodeMetrics; p: ThemePalette }) {
  const ds = (m.display_state as string) || "unknown", dsC = ds === "alert" ? p["red-400"] : ds === "active" ? p["green-400"] : ds === "ambient" ? p["emerald-400"] : p["zinc-500"];
  const zones = (m.zone_opacities as Record<string, number>) || {}, maxS = (m.max_severity as number) ?? 0, sc = (m.signal_count as number) ?? 0;
  return <>
    <span style={{ color: dsC, fontSize: 9, fontWeight: 600 }}>{ds}</span>
    <div style={{ display: "flex", gap: 1, marginTop: 3 }}>{Object.entries(zones).map(([z, o]) => <div key={z} title={`${z}: ${(o*100).toFixed(0)}%`} style={{ width: 8, height: 12, borderRadius: 1, background: p[(SIG_CAT[z] || "zinc-600") as keyof ThemePalette] || p["zinc-600"], opacity: Math.max(0.1, o) }} />)}</div>
    {sc > 0 && <div style={{ display: "flex", alignItems: "center", gap: 3, marginTop: 2 }}><span style={{ width: maxS > 0.7 ? 8 : 6, height: maxS > 0.7 ? 8 : 6, borderRadius: "50%", background: sevColor(maxS, p) }} /><span style={{ color: p["text-muted"], fontSize: 9 }}>{sc} sig</span></div>}
  </>;
}

function EngineBody({ m, p }: { m: NodeMetrics; p: ThemePalette }) {
  const evt = (m.events_processed as number) ?? 0, act = (m.actions_executed as number) ?? 0, err = (m.error_count as number) ?? 0;
  const nov = (m.novelty_score as number) ?? 0, shf = (m.shift_score as number) ?? 0;
  return <>
    <div style={{ color: p["text-muted"], fontSize: 9 }}>{evt} evt / {act} act{err > 0 && <span style={{ color: p["red-400"] }}> / {err} err</span>}</div>
    <div style={{ display: "flex", gap: 4, marginTop: 3, alignItems: "center" }}>
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: sevColor(nov, p) }} title={`novelty ${nov.toFixed(2)}`} /><span style={{ color: p["text-muted"], fontSize: 8 }}>nov</span>
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: sevColor(shf, p) }} title={`shift ${shf.toFixed(2)}`} /><span style={{ color: p["text-muted"], fontSize: 8 }}>shf</span>
    </div>
  </>;
}

function ConsentBody({ m, p, bc }: { m: NodeMetrics; p: ThemePalette; bc: string }) {
  const phase = (m.phase as string) || "none", cov = (m.coverage_pct as number) ?? 0, cts = (m.active_contracts as number) ?? 0;
  const sts = ["none", "guest_detected", "consent_pending", "consent_granted", "consent_refused"];
  return <>
    <div style={{ display: "flex", gap: 4, justifyContent: "center" }}>{sts.map(s => <span key={s} title={s.replace(/_/g, " ")} style={{ width: 6, height: 6, borderRadius: "50%", background: s === phase ? bc : "transparent", border: `1px solid ${s === phase ? bc : p["border-muted"]}`, transition: "all 0.5s ease" }} />)}</div>
    <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 4 }}><ArcGauge value={cov/100} color={cov > 80 ? p["green-400"] : cov > 50 ? p["yellow-400"] : p["red-400"]} /><span style={{ color: p["text-muted"], fontSize: 9 }}>{cov.toFixed(0)}%</span></div>
    <div style={{ color: p["text-muted"], fontSize: 9, marginTop: 2 }}>{cts} contract{cts !== 1 ? "s" : ""}</div>
  </>;
}

function VoiceBody({ m, p }: { m: NodeMetrics; p: ThemePalette }) {
  const state = (m.state as string) || "off", act = (m.routing_activation as number) ?? 0, tier = (m.routing_tier as string) || "";
  const turns = (m.turn_count as number) ?? 0, frust = (m.frustration_score as number) ?? 0;
  const sc = p[(VOICE_COL[state] || "zinc-500") as keyof ThemePalette] || p["zinc-500"];
  const tc = tier === "CAPABLE" ? p["green-400"] : tier === "FAST" ? p["yellow-400"] : p["zinc-500"];
  return <>
    <span style={{ color: sc, fontSize: 9, fontWeight: 600 }}>{state}</span>
    <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 3 }}><span style={{ color: p["text-muted"], fontSize: 9 }}>sal</span><HBar value={act} color={sevColor(act, p)} width={50} /></div>
    <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 2 }}><span style={{ color: tc, fontSize: 9, fontWeight: 600 }}>{tier}</span><span style={{ color: p["text-muted"], fontSize: 9 }}>turn {turns}</span>{frust > 0.3 && <span style={{ width: 5, height: 5, borderRadius: "50%", background: p["red-400"] }} />}</div>
  </>;
}

function PhenomenalBody({ m, p }: { m: NodeMetrics; p: ThemePalette }) {
  const bound = m.bound as boolean, coh = m.coherence as number | null, sur = m.surprise as number | null, dims = (m.active_dimensions as number) ?? 0;
  return <>
    <span style={{ width: 6, height: 6, borderRadius: "50%", display: "inline-block", background: bound ? p["green-400"] : p["orange-400"] }} /><span style={{ color: p["text-muted"], fontSize: 9, marginLeft: 4 }}>{bound ? "bound" : "fragmented"}</span>
    <div style={{ display: "flex", gap: 8, marginTop: 3 }}>{coh != null && <span style={{ color: sevColor(1-coh, p), fontSize: 9 }}>coh {coh.toFixed(2)}</span>}{sur != null && <span style={{ color: sevColor(sur, p), fontSize: 9 }}>sur {sur.toFixed(2)}</span>}</div>
    <div style={{ color: p["text-muted"], fontSize: 9, marginTop: 2 }}>{dims} dims</div>
  </>;
}

// ── System Node ─────────────────────────────────────────────────────

function SystemNode({ data }: { data: FlowNode }) {
  const { palette: p } = useTheme();
  const fc = flowColors(p), colors = fc[data.status as keyof typeof fc] || fc.offline;
  const m = data.metrics || {}, br = breathDur(data.age_s, data.status), op = nodeOp(data.age_s, data.status);
  const sk = SP_METRIC[data.id]; if (sk && m[sk] !== undefined) pushSp(data.id, m[sk] as number);

  const body = () => { switch (data.id) {
    case "perception": return <PerceptionBody m={m} p={p} />;
    case "stimmung": return <StimmungBody m={m} p={p} />;
    case "temporal": return <TemporalBody m={m} p={p} />;
    case "apperception": return <ApperceptionBody m={m} p={p} />;
    case "compositor": return <CompositorBody m={m} p={p} />;
    case "engine": return <EngineBody m={m} p={p} />;
    case "consent": return <ConsentBody m={m} p={p} bc={colors.border} />;
    case "voice": return <VoiceBody m={m} p={p} />;
    case "phenomenal": return <PhenomenalBody m={m} p={p} />;
    default: return null;
  }};

  return (
    <div style={{ background: colors.bg, border: `1.5px solid ${colors.border}`, borderRadius: 12, padding: "10px 14px", minWidth: 150, maxWidth: 220, opacity: op, transition: "opacity 2s ease, box-shadow 1s ease", fontFamily: "'JetBrains Mono', monospace", animation: br !== "0s" ? `breathe ${br} ease-in-out infinite` : "none" }}>
      <Handle type="target" position={Position.Top} style={{ background: colors.border, width: 6, height: 6 }} />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 5 }}>
        <span style={{ color: p["text-emphasis"], fontSize: 12, fontWeight: 600, letterSpacing: "0.02em" }}>{data.label}</span>
        <span style={{ width: 6, height: 6, borderRadius: "50%", background: colors.border, boxShadow: data.status === "active" ? `0 0 6px ${colors.border}` : "none" }} />
      </div>
      <div style={{ fontSize: 10, lineHeight: "1.6" }}>
        {body()}
        {SP_METRIC[data.id] && <Sparkline nodeId={data.id} color={colors.border} />}
        {data.status !== "offline" && <div style={{ color: p["border-muted"], marginTop: 3, fontSize: 9, textAlign: "right" }}>{data.age_s < 1 ? "now" : `${data.age_s.toFixed(0)}s`}</div>}
      </div>
      <Handle type="source" position={Position.Bottom} style={{ background: colors.border, width: 6, height: 6 }} />
    </div>
  );
}
const nodeTypes = { system: SystemNode };

// ── Detail Panel ────────────────────────────────────────────────────

function DetailPanel({ node, onClose }: { node: FlowNode | null; onClose: () => void }) {
  const { palette: p } = useTheme(); if (!node) return null;
  const fc = flowColors(p), colors = fc[node.status as keyof typeof fc] || fc.offline, m = node.metrics || {};

  const detail = () => { switch (node.id) {
    case "stimmung": { const dims = (m.dimensions as Record<string, { value: number; trend: string; freshness_s: number }>) || {};
      return <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>{Object.entries(dims).map(([n, d]) => <div key={n} style={{ display: "flex", alignItems: "center", gap: 4 }}><span style={{ color: d.freshness_s > 300 ? p["zinc-600"] : p["text-secondary"], fontSize: 10, width: 90 }}>{n.replace(/_/g, " ")}</span><HBar value={d.value} color={sevColor(d.value, p)} width={60} height={4} /><span style={{ color: p["text-primary"], fontSize: 10, width: 30 }}>{d.value.toFixed(2)}</span></div>)}</div>; }
    case "engine": return <div style={{ display: "flex", flexDirection: "column", gap: 2, fontSize: 10 }}>
      {[["events", m.events_processed], ["actions", m.actions_executed], ["rules", m.rules_evaluated], ["errors", m.error_count], ["novelty", (m.novelty_score as number)?.toFixed(3)], ["shift", (m.shift_score as number)?.toFixed(3)], ["uptime", `${Math.round(((m.uptime_s as number) ?? 0) / 60)}m`]].map(([k, v]) => <div key={k as string} style={{ color: p["text-secondary"] }}>{k as string}: <span style={{ color: k === "errors" && (v as number) > 0 ? p["red-400"] : p["text-primary"] }}>{String(v ?? 0)}</span></div>)}
    </div>;
    case "voice": return <div style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 10 }}>
      <div style={{ color: p["text-secondary"] }}>tier: <span style={{ color: p["text-primary"] }}>{(m.routing_tier as string) || "none"}</span></div>
      <div style={{ color: p["text-secondary"] }}>reason: <span style={{ color: p["text-primary"] }}>{(m.routing_reason as string) || ""}</span></div>
      <div style={{ color: p["text-secondary"] }}>frustration: <span style={{ color: p["text-primary"] }}>{((m.frustration_score as number) ?? 0).toFixed(2)}</span></div>
      {(m.last_utterance as string) && <div style={{ color: p["text-muted"], fontSize: 9, maxHeight: 60, overflow: "auto" }}>"{m.last_utterance as string}"</div>}
    </div>;
    default: return <pre style={{ background: `color-mix(in srgb, ${p.bg} 80%, transparent)`, padding: 10, borderRadius: 8, overflow: "auto", maxHeight: 350, fontSize: 10, color: p["text-primary"], lineHeight: "1.5" }}>{JSON.stringify(m, null, 2)}</pre>;
  }};

  return (
    <div style={{ position: "absolute", right: 16, top: 16, width: 320, background: `color-mix(in srgb, ${p.surface} 95%, transparent)`, border: `1px solid ${colors.border}`, borderRadius: 12, padding: 16, zIndex: 100, fontFamily: "'JetBrains Mono', monospace", boxShadow: `0 8px 32px rgba(0,0,0,0.5), 0 0 20px ${colors.glow}`, backdropFilter: "blur(8px)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}><h3 style={{ color: p["text-emphasis"], margin: 0, fontSize: 14 }}>{node.label}</h3><button onClick={onClose} style={{ background: "none", border: "none", color: p["text-muted"], cursor: "pointer", fontSize: 16 }}>x</button></div>
      <div style={{ color: p["text-secondary"], fontSize: 11, marginBottom: 8 }}><span style={{ color: colors.border }}>*</span> {node.status} — {node.age_s.toFixed(1)}s ago</div>
      {detail()}
    </div>
  );
}

// ── System Summary ──────────────────────────────────────────────────

function useSystemSummary() {
  const [s, setS] = useState<{ hp: number; ht: number; gp: number; gt: number; ct: number } | null>(null);
  useEffect(() => { let m = true;
    const poll = async () => { try { const [h, g, c] = await Promise.allSettled([api.health(), api.gpu(), api.cost()]);
      if (!m) return;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const hv: any = h.status === "fulfilled" ? h.value : {}, gv: any = g.status === "fulfilled" ? g.value : {}, cv: any = c.status === "fulfilled" ? c.value : {};
      setS({ hp: (hv.total_checks ?? 0) - (hv.failed ?? 0), ht: hv.total_checks ?? 0, gp: gv.usage_pct ?? 0, gt: gv.temperature_c ?? 0, ct: cv.today_cost ?? 0 }); } catch { /* polling failure — stale data shown */ } };
    poll(); const iv = setInterval(poll, 30000); return () => { m = false; clearInterval(iv); };
  }, []); return s;
}

// ── Static fallback ─────────────────────────────────────────────────

function staticTopology(): SystemFlowState {
  const off = (id: string, label: string): FlowNode => ({ id, label, status: "offline", age_s: 999, metrics: {} });
  return { nodes: [off("perception","Perception"),off("stimmung","Stimmung"),off("temporal","Temporal Bands"),off("apperception","Apperception"),off("phenomenal","Phenomenal Context"),off("voice","Voice Pipeline"),off("compositor","Compositor"),off("engine","Reactive Engine"),off("consent","Consent")],
    edges: [{source:"perception",target:"stimmung",active:false,label:"perception confidence"},{source:"perception",target:"temporal",active:false,label:"perception ring"},{source:"perception",target:"consent",active:false,label:"faces + speaker"},{source:"stimmung",target:"apperception",active:false,label:"stance"},{source:"temporal",target:"apperception",active:false,label:"surprise"},{source:"temporal",target:"phenomenal",active:false,label:"bands"},{source:"apperception",target:"phenomenal",active:false,label:"self-band"},{source:"stimmung",target:"phenomenal",active:false,label:"attunement"},{source:"phenomenal",target:"voice",active:false,label:"orientation"},{source:"perception",target:"voice",active:false,label:"salience"},{source:"voice",target:"compositor",active:false,label:"voice state"},{source:"stimmung",target:"compositor",active:false,label:"visual mood"},{source:"perception",target:"compositor",active:false,label:"signals"},{source:"engine",target:"compositor",active:false,label:"engine state"},{source:"stimmung",target:"engine",active:false,label:"phase gating"},{source:"consent",target:"voice",active:false,label:"consent gate"}],
    timestamp: Date.now() / 1000 };
}

// ── Main Page ───────────────────────────────────────────────────────

export function FlowPage() {
  const { palette: p } = useTheme();
  const [flowState, setFlowState] = useState<SystemFlowState | null>(null);
  const [selectedNode, setSelectedNode] = useState<FlowNode | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const prevPos = useRef<Record<string, { x: number; y: number }>>({});
  const ss = useSystemSummary();

  useEffect(() => { let m = true;
    const poll = async () => { try { const st = await invoke<SystemFlowState>("get_system_flow"); if (m) setFlowState(st); } catch { try { const st = await api.get<SystemFlowState>("/api/flow/state"); if (m) setFlowState(st); } catch { if (m && !flowState) setFlowState(staticTopology()); } } };
    poll(); const iv = setInterval(poll, 3000); return () => { m = false; clearInterval(iv); };
  }, []);

  useEffect(() => { if (!flowState) return;
    const am: Record<string, number> = {}; for (const n of flowState.nodes) am[n.id] = n.age_s;
    const cp = flowState.nodes.find(n => n.id === "consent")?.metrics?.phase as string || "none";
    const ca = cp !== "none" && cp !== "consent_granted";
    setNodes(flowState.nodes.map(n => ({ id: n.id, type: "system", position: prevPos.current[n.id] || POSITIONS[n.id] || { x: 0, y: 0 }, data: n, draggable: true })));
    setEdges(flowState.edges.map((e, i) => ({ id: `${e.source}-${e.target}-${i}`, source: e.source, target: e.target, type: "flowing", data: { active: e.active, age_s: am[e.source] || 999, label: e.label, gated: ca && e.label === "consent gate" }, markerEnd: { type: MarkerType.ArrowClosed, color: edgeColor(am[e.source] || 999, e.active, p), width: 12, height: 12 } })));
  }, [flowState, setNodes, setEdges]);

  const onNodeClick = useCallback((_: unknown, node: Node) => { setSelectedNode(node.data as FlowNode); }, []);
  const onNodeDragStop = useCallback((_: unknown, node: Node) => { prevPos.current[node.id] = node.position; }, []);
  const ac = flowState?.nodes.filter(n => n.status === "active").length ?? 0, tc = flowState?.nodes.length ?? 0;

  return (
    <div style={{ width: "100%", height: "100%", background: p.bg, position: "relative" }}>
      <style>{`
        @keyframes breathe { 0%, 100% { box-shadow: 0 0 12px var(--glow-color, rgba(16,185,129,0.25)); } 50% { box-shadow: 0 0 24px var(--glow-color, rgba(16,185,129,0.4)); } }
        .react-flow__edge-path { transition: stroke 1s ease, opacity 1s ease; }
        .react-flow__handle { border: none !important; }
        .react-flow__controls { border-radius: 8px; overflow: hidden; }
        .react-flow__controls button { background: ${p.surface} !important; border-color: ${p.elevated} !important; color: ${p["text-muted"]} !important; }
        .react-flow__controls button:hover { background: ${p.elevated} !important; color: ${p["text-secondary"]} !important; }
        .flow-edge-group .flow-edge-label { opacity: 0; transition: opacity 0.3s ease; }
        .flow-edge-group:hover .flow-edge-label { opacity: 1; }
      `}</style>
      <ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onNodeClick={onNodeClick} onNodeDragStop={onNodeDragStop} nodeTypes={nodeTypes} edgeTypes={edgeTypes} fitView fitViewOptions={{ padding: 0.25 }} proOptions={{ hideAttribution: true }} minZoom={0.3} maxZoom={2.5}>
        <Background color={p["border-muted"]} gap={32} size={1} /><Controls showInteractive={false} />
      </ReactFlow>
      <DetailPanel node={selectedNode} onClose={() => setSelectedNode(null)} />
      <div style={{ position: "absolute", top: 12, left: 12, color: p["text-muted"], fontSize: 11, fontFamily: "'JetBrains Mono', monospace", zIndex: 10, letterSpacing: "0.08em" }}>SYSTEM ANATOMY — {flowState ? <><span style={{ color: ac > 0 ? p["green-400"] : p["text-muted"] }}>{ac}</span>/{tc} active</> : "connecting..."}</div>
      {flowState && (() => { const sn = flowState.nodes.find(n => n.id === "stimmung"), stance = (sn?.metrics?.stance as string) || "unknown";
        const ol = flowState.nodes.filter(n => n.status === "offline").length, ae = flowState.edges.filter(e => e.active).length, te = flowState.edges.length;
        return <div style={{ position: "absolute", bottom: 12, left: "50%", transform: "translateX(-50%)", display: "flex", gap: 24, color: p["text-muted"], fontSize: 10, fontFamily: "'JetBrains Mono', monospace", zIndex: 10, letterSpacing: "0.05em", opacity: 0.8 }}>
          <span>stance: <span style={{ color: stColor(stance, p) }}>{stance}</span></span>
          <span>flows: <span style={{ color: p["text-secondary"] }}>{ae}/{te}</span></span>
          {ss && <span>health: <span style={{ color: ss.hp === ss.ht ? p["green-400"] : p["yellow-400"] }}>{ss.hp}/{ss.ht}</span></span>}
          {ss && ss.gp > 0 && <span>gpu: <span style={{ color: p["text-secondary"] }}>{ss.gp.toFixed(0)}%</span> <span style={{ color: p["text-muted"] }}>{ss.gt.toFixed(0)}&deg;C</span></span>}
          {ss && ss.ct > 0 && <span>cost: <span style={{ color: p["text-secondary"] }}>${ss.ct.toFixed(2)}</span></span>}
          {ol > 0 && <span>offline: <span style={{ color: p["text-muted"] }}>{ol}</span></span>}
        </div>; })()}
    </div>
  );
}
