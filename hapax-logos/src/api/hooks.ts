import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type { NudgeActionResponse } from "./types";

const FAST = 30_000; // 30s
const SLOW = 300_000; // 5min

export const useHealth = () =>
  useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: FAST });

export const useGpu = () =>
  useQuery({ queryKey: ["gpu"], queryFn: api.gpu, refetchInterval: FAST });

export const useInfrastructure = () =>
  useQuery({ queryKey: ["infrastructure"], queryFn: api.infrastructure, refetchInterval: FAST });

export const useNudges = () =>
  useQuery({ queryKey: ["nudges"], queryFn: api.nudges, refetchInterval: SLOW });

export const useBriefing = () =>
  useQuery({ queryKey: ["briefing"], queryFn: api.briefing, refetchInterval: SLOW });

export const useGoals = () =>
  useQuery({ queryKey: ["goals"], queryFn: api.goals, refetchInterval: SLOW });

export const useReadiness = () =>
  useQuery({ queryKey: ["readiness"], queryFn: api.readiness, refetchInterval: SLOW });

export const useAgents = () =>
  useQuery({ queryKey: ["agents"], queryFn: api.agents, refetchInterval: SLOW });

export const useScout = () =>
  useQuery({ queryKey: ["scout"], queryFn: api.scout, refetchInterval: SLOW });

export const useCost = () =>
  useQuery({ queryKey: ["cost"], queryFn: api.cost, refetchInterval: SLOW });

export const useDrift = () =>
  useQuery({ queryKey: ["drift"], queryFn: api.drift, refetchInterval: SLOW });

export const useManagement = () =>
  useQuery({ queryKey: ["management"], queryFn: api.management, refetchInterval: SLOW });

export const useAccommodations = () =>
  useQuery({ queryKey: ["accommodations"], queryFn: api.accommodations, refetchInterval: SLOW });

export const useHealthHistory = (days = 7) =>
  useQuery({ queryKey: ["healthHistory", days], queryFn: () => api.healthHistory(days), refetchInterval: SLOW });

export const useManual = () =>
  useQuery({ queryKey: ["manual"], queryFn: api.manual, staleTime: Infinity });

export const useCopilot = () =>
  useQuery({ queryKey: ["copilot"], queryFn: api.copilot, refetchInterval: FAST });

// --- Mutations ---

export function useNudgeAction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ sourceId, action }: { sourceId: string; action: "act" | "dismiss" }) =>
      api.post<NudgeActionResponse>(`/nudges/${sourceId}/${action}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["nudges"] });
    },
  });
}

export const useChatModels = () =>
  useQuery({
    queryKey: ["chatModels"],
    queryFn: () => api.get<import("./types").ChatModelsResponse>("/chat/models"),
    staleTime: Infinity,
  });

export function useAccommodationAction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "confirm" | "disable" }) =>
      api.post<{ status: string }>(`/accommodations/${id}/${action}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["accommodations"] });
    },
  });
}

export function useCancelAgent() {
  return useMutation({
    mutationFn: () => api.del<{ status: string }>("/agents/runs/current"),
  });
}

// --- Working Mode ---

export const useWorkingMode = () =>
  useQuery({ queryKey: ["workingMode"], queryFn: api.workingMode, refetchInterval: SLOW });

export function useSetWorkingMode() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (mode: "research" | "rnd") => api.setWorkingMode(mode),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workingMode"] });
    },
  });
}

// --- Scout Decisions ---

export const useScoutDecisions = () =>
  useQuery({ queryKey: ["scoutDecisions"], queryFn: api.scoutDecisions, refetchInterval: SLOW });

export function useScoutDecide() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ component, decision, notes }: { component: string; decision: string; notes?: string }) =>
      api.scoutDecide(component, decision, notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scoutDecisions"] });
    },
  });
}

// --- Studio ---

export const useStudio = () =>
  useQuery({ queryKey: ["studio"], queryFn: api.studio, refetchInterval: FAST });

export const useStudioStreamInfo = () =>
  useQuery({ queryKey: ["studioStreamInfo"], queryFn: api.studioStreamInfo, refetchInterval: FAST });

const FAST_POLL = 10_000; // 10s — compositor state changes rarely

export const useCompositorLive = () =>
  useQuery({ queryKey: ["compositorLive"], queryFn: api.compositorLive, refetchInterval: FAST_POLL });

export const useStudioDisk = () =>
  useQuery({ queryKey: ["studioDisk"], queryFn: api.studioDisk, refetchInterval: FAST });

export function useRecordingToggle() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (enable: boolean) => (enable ? api.enableRecording() : api.disableRecording()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["compositorLive"] });
      queryClient.invalidateQueries({ queryKey: ["studio"] });
    },
  });
}

// --- Demos ---

export const useDemos = () =>
  useQuery({ queryKey: ["demos"], queryFn: api.demos, refetchInterval: SLOW });

