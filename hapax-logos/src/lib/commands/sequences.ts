import type { CommandRegistry } from "../commandRegistry";

/**
 * Register the built-in command sequences for the Logos application.
 *
 * Three sequences are registered:
 * - studio.enter  — focus ground → set ground depth to core → enable smooth
 * - studio.exit   — disable smooth → collapse terrain
 * - escape        — hierarchical dismiss (stopOnSuccess): overlay → split → terrain
 */
export function registerBuiltinSequences(registry: CommandRegistry): void {
  // studio.enter: prepare the ground surface for studio use
  registry.sequence("studio.enter", [
    { command: "terrain.focus", args: { region: "ground" } },
    { command: "terrain.depth.set", args: { region: "ground", depth: "core" } },
    { command: "studio.smooth.enable" },
  ]);

  // studio.exit: tear down studio surface state
  registry.sequence("studio.exit", [
    { command: "studio.smooth.disable" },
    { command: "terrain.collapse" },
  ]);

  // escape: dismiss the most recent layer; stops at first success
  registry.sequence(
    "escape",
    [
      { command: "overlay.clear" },
      { command: "split.close" },
      { command: "terrain.collapse" },
    ],
    { stopOnSuccess: true },
  );
}
