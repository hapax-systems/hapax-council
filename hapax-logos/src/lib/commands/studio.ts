import type { CommandRegistry, CommandResult } from "../commandRegistry";
import { useStudioGraph } from "../../stores/studioGraphStore";
import { api } from "../../api/client";

// ─── Types ───────────────────────────────────────────────────────────────────

export interface StudioState {
  smoothMode: boolean;
  activePreset: string;
  recording: boolean;
  broadcastMode: "desktop" | "mobile" | "dual";
}

export interface StudioActions {
  setSmoothMode(value: boolean): void;
  setActivePreset(name: string): void;
  cyclePreset(direction: "next" | "prev"): void;
  setRecording(value: boolean): void;
  setBroadcastMode(value: "desktop" | "mobile" | "dual"): void;
}

// ─── Register ────────────────────────────────────────────────────────────────

export function registerStudioCommands(
  registry: CommandRegistry,
  getState: () => StudioState,
  actions: StudioActions,
): void {
  registry.register({
    path: "studio.smooth.enable",
    description: "Enable smooth mode",
    execute(): CommandResult {
      actions.setSmoothMode(true);
      return { ok: true };
    },
  });

  registry.register({
    path: "studio.smooth.disable",
    description: "Disable smooth mode",
    execute(): CommandResult {
      actions.setSmoothMode(false);
      return { ok: true };
    },
  });

  registry.register({
    path: "studio.smooth.toggle",
    description: "Toggle smooth mode",
    execute(): CommandResult {
      actions.setSmoothMode(!getState().smoothMode);
      return { ok: true };
    },
  });

  registry.register({
    path: "studio.preset.activate",
    description: "Activate a studio preset by name",
    args: {
      name: { type: "string", required: true, description: "Preset name" },
    },
    execute(args): CommandResult {
      if (typeof args.name !== "string" || args.name.trim() === "") {
        return { ok: false, error: "Missing required arg: name" };
      }
      actions.setActivePreset(args.name);
      return { ok: true };
    },
  });

  registry.register({
    path: "studio.preset.cycle",
    description: "Cycle to next or previous preset",
    args: {
      direction: { type: "string", required: true, enum: ["next", "prev"] },
    },
    execute(args): CommandResult {
      if (args.direction !== "next" && args.direction !== "prev") {
        return { ok: false, error: `Invalid direction: ${String(args.direction)}` };
      }
      actions.cyclePreset(args.direction);
      return { ok: true };
    },
  });

  registry.register({
    path: "studio.recording.toggle",
    description: "Toggle recording on/off",
    execute(): CommandResult {
      actions.setRecording(!getState().recording);
      return { ok: true };
    },
  });

  registry.register({
    path: "studio.broadcast.mode",
    description: "Set compositor livestream egress mode",
    args: {
      mode: { type: "string", required: true, enum: ["desktop", "mobile", "dual"] },
    },
    execute(args): CommandResult {
      if (args.mode !== "desktop" && args.mode !== "mobile" && args.mode !== "dual") {
        return { ok: false, error: `Invalid broadcast mode: ${String(args.mode)}` };
      }
      actions.setBroadcastMode(args.mode);
      api.patch("/studio/broadcast-mode", { mode: args.mode }).catch(() => {});
      return { ok: true };
    },
  });

  registry.register({
    path: "studio.output.fullscreen",
    description: "Toggle output node fullscreen with live preview and preset controls",
    execute(): CommandResult {
      const current = useStudioGraph.getState().outputFullscreen;
      useStudioGraph.getState().setOutputFullscreen(!current);
      return { ok: true };
    },
  });

  registry.register({
    path: "studio.node.param",
    description: "Adjust a shader node parameter by name and value",
    args: {
      node_id: { type: "string", required: true, description: "Node instance ID in the graph" },
      param: { type: "string", required: true, description: "Parameter name" },
      value: { type: "number", required: true, description: "New value" },
    },
    execute(args): CommandResult {
      if (!args.node_id || !args.param || args.value === undefined) {
        return { ok: false, error: "Missing node_id, param, or value" };
      }
      api.patch(`/studio/effect/graph/node/${args.node_id}/params`, {
        [args.param as string]: args.value,
      }).catch(() => {});
      return { ok: true };
    },
  });

  registry.register({
    path: "studio.layer.toggle",
    description: "Enable or disable a compositor output layer",
    args: {
      layer: { type: "string", required: true, description: "Layer name: live, smooth, or hls" },
      enabled: { type: "boolean", required: true, description: "Whether to enable the layer" },
    },
    execute(args): CommandResult {
      if (!args.layer) return { ok: false, error: "Missing layer name" };
      api.patch(`/studio/layer/${args.layer}/enabled`, {
        enabled: !!args.enabled,
      }).catch(() => {});
      return { ok: true };
    },
  });

  registry.register({
    path: "studio.camera.select",
    description: "Select the hero camera perspective",
    args: {
      role: { type: "string", required: true, description: "Camera role name" },
    },
    execute(args): CommandResult {
      if (!args.role) return { ok: false, error: "Missing camera role" };
      api.post("/studio/camera/select", { role: args.role }).catch(() => {});
      return { ok: true };
    },
  });

  registry.register({
    path: "studio.graph.add_node",
    description: "Insert a shader effect node into the active graph",
    args: {
      node_type: { type: "string", required: true, description: "Shader node type from registry" },
      node_id: { type: "string", required: true, description: "Unique instance ID for the node" },
    },
    execute(args): CommandResult {
      if (!args.node_type || !args.node_id) {
        return { ok: false, error: "Missing node_type or node_id" };
      }
      api.patch("/studio/effect/graph", {
        add_nodes: [{ id: args.node_id, type: args.node_type, params: {} }],
      }).catch(() => {});
      return { ok: true };
    },
  });

  registry.register({
    path: "studio.graph.remove_node",
    description: "Remove a shader effect node from the active graph",
    args: {
      node_id: { type: "string", required: true, description: "Node instance ID to remove" },
    },
    execute(args): CommandResult {
      if (!args.node_id) return { ok: false, error: "Missing node_id" };
      api.del(`/studio/effect/graph/node/${args.node_id}`).catch(() => {});
      return { ok: true };
    },
  });

  // ── Queries ──────────────────────────────────────────────────────────────

  registry.registerQuery("studio.smoothMode", () => getState().smoothMode);
  registry.registerQuery("studio.activePreset", () => getState().activePreset);
  registry.registerQuery("studio.recording", () => getState().recording);
  registry.registerQuery("studio.broadcastMode", () => getState().broadcastMode);
}
