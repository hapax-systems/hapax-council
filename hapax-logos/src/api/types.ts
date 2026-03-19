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
  // Computed fields from cockpit API
  score?: number;
  total?: number;
  summary?: { stance: string };
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
  one_liner?: string;
}

export interface ActionItem {
  priority: string;
  action: string;
  reason: string;
  command: string;
}

export interface GovernanceHeartbeat {
  score: number;
  axiom_count: number;
  violations: string[];
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
  tax_percentage?: number;
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
  consent_recording_allowed: boolean;
  guest_present: boolean;
  consent_phase: string;
  audio_energy_rms: number;
}

export interface LiveCompositorStatus {
  state: string;
  cameras: Record<string, string>;
  active_cameras: number;
  total_cameras: number;
  recording_enabled: boolean;
  recording_cameras: Record<string, string>;
  hls_enabled: boolean;
  consent_recording_allowed: boolean;
  guest_present: boolean;
  consent_phase: string;
  audio_energy_rms: number;
  timestamp: number;
}

export interface StudioDisk {
  path: string;
  total_gb: number;
  used_gb: number;
  free_gb: number;
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

// --- Visual Layer ---

export interface VisualLayerSignal {
  category: string;
  severity: number;
  title: string;
  detail: string;
  source_id: string;
}

export type SignalEntry = VisualLayerSignal;

export interface AmbientParams {
  speed: number;
  turbulence: number;
  color_warmth: number;
  brightness: number;
}

export interface BiometricState {
  heart_rate_bpm: number;
  stress_elevated: boolean;
  physiological_load: number;
  sleep_quality: number;
  watch_activity: string;
}

export interface TemporalContext {
  trend_flow: number;
  trend_audio: number;
  trend_hr: number;
  perception_age_s: number;
  ring_depth: number;
}

export interface SignalStaleness {
  perception_s: number;
  health_s: number;
  gpu_s: number;
  nudges_s: number;
  briefing_s: number;
}

export type StimmungStance = "nominal" | "cautious" | "degraded" | "critical";

export interface VisualLayerState {
  available: boolean;
  display_state: "ambient" | "peripheral" | "informational" | "alert" | "performative";
  zone_opacities: Record<string, number>;
  signals: Record<string, VisualLayerSignal[]>;
  ambient_params: AmbientParams;
  biometrics?: BiometricState;
  temporal_context?: TemporalContext;
  signal_staleness?: SignalStaleness;
  stimmung_stance?: StimmungStance;
  classification_detections?: ClassificationDetection[];
  classification_directives?: Record<string, string>;
  timestamp: number;
  aggregator?: string;
}

// --- Classification Detection ---

export interface ClassificationDetection {
  entity_id: string;
  label: string;
  camera: string;
  box: [number, number, number, number]; // x1, y1, x2, y2 normalized 0-1
  confidence: number;
  mobility: "static" | "dynamic" | "unknown";
  novelty: number; // 0.0=familiar, 1.0=brand new
  consent_suppressed: boolean;
}

// --- Perception ---

export interface PerceptionState {
  available: boolean;
  production_activity: string;
  music_genre: string;
  flow_state: string;
  flow_score: number;
  emotion_valence: number;
  emotion_arousal: number;
  audio_energy_rms: number;
  face_count: number;
  vad_confidence: number;
  activity_mode: string;
  interruptibility_score: number;
  presence_score: number;
  operator_present: boolean;
  guest_present: boolean;
  consent_phase: string;
  timestamp: number;
  top_emotion: string;
  detected_objects: string;
  person_count: number;
  pose_summary: string;
  scene_objects: string;
  scene_type: string;
  gaze_direction: string;
  hand_gesture: string;
  nearest_person_distance: string;
  speech_emotion: string;
  audio_events: string;
  speech_language: string;
  ambient_brightness: number;
  color_temperature: string;
  posture: string;
  detected_action: string;
  usb_devices: string;
  bluetooth_nearby: string;
  network_devices: string;
}
