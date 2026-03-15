// Types matching cockpit/data/ Python dataclasses

export interface HealthSnapshot {
  overall_status: "healthy" | "degraded" | "failed";
  total_checks: number;
  healthy: number;
  degraded: number;
  failed: number;
  duration_ms: number;
  failed_checks: string[];
  timestamp: string;
}

export interface VramSnapshot {
  name: string;
  total_mb: number;
  used_mb: number;
  free_mb: number;
  usage_pct: number;
  temperature_c: number;
  loaded_models: string[];
}

export interface ContainerStatus {
  name: string;
  service: string;
  state: string;
  health: string;
  image: string;
  ports: string[];
}

export interface TimerStatus {
  unit: string;
  next_fire: string;
  last_fired: string;
  activates: string;
}

export interface Infrastructure {
  containers: ContainerStatus[];
  timers: TimerStatus[];
}

export interface Nudge {
  category: string;
  priority_score: number;
  priority_label: "critical" | "high" | "medium" | "low";
  title: string;
  detail: string;
  suggested_action: string;
  command_hint: string;
  source_id: string;
}

export interface BriefingData {
  headline: string;
  generated_at: string;
  body: string;
  action_items: ActionItem[];
}

export interface ActionItem {
  priority: string;
  action: string;
  reason: string;
  command: string;
}

export interface GoalSnapshot {
  goals: GoalStatus[];
  active_count: number;
  stale_count: number;
  primary_stale: string[];
}

export interface GoalStatus {
  id: string;
  name: string;
  status: string;
  category: string;
  last_activity_h: number | null;
  stale: boolean;
  progress_summary: string;
  description: string;
}

export interface ReadinessSnapshot {
  level: "bootstrapping" | "developing" | "operational";
  interview_conducted: boolean;
  profile_coverage_pct: number;
  total_facts: number;
  populated_dimensions: number;
  total_dimensions: number;
  missing_dimensions: string[];
  sparse_dimensions: string[];
  top_gap: string;
  gaps: string[];
}

export interface AgentInfo {
  name: string;
  uses_llm: boolean;
  description: string;
  command: string;
  module: string;
  flags: AgentFlag[];
}

export interface AgentFlag {
  flag: string;
  description: string;
  flag_type: string;
  default: string | null;
  choices: string[] | null;
  metavar: string | null;
}

export interface ScoutData {
  generated_at: string;
  components_scanned: number;
  recommendations: ScoutRecommendation[];
  adopt_count: number;
  evaluate_count: number;
}

export interface ScoutRecommendation {
  component: string;
  current: string;
  tier: string;
  summary: string;
  confidence: string;
  migration_effort: string;
}

export interface CostSnapshot {
  today_cost: number;
  period_cost: number;
  daily_average: number;
  top_models: { model: string; cost: number }[];
  available: boolean;
}

// --- Drift ---

export interface DriftItem {
  severity: string;
  category: string;
  doc_file: string;
  description: string;
  suggestion: string;
}

export interface DriftSummary {
  drift_count: number;
  docs_analyzed: number;
  summary: string;
  latest_timestamp: string;
  items: DriftItem[];
  report_age_h: number;
}

// --- Management ---

export interface PersonState {
  name: string;
  team: string;
  role: string;
  cadence: string;
  status: string;
  cognitive_load: number | null;
  growth_vector: string;
  feedback_style: string;
  last_1on1: string;
  coaching_active: boolean;
  stale_1on1: boolean;
  days_since_1on1: number | null;
}

export interface CoachingState {
  title: string;
  person: string;
  status: string;
  check_in_by: string;
  overdue: boolean;
  days_overdue: number;
}

export interface FeedbackState {
  title: string;
  person: string;
  direction: string;
  category: string;
  follow_up_by: string;
  followed_up: boolean;
  overdue: boolean;
  days_overdue: number;
}

export interface ManagementSnapshot {
  people: PersonState[];
  coaching: CoachingState[];
  feedback: FeedbackState[];
}

// --- Accommodations ---

export interface Accommodation {
  id: string;
  pattern_category: string;
  description: string;
  active: boolean;
  proposed_at: string;
  confirmed_at: string;
}

export interface AccommodationSet {
  accommodations: Accommodation[];
  time_anchor_enabled: boolean;
  soft_framing: boolean;
  energy_aware: boolean;
  peak_hours: number[];
  low_hours: number[];
}

// --- Health History ---

export interface HealthHistoryEntry {
  timestamp: string;
  status: string;
  healthy: number;
  degraded: number;
  failed: number;
  duration_ms: number;
  failed_checks: string[];
}

export interface HealthHistory {
  entries: HealthHistoryEntry[];
  uptime_pct: number;
  total_runs: number;
}

// --- Manual ---

export interface ManualResponse {
  content: string;
  updated_at?: string;
}

// --- Copilot ---

export interface CopilotResponse {
  message: string;
}

// --- Agent Run ---

export interface AgentRunStatus {
  running: boolean;
  agent_name?: string;
  pid?: number;
  elapsed_s?: number;
}

export interface NudgeActionResponse {
  status: string;
  source_id: string;
  action: string;
}

// --- Chat ---

export interface ChatSessionInfo {
  session_id: string;
  model: string;
  message_count: number;
  total_tokens: number;
  mode: "chat" | "interview";
  generating: boolean;
}

export interface ChatModelsResponse {
  models: string[];
}

// --- Cycle Mode ---

export interface CycleModeResponse {
  mode: "dev" | "prod";
  switched_at: string | null;
}

// --- Scout Decisions ---

export interface ScoutDecision {
  component: string;
  decision: "adopted" | "deferred" | "dismissed";
  timestamp: string;
  notes: string;
}

export interface ScoutDecisionsResponse {
  decisions: ScoutDecision[];
}

// --- Studio ---

export interface CompositorStatus {
  state: string;
  cameras: Record<string, string>;
  active_cameras: number;
  total_cameras: number;
  output_device: string;
  resolution: string;
  recording_enabled: boolean;
  recording_cameras: Record<string, string>;
  hls_enabled: boolean;
  hls_url: string;
}

export interface StudioSnapshot {
  compositor: CompositorStatus;
  capture: { audio_recorder_active: boolean; video_cameras: string[] };
}

export interface StudioStreamInfo {
  hls_url: string;
  hls_enabled: boolean;
  mjpeg_url: string;
  mjpeg_enabled: boolean;
  enabled: boolean;
}

// --- Demos ---

export interface Demo {
  id: string;
  title: string;
  audience: string;
  scope: string;
  scenes: number;
  format: string;
  duration: number;
  timestamp: string;
  primary_file: string;
  files: string[];
  dir: string;
  has_video?: boolean;
  has_audio?: boolean;
}
