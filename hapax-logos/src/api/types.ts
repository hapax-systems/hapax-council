// Types matching logos/data/ Python dataclasses

export interface HealthSnapshot {
  overall_status: "healthy" | "degraded" | "failed";
  total_checks: number;
  healthy: number;
  degraded: number;
  failed: number;
  duration_ms: number;
  failed_checks: string[];
  timestamp: string;
  // Computed fields from logos API
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
  interview_fact_count: number;
  priorities_known: boolean;
  neurocognitive_mapped: boolean;
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
  hygiene_count: number;
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

// --- Working Mode ---

export interface WorkingModeResponse {
  mode: "research" | "rnd" | "fortress";
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
  rtmp_attached: boolean;
  rtmp_rebuild_count: number;
  egress_state: string;
  public_claim_allowed: boolean;
  livestream_egress: LivestreamEgressState;
  timestamp: number;
}

export interface LivestreamEgressEvidence {
  source: string;
  status: "pass" | "warn" | "fail" | "unknown";
  summary: string;
  observed: Record<string, unknown>;
  age_s: number | null;
  stale: boolean;
  timestamp: string | null;
}

export interface LivestreamEgressState {
  state:
    | "offline"
    | "local_preview"
    | "research_capture_ready"
    | "public_blocked"
    | "public_ready"
    | "public_live";
  confidence: number;
  public_claim_allowed: boolean;
  public_ready: boolean;
  research_capture_ready: boolean;
  monetization_risk: string;
  privacy_floor: "satisfied" | "blocked" | "unknown";
  audio_floor: "satisfied" | "blocked" | "unknown";
  evidence: LivestreamEgressEvidence[];
  last_transition: string | null;
  operator_action: string;
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
  phone_battery_pct: number;
  phone_connected: boolean;
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

export interface VoiceSession {
  active: boolean;
  state: string;
  turn_count: number;
  last_utterance: string;
  last_response: string;
  active_tool: string | null;
  barge_in: boolean;
  routing_tier: string;
  routing_reason: string;
  routing_activation: number;
  context_anchor_success: number;
  frustration_score: number;
  frustration_rolling_avg: number;
  acceptance_type: string;
  spoken_words: number;
  word_limit: number;
}

export interface SupplementaryContent {
  content_type: string;
  title: string;
  body: string;
  image_path: string;
  timestamp: number;
}

export interface VisualLayerState {
  available: boolean;
  display_state: "ambient" | "peripheral" | "informational" | "alert" | "performative";
  zone_opacities: Record<string, number>;
  signals: Record<string, VisualLayerSignal[]>;
  ambient_params: AmbientParams;
  voice_session?: VoiceSession;
  voice_content?: SupplementaryContent[];
  biometrics?: BiometricState;
  temporal_context?: TemporalContext;
  signal_staleness?: SignalStaleness;
  stimmung_stance?: StimmungStance;
  classification_detections?: ClassificationDetection[];
  classification_directives?: Record<string, string>;
  ambient_text?: string;
  secondary_ambient_text?: string;
  activity_label?: string;
  activity_detail?: string;
  display_density?: string;
  watershed_events?: WatershedEvent[];
  readiness?: "waiting" | "collecting" | "ready";
  timestamp: number;
  aggregator?: string;
}

// --- Watershed Events ---

export interface WatershedEvent {
  category: string;
  severity: number;
  title: string;
  detail: string;
  emitted_at: number;
  ttl_s: number;
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

  // Person enrichments (operator camera, consent-gated)
  gaze_direction?: string | null; // screen/hardware/away/person
  emotion?: string | null; // 8-class HSEmotion
  posture?: string | null; // upright/slouching/leaning_forward/leaning_back
  gesture?: string | null; // MediaPipe hand gestures
  action?: string | null; // Kinetics-400 or heuristic
  depth?: string | null; // close/medium/far

  // Entity metadata (all entities)
  mobility_score?: number | null; // continuous 0.0-1.0
  first_seen_age_s?: number | null; // seconds since first detection
  camera_count?: number | null; // cameras that have seen this entity
  sightings?: [number, number, number, number][] | null; // last 5 box positions

