import { useEffect, useState } from "react";

const API = "/api";
const POLL_MS = 2000;

interface SignalEntry {
  category: string;
  severity: number;
  title: string;
  detail: string;
  source_id: string;
}

interface AmbientParams {
  speed: number;
  turbulence: number;
  color_warmth: number;
  brightness: number;
}

interface VoiceSession {
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
}

interface SupplementaryContent {
  content_type: string;
  title: string;
  body: string;
  image_path: string;
  timestamp: number;
}

interface InjectedFeed {
  role: string;
  x: number;
  y: number;
  w: number;
  h: number;
  opacity: number;
  css_filter: string;
  duration_s: number;
  injected_at: number;
}

export interface VisualLayerState {
  available?: boolean;
  display_state: string;
  zone_opacities: Record<string, number>;
  signals: Record<string, SignalEntry[]>;
  ambient_params: AmbientParams;
  voice_session: VoiceSession;
  voice_content: SupplementaryContent[];
  injected_feeds: InjectedFeed[];
  ambient_text: string;
  activity_label: string;
  activity_detail: string;
  timestamp: number;
}

const DEFAULT_AMBIENT: AmbientParams = {
  speed: 0.08,
  turbulence: 0.1,
  color_warmth: 0.3,
  brightness: 0.25,
};

const DEFAULT_VOICE: VoiceSession = {
  active: false,
  state: "idle",
  turn_count: 0,
  last_utterance: "",
  last_response: "",
  active_tool: null,
  barge_in: false,
  routing_tier: "",
  routing_reason: "",
  routing_activation: 0.0,
};

export function useVisualLayerPoll() {
  const [vlState, setVlState] = useState<VisualLayerState | null>(null);

  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const res = await fetch(`${API}/studio/visual-layer`);
        if (res.ok && active) setVlState(await res.json());
      } catch {
        /* offline */
      }
    };
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  const state = vlState?.display_state ?? "ambient";
  const signals = vlState?.signals ?? {};
  const opacities = vlState?.zone_opacities ?? {};
  const ambient = vlState?.ambient_params ?? DEFAULT_AMBIENT;
  const voiceSession = vlState?.voice_session ?? DEFAULT_VOICE;
  const voiceContent = vlState?.voice_content ?? [];
  const injectedFeeds = vlState?.injected_feeds ?? [];
  const activityLabel = vlState?.activity_label ?? "present";
  const activityDetail = vlState?.activity_detail ?? "";
  const ambientText = vlState?.ambient_text ?? "";

  return {
    raw: vlState,
    state,
    signals,
    opacities,
    ambient,
    voiceSession,
    voiceContent,
    injectedFeeds,
    activityLabel,
    activityDetail,
    ambientText,
  };
}
