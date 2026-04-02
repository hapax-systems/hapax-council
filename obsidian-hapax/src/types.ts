export enum NoteKind {
  Measure = "Measure",
  Gate = "Gate",
  SprintSummary = "SprintSummary",
  PosteriorTracker = "PosteriorTracker",
  Research = "Research",
  Concept = "Concept",
  Briefing = "Briefing",
  Nudges = "Nudges",
  Unknown = "Unknown",
}

export interface NoteContext {
  kind: NoteKind;
  id?: string;
  model?: string;
  tags?: string[];
}

export interface SprintState {
  current_sprint: number;
  current_day: number;
  measures_completed: number;
  measures_total: number;
  measures_in_progress: number;
  measures_blocked: number;
  measures_skipped: number;
  measures_pending: number;
  effort_completed: number;
  effort_total: number;
  gates_passed: number;
  gates_failed: number;
  gates_pending: number;
  next_block: { measure: string; title: string; day: number; scheduled: string } | null;
  blocking_gate: string | null;
  models: Record<string, ModelPosterior>;
}

export interface ModelPosterior {
  baseline: number;
  gained: number;
  current: number;
  possible: number;
  completed: number;
  total: number;
}

export interface Measure {
  id: string;
  title: string;
  model: string;
  status: string;
  sprint: number;
  day: number;
  block: string;
  effort_hours: number;
  posterior_gain: number;
  gate: string | null;
  depends_on: string[];
  blocks: string[];
  completed_at: string | null;
  result_summary: string | null;
}

export interface Gate {
  id: string;
  title: string;
  model: string;
  trigger_measure: string | null;
  condition: string;
  status: string;
  result_value: number | null;
  downstream_measures: string[];
  nudge_required: boolean;
  acknowledged: boolean;
}

export interface StimmungDimension {
  value: number;
  trend: string;
}

export interface StimmungState {
  overall_stance: string;
  dimensions: Record<string, StimmungDimension>;
  timestamp: number;
}

export interface Nudge {
  category: string;
  priority_score: number;
  title: string;
  detail: string;
  source_id: string;
}

/** Tailscale IP for the hapax workstation — stable across networks. */
export const TAILSCALE_API_URL = "http://100.117.1.83:8051";
export const LOCAL_API_URL = "http://localhost:8051";

export interface HapaxSettings {
  logosApiUrl: string;
  refreshInterval: number;
  showOnUnknownNotes: boolean;
  collapsedSections: string[];
}

export const DEFAULT_SETTINGS: HapaxSettings = {
  logosApiUrl: LOCAL_API_URL,
  refreshInterval: 30,
  showOnUnknownNotes: true,
  collapsedSections: [],
};