  // Temporal delta (derived from sightings history)
  velocity?: number | null; // normalized coords/s
  direction_deg?: number | null; // 0=right, 90=down, 180=left, 270=up
  confidence_stability?: number | null; // stddev of confidence over sightings
  dwell_s?: number | null; // seconds at current position
  is_entering?: boolean; // first appeared within last 2 ticks
  is_exiting?: boolean; // not seen recently
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
  per_camera_scenes?: Record<string, string>;
  gaze_direction: string;
  hand_gesture: string;
  nearest_person_distance: string;
  speech_emotion: string;
  audio_events: string;
  speech_language: string;
  ambient_brightness: number;
  color_temperature: string;
  audio_scene: string;
  posture: string;
  detected_action: string;
  // Contact mic (desk vibration sensing)
  desk_activity: string;
  desk_energy: number;
  desk_onset_rate: number;
  desk_tap_gesture: string;
  desk_spectral_centroid: number;
  desk_autocorr_peak: number;
  // Overhead hand tracking
  overhead_hand_zones: string;
  usb_devices: string;
  bluetooth_nearby: string;
  network_devices: string;
}

export interface InsightQuery {
  id: string;
  query: string;
  status: "running" | "done" | "error";
  agent_type: string;
  markdown: string;
  created_at: string;
  completed_at: string | null;
  elapsed_ms: number | null;
  tokens_in: number | null;
  tokens_out: number | null;
  error: string | null;
  parent_id: string | null;
}

export interface InsightQueryList {
  queries: InsightQuery[];
}

// --- Orientation ---

export interface SessionContext {
  last_active_domain: string;
  last_active_goal: string | null;
  last_active_measure: string | null;
  absence_hours: number;
  session_boundary: boolean;
  domain_recency: Record<string, number>;
  active_signals: string[];
}

export interface GoalSummary {
  id: string;
  title: string;
  priority: string;
  status: string;
  progress: number | null;
  stale: boolean;
  file_path: string;
  obsidian_uri: string;
  target_date: string | null;
}

export interface SprintSummary {
  current_sprint: number;
  measures_completed: number;
  measures_total: number;
  blocking_gate: string | null;
  next_measure: string | null;
  next_measure_title: string | null;
  models: Record<string, number>;
}

export interface DomainState {
  domain: string;
  top_goal: GoalSummary | null;
  goal_count: number;
  stale_count: number;
  recency_hours: number;
  health: "active" | "stale" | "dormant" | "blocked";
  sprint_progress: SprintSummary | null;
  next_action: string | null;
  next_action_link: string | null;
}

export interface OrientationState {
  session: SessionContext;
  domains: DomainState[];
  briefing_headline: string | null;
  briefing_generated_at: string | null;
  system_health: string;
  drift_high_count: number;
  narrative: string | null;
  narrative_generated_at: string | null;
  stimmung_stance: string;
}

// --- Fortress types ---

export interface FortressEvent {
  type: string;
  [key: string]: unknown;
}

export interface FortressState {
  timestamp: number;
  game_tick: number;
  year: number;
  season: number;
  month: number;
  day: number;
  fortress_name: string;
  paused: boolean;
  population: number;
  food_count: number;
  drink_count: number;
  active_threats: number;
  job_queue_length: number;
  idle_dwarf_count: number;
  most_stressed_value: number;
  pending_events: FortressEvent[];
}

export interface FortressChainStatus {
  active: boolean;
  last_action: string | null;
}

export interface FortressGovernance {
  chains: Record<string, FortressChainStatus>;
  suppression: Record<string, number>;
}

export interface FortressGoalSubgoal {
  id: string;
  description: string;
  chain: string;
  state: string;
}

export interface FortressGoal {
  id: string;
  description: string;
  priority: number;
  state: string;
  subgoals: FortressGoalSubgoal[];
}

export interface FortressGoals {
  goals: FortressGoal[];
}

export interface FortressEvents {
  events: FortressEvent[];
}

export interface FortressMetrics {
  session_id: string | null;
  survival_days: number;
  total_commands: number;
  chain_metrics: Record<string, { issued: number; vetoed: number }>;
}

export interface FortressSession {
  session_id: string;
  fortress_name: string;
  survival_days: number;
  survival_years: number;
  peak_population: number;
  cause_of_death: string;
}

export interface FortressSessions {
  sessions: FortressSession[];
}

export interface FortressChronicleEntry {
  fortress_name: string;
  year: number;
  season: number;
  trigger: string;
  narrative: string;
  population: number;
}

export interface FortressChronicle {
  entries: FortressChronicleEntry[];
}

// One refusal event from /api/refusals — raw individual, NEVER aggregated.
// Constitutional load-bearing: per feedback_full_automation_or_no_engagement
// + drop §3 fresh patterns, refusal events are first-class displayed
// elements; UI must not collapse, summarize, or offer ack/dismiss/archive
// affordances.
export interface RefusalEvent {
  timestamp: string; // ISO-8601 UTC
  surface: string; // e.g. "twitter" / "linkedin" / "bandcamp"
  reason: string; // short rationale string
  refused_artifact_slug?: string | null;
  // Optional axiom tag — surface field naming varies by emitter.
  axiom?: string;
}

export interface RefusalsResponse {
  refusals: RefusalEvent[];
  total_in_window: number;
}

// --- CC-hygiene state (workstream hygiene panel) ---
//
// Schema mirrors scripts/cc_hygiene/cc-hygiene-state.schema.json. Kept
// loose (Record<string, unknown>) on the wrapper to absorb schema
// evolution without a coordinated TS/Rust/Python triple-update.

export interface CcHygieneSession {
  role: string;
  current_claim: string | null;
  relay_updated: string | null;
  in_progress_count: number;
}

export interface CcHygieneCheckSummary {
  check_id: string;
  fired: number;
}

export interface CcHygieneEvent {
  timestamp: string;
  check_id: string;
  task_id?: string | null;
  message: string;
}

export interface CcHygieneState {
  schema_version: number;
  sweep_timestamp: string;
  sweep_duration_ms: number;
  killswitch_active: boolean;
  sessions: CcHygieneSession[];
  check_summaries: CcHygieneCheckSummary[];
  events: CcHygieneEvent[];
}

export interface CcHygieneStateResponse {
  state: CcHygieneState | null;
  mtime_unix: number | null;
}