export function useDeleteDemo() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteDemo(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["demos"] });
    },
  });
}

// --- Governance & Consent ---

export const useConsentContracts = () =>
  useQuery({ queryKey: ["consentContracts"], queryFn: api.consentContracts, refetchInterval: SLOW });

export const useConsentCoverage = () =>
  useQuery({ queryKey: ["consentCoverage"], queryFn: api.consentCoverage, refetchInterval: SLOW });

export const useConsentOverhead = () =>
  useQuery({ queryKey: ["consentOverhead"], queryFn: api.consentOverhead, refetchInterval: SLOW });

export const useConsentPrecedents = () =>
  useQuery({ queryKey: ["consentPrecedents"], queryFn: api.consentPrecedents, refetchInterval: SLOW });

export const useGovernanceHeartbeat = () =>
  useQuery({ queryKey: ["governanceHeartbeat"], queryFn: api.governanceHeartbeat, refetchInterval: FAST });

export const useGovernanceCoverage = () =>
  useQuery({ queryKey: ["governanceCoverage"], queryFn: api.governanceCoverage, refetchInterval: SLOW });

export const useGovernanceCarriers = () =>
  useQuery({ queryKey: ["governanceCarriers"], queryFn: api.governanceCarriers, refetchInterval: SLOW });

// --- Engine ---

export const useEngineStatus = () =>
  useQuery({ queryKey: ["engineStatus"], queryFn: api.engineStatus, refetchInterval: FAST });

export const useEngineRules = () =>
  useQuery({ queryKey: ["engineRules"], queryFn: api.engineRules, staleTime: Infinity });

export const useEngineHistory = () =>
  useQuery({ queryKey: ["engineHistory"], queryFn: api.engineHistory, refetchInterval: FAST });

// --- Profile ---

export const useProfile = () =>
  useQuery({ queryKey: ["profile"], queryFn: api.profile, refetchInterval: SLOW });

export const useProfilePending = () =>
  useQuery({ queryKey: ["profilePending"], queryFn: api.profilePending, refetchInterval: SLOW });

// --- Perception (restored for overlay system) ---

const PERCEPTION = 3_000;
const FAST_VL = 2_000;

export const usePerception = () =>
  useQuery({ queryKey: ["perception"], queryFn: api.perception, refetchInterval: PERCEPTION, refetchIntervalInBackground: false });

export const useVisualLayer = () =>
  useQuery({ queryKey: ["visualLayer"], queryFn: api.visualLayer, refetchInterval: FAST_VL, refetchIntervalInBackground: false });

// ── Insight Queries ─────────────────────────────────────────────────────────

const INSIGHT_ACTIVE = 2_000; // 2s when queries are running

export const useInsightQueries = (hasRunning: boolean) =>
  useQuery({
    queryKey: ["insightQueries"],
    queryFn: api.insightQueries,
    refetchInterval: hasRunning ? INSIGHT_ACTIVE : FAST,
  });

export function useRunInsightQuery() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (query: string) => api.runInsightQuery(query),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["insightQueries"] }),
  });
}

export function useRefineInsightQuery() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { query: string; parentId: string; priorResult: string; agentType: string }) =>
      api.refineInsightQuery(args.query, args.parentId, args.priorResult, args.agentType),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["insightQueries"] }),
  });
}

export function useDeleteInsightQuery() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteInsightQuery(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["insightQueries"] }),
  });
}

// --- Orientation ---

export const useOrientation = () =>
  useQuery({
    queryKey: ["orientation"],
    queryFn: api.orientation,
    refetchInterval: SLOW,
  });

// --- Fortress ---

const FORTRESS = 30_000; // 30s for fortress state (was 5s — too aggressive)

export const useFortressState = () =>
  useQuery({ queryKey: ["fortressState"], queryFn: api.fortressState, refetchInterval: FORTRESS, retry: false });

export const useFortressGovernance = () =>
  useQuery({ queryKey: ["fortressGovernance"], queryFn: api.fortressGovernance, refetchInterval: 15_000, retry: false });

export const useFortressGoals = () =>
  useQuery({ queryKey: ["fortressGoals"], queryFn: api.fortressGoals, refetchInterval: FORTRESS, retry: false });

export const useFortressEvents = () =>
  useQuery({ queryKey: ["fortressEvents"], queryFn: api.fortressEvents, refetchInterval: FORTRESS, retry: false });

export const useFortressMetrics = () =>
  useQuery({ queryKey: ["fortressMetrics"], queryFn: api.fortressMetrics, refetchInterval: FORTRESS, retry: false });

export const useFortressSessions = () =>
  useQuery({ queryKey: ["fortressSessions"], queryFn: api.fortressSessions, refetchInterval: 60_000, retry: false });

export const useFortressChronicle = () =>
  useQuery({ queryKey: ["fortressChronicle"], queryFn: api.fortressChronicle, refetchInterval: FORTRESS, retry: false });
