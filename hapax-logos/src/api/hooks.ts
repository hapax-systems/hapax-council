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
  useQuery({ queryKey: ["agents"], queryFn: api.agents, staleTime: Infinity });

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
    queryFn: () => fetch("/api/chat/models").then(r => r.json()) as Promise<import("./types").ChatModelsResponse>,
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

// --- Cycle Mode ---

export const useCycleMode = () =>
  useQuery({ queryKey: ["cycleMode"], queryFn: api.cycleMode, refetchInterval: SLOW });

export function useSetCycleMode() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (mode: "dev" | "prod") => api.setCycleMode(mode),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["cycleMode"] });
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

const FAST_POLL = 2_000; // 2s

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
const VISUAL_LAYER = 5_000;

export const usePerception = () =>
  useQuery({ queryKey: ["perception"], queryFn: api.perception, refetchInterval: PERCEPTION });

export const useVisualLayer = () =>
  useQuery({ queryKey: ["visualLayer"], queryFn: api.visualLayer, refetchInterval: VISUAL_LAYER });
