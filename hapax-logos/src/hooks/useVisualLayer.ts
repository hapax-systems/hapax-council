/**
 * Re-exports from api/types for backward compatibility.
 * The actual data hook is useVisualLayer() in api/hooks.ts (react-query).
 * useVisualLayerPoll() has been removed — all consumers use the shared react-query cache.
 */
export type {
  BiometricState,
  ClassificationDetection,
  SignalStaleness,
  StimmungStance,
  TemporalContext,
  VisualLayerState,
} from "../api/types";
